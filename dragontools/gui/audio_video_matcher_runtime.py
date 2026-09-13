# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from ..worker.audio_video_match_thread import AudioVideoMatchThread


class AudioVideoMatcherRuntimeMixin:
    """Owns worker creation, signal wiring, cancellation and lifecycle."""

    def _start_analyze(self) -> None:
        if not self._validate_paths(require_output=False):
            return
        self._analysis = None
        self._cut_results = []
        self.log.clear()
        self.progress.setValue(0)
        self._set_running(True)
        worker = AudioVideoMatchThread(
            "analyze",
            source_path=self.source_edit.text().strip(),
            target_path=self.target_edit.text().strip(),
            parent=self,
        )
        self._worker = worker
        self._wire_worker(worker)
        worker.analysis_ready.connect(self._analysis_ready)
        worker.start()

    def _start_refine(self) -> None:
        if self._analysis is None:
            QMessageBox.information(self, "Audio-Video-Matcher", "Bitte zuerst analysieren.")
            return
        if not self.cut_ranges.text().strip():
            QMessageBox.information(
                self,
                "Schnittbereiche",
                "Bitte mindestens einen ungefähren Schnittbereich eintragen.",
            )
            return
        self.progress.setValue(0)
        self._set_running(True)
        worker = AudioVideoMatchThread(
            "refine",
            source_path=self.source_edit.text().strip(),
            target_path=self.target_edit.text().strip(),
            mapping_result=self._analysis,
            cut_ranges_text=self.cut_ranges.text(),
            parent=self,
        )
        self._worker = worker
        self._wire_worker(worker)
        worker.cuts_ready.connect(self._cuts_ready)
        worker.start()

    def _start_create(self) -> None:
        if self._analysis is None:
            QMessageBox.information(self, "Audio-Video-Matcher", "Bitte zuerst analysieren.")
            return
        if not self._validate_paths(require_output=True):
            return
        if Path(self.output_edit.text().strip()).exists():
            QMessageBox.warning(
                self,
                "Ausgabe existiert",
                "Die Ausgabedatei existiert bereits.\nBitte einen neuen Namen wählen.",
            )
            return
        self.progress.setValue(0)
        self._set_running(True)
        worker = AudioVideoMatchThread(
            "create",
            source_path=self.source_edit.text().strip(),
            target_path=self.target_edit.text().strip(),
            output_path=self.output_edit.text().strip(),
            audio_stream_index=self._selected_audio_index(),
            mapping_result=self._analysis,
            cut_results=self._cut_results,
            parent=self,
        )
        self._worker = worker
        self._wire_worker(worker)
        worker.result_ready.connect(self._result_ready)
        worker.start()

    def _wire_worker(self, worker: AudioVideoMatchThread) -> None:
        worker.log_line.connect(self._log)
        worker.progress.connect(self.progress.setValue)
        worker.error.connect(self._error)
        worker.finished.connect(self._finished)

    def iter_shutdown_workers(self) -> tuple:
        return (self._worker,) if self._worker is not None else ()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _finished(self) -> None:
        self._set_running(False)
        self._worker = None

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "Audio-Video-Matcher", str(message))
