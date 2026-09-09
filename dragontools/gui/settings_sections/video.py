# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt6.QtWidgets import QComboBox, QGridLayout, QGroupBox, QLabel, QSpinBox
from ...core import settings as cfg
from ..info_button import InfoButton
from .base import SettingsSection


class VideoAnalysisSection(SettingsSection):
    section_keys = ("containers", "autocrop", "imax")

    def build(self, vl) -> None:
        d = self.dialog
        # ── Ausgabecontainer ────────────────────────────────────────────────
        container_grp = QGroupBox("Ausgabecontainer")
        d._section_widgets["containers"] = container_grp
        cg = QGridLayout(container_grp)
        desc = QLabel(
            "Container werden getrennt nach normalem/HDR10+-Pfad und Dolby-Vision-Pfad gewählt. "
            "MP4 wird streamingoptimiert erzeugt (Faststart/Interleaving)."
        )
        desc.setWordWrap(True)
        cg.addWidget(desc, 0, 0, 1, 3)
        cg.addWidget(QLabel("Standard / HDR10+:"), 1, 0)
        d.standard_container_combo = QComboBox()
        d.standard_container_combo.addItem("MKV (Matroska)", "mkv")
        d.standard_container_combo.addItem("MP4 (streamingoptimiert)", "mp4")
        cg.addWidget(d.standard_container_combo, 1, 1)
        cg.addWidget(InfoButton(
            "Gilt für Standard- und reinen HDR10+-Pfad. Bei MP4 werden nicht kompatible "
            "Untertitel als Sidecars exportiert statt blind intern kopiert."
        ), 1, 2)
        cg.addWidget(QLabel("Dolby Vision / DV+HDR10+ / DV-Remux:"), 2, 0)
        d.dv_container_combo = QComboBox()
        d.dv_container_combo.addItem("MP4 (streamingoptimiert)", "mp4")
        d.dv_container_combo.addItem("MKV (Matroska)", "mkv")
        cg.addWidget(d.dv_container_combo, 2, 1)
        cg.addWidget(InfoButton(
            "Gilt für Dolby Vision, DV+HDR10+ und den separaten DV-Remux-Button. "
            "MP4 wird streamingoptimiert mit MP4Box gemuxt; MKV über mkvmerge. "
            "Der Videostream bleibt beim DV-Remux unverändert."
        ), 2, 2)
        vl.addWidget(container_grp)

        # ── Auto-Crop ─────────────────────────────────────────────────────
        autocrop_grp = QGroupBox("Auto-Crop")
        d._section_widgets["autocrop"] = autocrop_grp
        acg = QGridLayout(autocrop_grp)
        autocrop_desc = QLabel(
            "Auto-Crop sucht schwarze Balken per ffmpeg cropdetect. "
            "Der alte Standard bleibt ein einzelner Prüfpunkt bei 30 Sekunden für 45 Sekunden."
        )
        autocrop_desc.setWordWrap(True)
        acg.addWidget(autocrop_desc, 0, 0, 1, 3)
        acg.addWidget(QLabel("Analysemodus:"), 1, 0)
        d.autocrop_mode_combo = QComboBox()
        d.autocrop_mode_combo.addItem("Ein Prüfpunkt (schnell)", "single")
        d.autocrop_mode_combo.addItem("Mehrere Prüfpunkte", "multi")
        acg.addWidget(d.autocrop_mode_combo, 1, 1)
        acg.addWidget(InfoButton(
            "Ein Prüfpunkt entspricht dem bisherigen Verhalten. "
            "Mehrere Prüfpunkte helfen bei Intros, Logos oder wechselndem Bildinhalt."
        ), 1, 2)
        acg.addWidget(QLabel("Startpunkt:"), 2, 0)
        d.autocrop_start_spin = QSpinBox()
        d.autocrop_start_spin.setRange(0, 3600)
        d.autocrop_start_spin.setSuffix(" s")
        acg.addWidget(d.autocrop_start_spin, 2, 1)
        acg.addWidget(InfoButton("Zeitpunkt, an dem die erste Crop-Prüfung beginnt."), 2, 2)
        acg.addWidget(QLabel("Prüfdauer:"), 3, 0)
        d.autocrop_duration_spin = QSpinBox()
        d.autocrop_duration_spin.setRange(2, 120)
        d.autocrop_duration_spin.setSuffix(" s")
        acg.addWidget(d.autocrop_duration_spin, 3, 1)
        acg.addWidget(InfoButton("Wie lange ffmpeg je Prüfpunkt cropdetect laufen lässt."), 3, 2)
        acg.addWidget(QLabel("Intervall bei Mehrpunkt:"), 4, 0)
        d.autocrop_interval_spin = QSpinBox()
        d.autocrop_interval_spin.setRange(60, 1800)
        d.autocrop_interval_spin.setSingleStep(60)
        d.autocrop_interval_spin.setSuffix(" s")
        acg.addWidget(d.autocrop_interval_spin, 4, 1)
        acg.addWidget(InfoButton(
            "Abstand zwischen den Prüfpunkten, wenn der Mehrpunkt-Modus aktiv ist."
        ), 4, 2)
        d.autocrop_mode_combo.currentIndexChanged.connect(d.sync_autocrop_mode)
        vl.addWidget(autocrop_grp)

        # ── IMAX Auto-Erkennung ────────────────────────────────────────────
        imax_grp = QGroupBox("IMAX Auto-Erkennung")
        d._section_widgets["imax"] = imax_grp
        ig = QGridLayout(imax_grp)
        imax_desc = QLabel(
            "Die IMAX-Auto-Erkennung prüft die aktive Bildfläche per Cropdetect. "
            "So werden wechselnde Bildformate auch dann erkannt, wenn die technische "
            "Dateiauflösung durchgehend gleich bleibt."
        )
        imax_desc.setWordWrap(True)
        ig.addWidget(imax_desc, 0, 0, 1, 3)
        ig.addWidget(QLabel("Prüfintervall:"), 1, 0)
        d.imax_probe_interval_spin = QSpinBox()
        d.imax_probe_interval_spin.setRange(30, 600)
        d.imax_probe_interval_spin.setSingleStep(30)
        d.imax_probe_interval_spin.setSuffix(" s")
        d.imax_probe_interval_spin.setValue(
            int(d.settings.value(
                cfg.SET_KEY_IMAX_PROBE_INTERVAL,
                cfg.DEFAULT_IMAX_PROBE_INTERVAL_S,
                type=int,
            ))
        )
        ig.addWidget(d.imax_probe_interval_spin, 1, 1)
        ig.addWidget(InfoButton(
            "Abstand zwischen den IMAX-Prüfpunkten.\n"
            "Standard: 90 s. Kürzer erkennt Wechsel zuverlässiger, verlängert aber die Voranalyse.\n"
            "Diese Einstellung wirkt, wenn die IMAX Auto-Erkennung im Konverter aktiviert ist."
        ), 1, 2)
        ig.addWidget(QLabel("Prüfdauer je Punkt:"), 2, 0)
        d.imax_probe_duration_spin = QSpinBox()
        d.imax_probe_duration_spin.setRange(1, 30)
        d.imax_probe_duration_spin.setSuffix(" s")
        ig.addWidget(d.imax_probe_duration_spin, 2, 1)
        ig.addWidget(InfoButton(
            "Wie lange cropdetect je IMAX-Prüfpunkt laufen soll. "
            "Standard: 3 s."
        ), 2, 2)
        ig.addWidget(QLabel("Mindestabweichung:"), 3, 0)
        d.imax_min_variance_spin = QSpinBox()
        d.imax_min_variance_spin.setRange(1, 100)
        d.imax_min_variance_spin.setSuffix(" %")
        ig.addWidget(d.imax_min_variance_spin, 3, 1)
        ig.addWidget(InfoButton(
            "Wie stark sich das aktive Bildformat unterscheiden muss, damit IMAX erkannt wird. "
            "Standard: 15 %."
        ), 3, 2)
        ig.addWidget(QLabel("Min. verwertbare Prüfpunkte:"), 4, 0)
        d.imax_min_hits_spin = QSpinBox()
        d.imax_min_hits_spin.setRange(2, 50)
        ig.addWidget(d.imax_min_hits_spin, 4, 1)
        ig.addWidget(InfoButton(
            "Mindestens so viele erfolgreiche Prüfpunkte müssen vorliegen, bevor die IMAX-Entscheidung getroffen wird."
        ), 4, 2)
        vl.addWidget(imax_grp)


    def load(self) -> None:
        d, s = self.dialog, self.settings
        standard_container = cfg.settings_text(
            s, cfg.SET_KEY_OUTPUT_CONTAINER_STANDARD, cfg.DEFAULT_OUTPUT_CONTAINER_STANDARD,
            allowed=("mkv", "mp4"),
        )
        idx = d.standard_container_combo.findData(standard_container)
        d.standard_container_combo.setCurrentIndex(idx if idx >= 0 else 0)
        dv_container = cfg.settings_text(
            s, cfg.SET_KEY_OUTPUT_CONTAINER_DV, cfg.DEFAULT_OUTPUT_CONTAINER_DV,
            allowed=("mkv", "mp4"),
        )
        idx = d.dv_container_combo.findData(dv_container)
        d.dv_container_combo.setCurrentIndex(idx if idx >= 0 else 0)
        autocrop_mode = s.value(cfg.SET_KEY_AUTOCROP_MODE, cfg.DEFAULT_AUTOCROP_MODE, type=str)
        idx = d.autocrop_mode_combo.findData(autocrop_mode)
        d.autocrop_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        d.autocrop_start_spin.setValue(int(s.value(cfg.SET_KEY_AUTOCROP_PROBE_START, cfg.DEFAULT_AUTOCROP_PROBE_START_S, type=int)))
        d.autocrop_duration_spin.setValue(int(s.value(cfg.SET_KEY_AUTOCROP_PROBE_DURATION, cfg.DEFAULT_AUTOCROP_PROBE_DURATION_S, type=int)))
        d.autocrop_interval_spin.setValue(int(s.value(cfg.SET_KEY_AUTOCROP_PROBE_INTERVAL, cfg.DEFAULT_AUTOCROP_PROBE_INTERVAL_S, type=int)))
        self.sync_autocrop_mode()
        d.imax_probe_interval_spin.setValue(int(s.value(cfg.SET_KEY_IMAX_PROBE_INTERVAL, cfg.DEFAULT_IMAX_PROBE_INTERVAL_S, type=int)))
        d.imax_probe_duration_spin.setValue(int(s.value(cfg.SET_KEY_IMAX_PROBE_DURATION, cfg.DEFAULT_IMAX_PROBE_DURATION_S, type=int)))
        d.imax_min_variance_spin.setValue(int(s.value(cfg.SET_KEY_IMAX_MIN_VARIANCE_PERCENT, cfg.DEFAULT_IMAX_MIN_VARIANCE_PERCENT, type=int)))
        d.imax_min_hits_spin.setValue(int(s.value(cfg.SET_KEY_IMAX_MIN_HITS, cfg.DEFAULT_IMAX_MIN_HITS, type=int)))

    def save(self) -> bool:
        d, s = self.dialog, self.settings
        s.setValue(cfg.SET_KEY_OUTPUT_CONTAINER_STANDARD, d.standard_container_combo.currentData() or cfg.DEFAULT_OUTPUT_CONTAINER_STANDARD)
        s.setValue(cfg.SET_KEY_OUTPUT_CONTAINER_DV, d.dv_container_combo.currentData() or cfg.DEFAULT_OUTPUT_CONTAINER_DV)
        s.setValue(cfg.SET_KEY_AUTOCROP_MODE, d.autocrop_mode_combo.currentData() or cfg.DEFAULT_AUTOCROP_MODE)
        s.setValue(cfg.SET_KEY_AUTOCROP_PROBE_START, d.autocrop_start_spin.value())
        s.setValue(cfg.SET_KEY_AUTOCROP_PROBE_DURATION, d.autocrop_duration_spin.value())
        s.setValue(cfg.SET_KEY_AUTOCROP_PROBE_INTERVAL, d.autocrop_interval_spin.value())
        s.setValue(cfg.SET_KEY_IMAX_PROBE_INTERVAL, d.imax_probe_interval_spin.value())
        s.setValue(cfg.SET_KEY_IMAX_PROBE_DURATION, d.imax_probe_duration_spin.value())
        s.setValue(cfg.SET_KEY_IMAX_MIN_VARIANCE_PERCENT, d.imax_min_variance_spin.value())
        s.setValue(cfg.SET_KEY_IMAX_MIN_HITS, d.imax_min_hits_spin.value())
        return True

    def sync_autocrop_mode(self) -> None:
        d = self.dialog
        d.autocrop_interval_spin.setEnabled(d.autocrop_mode_combo.currentData() == "multi")
