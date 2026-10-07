# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from ..worker.audio_video_match_thread import AudioVideoMatchThread
from .quality_worker_lifecycle import start_owned_quality_worker, connect_quality_worker


class AudioVideoMatcherRuntimeMixin:
    """Owns worker creation, signal wiring, cancellation and lifecycle."""

    def _start_analyze(self) -> None:
        if self._worker is not None:
            return
        if not self._validate_paths(require_output=False):
            return
        self._analysis = None
        self._cut_results = []
        self.log.clear()
        self.progress.setValue(0)
        factory = lambda: AudioVideoMatchThread(
            "analyze",
            source_path=self.source_edit.text().strip(),
            target_path=self.target_edit.text().strip(),
            parent=self,
        )
        start_owned_quality_worker(self, factory=factory, wire=self._wire_worker,
            set_running=self._set_running, report_error=self._error)

    def _start_refine(self) -> None:
        if self._worker is not None:
            return
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
        factory = lambda: AudioVideoMatchThread(
            "refine",
            source_path=self.source_edit.text().strip(),
            target_path=self.target_edit.text().strip(),
            mapping_result=self._analysis,
            cut_ranges_text=self.cut_ranges.text(),
            parent=self,
        )
        start_owned_quality_worker(self, factory=factory, wire=self._wire_worker,
            set_running=self._set_running, report_error=self._error)

    def _start_create(self) -> None:
        if self._worker is not None:
            return
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
        factory = lambda: AudioVideoMatchThread(
            "create",
            source_path=self.source_edit.text().strip(),
            target_path=self.target_edit.text().strip(),
            output_path=self.output_edit.text().strip(),
            audio_stream_index=self._selected_audio_index(),
            mapping_result=self._analysis,
            cut_results=self._cut_results,
            parent=self,
        )
        start_owned_quality_worker(self, factory=factory, wire=self._wire_worker,
            set_running=self._set_running, report_error=self._error)

    def _wire_worker(self, worker: AudioVideoMatchThread) -> None:
        connect_quality_worker(self, worker, log_line=self._log, progress=self.progress.setValue,
            error=self._error, finished=self._finished, result_ready=self._result_ready,
            analysis_ready=self._analysis_ready, cuts_ready=self._cuts_ready)

    def iter_shutdown_workers(self) -> tuple:
        return (self._worker,) if self._worker is not None else ()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _finished(self) -> None:
        self._worker = None
        self._set_running(False)

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "Audio-Video-Matcher", str(message))
