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
  Der DV-RPU enthält die Mastering-Auflösung fest (z.B. 3840x2160).
  Wenn der HEVC-Stream auf 1632px gecroppt wird aber der RPU 2160 sagt,
  ignoriert der LG TV WebOS den HEVC-SPS und zeigt das Bild falsch.
  Fix: Nach dem Encode -> dovi_tool editor setzt Level 5 active area
  auf die exakten Crop-Offsets.
"""
from __future__ import annotations

from subprocess import Popen
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, QSettings

from ..core.logger import create_worker_logger, create_verbose_logger
from ..core.settings import APP_ORG, APP_NAME
from .dv_runtime_models import DVTempState
from .converter_config import ConverterConfig
from .converter_queue_state import ConverterQueueState
from .worker_contracts import RemoveFileStatus, normalize_worker_path
from .worker_events import log_event
from .worker_runtime_state import WorkerRuntimeState
from .converter_runtime_builder import ConverterRuntimeBuilder
from .converter_run_loop import ConverterRunLoop
from .converter_lifecycle import ConverterLifecycleService
from .converter_file_executor import ConverterFileExecutor
from .converter_control import ConverterControlService
from .converter_static_composition import build_static_converter_services
from .converter_thread_state import (
    ConverterControlState,
    ConverterJobState,
    ConverterSessionState,
    NestedStateAlias,
)


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
    finished = pyqtSignal()

    # ------------------------------------------------------------------
    # Kompatibilitätsoberfläche
    # ------------------------------------------------------------------
    # Diese Deskriptoren enthalten keinerlei Fachlogik. Sie halten historische
    # Worker-Attribute für GUI, Tests und schrittweise migrierte Services stabil,
    # während Ownership intern in klaren Context-Objekten liegt.
    codec = NestedStateAlias("_job_state", "codec")
    crf = NestedStateAlias("_job_state", "crf")
    preset = NestedStateAlias("_job_state", "preset")
    scale_mode = NestedStateAlias("_job_state", "scale_mode")
    overwrite_original = NestedStateAlias("_job_state", "overwrite_original")
    strip_only = NestedStateAlias("_job_state", "strip_only")
    encoder_options = NestedStateAlias("_job_state", "encoder_options")
    file_overrides = NestedStateAlias("_job_state", "file_overrides")
    subtitle_rules = NestedStateAlias("_job_state", "subtitle_rules")
    tv_path = NestedStateAlias("_job_state", "tv_path")
    anime_path = NestedStateAlias("_job_state", "anime_path")
    filme_path = NestedStateAlias("_job_state", "filme_path")

    abort_requested = NestedStateAlias("_control_state", "abort_requested")
    abort_type = NestedStateAlias("_control_state", "abort_type")
    _paused = NestedStateAlias("_control_state", "paused")
    _pause_ev = NestedStateAlias("_control_state", "pause_event")
    _current_process = NestedStateAlias("_control_state", "current_process")
    _lock = NestedStateAlias("_control_state", "process_lock")

    _all_input_files = NestedStateAlias("_session_state", "all_input_files")
    _sidecar_outputs = NestedStateAlias("_session_state", "sidecar_outputs")
    _postprocess_outputs = NestedStateAlias("_session_state", "postprocess_outputs")
    _failure_details = NestedStateAlias("_session_state", "failure_details")
    _keep_verbose_log = NestedStateAlias("_session_state", "keep_verbose_log")
    _suppress_session_header = NestedStateAlias("_session_state", "suppress_session_header")
    _display_index_by_path = NestedStateAlias("_session_state", "display_index_by_path")
    _display_total = NestedStateAlias("_session_state", "display_total")
    _dv_crop_decisions = NestedStateAlias("_session_state", "dv_crop_decisions")
    _dv_crop_decision_lock = NestedStateAlias("_session_state", "dv_crop_decision_lock")
    _run_start_ts = NestedStateAlias("_session_state", "run_start_ts")

    tools = NestedStateAlias("_services", "tools")
    _progress = NestedStateAlias("_services", "progress")
    _detect = NestedStateAlias("_services", "detection")
    _stream_args = NestedStateAlias("_services", "stream_args")
    _strip = NestedStateAlias("_services", "strip")
    _archive_service = NestedStateAlias("_services", "archive")
    _pipeline_decision = NestedStateAlias("_services", "pipeline_decision")
    _output_paths = NestedStateAlias("_services", "output_paths")
    _replace_service = NestedStateAlias("_services", "replace")
    _cleanup_service = NestedStateAlias("_services", "cleanup")
    _encode_plan_service = NestedStateAlias("_services", "encode_plan")
    _result_service = NestedStateAlias("_services", "result")
    _hdrplus_helper = NestedStateAlias("_services", "hdrplus")
    _media_analysis = NestedStateAlias("_services", "media_analysis")
    _standard_pipeline = NestedStateAlias("_services", "standard_pipeline")
    _output_verifier = NestedStateAlias("_services", "output_verifier")
    _duration_repair_service = NestedStateAlias("_services", "duration_repair")
    _dv_pipeline = NestedStateAlias("_services", "dv_pipeline")
    _av1_dv_pipeline = NestedStateAlias("_services", "av1_dv_pipeline")
    _av1_hdrplus_pipeline = NestedStateAlias("_services", "av1_hdrplus_pipeline")
    _postprocess_service = NestedStateAlias("_services", "postprocess")
    _postprocess_coordinator = NestedStateAlias("_services", "postprocess_coordinator")
    _source_visual_check_service = NestedStateAlias("_services", "source_visual_check")
    _workflow_services = NestedStateAlias("_services", "workflow_services")
    _workflow_runner = NestedStateAlias("_services", "workflow_runner")

    def __init__(self, files, config: ConverterConfig, *, shared_logger=None, parent=None):
        super().__init__(parent)
        if not isinstance(config, ConverterConfig):
            raise TypeError("config muss eine ConverterConfig-Instanz sein.")

        input_files = list(files)
        self.config = config
        self._job_state = ConverterJobState.from_config(config)
        self._control_state = ConverterControlState()
        self._session_state = ConverterSessionState(all_input_files=input_files)
        self._queue = ConverterQueueState(input_files)
        self.files = self._queue.files
        self._files_lock = self._queue.lock
        self._runtime_state = WorkerRuntimeState(total_count=self._queue.initial_total)
        self._temp_state = DVTempState()

        # GPU-Info für Log-Header: im Main-Thread ermitteln, nicht im Worker.
        try:
            from ..core.gpu_detection import detect_gpus, best_encoder
            self._log_gpu_list = [g.name for g in detect_gpus()]
            encoder = self._job_state.encoder_options.get("encoder", "cpu")
            self._log_enc_name = best_encoder() if encoder == "auto" else encoder
        except Exception:
            self._log_gpu_list = []
            self._log_enc_name = self._job_state.encoder_options.get("encoder", "cpu")

        self.settings = QSettings(APP_ORG, APP_NAME)
        self._logger = shared_logger or create_worker_logger(
            settings=self.settings,
            log_file_path=config.log_file_path,
            gui_callback=self.log_line.emit,
        )
        self.log_file_path = str(self._logger.log_file) if self._logger.log_file else None
        self._verbose_logger = create_verbose_logger(settings=self.settings)

        self._services = build_static_converter_services(
            self,
            job=self._job_state,
            settings=self.settings,
            logger=self._logger,
            runtime_state=self._runtime_state,
            failure_details=self._session_state.failure_details,
        )

        # Run-spezifische Orchestratoren. Fachzustand liegt in den Contexts oben.
        self._runtime_builder = ConverterRuntimeBuilder(self)
        self._run_loop = ConverterRunLoop(self)
        self._lifecycle = ConverterLifecycleService(self)
        self._file_executor = ConverterFileExecutor(self)
        self._control = ConverterControlService(self, self._control_state)


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
            self.finished.emit()

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

    @property
    def _burn_sub_tmp(self) -> str | None:
        # Convenience-Property für converter_stream_args.py, das den Worker
        # als Parameter erhaelt und keinen direkten DVTempState-Zugriff hat.
        # WorkflowServices und HDRPlusConversionHelper greifen direkt auf
        # _temp_state zu – diese Property ist der letzte verbleibende Zugriffspunkt.
        return self._temp_state.burn_sub_tmp

    @_burn_sub_tmp.setter
    def _burn_sub_tmp(self, value: str | None) -> None:
        self._temp_state.burn_sub_tmp = value

    @property
    def _last_stderr(self) -> str:
        return self._temp_state.stderr

    @_last_stderr.setter
    def _last_stderr(self, value: str) -> None:
        self._temp_state.stderr = value
