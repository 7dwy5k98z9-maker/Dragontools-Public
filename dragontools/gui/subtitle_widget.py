# -*- coding: utf-8 -*-
"""
Untertitel-Widget: UI-Orchestrierung für Extraktion, Injection und Konvertierung.
Die QThread-Worker und Drag-and-Drop-Dateiliste liegen in fokussierten Modulen.
"""
from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QFileDialog, QLineEdit, QCheckBox,
    QProgressBar, QTextEdit, QGroupBox, QComboBox, QFontComboBox, QSpinBox,
)
from PyQt6.QtGui import QFont, QPainter, QPixmap, QLinearGradient, QColor, QPen

from ..core.tool_paths import get_tool_paths
from .subtitle_widget_workers import _SubWorker, _ExtractWorker, _InjectWorker, _ConvertWorker
from .subtitle_widget_files import _FileDropList, _parse_exts

class SubtitleWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tools = get_tool_paths()
        self._workers: dict[str, _SubWorker] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_extract_tab(), "Extrahieren")
        tabs.addTab(self._build_inject_tab(),  "Einfügen")
        tabs.addTab(self._build_convert_tab(), "SRT → ASS")
        tabs.addTab(self._build_txt_tab(),     "→ TXT")
        tabs.addTab(self._build_txt_to_srt_tab(), "TXT → SRT")
        tabs.addTab(self._build_txt_to_ass_tab(), "TXT → ASS")
        root.addWidget(tabs)

    # ── Extrahieren ──────────────────────────────────────────────────

    def _build_extract_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        g = QGroupBox("Quell-Videos")
        gl = QVBoxLayout(g)
        self.ext_list = _FileDropList({"mkv", "mp4", "mov", "avi"})
        btn_row = QHBoxLayout()
        add_btn = QPushButton("➕ Dateien")
        add_btn.clicked.connect(lambda: self._add_videos(self.ext_list))
        clr_btn = QPushButton("🗑️ Leeren")
        clr_btn.clicked.connect(self.ext_list.clear)
        btn_row.addWidget(add_btn); btn_row.addWidget(clr_btn)
        gl.addWidget(self.ext_list); gl.addLayout(btn_row)
        v.addWidget(g)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Ausgabe-Ordner:"))
        self.ext_out = QLineEdit()
        browse_btn   = QPushButton("…")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(lambda: self._browse_dir(self.ext_out))
        out_row.addWidget(self.ext_out); out_row.addWidget(browse_btn)
        v.addLayout(out_row)

        self.ext_progress = QProgressBar()
        self.ext_log      = QTextEdit(); self.ext_log.setReadOnly(True); self.ext_log.setMaximumHeight(120)
        self.ext_start    = QPushButton("▶ Extrahieren starten")
        self.ext_cancel   = QPushButton("❌ Abbrechen"); self.ext_cancel.setEnabled(False)
        ctrl = QHBoxLayout(); ctrl.addWidget(self.ext_start); ctrl.addWidget(self.ext_cancel)
        v.addWidget(self.ext_progress); v.addWidget(self.ext_log); v.addLayout(ctrl)

        self.ext_start.clicked.connect(self._start_extract)
        self.ext_cancel.clicked.connect(lambda: self._cancel_worker("extract"))
        return w

    def _start_extract(self) -> None:
        try:
            files   = [self.ext_list.item(i).data(Qt.ItemDataRole.UserRole)
                       for i in range(self.ext_list.count())]
            out_dir = self.ext_out.text().strip()
            if not files:
                return
            if not out_dir:
                out_dir = str(Path(files[0]).parent)
            worker = _ExtractWorker(files, out_dir, self.tools)
            self._wire("extract", worker, self.ext_progress, self.ext_log, self.ext_start, self.ext_cancel)
            worker.start()
        except Exception:
            self.ext_log.append("❌ Unbehandelte Ausnahme in _start_extract()")
            self.ext_log.append(traceback.format_exc())
            
    # ── Einfügen ─────────────────────────────────────────────────────

    def _build_inject_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        g = QGroupBox("Ziel-Videos")
        gl = QVBoxLayout(g)
        self.inj_list = _FileDropList({"mkv", "mp4", "mov", "avi"})
        br = QHBoxLayout()
        ab = QPushButton("➕ Videos"); ab.clicked.connect(lambda: self._add_videos(self.inj_list))
        cb = QPushButton("🗑️ Leeren"); cb.clicked.connect(self.inj_list.clear)
        br.addWidget(ab); br.addWidget(cb)
        gl.addWidget(self.inj_list); gl.addLayout(br)
        v.addWidget(g)

        sub_row = QHBoxLayout()
        sub_row.addWidget(QLabel("Untertitel-Datei:"))
        self.inj_sub  = QLineEdit()
        self.inj_sub.setPlaceholderText("Leer lassen: passende Untertitel neben den Videos suchen")
        sub_btn       = QPushButton("…"); sub_btn.setFixedWidth(30)
        sub_btn.clicked.connect(lambda: self._browse_file(self.inj_sub, "Untertitel (*.srt *.ass *.sup)"))
        sub_row.addWidget(self.inj_sub); sub_row.addWidget(sub_btn)
        v.addLayout(sub_row)

        opt = QHBoxLayout()
        opt.addWidget(QLabel("Sprache:"))
        self.inj_lang = QComboBox()
        self.inj_lang.addItem("Deutsch", "deu")
        self.inj_lang.addItem("Englisch", "eng")
        self.inj_forced = QCheckBox("Forced")
        opt.addWidget(self.inj_lang); opt.addWidget(self.inj_forced); opt.addStretch()
        v.addLayout(opt)
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Titelname:"))
        self.inj_title = QComboBox()
        self.inj_title.setEditable(True)
        self.inj_title.addItems(["Deutsch", "Deutsch GPT"])
        self.inj_title.setToolTip("Frei editierbarer Spurtitel, z. B. Deutsch GPT oder Custom.")
        self.inj_lang.currentIndexChanged.connect(self._inject_language_changed)
        title_row.addWidget(self.inj_title)
        v.addLayout(title_row)

        self.inj_progress = QProgressBar()
        self.inj_log      = QTextEdit(); self.inj_log.setReadOnly(True); self.inj_log.setMaximumHeight(120)
        self.inj_start    = QPushButton("▶ Einfügen starten")
        self.inj_cancel   = QPushButton("❌ Abbrechen"); self.inj_cancel.setEnabled(False)
        ctrl = QHBoxLayout(); ctrl.addWidget(self.inj_start); ctrl.addWidget(self.inj_cancel)
        v.addWidget(self.inj_progress); v.addWidget(self.inj_log); v.addLayout(ctrl)

        self.inj_start.clicked.connect(self._start_inject)
        self.inj_cancel.clicked.connect(lambda: self._cancel_worker("inject"))
        return w

    def _inject_language_changed(self) -> None:
        title = self.inj_title.currentText()
        if title in {"Deutsch", "Englisch"}:
            self.inj_title.setEditText("Deutsch" if self.inj_lang.currentData() == "deu" else "Englisch")

    def _start_inject(self) -> None:
        try:
            files = [self.inj_list.item(i).data(Qt.ItemDataRole.UserRole)
                     for i in range(self.inj_list.count())]
            sub   = self.inj_sub.text().strip()
            if not files:
                return
            worker = _InjectWorker(
                files, sub, self.inj_lang.currentData(),
                self.inj_forced.isChecked(), self.tools,
                title=self.inj_title.currentText().strip() or ("Deutsch" if self.inj_lang.currentData() == "deu" else "Englisch"),
            )
            self._wire("inject", worker, self.inj_progress, self.inj_log, self.inj_start, self.inj_cancel)
            worker.start()
        except Exception:
            self.inj_log.append("❌ Unbehandelte Ausnahme in _start_inject()")
            self.inj_log.append(traceback.format_exc())
            
    # ── SRT → ASS ────────────────────────────────────────────────────

    def _build_convert_tab(self) -> QWidget:
        return self._simple_convert_tab("srt2ass", "SRT → ASS",
                                        "SRT-Dateien (*.srt)")

    # ── → TXT ────────────────────────────────────────────────────────

    def _build_txt_tab(self) -> QWidget:
        return self._simple_convert_tab("sub2txt", "Untertitel → TXT",
                                        "Untertitel (*.srt *.ass *.txt)")

    # ── TXT → SRT / ASS ─────────────────────────────────────────────

    def _build_txt_to_srt_tab(self) -> QWidget:
        return self._simple_convert_tab("txt2srt", "TXT → SRT",
                                        "TXT-Dateien (*.txt)")

    def _build_txt_to_ass_tab(self) -> QWidget:
        return self._simple_convert_tab("txt2ass", "TXT → ASS",
                                        "TXT-Dateien (*.txt)")

    def _build_subtitle_style_controls(self, mode: str) -> tuple[QWidget, QFontComboBox, QSpinBox, QLabel]:
        box = QGroupBox("Darstellung")
        layout = QVBoxLayout(box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Schriftart:"))
        font_combo = QFontComboBox()
        font_combo.setCurrentFont(QFont("Arial"))
        row.addWidget(font_combo, 1)
        row.addWidget(QLabel("Größe:"))
        size_spin = QSpinBox()
        size_spin.setRange(8, 200)
        size_spin.setValue(22)
        size_spin.setSuffix(" px")
        row.addWidget(size_spin)
        layout.addLayout(row)

        if mode == "txt2srt":
            note = QLabel(
                "Hinweis: SRT speichert keine Schriftart oder Schriftgröße. "
                "Die Einstellung dient hier nur der Vorschau; bei ASS wird sie in die Datei geschrieben."
            )
            note.setWordWrap(True)
            layout.addWidget(note)

        preview = QLabel()
        preview.setMinimumHeight(210)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setToolTip("16:9-Beispielbild zur Beurteilung der Untertitelgröße")
        layout.addWidget(preview)

        def update_preview(*_args) -> None:
            self._render_subtitle_preview(
                preview, font_combo.currentFont().family(), size_spin.value()
            )

        font_combo.currentFontChanged.connect(update_preview)
        size_spin.valueChanged.connect(update_preview)
        update_preview()
        return box, font_combo, size_spin, preview

    @staticmethod
    def _render_subtitle_preview(label: QLabel, font_family: str, font_size: int) -> None:
        width, height = 640, 360
        pixmap = QPixmap(width, height)
        painter = QPainter(pixmap)
        try:
            gradient = QLinearGradient(0, 0, 0, height)
            gradient.setColorAt(0.0, QColor(45, 65, 90))
            gradient.setColorAt(0.55, QColor(80, 95, 105))
            gradient.setColorAt(1.0, QColor(28, 33, 38))
            painter.fillRect(0, 0, width, height, gradient)

            # Simple generated sample frame: no external image dependency.
            painter.fillRect(0, int(height * 0.58), width, int(height * 0.42), QColor(20, 35, 24))
            painter.setPen(QPen(QColor(150, 160, 170), 2))
            painter.drawLine(0, int(height * 0.58), width, int(height * 0.58))

            # Scale ASS-like 1080p font values into the 360p preview.
            scaled_size = max(7, int(round(int(font_size) * (height / 1080.0))))
            font = QFont(font_family or "Arial")
            font.setPixelSize(scaled_size)
            font.setBold(False)
            painter.setFont(font)
            text = "Beispiel-Untertitel\nSo wirkt Schriftart und Größe im Bild"
            rect = QRect(30, int(height * 0.70), width - 60, int(height * 0.24))

            # Draw an outline for video readability, then the white glyphs.
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                painter.setPen(QColor(0, 0, 0))
                painter.drawText(rect.translated(dx, dy), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, text)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, text)
        finally:
            painter.end()
        label.setPixmap(
            pixmap.scaled(
                max(320, label.width() if label.width() > 0 else width),
                max(180, label.height() if label.height() > 0 else height),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _simple_convert_tab(self, mode: str, title: str, filt: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        lst = _FileDropList(_parse_exts(filt))
        br  = QHBoxLayout()
        ab  = QPushButton("➕ Dateien")
        cb  = QPushButton("🗑️ Leeren")
        ab.clicked.connect(lambda: self._add_subtitles(lst, filt))
        cb.clicked.connect(lst.clear)
        br.addWidget(ab); br.addWidget(cb)
        v.addWidget(QLabel(f"<b>{title}</b>"))
        v.addWidget(lst); v.addLayout(br)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Ausgabe-Ordner:"))
        out_edit = QLineEdit()
        ob = QPushButton("…"); ob.setFixedWidth(30)
        ob.clicked.connect(lambda: self._browse_dir(out_edit))
        out_row.addWidget(out_edit); out_row.addWidget(ob)
        v.addLayout(out_row)

        font_combo = None
        size_spin = None
        if mode in {"srt2ass", "txt2srt", "txt2ass"}:
            style_box, font_combo, size_spin, _preview = self._build_subtitle_style_controls(mode)
            v.addWidget(style_box)

        prog   = QProgressBar()
        log    = QTextEdit(); log.setReadOnly(True); log.setMaximumHeight(120)
        start  = QPushButton(f"▶ {title} starten")
        cancel = QPushButton("❌ Abbrechen"); cancel.setEnabled(False)
        ctrl   = QHBoxLayout(); ctrl.addWidget(start); ctrl.addWidget(cancel)
        v.addWidget(prog); v.addWidget(log); v.addLayout(ctrl)

        def _go():
            try:
                files = [lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lst.count())]
                out   = out_edit.text().strip()
                if not files:
                    return
                if not out:
                    out = str(Path(files[0]).parent)
                worker = _ConvertWorker(
                    files, mode, out,
                    font_family=(font_combo.currentFont().family() if font_combo is not None else "Arial"),
                    font_size=(size_spin.value() if size_spin is not None else 22),
                )
                self._wire(mode, worker, prog, log, start, cancel)
                worker.start()
            except Exception:
                log.append("❌ Unbehandelte Ausnahme in SubtitleWidget._go()")
                log.append(traceback.format_exc())

        start.clicked.connect(_go)
        cancel.clicked.connect(lambda _checked=False, key=mode: self._cancel_worker(key))
        return w

    # ── Hilfsmethoden ────────────────────────────────────────────────

    def _wire(self, job_key: str, worker: _SubWorker, progress: QProgressBar,
              log: QTextEdit, start: QPushButton, cancel: QPushButton) -> None:
        current = self._workers.get(job_key)
        if current is not None and current.isRunning():
            raise RuntimeError(f"Subtitle-Aufgabe '{job_key}' läuft bereits.")

        self._workers[job_key] = worker
        worker.log.connect(log.append)
        worker.progress.connect(lambda d, t: progress.setValue(int(d / max(1, t) * 100)))
        worker.done.connect(lambda: (start.setEnabled(True), cancel.setEnabled(False)))
        worker.finished.connect(lambda key=job_key, ref=worker: self._release_worker(key, ref))
        worker.finished.connect(worker.deleteLater)
        start.setEnabled(False)
        cancel.setEnabled(True)

    def _release_worker(self, job_key: str, worker: _SubWorker) -> None:
        if self._workers.get(job_key) is worker:
            self._workers.pop(job_key, None)

    def _cancel_worker(self, job_key: str) -> None:
        worker = self._workers.get(job_key)
        if worker is not None and worker.isRunning():
            worker.cancel()

    def iter_shutdown_workers(self) -> tuple:
        return tuple(self._workers.values())

    def _add_videos(self, lst: QListWidget) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Videos wählen", "",
            "Videodateien (*.mkv *.mp4 *.mov *.avi);;Alle (*)"
        )
        for f in files:
            item = QListWidgetItem(Path(f).name)
            item.setData(Qt.ItemDataRole.UserRole, f)
            lst.addItem(item)

    def _add_subtitles(self, lst: QListWidget, filt: str) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Dateien wählen", "", filt)
        for f in files:
            item = QListWidgetItem(Path(f).name)
            item.setData(Qt.ItemDataRole.UserRole, f)
            lst.addItem(item)

    def _browse_dir(self, edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Ordner wählen")
        if d:
            edit.setText(d)

    def _browse_file(self, edit: QLineEdit, filt: str) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Datei wählen", "", filt)
        if f:
            edit.setText(f)
