# -*- coding: utf-8 -*-
"""
dragontools/worker/dv_remux_thread.py

DV-Remux-Thread für Dolby-Vision-Dateien.
  - Zielcontainer folgt der Einstellung ``Dolby Vision / DV+HDR10+ / DV-Remux``
    und kann MP4 oder MKV sein.
  - Audio: normal nach den zentralen Audioregeln aufbereiten.
  - DV7: bei MKV optional unverändert; sonst verlustfreie Profilnormalisierung nach DV 8.1.
  - DV5: je nach Einstellung Wechsel in den bestehenden H.265-DV-Encodingpfad oder Skip.
  - Andere Remux-Fälle: Video ohne klassisches Re-Encoding; Zielcontainer folgt der DV-Einstellung.
  - Untertitel: MKV übernimmt die nach Regelwerk ausgewählten Untertitel intern.
    Bei MP4 folgt die Ablage der globalen MP4-Sidecar-Policy: entweder alle
    ausgewählten Untertitel extern oder – soweit kompatibel – Textspuren intern
    als mov_text; PGS/SUP/VobSub bleiben externe Sidecars.
  - MP4 wird final mit MP4Box gebaut; MKV mit mkvmerge.

Ablauf:
  1. Quelle analysieren und DV-Profil-Policy bestimmen
  2. DV7 bei Bedarf mit dovi_tool Mode 2 nach P8.1 normalisieren; DV5 ggf. an den normalen Encoder übergeben
  3. Audio containerabhängig extrahieren/konvertieren
  4. Untertitel nach Container und globaler MP4-Sidecar-Policy aufbereiten
  5. MP4Box oder mkvmerge: finale DV-Datei bauen und Profil/Medienvertrag verifizieren
"""
from __future__ import annotations

import threading, traceback

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, QSettings

from ..core.conversion_artifacts import ArtifactRegistry
from ..core.logger import create_worker_logger
from ..core.tool_paths import get_tool_paths
from ..core.settings_app import APP_ORG, APP_NAME
from ..core.settings_conversion import (
    DEFAULT_DV_REMUX_ENCODE_DV5,
    DEFAULT_DV_REMUX_KEEP_DV7_MKV,
    DEFAULT_OUTPUT_CONTAINER_DV,
    SET_KEY_DV_REMUX_ENCODE_DV5,
    SET_KEY_DV_REMUX_KEEP_DV7_MKV,
    SET_KEY_OUTPUT_CONTAINER_DV,
)
from ..core.settings_access import settings_text
from ..rules.rule_loader import load_subtitle_rules
from .worker_contracts import RemoveFileStatus, normalize_worker_path
from .converter_utils import _fd, _fs  # compatibility re-export for legacy tests/extensions
from .converter_queue_state import ConverterQueueState
from .process_control import terminate_process_tree, wait_while_paused
from .subtitle_sidecar_service import SubtitleSidecarService
from .dv_remux_components import (
    DVMP4BoxPipelineRunner,
    DVOutputManager,
    DVRemuxProcessRunner,
)
from .dv_remux_job import DVRemuxJobRunner
from .dv5_encode_fallback import DV5EncodeFallbackRunner
from .dv_remux_file_dispatcher import DVRemuxFileDispatcher
from .dv_result_contract import fail_unfinished_dv_inputs
from .postprocess_runner import PostProcessService
from .worker_events import log_event, progress_event, result_event


class DVRemuxThread(QThread):
    """Remuxt Dolby Vision ohne Video-Re-Encoding nach MP4 oder MKV."""

    progress      = pyqtSignal(int)
    file_progress = pyqtSignal(str, int, object)
    file_result   = pyqtSignal(str, str, str)  # (input_path, output_path, status)
    log_line      = pyqtSignal(str)
    event         = pyqtSignal(object)
    dv_crop_decision_requested = pyqtSignal(object)

    def __init__(self, files: list[str], *, overwrite_original: bool = False,
                 encoder_options: dict | None = None,
                 file_overrides: dict | None = None,
                 subtitle_rules: dict | None = None,
                 container: str | None = None,
                 dv5_fallback_config=None,
                 parent=None):
        super().__init__(parent)

        # Queue-Zustand: zentral über ConverterQueueState verwaltet.
        self._queue = ConverterQueueState(list(files))
        self.files = self._queue.files          # ?ffentliches Attribut für UI-Zugriff

        self.overwrite_original = overwrite_original
        settings = QSettings(APP_ORG, APP_NAME)
        configured_container = settings_text(
            settings,
            SET_KEY_OUTPUT_CONTAINER_DV,
            DEFAULT_OUTPUT_CONTAINER_DV,
            allowed=("mp4", "mkv"),
        )
        requested_container = str(container or configured_container).strip().lower()
        self.container = requested_container if requested_container in {"mp4", "mkv"} else DEFAULT_OUTPUT_CONTAINER_DV
        self.keep_dv7_mkv = bool(settings.value(
            SET_KEY_DV_REMUX_KEEP_DV7_MKV,
            DEFAULT_DV_REMUX_KEEP_DV7_MKV,
            type=bool,
        ))
        self.encode_dv5 = bool(settings.value(
            SET_KEY_DV_REMUX_ENCODE_DV5,
            DEFAULT_DV_REMUX_ENCODE_DV5,
            type=bool,
        ))
        self.dv5_fallback_config = dv5_fallback_config
        self.encoder_options = dict(encoder_options or {})
        self.file_overrides = dict(file_overrides or {})
        self.subtitle_rules = dict(
            subtitle_rules or load_subtitle_rules(default={"mp4_sidecars_enabled": True})
        )
        self.tools = get_tool_paths()

        # Abort-Flags (gleiches Schema wie ConverterThread)
        self.abort_requested = False
        self.abort_type: str | None = None

        # Pause-Interface (identisch mit ConverterThread)
        self._paused = False
        self._pause_ev = threading.Event()
        self._pause_ev.set()

        # Laufender Prozess (public, damit wait_while_paused ihn lesen kann)
        self.current_process = None

        # Prozess-Lock für laufende ffmpeg/mp4box-Prozesse
        self._lock = threading.Lock()
        self._last_stderr = ""
        self._active_fallback_worker = None

        self._artifacts = ArtifactRegistry()
        self._sidecar_outputs = self._artifacts.sidecar_outputs
        self._postprocess_outputs = self._artifacts.postprocess_outputs
        self._failure_details = self._artifacts.failure_details

        s = QSettings(APP_ORG, APP_NAME)
        self._logger = create_worker_logger(
            settings=s,
            gui_callback=self.log_line.emit,
        )
        self.log_file_path = str(self._logger.log_file) if self._logger.log_file else None
        self._process_runner = DVRemuxProcessRunner(self)
        self._subtitle_service = SubtitleSidecarService(
            ffmpeg_path=self.tools.ffmpeg,
            subtitle_rules=self.subtitle_rules,
            log=self.log,
            worker=self,
        )
        self._mp4box_pipeline = DVMP4BoxPipelineRunner(self, self._process_runner)
        self._output_manager = DVOutputManager(self)
        self._postprocess_service = PostProcessService(
            settings=s, tools=self.tools, log=self.log, worker=self
        )
        self._dv5_fallback = DV5EncodeFallbackRunner(self, self.dv5_fallback_config)
        self._file_dispatcher = DVRemuxFileDispatcher(self)

    # ==================================================================
    # Abort-Interface
    # ==================================================================

    def request_abort(self, mode: str = "sofort"):
        """
        mode:
          - 'sofort'     -> laufenden Prozess sofort terminieren
          - 'nach_datei' -> aktuelle Datei fertig machen, danach stoppen
        """
        self.abort_requested = True
        self.abort_type = mode

        fallback = self._active_fallback_worker
        if fallback is not None:
            fallback.request_abort(mode)

        # Wenn pausiert: fortsetzen, damit der Worker-Thread den Abbruch
        # wahrnehmen und sauber beenden kann.
        if self._paused:
            self.resume()

        if mode == "sofort":
            terminate_process_tree(
                self,
                self._lock,
                log=self.log,
                attr_name="current_process",
                label="DV-Remux-Prozess",
            )

    def cancel(self) -> None:
        self.request_abort()

    def pause(self) -> None:
        """Haelt den Worker an. Der laufende Prozess wird CPU-schonend suspendiert."""
        self._paused = True
        self._pause_ev.clear()
        fallback = self._active_fallback_worker
        if fallback is not None:
            fallback.pause()
        self._logger.info("⏸️ Pausiert.")

    def resume(self) -> None:
        """Setzt einen pausierten Worker fort."""
        self._paused = False
        self._pause_ev.set()
        fallback = self._active_fallback_worker
        if fallback is not None:
            fallback.resume()
        self._logger.info("▶️ Fortgesetzt.")

    def provide_dv_crop_decision(self, request_id: str, decision: str) -> bool:
        fallback = self._active_fallback_worker
        if fallback is None or not hasattr(fallback, "provide_dv_crop_decision"):
            return False
        return bool(fallback.provide_dv_crop_decision(request_id, decision))

    def wait_if_paused(self) -> None:
        """Blockiert solange der Worker pausiert ist; suspendiert dabei den laufenden Prozess."""
        wait_while_paused(self, self._lock)

    # ==================================================================
    # Live-Queue-Interface (delegiert an ConverterQueueState)
    # ==================================================================

    def add_file(self, path: str) -> bool:
        """Datei live zur Queue hinzufügen.

        Gibt True zurück wenn die Datei hinzugefügt wurde,
        False wenn sie bereits in der Queue, gerade verarbeitet oder erledigt ist.
        Identischer Vertrag wie ConverterThread.add_file().
        """
        result = self._queue.add_file(path, self._log)
        self.files = self._queue.files
        return result

    def remove_file(self, path: str) -> RemoveFileStatus:
        """Entfernt eine Datei aus der Queue oder merkt sie zur Spaet-Entfernung vor."""
        result = self._queue.remove_file(path, self._log)
        self.files = self._queue.files
        return result

    def is_current(self, path: str) -> bool:
        """True wenn path gerade vom Worker verarbeitet wird."""
        return self._queue.is_current(path)

    def reorder_waiting_files(self, new_order: list[str]) -> None:
        """Ordnet nur wartende Queue-Dateien neu.

        Bereits erledigte, als skip markierte oder aktuell laufende Dateien
        bleiben unberuehrt und werden aus der wartenden Liste gefiltert.
        """
        self._queue.reorder_waiting_files(new_order)
        self.files = self._queue.files

    def update_override(self, path: str, override: dict) -> bool:
        """Setzt einen per-Datei-Override für eine Datei in der Queue.

        Verhalten analog zu ConverterThread.update_override:
          - laufende Datei: abgelehnt
          - bereits erledigte Datei: abgelehnt
          - sonst: gespeichert, wird beim naechsten Verarbeiten angewandt
        """
        name = Path(path).name
        path_n = normalize_worker_path(path)

        with self._queue.lock:
            current_n = normalize_worker_path(self._queue.current_file) if self._queue.current_file else None
            done_n = {normalize_worker_path(p) for p in self._queue.done_files}

            if current_n == path_n:
                self.log(
                    f"⛔ Override für '{name}' abgelehnt - Datei wird gerade verarbeitet.",
                    "warn",
                )
                return False

            if path_n in done_n:
                self.log(
                    f"⛔ Override für '{name}' abgelehnt - Datei bereits abgeschlossen.",
                    "warn",
                )
                return False

            self.file_overrides[path] = override

        self.log(f"✏️ Override für '{name}' gesetzt.", "info")
        return True
    # ==================================================================
    # Logging
    # ==================================================================

    def log(self, msg, level="info"):
        self.event.emit(log_event(str(msg), severity=level))
        getattr(self._logger, level, self._logger.info)(msg)

    # ==================================================================
    # Per-file remux transaction
    # ==================================================================

    def prepare_remux_metadata(self, input_path: str):
        """Public dispatcher hook; honors legacy instance overrides."""
        legacy = self.__dict__.get("_prepare_remux_metadata")
        if callable(legacy):
            return legacy(input_path)
        return self._file_dispatcher.prepare_metadata(input_path)

    def emit_remux_success(self, *args) -> None:
        legacy = self.__dict__.get("_emit_remux_success")
        if callable(legacy):
            legacy(*args)
            return
        self._file_dispatcher.emit_success(*args)

    def _prepare_remux_metadata(self, input_path: str):
        return self.prepare_remux_metadata(input_path)

    def _emit_remux_success(self, *args) -> None:
        self.emit_remux_success(*args)

    def _remux_file_safe(self, input_path: str) -> bool:
        """Run one file through the extracted policy/transaction dispatcher."""
        return self._file_dispatcher.run(input_path)

    @staticmethod
    def _cleanup_generated_sidecars(paths: list[str] | tuple[str, ...]) -> None:
        DVRemuxJobRunner.cleanup_generated_sidecars(paths)
    # ==================================================================
    # Run-Loop
    # ==================================================================

    def run(self):
        try:
            self.tools = get_tool_paths()
            self._postprocess_service.tools = self.tools
            self._logger.separator()

            initial_total = self._queue.initial_total
            self._logger.info(f"DV-Remux -> {self.container.upper()} | {initial_total} Datei(en)")

            ok_count = 0
            processed_count = 0

            while True:
                self.wait_if_paused()

                if self.abort_requested and self.abort_type == "sofort":
                    break

                next_item = self._queue.next_file(processed_count)
                self.files = self._queue.files

                if next_item is None:
                    break

                path, _total_now = next_item

                success = self._remux_file_safe(path)
                if success:
                    ok_count += 1

                self._queue.complete_current(path)
                self.files = self._queue.files

                processed_count += 1
                total_now = self._queue.total_after_processed(processed_count)
                self.progress.emit(
                    0 if total_now == 0
                    else min(100, int(processed_count / max(total_now, 1) * 100))
                )

                if self.abort_requested and self.abort_type == "nach_datei":
                    break

            self._logger.success(f"Fertig: {ok_count}/{processed_count} erfolgreich.")
        except Exception as exc:
            self.log("❌ Unbehandelte Ausnahme im Worker:", "error")
            self.log(traceback.format_exc(), "error")
            fail_unfinished_dv_inputs(
                self, f"Unbehandelte Ausnahme im DV-Worker: {exc}", stage="worker"
            )
