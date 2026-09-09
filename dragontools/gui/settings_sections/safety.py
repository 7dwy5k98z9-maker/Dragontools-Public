# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QGroupBox, QLabel, QPushButton, QSpinBox
from ...core import settings as cfg
from ..info_button import InfoButton
from .base import SettingsSection


class SafetyValidationSection(SettingsSection):
    section_keys = ("timeouts", "save", "validation", "move_conflict")

    def build(self, vl) -> None:
        d = self.dialog
        # ── Timeouts ───────────────────────────────────────────────────────
        timeout_grp = QGroupBox("Timeouts")
        d._section_widgets["timeouts"] = timeout_grp
        tog = QGridLayout(timeout_grp)
        timeout_desc = QLabel(
            "Hier erreichst du die zentralen Laufzeit- und Inaktivitäts-Timeouts "
            "für Analyse, Encoder, DV-Pipeline, Untertitel und Zusatzwerkzeuge."
        )
        timeout_desc.setWordWrap(True)
        tog.addWidget(timeout_desc, 0, 0, 1, 3)
        timeout_btn = QPushButton("⏱ Timeout-Einstellungen öffnen …")
        timeout_btn.clicked.connect(d.open_timeout_settings)
        tog.addWidget(timeout_btn, 1, 0, 1, 2)
        tog.addWidget(InfoButton(
            "Öffnet den bestehenden Timeout-Dialog mit allen Timeout-Werten, "
            "Aktiv-Checkboxen und Standard-Zurücksetzen-Funktionen."
        ), 1, 2)
        vl.addWidget(timeout_grp)

        # ── Speichereinstellungen ───────────────────────────────────────────
        save_grp = QGroupBox("Speichereinstellungen")
        d._section_widgets["save"] = save_grp
        sg = QGridLayout(save_grp)
        d.save_allow_larger_cb = QCheckBox("Größere Output Datei akzeptieren")
        sg.addWidget(d.save_allow_larger_cb, 0, 0, 1, 2)
        sg.addWidget(InfoButton(
            "Erlaubt größere Ausgabedateien bis zu einem prozentualen Aufschlag "
            "gegenüber der Quelldatei."
        ), 0, 2)
        sg.addWidget(QLabel("Maximaler Aufschlag:"), 1, 0)
        d.save_allow_larger_percent_spin = QSpinBox()
        d.save_allow_larger_percent_spin.setRange(1, 100)
        d.save_allow_larger_percent_spin.setSuffix(" %")
        sg.addWidget(d.save_allow_larger_percent_spin, 1, 1)
        sg.addWidget(InfoButton(
            "Beispiel: 10 % erlaubt bei 1,0 GB Input maximal 1,1 GB Output."
        ), 1, 2)

        d.save_min_output_cb = QCheckBox("Mindestgröße Output Datei")
        sg.addWidget(d.save_min_output_cb, 2, 0, 1, 2)
        sg.addWidget(InfoButton(
            "Verhindert automatisches Ersetzen wenn die Ausgabedatei zu klein wird."
        ), 2, 2)
        sg.addWidget(QLabel("Mindestens:"), 3, 0)
        d.save_min_output_percent_spin = QSpinBox()
        d.save_min_output_percent_spin.setRange(1, 100)
        d.save_min_output_percent_spin.setSuffix(" %")
        sg.addWidget(d.save_min_output_percent_spin, 3, 1)
        sg.addWidget(InfoButton(
            "Beispiel: 50 % bedeutet bei 1,0 GB Input mindestens 0,5 GB Output."
        ), 3, 2)
        vl.addWidget(save_grp)

        # ── Output-Validierung / Reparatur ────────────────────────────────
        validation_grp = QGroupBox("Output-Validierung / Reparatur")
        d._section_widgets["validation"] = validation_grp
        vg = QGridLayout(validation_grp)
        validation_desc = QLabel(
            "Diese Werte steuern die technische Plausibilitätsprüfung nach dem Encode. "
            "Die Grundprüfung auf vorhandenes Video, Audio und lesbare Containerdaten bleibt immer aktiv."
        )
        validation_desc.setWordWrap(True)
        vg.addWidget(validation_desc, 0, 0, 1, 3)
        vg.addWidget(QLabel("Min. Dateigröße:"), 1, 0)
        d.output_min_size_spin = QSpinBox()
        d.output_min_size_spin.setRange(1, 102400)
        d.output_min_size_spin.setSuffix(" KB")
        vg.addWidget(d.output_min_size_spin, 1, 1)
        vg.addWidget(InfoButton(
            "Ausgaben darunter gelten als unplausibel klein. Standard: 1 KB."
        ), 1, 2)
        vg.addWidget(QLabel("Dauer-Untergrenze:"), 2, 0)
        d.duration_min_percent_spin = QSpinBox()
        d.duration_min_percent_spin.setRange(1, 100)
        d.duration_min_percent_spin.setSuffix(" %")
        vg.addWidget(d.duration_min_percent_spin, 2, 1)
        vg.addWidget(InfoButton(
            "Mindestens so viel Prozent der Quelldauer muss die Ausgabe haben. Standard: 90 %."
        ), 2, 2)
        vg.addWidget(QLabel("Dauer-Obergrenze:"), 3, 0)
        d.duration_max_percent_spin = QSpinBox()
        d.duration_max_percent_spin.setRange(100, 1000)
        d.duration_max_percent_spin.setSuffix(" %")
        vg.addWidget(d.duration_max_percent_spin, 3, 1)
        vg.addWidget(InfoButton(
            "Maximal so viel Prozent der Quelldauer darf die Ausgabe haben. Standard: 125 %."
        ), 3, 2)
        vg.addWidget(QLabel("Zusätzliche Max-Toleranz:"), 4, 0)
        d.duration_max_extra_spin = QSpinBox()
        d.duration_max_extra_spin.setRange(0, 3600)
        d.duration_max_extra_spin.setSuffix(" s")
        vg.addWidget(d.duration_max_extra_spin, 4, 1)
        vg.addWidget(InfoButton(
            "Zusätzlicher Puffer nach oben, damit kurze Dateien nicht zu streng geprüft werden. Standard: 60 s."
        ), 4, 2)
        d.repair_remux_cb = QCheckBox("Bei fehlerhafter Container-Laufzeit normalen Remux versuchen (MKVToolNix/MP4Box)")
        vg.addWidget(d.repair_remux_cb, 5, 0, 1, 2)
        vg.addWidget(InfoButton(
            "Erster Reparaturschritt: MKV mit MKVToolNix bzw. MP4 mit MP4Box ohne Neukodierung neu verpacken."
        ), 5, 2)
        d.repair_timestamp_cb = QCheckBox("Wenn nötig verlustfreie Timestamp-Reparatur versuchen")
        vg.addWidget(d.repair_timestamp_cb, 6, 0, 1, 2)
        vg.addWidget(InfoButton(
            "Zweiter Reparaturschritt: Videotimeline ohne erneuten Encode rekonstruieren."
        ), 6, 2)
        vl.addWidget(validation_grp)

        # ── Verschieben – Konfliktverhalten ────────────────────────
        mc_grp = QGroupBox("📁 Verschieben – Konfliktverhalten")
        d._section_widgets["move_conflict"] = mc_grp
        mc = QGridLayout(mc_grp)
        mc.addWidget(QLabel(
            "Was soll passieren, wenn eine gleichnamige Videodatei im Zielordner bereits existiert?"
        ), 0, 0, 1, 3)

        mc.addWidget(QLabel("Konfliktmodus:"), 1, 0)
        d.move_conflict_combo = QComboBox()
        d.move_conflict_combo.addItems([
            "Überspringen (Warnung ausgeben)",
            "Zieldatei zuerst löschen, dann verschieben",
            "Zieldatei direkt ersetzen (überschreiben)",
            "Umbenennen mit Suffix (_01, _02, …)",
        ])
        mc.addWidget(d.move_conflict_combo, 1, 1)
        mc.addWidget(InfoButton(
            "Überspringen: Datei wird NICHT verschoben, Warnung im Log.\n"
            "Zuerst löschen: Vorhandene Datei wird gelöscht, dann wird die neue verschoben.\n"
            "Direkt ersetzen: Neue Datei überschreibt die vorhandene atomar (sicherer als löschen).\n"
            "Umbenennen: Neue Datei bekommt einen Suffix, z.B. Film_01.mkv, Film_02.mkv …\n"
            "  → Mehrere Versionen werden nebeneinander gespeichert, nichts geht verloren.\n"
            "Bei Videodateien zählt gleicher Name vor der Endung als Konflikt, z.B. Film.mp4 ↔ Film.mkv."
        ), 1, 2)
        vl.addWidget(mc_grp)
        d.save_allow_larger_cb.toggled.connect(d.save_allow_larger_percent_spin.setEnabled)
        d.save_min_output_cb.toggled.connect(d.save_min_output_percent_spin.setEnabled)


    def load(self) -> None:
        d, s = self.dialog, self.settings
        d.save_allow_larger_cb.setChecked(s.value(cfg.SET_KEY_SAVE_ALLOW_LARGER_OUTPUT, False, type=bool))
        d.save_allow_larger_percent_spin.setValue(int(s.value(cfg.SET_KEY_SAVE_ALLOW_LARGER_OUTPUT_PERCENT, 10, type=int)))
        d.save_min_output_cb.setChecked(s.value(cfg.SET_KEY_SAVE_MIN_OUTPUT_SIZE_ENABLED, False, type=bool))
        d.save_min_output_percent_spin.setValue(int(s.value(cfg.SET_KEY_SAVE_MIN_OUTPUT_SIZE_PERCENT, 50, type=int)))
        d.save_allow_larger_percent_spin.setEnabled(d.save_allow_larger_cb.isChecked())
        d.save_min_output_percent_spin.setEnabled(d.save_min_output_cb.isChecked())
        d.output_min_size_spin.setValue(int(s.value(cfg.SET_KEY_OUTPUT_MIN_SIZE_KB, cfg.DEFAULT_OUTPUT_MIN_SIZE_KB, type=int)))
        d.duration_min_percent_spin.setValue(int(s.value(cfg.SET_KEY_OUTPUT_DURATION_MIN_PERCENT, cfg.DEFAULT_OUTPUT_DURATION_MIN_PERCENT, type=int)))
        d.duration_max_percent_spin.setValue(int(s.value(cfg.SET_KEY_OUTPUT_DURATION_MAX_PERCENT, cfg.DEFAULT_OUTPUT_DURATION_MAX_PERCENT, type=int)))
        d.duration_max_extra_spin.setValue(int(s.value(cfg.SET_KEY_OUTPUT_DURATION_MAX_EXTRA_S, cfg.DEFAULT_OUTPUT_DURATION_MAX_EXTRA_S, type=int)))
        d.repair_remux_cb.setChecked(s.value(cfg.SET_KEY_REPAIR_DURATION_REMUX_ENABLED, cfg.DEFAULT_REPAIR_DURATION_REMUX_ENABLED, type=bool))
        d.repair_timestamp_cb.setChecked(s.value(cfg.SET_KEY_REPAIR_DURATION_TIMESTAMP_ENABLED, cfg.DEFAULT_REPAIR_DURATION_TIMESTAMP_ENABLED, type=bool))
        values = ["skip", "delete_first", "overwrite", "rename"]
        conflict = s.value(cfg.SET_KEY_MOVE_CONFLICT, "skip", type=str)
        d.move_conflict_combo.setCurrentIndex(values.index(conflict) if conflict in values else 0)

    def save(self) -> bool:
        d, s = self.dialog, self.settings
        s.setValue(cfg.SET_KEY_SAVE_ALLOW_LARGER_OUTPUT, d.save_allow_larger_cb.isChecked())
        s.setValue(cfg.SET_KEY_SAVE_ALLOW_LARGER_OUTPUT_PERCENT, d.save_allow_larger_percent_spin.value())
        s.setValue(cfg.SET_KEY_SAVE_MIN_OUTPUT_SIZE_ENABLED, d.save_min_output_cb.isChecked())
        s.setValue(cfg.SET_KEY_SAVE_MIN_OUTPUT_SIZE_PERCENT, d.save_min_output_percent_spin.value())
        s.setValue(cfg.SET_KEY_OUTPUT_MIN_SIZE_KB, d.output_min_size_spin.value())
        s.setValue(cfg.SET_KEY_OUTPUT_DURATION_MIN_PERCENT, d.duration_min_percent_spin.value())
        s.setValue(cfg.SET_KEY_OUTPUT_DURATION_MAX_PERCENT, d.duration_max_percent_spin.value())
        s.setValue(cfg.SET_KEY_OUTPUT_DURATION_MAX_EXTRA_S, d.duration_max_extra_spin.value())
        s.setValue(cfg.SET_KEY_REPAIR_DURATION_REMUX_ENABLED, d.repair_remux_cb.isChecked())
        s.setValue(cfg.SET_KEY_REPAIR_DURATION_TIMESTAMP_ENABLED, d.repair_timestamp_cb.isChecked())
        values = ["skip", "delete_first", "overwrite", "rename"]
        s.setValue(cfg.SET_KEY_MOVE_CONFLICT, values[d.move_conflict_combo.currentIndex()])
        return True

    def open_timeout_settings(self) -> None:
        from ..timeout_settings_dialog import TimeoutSettingsDialog
        dlg = TimeoutSettingsDialog(self.dialog)
        dlg.exec()
