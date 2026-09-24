# -*- coding: utf-8 -*-
"""Controller for media-library issue discovery and the session Fix Queue."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import QMessageBox, QTableWidgetItem

from ..core.media_library_fix_queue import MediaLibraryFixIssue, dedupe_fix_issues
from ..core.settings_media_library import (
    DEFAULT_MEDIA_LIBRARY_LANGUAGE_AUDIO_SAMPLES,
    DEFAULT_MEDIA_LIBRARY_LANGUAGE_MIN_CONFIDENCE,
    DEFAULT_MEDIA_LIBRARY_LANGUAGE_MODEL,
    DEFAULT_MEDIA_LIBRARY_LANGUAGE_SAMPLE_SECONDS,
    DEFAULT_MEDIA_LIBRARY_OCR_LANGUAGES,
    DEFAULT_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE,
    SET_KEY_MEDIA_LIBRARY_LANGUAGE_AUDIO_SAMPLES,
    SET_KEY_MEDIA_LIBRARY_LANGUAGE_MIN_CONFIDENCE,
    SET_KEY_MEDIA_LIBRARY_LANGUAGE_MODEL,
    SET_KEY_MEDIA_LIBRARY_LANGUAGE_SAMPLE_SECONDS,
    SET_KEY_MEDIA_LIBRARY_OCR_LANGUAGES,
    SET_KEY_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE,
)
from .bitmap_subtitle_ocr_review import BitmapSubtitleOcrReviewDialog
from .media_library_fix_worker import MediaLibraryFixDiscoveryThread, MediaLibraryFixWorker


class MediaLibraryFixController:
    def __init__(
        self,
        *,
        parent,
        view,
        service,
        settings,
        get_db_path: Callable[[], str],
        refresh_stats: Callable[[], None],
        other_task_running: Callable[[], bool],
    ) -> None:
        self._parent = parent
        self._view = view
        self._service = service
        self._settings = settings
        self._get_db_path = get_db_path
        self._refresh_stats = refresh_stats
        self._other_task_running = other_task_running
        self._issues: list[MediaLibraryFixIssue] = []
        self._queue: list[MediaLibraryFixIssue] = []
        self._results: dict[str, tuple[str, str]] = {}
        self._outcomes: dict[str, object] = {}
        self._discovery: MediaLibraryFixDiscoveryThread | None = None
        self._worker: MediaLibraryFixWorker | None = None
        self._load_settings()

    @property
    def is_running(self) -> bool:
        return self._discovery is not None or self._worker is not None

    def scan(self) -> None:
        if self.is_running or self._other_task_running():
            QMessageBox.information(self._parent, "Fix Queue", "Es läuft bereits eine Mediathek-Aufgabe.")
            return
        self._view.fix_issue_label.setText("Mediathek-Probleme werden geprüft …")
        self._set_running(True, allow_abort=False)
        categories = self._selected_categories()
        if not categories:
            QMessageBox.information(self._parent, "Fix Queue", "Bitte mindestens eine Problemkategorie auswählen.")
            self._view.fix_issue_label.setText("Keine Problemkategorie ausgewählt.")
            self._set_running(False, allow_abort=False)
            return
        thread = MediaLibraryFixDiscoveryThread(
            service=self._service,
            db_path=self._get_db_path(),
            categories=categories,
            parent=self._parent,
        )
        self._discovery = thread
        thread.completed.connect(self._on_discovery_completed)
        thread.finished.connect(self._on_discovery_finished)
        thread.start()

    def _selected_categories(self) -> set[str]:
        categories: set[str] = set()
        if self._view.fix_nfo_cb.isChecked():
            categories.add("nfo")
        if self._view.fix_trickplay_cb.isChecked():
            categories.add("trickplay")
        if self._view.fix_metadata_cb.isChecked():
            categories.add("metadata")
        if self._view.fix_streams_cb.isChecked():
            categories.add("streams")
        if self._view.fix_ocr_cb.isChecked():
            categories.add("ocr")
        return categories

    def _load_settings(self) -> None:
        model = self._settings.value(
            SET_KEY_MEDIA_LIBRARY_LANGUAGE_MODEL,
            DEFAULT_MEDIA_LIBRARY_LANGUAGE_MODEL,
            type=str,
        )
        self._view.fix_language_model_combo.setCurrentText(str(model or DEFAULT_MEDIA_LIBRARY_LANGUAGE_MODEL))
        self._view.fix_language_confidence_spin.setValue(self._setting_int(
            SET_KEY_MEDIA_LIBRARY_LANGUAGE_MIN_CONFIDENCE,
            DEFAULT_MEDIA_LIBRARY_LANGUAGE_MIN_CONFIDENCE,
        ))
        self._view.fix_language_samples_spin.setValue(self._setting_int(
            SET_KEY_MEDIA_LIBRARY_LANGUAGE_AUDIO_SAMPLES,
            DEFAULT_MEDIA_LIBRARY_LANGUAGE_AUDIO_SAMPLES,
        ))
        self._view.fix_language_seconds_spin.setValue(self._setting_int(
            SET_KEY_MEDIA_LIBRARY_LANGUAGE_SAMPLE_SECONDS,
            DEFAULT_MEDIA_LIBRARY_LANGUAGE_SAMPLE_SECONDS,
        ))
        self._view.fix_ocr_languages_edit.setText(str(self._settings.value(
            SET_KEY_MEDIA_LIBRARY_OCR_LANGUAGES,
            DEFAULT_MEDIA_LIBRARY_OCR_LANGUAGES,
            type=str,
        ) or DEFAULT_MEDIA_LIBRARY_OCR_LANGUAGES))
        self._view.fix_ocr_confidence_spin.setValue(self._setting_int(
            SET_KEY_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE,
            DEFAULT_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE,
        ))

    def save_settings(self) -> None:
        self._settings.setValue(SET_KEY_MEDIA_LIBRARY_LANGUAGE_MODEL, self._view.fix_language_model_combo.currentText())
        self._settings.setValue(SET_KEY_MEDIA_LIBRARY_LANGUAGE_MIN_CONFIDENCE, self._view.fix_language_confidence_spin.value())
        self._settings.setValue(SET_KEY_MEDIA_LIBRARY_LANGUAGE_AUDIO_SAMPLES, self._view.fix_language_samples_spin.value())
        self._settings.setValue(SET_KEY_MEDIA_LIBRARY_LANGUAGE_SAMPLE_SECONDS, self._view.fix_language_seconds_spin.value())
        self._settings.setValue(
            SET_KEY_MEDIA_LIBRARY_OCR_LANGUAGES,
            self._view.fix_ocr_languages_edit.text().strip() or DEFAULT_MEDIA_LIBRARY_OCR_LANGUAGES,
        )
        self._settings.setValue(SET_KEY_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE, self._view.fix_ocr_confidence_spin.value())
        self._settings.sync()

    def add_selected(self) -> None:
        rows = sorted({index.row() for index in self._view.fix_issue_table.selectionModel().selectedRows()})
        self._append_to_queue(self._issues[row] for row in rows if 0 <= row < len(self._issues))

    def add_all(self) -> None:
        self._append_to_queue(self._issues)

    def remove_selected(self) -> None:
        if self._worker is not None:
            return
        rows = sorted({index.row() for index in self._view.fix_queue_table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self._queue):
                issue = self._queue.pop(row)
                self._results.pop(issue.key, None)
                self._outcomes.pop(issue.key, None)
        self._render_queue()

    def clear(self) -> None:
        if self._worker is not None:
            return
        self._queue.clear()
        self._results.clear()
        self._outcomes.clear()
        self._render_queue()

    def run(self) -> None:
        if self.is_running or self._other_task_running():
            QMessageBox.information(self._parent, "Fix Queue", "Es läuft bereits eine Mediathek-Aufgabe.")
            return
        if not self._queue:
            QMessageBox.information(self._parent, "Fix Queue", "Die Fix Queue ist leer.")
            return
        self.save_settings()
        self._results.clear()
        self._outcomes.clear()
        self._render_queue()
        self._view.fix_progress.setValue(0)
        self._view.fix_status_label.setText(f"Fix Queue startet ({len(self._queue)} Einträge) …")
        worker = MediaLibraryFixWorker(
            db_path=self._get_db_path(),
            issues=list(self._queue),
            tools=self._service.tool_paths(self._settings),
            parent=self._parent,
        )
        self._worker = worker
        worker.item_started.connect(self._on_item_started)
        worker.item_finished.connect(self._on_item_finished)
        worker.log_line.connect(self._on_log)
        worker.completed.connect(self._on_completed)
        worker.finished.connect(self._on_worker_finished)
        self._set_running(True, allow_abort=True)
        worker.start()

    def abort(self) -> None:
        if self._worker is None:
            return
        self._worker.request_abort()
        self._view.fix_abort_btn.setEnabled(False)
        self._view.fix_status_label.setText("Fix Queue wird nach der aktuellen Aktion abgebrochen …")

    def review_selected_ocr_draft(self) -> None:
        if self._worker is not None:
            return
        rows = sorted({index.row() for index in self._view.fix_queue_table.selectionModel().selectedRows()})
        if len(rows) != 1 or not (0 <= rows[0] < len(self._queue)):
            QMessageBox.information(self._parent, "OCR-Untertitel", "Bitte genau einen OCR-Entwurf auswählen.")
            return
        issue = self._queue[rows[0]]
        outcome = self._outcomes.get(issue.key)
        report_path = str(getattr(outcome, "report_path", "") or "")
        if getattr(outcome, "status", "") != "review" or not report_path:
            QMessageBox.information(
                self._parent,
                "OCR-Untertitel",
                "Für den ausgewählten Eintrag liegt noch kein prüfbarer OCR-Entwurf vor.",
            )
            return
        try:
            dialog = BitmapSubtitleOcrReviewDialog(report_path, self._parent, expected_media=issue.path)
        except Exception as exc:
            QMessageBox.critical(self._parent, "OCR-Untertitel", str(exc))
            return
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        final_path = str(dialog.final_path or "")
        self._results[issue.key] = ("success", f"Geprüftes SRT gespeichert: {final_path}")
        self._outcomes.pop(issue.key, None)
        self._render_queue()
        self._refresh_stats()

    def _append_to_queue(self, issues) -> None:
        self._queue = dedupe_fix_issues([*self._queue, *list(issues)])
        self._render_queue()

    def _on_discovery_completed(self, result, error) -> None:
        if error is not None:
            self._issues = []
            self._render_issues()
            self._view.fix_issue_label.setText("Problemprüfung fehlgeschlagen.")
            QMessageBox.critical(self._parent, "Fix Queue", str(error))
            return
        self._issues = list(getattr(result, "issues", ()) or ())
        self._render_issues()
        suffix = " – Anzeige begrenzt; weitere Kandidaten vorhanden." if getattr(result, "truncated", False) else ""
        self._view.fix_issue_label.setText(
            f"{len(self._issues)} reparierbare Probleme in {getattr(result, 'scanned_media', 0)} Mediendateien gefunden{suffix}"
        )

    def _on_discovery_finished(self) -> None:
        thread = self._discovery
        self._discovery = None
        if thread is not None:
            thread.deleteLater()
        self._set_running(False, allow_abort=False)

    def _on_item_started(self, index: int, total: int, issue: MediaLibraryFixIssue) -> None:
        self._view.fix_status_label.setText(f"Fix {index}/{total}: {Path(issue.path).name} – {issue.action_label}")

    def _on_item_finished(self, index: int, total: int, outcome) -> None:
        self._results[outcome.issue.key] = (outcome.status, outcome.message)
        self._outcomes[outcome.issue.key] = outcome
        self._render_queue()
        self._view.fix_progress.setValue(int((index / max(1, total)) * 100))

    def _on_log(self, message: str) -> None:
        if message:
            self._view.fix_status_label.setText(message)

    def _on_completed(self, outcomes, aborted: bool) -> None:
        succeeded = sum(1 for item in outcomes if getattr(item, "status", "") == "success")
        failed = sum(1 for item in outcomes if getattr(item, "status", "") == "error")
        skipped = sum(1 for item in outcomes if getattr(item, "status", "") == "skipped")
        review = sum(1 for item in outcomes if getattr(item, "status", "") == "review")
        self._refresh_stats()
        if not aborted:
            self._view.fix_progress.setValue(100)
        state = "abgebrochen" if aborted else "abgeschlossen"
        self._view.fix_status_label.setText(
            f"Fix Queue {state}: {succeeded} erfolgreich, {review} OCR-Review offen, "
            f"{skipped} übersprungen, {failed} fehlgeschlagen."
        )

    def _on_worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_running(False, allow_abort=False)

    def _set_running(self, running: bool, *, allow_abort: bool) -> None:
        self._view.set_fix_running(running, allow_abort=allow_abort)

    def _render_issues(self) -> None:
        table = self._view.fix_issue_table
        table.setRowCount(len(self._issues))
        for row, issue in enumerate(self._issues):
            self._fill_issue_row(table, row, issue)

    def _render_queue(self) -> None:
        table = self._view.fix_queue_table
        table.setRowCount(len(self._queue))
        for row, issue in enumerate(self._queue):
            self._fill_issue_row(table, row, issue)
            status, message = self._results.get(issue.key, ("wartend", ""))
            table.setItem(row, 5, QTableWidgetItem(status))
            table.setItem(row, 6, QTableWidgetItem(message))
        if self._worker is None:
            self._view.fix_status_label.setText(
                "Fix Queue ist leer." if not self._queue else f"{len(self._queue)} Aktion(en) in der Fix Queue."
            )

    @staticmethod
    def _fill_issue_row(table, row: int, issue: MediaLibraryFixIssue) -> None:
        values = [
            issue.problem + (f" ({issue.detail})" if issue.detail else ""),
            issue.action_label,
            issue.title,
            issue.item_type,
            issue.path,
        ]
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value or "")))

    def _setting_int(self, key: str, default: int) -> int:
        try:
            return int(self._settings.value(key, default, type=int))
        except (AttributeError, TypeError, ValueError):
            return int(default)


__all__ = ["MediaLibraryFixController"]
