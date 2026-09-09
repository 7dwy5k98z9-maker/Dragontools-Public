# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy, QTextEdit,
    QVBoxLayout,
)
from .convert_widget_custom_widgets import DragonProgressBar
from .convert_widget_layout_components import CollapsibleGroupBox, FileListBannerOverlay

class ConvertWidgetLayoutRuntimeMixin:
    def _build_file_list_section(self, root: QVBoxLayout) -> None:
        # Kein QGroupBox-Titel mehr: spart Höhe und vermeidet den unnötigen Text
        # "Dateien – Drag & Drop oder Ordner wählen (Entf = Entfernen)".
        lg = QFrame()
        ll = QVBoxLayout(lg)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)
        # Wichtig: file_list ist eine read-only @property auf ConvertWidget
        # (delegiert nach self._ui.file_list). Der Builder darf den Namen
        # daher NICHT auf self.w setzen – er speichert die Referenz intern
        # und übergibt sie in _make_ui_bundle direkt an ConvertWidgetUI.
        self._file_list_overlay = FileListBannerOverlay()
        self._file_list = self._file_list_overlay.file_list
        ll.addWidget(self._file_list_overlay)
        button_row = QHBoxLayout()
        self.w.add_files_btn  = QPushButton("\u2795 Dateien")
        self.w.add_folder_btn = QPushButton("\U0001F4C1 Ordner")
        self.w.remove_btn     = QPushButton("\u2796 Entfernen")
        self.w.clear_btn      = QPushButton("\U0001F5D1\ufe0f Alle")
        button_row.addWidget(self.w.add_files_btn)
        button_row.addWidget(self.w.add_folder_btn)
        button_row.addWidget(self.w.remove_btn)
        button_row.addWidget(self.w.clear_btn)
        ll.addLayout(button_row)

        # Nur die Dateiliste soll bei hoeherem Fenster vertikal mitwachsen.
        # Ohne Stretch-Faktor verteilt QVBoxLayout freien Platz auch an die
        # nachfolgenden Bereiche (insbesondere den Log-Container).
        lg.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        root.addWidget(lg, 1)

    def _build_controls_section(self, root: QVBoxLayout) -> None:
        start_row = QHBoxLayout()
        self.w.start_btn = QPushButton("\U0001F504 Konvertierung starten")
        self.w.start_btn.setMinimumHeight(34)
        self.w.start_btn.setStyleSheet("font-weight:bold;font-size:13px;")
        self.w.dv_remux_btn = QPushButton("\U0001F4E6 DV-Remux")
        self.w.dv_remux_btn.setMinimumHeight(34)
        self.w.dv_remux_btn.setToolTip(
            "Dolby-Vision-Dateien ohne Video-Re-Encoding remuxen.\n"
            "Der Zielcontainer (MP4/MKV) folgt der Dolby-Vision-Containerwahl in den Einstellungen."
        )
        self.w.dv_remux_btn.setStyleSheet("font-size:12px;")
        self.w.move_only_btn = QPushButton("\U0001F69A Nur verschieben")
        self.w.move_only_btn.setMinimumHeight(34)
        self.w.move_only_btn.setToolTip(
            "Move-Only Modus: Keine Konvertierung.\n"
            "Öffnet den Preflight-Dialog zur Zielordner-Auswahl\n"
            "und verschiebt die Dateien danach direkt.\n"
            "Der Verschiebebericht wird trotzdem erstellt."
        )
        self.w.move_only_btn.setStyleSheet("font-size:12px;")
        start_row.addWidget(self.w.start_btn, 3)
        start_row.addWidget(self.w.dv_remux_btn, 2)
        start_row.addWidget(self.w.move_only_btn, 2)
        root.addLayout(start_row)

        action_row = QHBoxLayout()
        self.w.move_finished_btn = QPushButton("📦 Fertige verschieben")
        self.w.move_finished_btn.setEnabled(False)
        self.w.move_finished_btn.setToolTip(
            "Verschiebt nur bereits erfolgreich abgeschlossene Dateien.\n"
            "Die aktuell laufende Datei und Fehlerdateien werden ignoriert.\n"
            "Verwendet dieselben Zielordner, Preflight-Daten und Konfliktregeln "
            "wie das normale Verschieben nach Abschluss."
        )
        self.w.pause_btn = QPushButton("\u23f8 Pause")
        self.w.pause_btn.setEnabled(False)
        self.w.abort_combo = QComboBox()
        self.w.abort_combo.addItems(["Sofort abbrechen", "Nach Datei abbrechen"])
        self.w.abort_btn = QPushButton("\u274c Abbrechen")
        self.w.abort_btn.setEnabled(False)
        action_row.addWidget(self.w.move_finished_btn, 1)
        action_row.addWidget(self.w.pause_btn, 1)
        action_row.addWidget(self.w.abort_combo, 2)
        action_row.addWidget(self.w.abort_btn, 1)
        root.addLayout(action_row)

    def _build_progress_section(self, root: QVBoxLayout) -> None:
        # Fortschritt ist jetzt einklappbar, bleibt aber standardmäßig geöffnet.
        # Dadurch bleibt die aktuelle Arbeitsansicht unverändert und kann bei Bedarf
        # platzsparend geschlossen werden.
        prg = CollapsibleGroupBox(
            "📊 Fortschritt",
            collapsed=False,
            settings=self.settings,
            section_id="convert/progress",
        )
        self.w.file_lbl  = QLabel("")
        self.w.file_focus_combo = QComboBox()
        self.w.file_focus_combo.setMinimumWidth(260)
        self.w.file_focus_combo.setToolTip(
            "Bei paralleler Bearbeitung: kombinierten Fortschritt anzeigen "
            "oder eine aktive Datei gezielt fokussieren."
        )
        self.w.file_focus_combo.setVisible(False)
        self.w.file_bar  = DragonProgressBar()
        self.w.file_bar.setFormat("%p%  \u2013  aktuelle Datei")
        self.w.eta_lbl   = QLabel("")
        self.w.total_lbl = QLabel("")
        self.w.progress_bar = DragonProgressBar()
        self.w.progress_bar.setFormat("Gesamt: %p%")
        file_row = QHBoxLayout()
        file_row.addWidget(self.w.file_lbl, 1)
        file_row.addWidget(self.w.file_focus_combo, 0)
        prg.addLayout(file_row)
        prg.addWidget(self.w.file_bar)
        prg.addWidget(self.w.eta_lbl)
        prg.addWidget(self.w.total_lbl)
        prg.addWidget(self.w.progress_bar)
        root.addWidget(prg)

    def _build_log_section(self, root: QVBoxLayout) -> None:
        # Log ist ebenfalls einklappbar. Die Höhe bleibt erhalten, sobald der
        # Bereich geöffnet ist.
        lgrp = CollapsibleGroupBox(
            "📜 Log",
            collapsed=False,
            settings=self.settings,
            section_id="convert/log",
        )
        self.w.log_edit = QTextEdit()
        self.w.log_edit.setReadOnly(True)
        self.w.log_edit.setFixedHeight(130)
        self.w.log_edit.setStyleSheet("font-family:Consolas,monospace;font-size:10px;")
        btn_row = QHBoxLayout()
        self.w.logfile_btn      = QPushButton("\U0001F4C2 Logordner")
        self.w.curlog_btn       = QPushButton("\U0001F4C4 Aktuellen Log \u00f6ffnen")
        self.w.curlog_btn.setEnabled(False)
        btn_row.addWidget(self.w.logfile_btn)
        btn_row.addWidget(self.w.curlog_btn)
        lgrp.addWidget(self.w.log_edit)
        lgrp.addLayout(btn_row)
        # Der Log bleibt auf seiner Inhaltshoehe; zusaetzlicher vertikaler Platz
        # geht ausschliesslich an die Dateiliste.
        lgrp.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        root.addWidget(lgrp, 0)

    def _style_progress_labels(self) -> None:
        self.w.file_lbl.setStyleSheet("color: #ff4a1f; font-size: 12px; font-weight: 700;")
        self.w.eta_lbl.setStyleSheet("color: #ff8a33; font-size: 11px; font-weight: 600;")
        self.w.total_lbl.setStyleSheet("color: #ff9f1a; color: #ffc14d; font-weight: 700;")
