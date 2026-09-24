# -*- coding: utf-8 -*-
"""Watch-Folder automation settings section."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ...core import settings as cfg
from ...core.settings_watch import load_watch_rules, save_watch_rules
from ..info_button import InfoButton
from ..watch_folder_rule_dialog import WatchFolderRuleDialog


class WatchFolderAutomationPanel:
    def __init__(self, dialog) -> None:
        self.dialog = dialog
        self.settings = dialog.settings

    def build(self, layout) -> None:
        d = self.dialog
        grp = QGroupBox("Automatisierung / Watch-Folder")
        d._section_widgets["watch_folders"] = grp
        outer = QVBoxLayout(grp)

        desc = QLabel(
            "Überwacht beliebig viele Eingangsordner und übergibt stabile Videodateien an die vorhandene "
            "Dragon-Tools-Queue. Es wird keine zweite Verarbeitungspipeline angelegt."
        )
        desc.setWordWrap(True)
        outer.addWidget(desc)

        grid = QGridLayout()
        d.watch_enabled_cb = QCheckBox("Watch-Folder aktivieren")
        grid.addWidget(d.watch_enabled_cb, 0, 0, 1, 2)
        grid.addWidget(InfoButton("Globaler Hauptschalter. Ist er aus, werden keine Ordner gescannt."), 0, 2)

        grid.addWidget(QLabel("Scan-Intervall:"), 1, 0)
        d.watch_scan_spin = QSpinBox()
        d.watch_scan_spin.setRange(2, 300)
        d.watch_scan_spin.setSuffix(" s")
        grid.addWidget(d.watch_scan_spin, 1, 1)
        grid.addWidget(InfoButton("Zeit zwischen zwei Watch-Folder-Prüfungen."), 1, 2)

        grid.addWidget(QLabel("Datei stabil seit:"), 2, 0)
        d.watch_stable_spin = QSpinBox()
        d.watch_stable_spin.setRange(5, 3600)
        d.watch_stable_spin.setSuffix(" s")
        grid.addWidget(d.watch_stable_spin, 2, 1)
        grid.addWidget(InfoButton(
            "Eine Datei wird erst übernommen, wenn Größe und Änderungszeit so lange unverändert sind. "
            "Unfertige Downloads wie .part/.tmp werden zusätzlich durch den Videofilter ignoriert."
        ), 2, 2)
        outer.addLayout(grid)

        d.watch_rules_table = QTableWidget(0, 6)
        d.watch_rules_table.setHorizontalHeaderLabels([
            "Aktiv", "Name", "Ordner", "Unterordner", "Converter", "Profil / Auto-Start",
        ])
        d.watch_rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        d.watch_rules_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        d.watch_rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        d.watch_rules_table.horizontalHeader().setStretchLastSection(True)
        d.watch_rules_table.doubleClicked.connect(self.edit_rule)
        outer.addWidget(d.watch_rules_table)

        buttons = QHBoxLayout()
        add_btn = QPushButton("＋ Hinzufügen")
        add_btn.clicked.connect(self.add_rule)
        edit_btn = QPushButton("✎ Bearbeiten")
        edit_btn.clicked.connect(self.edit_rule)
        remove_btn = QPushButton("− Entfernen")
        remove_btn.clicked.connect(self.remove_rule)
        buttons.addWidget(add_btn)
        buttons.addWidget(edit_btn)
        buttons.addWidget(remove_btn)
        buttons.addStretch(1)
        outer.addLayout(buttons)

        note = QLabel(
            "Auto-Start gilt für die normale Konvertierung. Wenn im betroffenen Converter »Verschieben« aktiv ist, "
            "wird die Datei sicher eingereiht, aber nicht unbeaufsichtigt gestartet: der bestehende Preflight bleibt "
            "die verbindliche Zielentscheidung. Jellyfin-Aktualisierung folgt weiterhin den normalen Jellyfin-/Move-Einstellungen."
        )
        note.setWordWrap(True)
        outer.addWidget(note)
        layout.addWidget(grp)

    def load(self) -> None:
        d, s = self.dialog, self.settings
        d.watch_enabled_cb.setChecked(s.value(cfg.SET_KEY_WATCH_ENABLED, cfg.DEFAULT_WATCH_ENABLED, type=bool))
        d.watch_scan_spin.setValue(s.value(
            cfg.SET_KEY_WATCH_SCAN_INTERVAL, cfg.DEFAULT_WATCH_SCAN_INTERVAL, type=int
        ))
        d.watch_stable_spin.setValue(s.value(
            cfg.SET_KEY_WATCH_STABLE_SECONDS, cfg.DEFAULT_WATCH_STABLE_SECONDS, type=int
        ))
        d._watch_rules = load_watch_rules(s)
        self._refresh_table()

    def save(self) -> bool:
        d, s = self.dialog, self.settings
        s.setValue(cfg.SET_KEY_WATCH_ENABLED, d.watch_enabled_cb.isChecked())
        s.setValue(cfg.SET_KEY_WATCH_SCAN_INTERVAL, d.watch_scan_spin.value())
        s.setValue(cfg.SET_KEY_WATCH_STABLE_SECONDS, d.watch_stable_spin.value())
        save_watch_rules(s, list(getattr(d, "_watch_rules", [])))
        return True

    def add_rule(self) -> None:
        dlg = WatchFolderRuleDialog(self.dialog)
        if dlg.exec():
            rule = dlg.rule()
            if rule is not None:
                self.dialog._watch_rules.append(rule)
                self._refresh_table()

    def edit_rule(self, *_args) -> None:
        row = self.dialog.watch_rules_table.currentRow()
        rules = getattr(self.dialog, "_watch_rules", [])
        if row < 0 or row >= len(rules):
            return
        dlg = WatchFolderRuleDialog(self.dialog, rule=rules[row])
        if dlg.exec():
            rule = dlg.rule()
            if rule is not None:
                rules[row] = rule
                self._refresh_table()
                self.dialog.watch_rules_table.selectRow(row)

    def remove_rule(self) -> None:
        row = self.dialog.watch_rules_table.currentRow()
        rules = getattr(self.dialog, "_watch_rules", [])
        if row < 0 or row >= len(rules):
            return
        del rules[row]
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.dialog.watch_rules_table
        rules = list(getattr(self.dialog, "_watch_rules", []))
        table.setRowCount(len(rules))
        codec_labels = {"h265": "H.265", "h264": "H.264", "av1": "AV1"}
        for row, rule in enumerate(rules):
            profile = rule.profile_key or "Global"
            auto = "Auto-Start" if rule.auto_start else "nur Queue"
            values = [
                "Ja" if rule.enabled else "Nein",
                rule.name,
                rule.path,
                "Ja" if rule.recursive else "Nein",
                codec_labels.get(rule.codec, rule.codec),
                f"{profile} · {auto}",
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(value))
        table.resizeColumnsToContents()
