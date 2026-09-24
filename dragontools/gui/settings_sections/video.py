# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel, QLineEdit, QSpinBox
from ...core import settings as cfg
from ..info_button import InfoButton
from .comfyui_fields import build_comfyui_fields
from .base import SettingsSection


class VideoAnalysisSection(SettingsSection):
    section_keys = ("containers", "autocrop", "imax", "quality_target", "sdr_hdr", "hdr10plus_generator")

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
            "Beim DV-Remux kann Profil 7 abhängig von der Remux-Policy verlustfrei "
            "beibehalten oder zu Profil 8.1 normalisiert werden."
        ), 4, 2)

        d.dv_remux_keep_dv7_mkv_cb = QCheckBox("DV7 bei MKV-Remux beibehalten")
        cg.addWidget(d.dv_remux_keep_dv7_mkv_cb, 3, 0, 1, 2)
        cg.addWidget(InfoButton(
            "Nur für DV-Remux nach MKV. Aktiv: Profil 7 bleibt als Profil 7 erhalten. "
            "Aus (Standard): Profil 7 wird mit dovi_tool Mode 2 nach DV 8.1 normalisiert. "
            "Bei MP4 wird Profil 7 unabhängig von dieser Option immer nach DV 8.1 normalisiert."
        ), 3, 2)

        d.dv_remux_encode_dv5_cb = QCheckBox("DV5 bei Remux automatisch encodieren")
        cg.addWidget(d.dv_remux_encode_dv5_cb, 4, 0, 1, 2)
        cg.addWidget(InfoButton(
            "Profil 5 kann nicht als einfacher HDR10/DV8.1-Remux behandelt werden. "
            "Aktiv (Standard): DragonTools übergibt die Datei automatisch an den normalen "
            "H.265-Dolby-Vision-Encodingpfad. Aus: die Datei wird im DV-Remux übersprungen."
        ), 4, 2)
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

        # ── Automatisches VMAF-Qualitätsziel ───────────────────────────────
        quality_grp = QGroupBox("Automatisches VMAF-Qualitätsziel")
        d._section_widgets["quality_target"] = quality_grp
        qg = QGridLayout(quality_grp)
        d.quality_target_enabled_cb = QCheckBox("CQ/CRF automatisch per VMAF bestimmen")
        qg.addWidget(d.quality_target_enabled_cb, 0, 0, 1, 2)
        qg.addWidget(InfoButton(
            "Optional. Dragon Tools encodiert kurze SDR-Testsegmente und sucht den höchsten "
            "CQ/CRF/QP-Wert, der das Ziel-VMAF gegenüber der Quelle noch erreicht. "
            "HDR/DV/HLG bleibt aus Sicherheitsgründen beim festen Qualitätswert."
        ), 0, 2)
        qg.addWidget(QLabel("Ziel-VMAF:"), 1, 0)
        d.quality_target_vmaf_spin = QDoubleSpinBox()
        d.quality_target_vmaf_spin.setRange(70.0, 100.0); d.quality_target_vmaf_spin.setDecimals(1); d.quality_target_vmaf_spin.setSingleStep(0.5)
        qg.addWidget(d.quality_target_vmaf_spin, 1, 1)
        qg.addWidget(QLabel("Samples:"), 2, 0)
        d.quality_target_samples_spin = QSpinBox(); d.quality_target_samples_spin.setRange(1, 10)
        qg.addWidget(d.quality_target_samples_spin, 2, 1)
        qg.addWidget(QLabel("Samplelänge:"), 3, 0)
        d.quality_target_duration_spin = QSpinBox(); d.quality_target_duration_spin.setRange(2, 60); d.quality_target_duration_spin.setSuffix(" s")
        qg.addWidget(d.quality_target_duration_spin, 3, 1)
        qg.addWidget(QLabel("Suchbereich CQ/CRF/QP:"), 4, 0)
        range_row = QGridLayout()
        d.quality_target_min_spin = QSpinBox(); d.quality_target_min_spin.setRange(0, 63)
        d.quality_target_max_spin = QSpinBox(); d.quality_target_max_spin.setRange(0, 63)
        range_row.addWidget(QLabel("von"), 0, 0); range_row.addWidget(d.quality_target_min_spin, 0, 1)
        range_row.addWidget(QLabel("bis"), 0, 2); range_row.addWidget(d.quality_target_max_spin, 0, 3)
        qg.addLayout(range_row, 4, 1)
        qg.addWidget(InfoButton(
            "Niedriger = höhere Qualität/größere Datei. Gesucht wird adaptiv der höchste Wert, "
            "der das Ziel noch erreicht. Standard 18–30."
        ), 4, 2)
        vl.addWidget(quality_grp)

        # ── Experimentelles SDR → HDR Enhancement ─────────────────────────
        sdr_hdr_grp = QGroupBox("SDR → HDR Enhancement (experimentell)")
        d._section_widgets["sdr_hdr"] = sdr_hdr_grp
        shg = QGridLayout(sdr_hdr_grp)
        d.sdr_hdr_enabled_cb = QCheckBox("SDR BT.709 nach HDR10/PQ erweitern")
        shg.addWidget(d.sdr_hdr_enabled_cb, 0, 0, 1, 2)
        shg.addWidget(InfoButton(
            "Experimentell und standardmäßig aus. Nur eindeutig als SDR BT.709 getaggte Quellen werden berücksichtigt. "
            "FFmpeg/libplacebo und ComfyUI/HDRTVDM sind ausführbare Backends. Bei HDRTVDM lag der gemessene Praxiswert "
            "auf einer RTX 4080 SUPER bei 1080p bei ungefähr 4:1 Konvertierungsdauer zu Filmdauer; Quelle, Auflösung, "
            "Modell und Hardware können deutlich abweichen. HDR/DV/HLG, H.264-Ziele oder fehlende Backend-Voraussetzungen "
            "fallen sicher auf den normalen SDR-Encode zurück."
        ), 0, 2)
        shg.addWidget(QLabel("Backend:"), 1, 0)
        d.sdr_hdr_backend_combo = QComboBox()
        d.sdr_hdr_backend_combo.addItem("FFmpeg / libplacebo", "ffmpeg")
        d.sdr_hdr_backend_combo.addItem("DaVinci Resolve Free (vorbereitet)", "davinci_free")
        d.sdr_hdr_backend_combo.addItem("ComfyUI / HDRTVDM", "comfyui")
        shg.addWidget(d.sdr_hdr_backend_combo, 1, 1)
        shg.addWidget(InfoButton(
            "FFmpeg/libplacebo ist der klassische lokale Filterpfad. ComfyUI/HDRTVDM verarbeitet geeignete CFR-Quellen "
            "über die lokale API als Voll-Datei-Workflow und kann bei Bedarf automatisch gestartet werden. DaVinci Resolve Free "
            "bleibt ein manuell zu startendes externes Werkzeug; DragonTools setzt keine Studio-only Remote-/Developer-Scripting-API voraus."
        ), 1, 2)
        next_sdr_hdr_row = self._build_comfyui_fields(shg)
        shg.addWidget(QLabel("Kontrast-Recovery (FFmpeg):"), next_sdr_hdr_row, 0)
        d.sdr_hdr_contrast_spin = QDoubleSpinBox()
        d.sdr_hdr_contrast_spin.setRange(0.0, 3.0)
        d.sdr_hdr_contrast_spin.setDecimals(2)
        d.sdr_hdr_contrast_spin.setSingleStep(0.05)
        shg.addWidget(d.sdr_hdr_contrast_spin, next_sdr_hdr_row, 1)
        shg.addWidget(InfoButton(
            "libplacebo contrast_recovery. Standard 0,30. Höhere Werte können lokalen HDR-Kontrast "
            "stärker betonen und sollten visuell geprüft werden."
        ), next_sdr_hdr_row, 2)
        vl.addWidget(sdr_hdr_grp)

        hdrgen_grp = QGroupBox("Dragon HDR10+ Generator")
        d._section_widgets["hdr10plus_generator"] = hdrgen_grp
        hgg = QGridLayout(hdrgen_grp)
        d.hdr10plus_generator_enabled_cb = QCheckBox("HDR10+-Erzeugung für geeignete HDR-Ausgaben erlauben")
        hgg.addWidget(d.hdr10plus_generator_enabled_cb, 0, 0, 1, 2)
        hgg.addWidget(InfoButton(
            "Optional und standardmäßig aus. Direkte PQ/ST2084-HEVC-Quellen ohne HDR10+ können beim Encode oder "
            "Strip-Only/Remux analysiert werden. Wird SDR→HDR angewandt, kann DragonTools anschließend auch den neu "
            "erzeugten PQ/BT.2020-HEVC-Stream analysieren. Der Generator erzeugt hdr10plus.json; Injection, Remux und "
            "Endvalidierung bleiben in DragonTools. HLG wird nicht automatisch in HDR10+ umgedeutet."
        ), 0, 2)
        hint = QLabel("Direkt erreichbar über Einstellungen → ✨ Dragon HDR10+ Generator. "
                     "Der ausführbare Generatorpfad wird unter Einstellungen → Werkzeugpfade definiert.")
        hint.setWordWrap(True)
        hgg.addWidget(hint, 1, 0, 1, 3)
        vl.addWidget(hdrgen_grp)

    def _build_comfyui_fields(self, grid: QGridLayout) -> int:
        return build_comfyui_fields(self.dialog, grid)

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
        d.dv_remux_keep_dv7_mkv_cb.setChecked(
            bool(s.value(
                cfg.SET_KEY_DV_REMUX_KEEP_DV7_MKV,
                cfg.DEFAULT_DV_REMUX_KEEP_DV7_MKV,
                type=bool,
            ))
        )
        d.dv_remux_encode_dv5_cb.setChecked(
            bool(s.value(
                cfg.SET_KEY_DV_REMUX_ENCODE_DV5,
                cfg.DEFAULT_DV_REMUX_ENCODE_DV5,
                type=bool,
            ))
        )
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

        d.quality_target_enabled_cb.setChecked(bool(s.value(cfg.SET_KEY_QUALITY_TARGET_ENABLED, cfg.DEFAULT_QUALITY_TARGET_ENABLED, type=bool)))
        d.quality_target_vmaf_spin.setValue(float(s.value(cfg.SET_KEY_QUALITY_TARGET_VMAF, cfg.DEFAULT_QUALITY_TARGET_VMAF)))
        d.quality_target_samples_spin.setValue(int(s.value(cfg.SET_KEY_QUALITY_TARGET_SAMPLES, cfg.DEFAULT_QUALITY_TARGET_SAMPLES, type=int)))
        d.quality_target_duration_spin.setValue(int(s.value(cfg.SET_KEY_QUALITY_TARGET_SAMPLE_DURATION, cfg.DEFAULT_QUALITY_TARGET_SAMPLE_DURATION_S, type=int)))
        d.quality_target_min_spin.setValue(int(s.value(cfg.SET_KEY_QUALITY_TARGET_MIN, cfg.DEFAULT_QUALITY_TARGET_MIN, type=int)))
        d.quality_target_max_spin.setValue(int(s.value(cfg.SET_KEY_QUALITY_TARGET_MAX, cfg.DEFAULT_QUALITY_TARGET_MAX, type=int)))
        d.sdr_hdr_enabled_cb.setChecked(bool(s.value(cfg.SET_KEY_SDR_HDR_ENABLED, cfg.DEFAULT_SDR_HDR_ENABLED, type=bool)))
        d.sdr_hdr_contrast_spin.setValue(float(s.value(cfg.SET_KEY_SDR_HDR_CONTRAST_RECOVERY, cfg.DEFAULT_SDR_HDR_CONTRAST_RECOVERY)))
        backend = cfg.settings_text(
            s, cfg.SET_KEY_SDR_HDR_BACKEND, cfg.DEFAULT_SDR_HDR_BACKEND,
            allowed=("ffmpeg", "davinci_free", "comfyui"),
        )
        idx = d.sdr_hdr_backend_combo.findData(backend)
        d.sdr_hdr_backend_combo.setCurrentIndex(idx if idx >= 0 else 0)
        d.comfyui_base_url_edit.setText(str(s.value(
            cfg.SET_KEY_COMFYUI_BASE_URL, cfg.DEFAULT_COMFYUI_BASE_URL, type=str
        ) or cfg.DEFAULT_COMFYUI_BASE_URL))
        d.comfyui_auto_start_cb.setChecked(bool(s.value(
            cfg.SET_KEY_COMFYUI_AUTO_START, cfg.DEFAULT_COMFYUI_AUTO_START, type=bool
        )))
        d.comfyui_start_file_edit.setText(str(s.value(
            cfg.SET_KEY_COMFYUI_START_FILE, cfg.DEFAULT_COMFYUI_START_FILE, type=str
        ) or ""))
        d.comfyui_start_wait_spin.setValue(int(s.value(
            cfg.SET_KEY_COMFYUI_START_WAIT_SECONDS, cfg.DEFAULT_COMFYUI_START_WAIT_SECONDS, type=int
        )))
        model_profile = str(s.value(
            cfg.SET_KEY_COMFYUI_MODEL_PROFILE, cfg.DEFAULT_COMFYUI_MODEL_PROFILE, type=str
        ) or cfg.DEFAULT_COMFYUI_MODEL_PROFILE)
        idx = d.comfyui_model_profile_combo.findData(model_profile)
        d.comfyui_model_profile_combo.setCurrentIndex(idx if idx >= 0 else 0)
        d.comfyui_model_root_edit.setText(str(s.value(
            cfg.SET_KEY_COMFYUI_MODEL_ROOT, cfg.DEFAULT_COMFYUI_MODEL_ROOT, type=str
        ) or ""))
        d.comfyui_checkpoint_edit.setText(str(s.value(
            cfg.SET_KEY_COMFYUI_CHECKPOINT, cfg.DEFAULT_COMFYUI_CHECKPOINT, type=str
        ) or ""))
        d.comfyui_workflow_path_edit.setText(str(s.value(
            cfg.SET_KEY_COMFYUI_WORKFLOW_PATH, cfg.DEFAULT_COMFYUI_WORKFLOW_PATH, type=str
        ) or ""))
        d.hdr10plus_generator_enabled_cb.setChecked(bool(s.value(
            cfg.SET_KEY_HDR10PLUS_GENERATOR_ENABLED,
            cfg.DEFAULT_HDR10PLUS_GENERATOR_ENABLED,
            type=bool,
        )))

    def save(self) -> bool:
        d, s = self.dialog, self.settings
        s.setValue(cfg.SET_KEY_OUTPUT_CONTAINER_STANDARD, d.standard_container_combo.currentData() or cfg.DEFAULT_OUTPUT_CONTAINER_STANDARD)
        s.setValue(cfg.SET_KEY_OUTPUT_CONTAINER_DV, d.dv_container_combo.currentData() or cfg.DEFAULT_OUTPUT_CONTAINER_DV)
        s.setValue(cfg.SET_KEY_DV_REMUX_KEEP_DV7_MKV, d.dv_remux_keep_dv7_mkv_cb.isChecked())
        s.setValue(cfg.SET_KEY_DV_REMUX_ENCODE_DV5, d.dv_remux_encode_dv5_cb.isChecked())
        s.setValue(cfg.SET_KEY_AUTOCROP_MODE, d.autocrop_mode_combo.currentData() or cfg.DEFAULT_AUTOCROP_MODE)
        s.setValue(cfg.SET_KEY_AUTOCROP_PROBE_START, d.autocrop_start_spin.value())
        s.setValue(cfg.SET_KEY_AUTOCROP_PROBE_DURATION, d.autocrop_duration_spin.value())
        s.setValue(cfg.SET_KEY_AUTOCROP_PROBE_INTERVAL, d.autocrop_interval_spin.value())
        s.setValue(cfg.SET_KEY_IMAX_PROBE_INTERVAL, d.imax_probe_interval_spin.value())
        s.setValue(cfg.SET_KEY_IMAX_PROBE_DURATION, d.imax_probe_duration_spin.value())
        s.setValue(cfg.SET_KEY_IMAX_MIN_VARIANCE_PERCENT, d.imax_min_variance_spin.value())
        s.setValue(cfg.SET_KEY_IMAX_MIN_HITS, d.imax_min_hits_spin.value())

        s.setValue(cfg.SET_KEY_QUALITY_TARGET_ENABLED, d.quality_target_enabled_cb.isChecked())
        s.setValue(cfg.SET_KEY_QUALITY_TARGET_VMAF, d.quality_target_vmaf_spin.value())
        s.setValue(cfg.SET_KEY_QUALITY_TARGET_SAMPLES, d.quality_target_samples_spin.value())
        s.setValue(cfg.SET_KEY_QUALITY_TARGET_SAMPLE_DURATION, d.quality_target_duration_spin.value())
        low, high = sorted((d.quality_target_min_spin.value(), d.quality_target_max_spin.value()))
        s.setValue(cfg.SET_KEY_QUALITY_TARGET_MIN, low)
        s.setValue(cfg.SET_KEY_QUALITY_TARGET_MAX, high)
        s.setValue(cfg.SET_KEY_SDR_HDR_ENABLED, d.sdr_hdr_enabled_cb.isChecked())
        s.setValue(cfg.SET_KEY_SDR_HDR_CONTRAST_RECOVERY, d.sdr_hdr_contrast_spin.value())
        s.setValue(cfg.SET_KEY_SDR_HDR_BACKEND, d.sdr_hdr_backend_combo.currentData() or cfg.DEFAULT_SDR_HDR_BACKEND)
        s.setValue(cfg.SET_KEY_COMFYUI_BASE_URL, d.comfyui_base_url_edit.text().strip() or cfg.DEFAULT_COMFYUI_BASE_URL)
        s.setValue(cfg.SET_KEY_COMFYUI_AUTO_START, d.comfyui_auto_start_cb.isChecked())
        s.setValue(cfg.SET_KEY_COMFYUI_START_FILE, d.comfyui_start_file_edit.text().strip())
        s.setValue(cfg.SET_KEY_COMFYUI_START_WAIT_SECONDS, d.comfyui_start_wait_spin.value())
        s.setValue(cfg.SET_KEY_COMFYUI_MODEL_PROFILE, d.comfyui_model_profile_combo.currentData() or cfg.DEFAULT_COMFYUI_MODEL_PROFILE)
        s.setValue(cfg.SET_KEY_COMFYUI_MODEL_ROOT, d.comfyui_model_root_edit.text().strip())
        s.setValue(cfg.SET_KEY_COMFYUI_CHECKPOINT, d.comfyui_checkpoint_edit.text().strip())
        s.setValue(cfg.SET_KEY_COMFYUI_WORKFLOW_PATH, d.comfyui_workflow_path_edit.text().strip())
        s.setValue(cfg.SET_KEY_HDR10PLUS_GENERATOR_ENABLED, d.hdr10plus_generator_enabled_cb.isChecked())
        return True

    def sync_autocrop_mode(self) -> None:
        d = self.dialog
        d.autocrop_interval_spin.setEnabled(d.autocrop_mode_combo.currentData() == "multi")
