# -*- coding: utf-8 -*-
"""
Untertitel-Widget: UI-Orchestrierung für Extraktion, Injection und Konvertierung.
Die QThread-Worker und Drag-and-Drop-Dateiliste liegen in fokussierten Modulen.
"""
from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QFileDialog, QLineEdit, QCheckBox,
    QProgressBar, QTextEdit, QGroupBox,
)

from ..core.paths import get_tool_paths
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
        sub_btn       = QPushButton("…"); sub_btn.setFixedWidth(30)
        sub_btn.clicked.connect(lambda: self._browse_file(self.inj_sub, "Untertitel (*.srt *.ass *.sup)"))
        sub_row.addWidget(self.inj_sub); sub_row.addWidget(sub_btn)
        v.addLayout(sub_row)

        opt = QHBoxLayout()
        opt.addWidget(QLabel("Sprache:"))
        self.inj_lang = QLineEdit("de"); self.inj_lang.setFixedWidth(50)
        self.inj_forced = QCheckBox("Forced")
        opt.addWidget(self.inj_lang); opt.addWidget(self.inj_forced); opt.addStretch()
        v.addLayout(opt)

        self.inj_progress = QProgressBar()
        self.inj_log      = QTextEdit(); self.inj_log.setReadOnly(True); self.inj_log.setMaximumHeight(120)
        self.inj_start    = QPushButton("▶ Einfügen starten")
        self.inj_cancel   = QPushButton("❌ Abbrechen"); self.inj_cancel.setEnabled(False)
        ctrl = QHBoxLayout(); ctrl.addWidget(self.inj_start); ctrl.addWidget(self.inj_cancel)
        v.addWidget(self.inj_progress); v.addWidget(self.inj_log); v.addLayout(ctrl)

        self.inj_start.clicked.connect(self._start_inject)
        self.inj_cancel.clicked.connect(lambda: self._cancel_worker("inject"))
        return w

    def _start_inject(self) -> None:
        try:
            files = [self.inj_list.item(i).data(Qt.ItemDataRole.UserRole)
                     for i in range(self.inj_list.count())]
            sub   = self.inj_sub.text().strip()
            if not files or not sub:
                return
            worker = _InjectWorker(
                files, sub, self.inj_lang.text().strip() or "de",
                self.inj_forced.isChecked(), self.tools,
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
                worker = _ConvertWorker(files, mode, out)
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
