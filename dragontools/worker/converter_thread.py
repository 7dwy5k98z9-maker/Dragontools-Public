# -*- coding: utf-8 -*-
"""
dragontools/worker/converter_thread.py

Schlanke QThread-Fassade für den Konvertierungs-Worker.

Fach- und Laufzeitverantwortungen sind auf spezialisierte Komponenten verteilt:
  - ConverterRuntimeBuilder   : laufzeitabhängige Services/Workflow-Verdrahtung
  - ConverterRunLoop          : Session- und Live-Queue-Orchestrierung
  - ConverterLifecycleService : Run-Fehlergrenze und Abschlussarbeiten
  - ConverterFileExecutor     : Per-Datei-Workflow + Quellbild-Preflight
  - ConverterControlService   : Pause/Abort/Diagnose/Prozesskontrolle
  - ConverterProgressHelper   : Prozesse + Fortschritt/ETA
  - ConverterDetectionHelper  : Auto-Crop + IMAX-Erkennung + externe Subs
  - ConverterStreamArgsHelper : Audio-/Sub-/Video-Filter-Argumente
  - ConverterStripHelper      : Strip-Only-Modus
  - DVProcessingPipeline      : DV/Level-5-Workflow

ConverterThread behält die öffentliche Worker-Oberfläche, Queue-Fassade,
Signale und die öffentliche Queue-/Lifecycle-API für GUI-Aufrufer.

DV-Crop-Fix:
  AutoCrop und RPU-Level-5 werden vor dem Encode abgeglichen. Wird der
  HEVC-Stream anschließend physisch gecroppt, sind diese Pixel im Ziel-Frame
  bereits entfernt. Deshalb setzt dovi_tool die finale RPU Active Area danach
  auf 0/0/0/0; alte Crop-Offsets würden am DV-Gerät einen Double-Crop auslösen.
  Die korrigierte RPU wird vor der Injection und bei gecroppten Ausgaben auch
  nach dem finalen MKV-/MP4-Mux verifiziert.
"""
from __future__ import annotations

from subprocess import Popen
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .converter_config import ConverterConfig
from .worker_contracts import RemoveFileStatus, normalize_worker_path
from .worker_events import log_event
from .converter_thread_bootstrap import bootstrap_converter_thread


# ------------------------------------------------------------------
# Haupt-Worker
# ------------------------------------------------------------------
class ConverterThread(QThread):
    progress = pyqtSignal(int)
    file_progress = pyqtSignal(str, int, object)
    file_result = pyqtSignal(str, str, str)  # (input_path, output_path, status)
    log_line = pyqtSignal(str)
    event = pyqtSignal(object)
    dv_crop_decision_requested = pyqtSignal(object)

    def __init__(self, files, config: ConverterConfig, *, shared_logger=None, parent=None):
        super().__init__(parent)
        if not isinstance(config, ConverterConfig):
            raise TypeError("config muss eine ConverterConfig-Instanz sein.")
        bootstrap_converter_thread(self, files, config, shared_logger=shared_logger)


    def request_dv_crop_decision(self, details: dict) -> str:
        """Blockierende Worker→GUI-Entscheidungsgrenze für große DV-Crop-Abweichungen."""
        import uuid
        request_id = uuid.uuid4().hex
        event = threading.Event()
        slot = {"event": event, "decision": ""}
        with self._session_state.dv_crop_decision_lock:
            self._session_state.dv_crop_decisions[request_id] = slot
        payload = dict(details or {})
        payload["request_id"] = request_id
        self.dv_crop_decision_requested.emit(payload)
        while not event.wait(0.2):
            if self._control_state.abort_requested:
                break
        with self._session_state.dv_crop_decision_lock:
            current = self._session_state.dv_crop_decisions.pop(request_id, slot)
        if self._control_state.abort_requested and not current.get("decision"):
            return "disable_dv"
        return str(current.get("decision") or "disable_dv")

    def provide_dv_crop_decision(self, request_id: str, decision: str) -> bool:
        with self._session_state.dv_crop_decision_lock:
            slot = self._session_state.dv_crop_decisions.get(str(request_id))
            if slot is None:
                return False
            slot["decision"] = str(decision or "")
            slot["event"].set()
            return True

    # ==================================================================
    # Live-Queue Methoden
    # ==================================================================
    def add_file(self, path: str) -> bool:
        ok = self._queue.add_file(path, self.log)
        if ok:
            self._session_state.all_input_files.append(path)
        return ok

    def remove_file(self, path: str) -> RemoveFileStatus:
        return self._queue.remove_file(path, self.log)

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
        name = Path(path).name
        path_n = normalize_worker_path(path)

        with self._files_lock:
            current_n = normalize_worker_path(self._queue.current_file) if self._queue.current_file else None
            done_n = {normalize_worker_path(p) for p in self._queue.done_files}

            if current_n == path_n:
                self.log(f"⛔ Override für '{name}' abgelehnt - Datei wird gerade verarbeitet.", "warn")
                return False

            if path_n in done_n:
                self.log(f"⛔ Override für '{name}' abgelehnt - Datei bereits abgeschlossen.", "warn")
                return False

            self._job_state.file_overrides[path] = override

        self.log(f"🛠️ Override für '{name}' gesetzt.", "info")
        return True

    # ==================================================================
    # Pause / Abort / Logging-Utility
    # ==================================================================

    @property
    def is_paused(self) -> bool:
        """Öffentlicher, read-only Pausezustand für GUI/Controller."""
        return bool(self._control_state.paused)

    @property
    def abort_requested(self) -> bool:
        """Öffentlicher Abortstatus ohne Legacy-State-Alias."""
        return bool(self._control_state.abort_requested)

    @property
    def abort_type(self) -> str | None:
        return self._control_state.abort_type

    @property
    def current_process(self) -> Popen | None:
        """Lock-gesicherter Zugriff auf den laufenden subprocess.

        GUI-Thread (request_abort) und Worker-Thread (run-Schleife) greifen
        gleichzeitig auf dieses Attribut zu – daher Lock wie in BaseWorker.
        """
        with self._control_state.process_lock:
            return self._control_state.current_process

    @current_process.setter
    def current_process(self, proc: Popen | None) -> None:
        with self._control_state.process_lock:
            self._control_state.current_process = proc

    def diagnostic_snapshot(self) -> dict:
        """Liefert einen kompakten Diagnosezustand für laufende Jobs."""
        return self._control.diagnostic_snapshot()

    def pause(self):
        self._control.pause()

    def resume(self):
        self._control.resume()

    def request_abort(self, mode: str = "sofort"):
        self._control.request_abort(mode)

    def terminate_current_ffmpeg(self, path: str | None = None) -> bool:
        """Beendet nur FFmpeg der aktuellen Datei; die Queue läuft weiter."""
        return self._control.terminate_current_ffmpeg(path)

    def clear_abort_request(self) -> bool:
        """Nimmt einen vorgemerkten Abbruch nach Datei zurück."""
        return self._control.clear_abort_request()

    def cancel(self) -> None:
        self.request_abort()

    def wait_if_paused(self):
        self._control.wait()

    def log(self, msg, level="info"):
        self.event.emit(log_event(str(msg), severity=level))
        getattr(self._logger, level, self._logger.info)(msg)

    def emit_file_progress(self, path, pct, eta=None):
        self._services.result.emit_file_progress(path, pct, eta)

    def emit_file_result(self, input_path: str, output_path: str, status: str) -> None:
        self._services.result.emit_file_result(input_path, output_path, status)

    # ==================================================================
    # Hoch-Level-Orchestrierung convert_file()
    # ==================================================================
    def convert_file(self, input_path: str) -> bool:
        return self._file_executor.execute(input_path)

    # ==================================================================
    # Run-Loop
    # ==================================================================
    def run(self):
        try:
            self._runtime_builder.initialize()
            self._run_loop.execute()
        except Exception as exc:
            self._lifecycle.handle_run_exception(exc, traceback.format_exc())
            self._session_state.keep_verbose_log = True
        finally:
            self._lifecycle.finalize_run()

    # ==================================================================
    # Refactoring state bridges
    # ==================================================================
    # These narrow properties keep the pre-refactor worker contract alive for
    # GUI/result and parallel orchestration code while the actual ownership
    # remains in ConverterSessionState / ConverterServiceRegistry. Without
    # these bridges, generated NFO/trickplay sidecars are not handed to Move.

    @property
    def _all_input_files(self) -> list[str]:
        return self._session_state.all_input_files

    @property
    def _sidecar_outputs(self) -> dict[str, list[str]]:
        return self._session_state.sidecar_outputs

    @property
    def _postprocess_outputs(self) -> dict[str, list[dict]]:
        return self._session_state.postprocess_outputs

    @property
    def _failure_details(self) -> dict[str, dict]:
        return self._session_state.failure_details

    @property
    def _replace_service(self):
        return self._services.replace

    @property
    def _suppress_session_header(self) -> bool:
        return self._session_state.suppress_session_header

    @_suppress_session_header.setter
    def _suppress_session_header(self, value: bool) -> None:
        self._session_state.suppress_session_header = bool(value)

    @property
    def _display_index_by_path(self) -> dict[str, int]:
        return self._session_state.display_index_by_path

    @_display_index_by_path.setter
    def _display_index_by_path(self, value) -> None:
        self._session_state.display_index_by_path = dict(value or {})

    @property
    def _display_total(self) -> int | None:
        return self._session_state.display_total

    @_display_total.setter
    def _display_total(self, value) -> None:
        self._session_state.display_total = None if value is None else int(value)

    @property
    def _run_start_ts(self) -> float | None:
        return self._session_state.run_start_ts

    @_run_start_ts.setter
    def _run_start_ts(self, value) -> None:
        self._session_state.run_start_ts = None if value is None else float(value)

    @property
    def total_before(self) -> int:
        return self._runtime_state.total_before

    @property
    def total_after(self) -> int:
        return self._runtime_state.total_after

    @property
    def erfolgreich(self) -> int:
        return self._runtime_state.erfolgreich

    @property
    def fehlgeschlagen(self) -> int:
        return self._runtime_state.fehlgeschlagen
