from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QComboBox,
    QProgressBar,
    QTextEdit,
    QFileDialog,
    QMessageBox,
)

from ..worker.merge_thread import MergeThread


class MergeWidget(QWidget):
    """Lokales Widget für konservatives, verlustfreies Merge."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.file_list: QListWidget | None = None
        self.output_edit: QLineEdit | None = None
        self.mode_combo: QComboBox | None = None
        self.result_label: QLabel | None = None
        self.progress_bar: QProgressBar | None = None
        self.log_edit: QTextEdit | None = None
        self._btn_add: QPushButton | None = None
        self._btn_remove: QPushButton | None = None
        self._btn_clear: QPushButton | None = None
        self._btn_check: QPushButton | None = None
        self._btn_browse: QPushButton | None = None
        self._btn_start: QPushButton | None = None
        self._btn_abort: QPushButton | None = None
        self._worker: MergeThread | None = None
        self._worker_mode: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        info = QLabel(
            "Konservatives Merge für Videodateien. "
            "Lossless wird nur bei klarer Kompatibilität freigegeben. "
            "Produktiv freigegeben ist nur der MKV-Lossless-Pfad."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        root.addWidget(QLabel("Dateireihenfolge:"))
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.setAlternatingRowColors(True)
        root.addWidget(self.file_list)

        file_btns = QHBoxLayout()
        self._btn_add = QPushButton("Dateien hinzufügen")
        self._btn_add.clicked.connect(self._add_files)
        self._btn_remove = QPushButton("Entfernen")
        self._btn_remove.clicked.connect(self._remove_selected)
        self._btn_clear = QPushButton("Leeren")
        self._btn_clear.clicked.connect(self._clear_files)
        self._btn_check = QPushButton("Kompatibilität prüfen")
        self._btn_check.clicked.connect(self._check_compatibility)
        file_btns.addWidget(self._btn_add)
        file_btns.addWidget(self._btn_remove)
        file_btns.addWidget(self._btn_clear)
        file_btns.addWidget(self._btn_check)
        file_btns.addStretch(1)
        root.addLayout(file_btns)

        self.result_label = QLabel("Ergebnis: noch nicht geprüft")
        self.result_label.setWordWrap(True)
        root.addWidget(self.result_label)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Modus:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["lossless"])
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Zieldatei:"))
        self.output_edit = QLineEdit()
        out_row.addWidget(self.output_edit)
        self._btn_browse = QPushButton("Durchsuchen")
        self._btn_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._btn_browse)
        root.addLayout(out_row)

        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("Merge starten")
        self._btn_start.clicked.connect(self._start)
        self._btn_abort = QPushButton("Abbrechen")
        self._btn_abort.clicked.connect(self._abort)
        self._btn_abort.setEnabled(False)
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_abort)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        root.addWidget(self.progress_bar)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        root.addWidget(self.log_edit)

    def _append_log(self, text: str) -> None:
        if self.log_edit is not None:
            self.log_edit.append(text)

    def _collect_files(self) -> list[str]:
        if self.file_list is None:
            return []
        return [
            str(self.file_list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.file_list.count())
        ]

    def _add_files(self) -> None:
        if self.file_list is None:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Videodateien wählen",
            "",
            "Video-Dateien (*.mkv *.mp4 *.m4v);;Alle Dateien (*)",
        )
        if not files:
            return

        existing = {
            str(self.file_list.item(i).data(Qt.ItemDataRole.UserRole)).lower()
            for i in range(self.file_list.count())
        }
        added = 0
        for raw in files:
            path = str(Path(raw).resolve())
            if path.lower() in existing:
                continue
            item = QListWidgetItem(Path(path).name)
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.file_list.addItem(item)
            existing.add(path.lower())
            added += 1

        if added:
            self._append_log(f"ℹ️  {added} Datei(en) hinzugefügt.")

    def _remove_selected(self) -> None:
        if self.file_list is None:
            return
        rows = sorted({idx.row() for idx in self.file_list.selectedIndexes()}, reverse=True)
        for row in rows:
            self.file_list.takeItem(row)
        if rows:
            self._append_log(f"ℹ️  {len(rows)} Datei(en) entfernt.")

    def _clear_files(self) -> None:
        if self.file_list is not None:
            count = self.file_list.count()
            self.file_list.clear()
            if count:
                self._append_log("ℹ️  Dateiliste geleert.")
        if self.result_label is not None:
            self.result_label.setText("Ergebnis: noch nicht geprüft")

    def _browse_output(self) -> None:
        if self.output_edit is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Zieldatei wählen",
            self.output_edit.text(),
            "MKV-Datei (*.mkv)",
        )
        if path:
            self.output_edit.setText(path)

    def _validate_output_path(self, output_path: str) -> bool:
        if Path(output_path).suffix.lower() != ".mkv":
            QMessageBox.warning(
                self,
                "Nicht verfügbar",
                "Lossless Merge ist aktuell nur für MKV implementiert.",
            )
            return False
        return True

    def _set_running(self, running: bool) -> None:
        for widget in (
            self.file_list,
            self.output_edit,
            self.mode_combo,
            self._btn_add,
            self._btn_remove,
            self._btn_clear,
            self._btn_check,
            self._btn_browse,
            self._btn_start,
        ):
            if widget is not None:
                widget.setEnabled(not running)
        if self._btn_abort is not None:
            self._btn_abort.setEnabled(running)

    def _set_check_result(self, ok: bool, reasons: list[str]) -> None:
        if self.result_label is None:
            return
        if ok:
            self.result_label.setText("Ergebnis: Lossless möglich")
            return
        text = "Ergebnis: Lossless nicht möglich"
        if reasons:
            text += "\n- " + "\n- ".join(reasons)
        self.result_label.setText(text)

    def _check_compatibility(self) -> None:
        try:
            files = self._collect_files()
            if len(files) < 2:
                QMessageBox.warning(self, "Zu wenige Dateien", "Bitte mindestens zwei Dateien hinzufügen.")
                return
            output_path = self.output_edit.text().strip() if self.output_edit is not None else ""
            if not output_path:
                QMessageBox.warning(self, "Keine Zieldatei", "Bitte zuerst eine Zieldatei wählen.")
                return
            if not self._validate_output_path(output_path):
                return

            self._append_log("")
            self._append_log("Prüfe Lossless-Kompatibilität ...")
            if self.progress_bar is not None:
                self.progress_bar.setValue(0)
            self._worker = MergeThread(
                files=files,
                output_path=output_path,
                mode="check_only",
                parent=self,
            )
            self._worker_mode = "check_only"
            self._worker.log_line.connect(self._append_log)
            self._worker.progress.connect(self._on_progress)
            self._worker.file_progress.connect(self._on_file_progress)
            self._worker.file_result.connect(self._on_file_result)
            self._worker.finished.connect(self._on_finished)
            self._set_running(True)
            self._worker.start()
        except Exception:
            self._append_log("Unbehandelte Ausnahme in _check_compatibility()")
            self._append_log(traceback.format_exc())
            self._set_check_result(False, ["Kompatibilitätsprüfung fehlgeschlagen."])

    def _start(self) -> None:
        try:
            files = self._collect_files()
            if len(files) < 2:
                QMessageBox.warning(self, "Zu wenige Dateien", "Bitte mindestens zwei Dateien hinzufügen.")
                return

            output_path = self.output_edit.text().strip() if self.output_edit is not None else ""
            if not output_path:
                QMessageBox.warning(self, "Keine Zieldatei", "Bitte eine Zieldatei wählen.")
                return
            if not self._validate_output_path(output_path):
                return

            mode = self.mode_combo.currentText().strip() if self.mode_combo is not None else "lossless"
            if self.progress_bar is not None:
                self.progress_bar.setValue(0)

            self._worker = MergeThread(
                files=files,
                output_path=output_path,
                mode=mode,
                parent=self,
            )
            self._worker_mode = mode
            self._worker.log_line.connect(self._append_log)
            self._worker.progress.connect(self._on_progress)
            self._worker.file_progress.connect(self._on_file_progress)
            self._worker.file_result.connect(self._on_file_result)
            self._worker.finished.connect(self._on_finished)

            self._set_running(True)
            self._append_log("")
            self._append_log(f"▶️ Starte Merge im Modus '{mode}'")
            self._worker.start()
        except Exception:
            self._append_log("Unbehandelte Ausnahme in _start()")
            self._append_log(traceback.format_exc())
            self._set_running(False)

    def iter_shutdown_workers(self) -> tuple:
        return (self._worker,) if self._worker is not None else ()

    def _abort(self) -> None:
        if self._worker is not None:
            self._worker.request_abort()
            self._append_log("⚠️  Abbruch angefordert ...")

    def _on_progress(self, pct: int) -> None:
        if self.progress_bar is not None:
            self.progress_bar.setValue(pct)

    def _on_file_progress(self, path: str, pct: int, obj) -> None:
        if self.progress_bar is not None:
            self.progress_bar.setValue(pct)
        if isinstance(obj, dict) and "lossless_possible" in obj:
            reasons = list(obj.get("reasons", []) or [])
            self._set_check_result(bool(obj.get("lossless_possible")), reasons)
            if bool(obj.get("lossless_possible")):
                self._append_log("✅ Lossless möglich.")
            else:
                self._append_log("⚠️  Lossless nicht möglich.")
                for reason in reasons:
                    self._append_log(f"  - {reason}")
        elif isinstance(obj, str) and obj:
            self._append_log(f"ℹ️  {Path(path).name}: {obj} ({pct}%)")

    def _on_file_result(self, path: str, success: bool, message: str) -> None:
        icon = "✅" if success else "❌"
        self._append_log(f"{icon} {Path(path).name if path else 'Merge'} → {message}")

    def _on_finished(self) -> None:
        self._set_running(False)
        self._append_log("")
        if self._worker_mode == "check_only":
            self._append_log("🏁 Kompatibilitätsprüfung abgeschlossen.")
        else:
            self._append_log("🏁 Merge abgeschlossen.")
        self._worker = None
        self._worker_mode = None
