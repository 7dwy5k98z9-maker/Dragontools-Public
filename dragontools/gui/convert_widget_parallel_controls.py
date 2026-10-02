"""Live worker limit and encoder-specific defaults in the converter UI."""
from __future__ import annotations

from PyQt6.QtCore import QObject, QSignalBlocker, QTimer
from PyQt6.QtWidgets import QLabel, QSpinBox

from ..core.parallel_settings import is_gpu_encoder, parallel_jobs_for_encoder
from ..core.settings_storage import (
    MAX_PARALLEL_JOBS, SET_KEY_PARALLEL_CPU_JOBS, SET_KEY_PARALLEL_GPU_JOBS,
)

_TOOLTIP = (
    "Maximale Zahl gleichzeitig konvertierter Dateien (1 = nacheinander). "
    "Eine Erhöhung startet wartende Dateien sofort; beim Reduzieren laufen aktive Dateien fertig. "
    "Während Pause oder Abbruch starten keine neuen Dateien. "
    "DV/HDR-Nachbearbeitung kann zusätzlich weiterlaufen. "
    "Die Auswahl wird als CPU- bzw. GPU-Vorgabe gespeichert."
)


class ParallelWorkerControl(QObject):
    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.owner = owner
        self.spin = QSpinBox(owner)
        self.spin.setRange(1, MAX_PARALLEL_JOBS)
        self.spin.setMaximumWidth(65)
        self.spin.setKeyboardTracking(False)
        self.spin.setToolTip(_TOOLTIP)
        self.active_label = QLabel(owner)
        self.active_label.setToolTip("Aktuell konvertierte Dateien; Nachbearbeitung wird im Fortschritt separat angezeigt.")
        self.spin.valueChanged.connect(self._change_limit)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        # Main encoder widgets are bound after the layout has been built.
        QTimer.singleShot(0, self.refresh)

    def _worker(self):
        worker = getattr(self.owner._state, "thread", None)
        return worker if worker is not None and worker.isRunning() else None

    def _encoder(self, worker=None) -> str:
        if worker is not None:
            return str(getattr(worker, "encoder_options", {}).get("encoder", "cpu"))
        # The encoder panel may still be under construction at the first refresh.
        controller = getattr(self.owner, "_enc_settings", None)
        if controller is not None:
            return str(controller.active_encoder())
        return "cpu"

    def refresh(self) -> None:
        worker = self._worker()
        move_worker = getattr(self.owner._state, "move_thread", None)
        supported = worker is None or callable(getattr(worker, "set_parallel_jobs", None))
        moving = move_worker is not None and move_worker.isRunning()
        starting = bool(getattr(self.owner._state, "start_reserved", False)) and worker is None
        self.spin.setEnabled(supported and not moving and not starting)
        if worker is not None and supported:
            value = worker.parallel_jobs
            self.active_label.setText(f"{worker.encode_active_count()} aktiv")
        else:
            value = parallel_jobs_for_encoder(self.owner.settings, self._encoder(worker))
            self.active_label.clear()
        if self.spin.value() != int(value):
            with QSignalBlocker(self.spin):
                self.spin.setValue(int(value))

    def _change_limit(self, value: int) -> None:
        worker = self._worker()
        if worker is not None and not callable(getattr(worker, "set_parallel_jobs", None)):
            self.refresh()
            return
        try:
            if worker is not None:
                value = worker.set_parallel_jobs(value)
            key = SET_KEY_PARALLEL_GPU_JOBS if is_gpu_encoder(self._encoder(worker)) else SET_KEY_PARALLEL_CPU_JOBS
            self.owner.settings.setValue(key, int(value))
            self.owner.settings.sync()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self.owner.log_message(f"Worker-Anzahl konnte nicht geändert werden: {exc}", "warn")
        self.refresh()
