# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSpinBox, QFrame, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
    QGridLayout, QToolButton,
)
from ..core.settings import SET_KEY_AUTOCROP_ENABLED, SET_KEY_IMAX_DETECT, settings_bool, settings_value, ui_section_expanded_key
from .convert_widget_custom_widgets import BannerLabel, DragonProgressBar, _find_banner_single
from .convert_widget_file_queue import FileListWidget
from .info_button import InfoButton
from .convert_widget_layout_components import CollapsibleGroupBox

class ConvertWidgetLayoutOptionsMixin:
    def _build_scroll_root(self) -> QVBoxLayout:
        outer = QVBoxLayout(self.w)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setSpacing(5)
        outer.addWidget(scroll)
        scroll.setWidget(inner)
        return root

    def _build_banner_section(self, root: QVBoxLayout) -> None:
        banner_img = _find_banner_single()
        self.w.banner = BannerLabel()
        self.w.banner.setFixedHeight(180)
        if banner_img:
            self.w.banner.setBannerPixmap(QPixmap(banner_img))
            glow = QGraphicsDropShadowEffect(self.w)
            glow.setBlurRadius(36)
            glow.setOffset(0, 0)
            glow.setColor(QColor(255, 140, 0, 140))
            self.w.banner.setGraphicsEffect(glow)
        else:
            self.w.banner.setText(
                f"\U0001F409 Dragon Tools \u2013 {self.default_codec.upper()} Konvertierung"
            )
            self.w.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.w.banner.setStyleSheet(
                """
                background:#1a1a2e;
                color:#e0e0e0;
                font-size:16px;
                font-weight:bold;
                padding:12px;
                border-radius:8px;
                """
            )
        root.addWidget(self.w.banner)

    def _build_encoder_scaling_section(self, root: QVBoxLayout) -> None:
        eq = CollapsibleGroupBox(
            "⚙️ Encoder / Skalierung",
            collapsed=False,
            settings=self.settings,
            section_id="convert/encoder_scaling",
        )
        el = QGridLayout()
        eq.addLayout(el)
        el.addWidget(QLabel("🎛️ Encoder:"), 0, 0)
        self.w.encoder_combo = QComboBox()
        self.w.encoder_combo.addItems([
            "\U0001F5A5\ufe0f CPU (Software)",
            "\U0001F916 Auto (GPU erkennen)",
            "\U0001F7E2 NVIDIA NVENC",
            "\U0001F535 Intel QSV",
            "\U0001F534 AMD AMF",
        ])
        el.addWidget(self.w.encoder_combo, 0, 1)
        el.addWidget(
            InfoButton("CPU=beste Qualit\u00e4t/langsam. NVENC/QSV/AMF=schnell. Auto erkennt deine GPU automatisch."),
            0, 2,
        )
        el.addWidget(QLabel("📐 Skalierung:"), 0, 3)
        self.w.scale_combo = QComboBox()
        self.w.scale_combo.addItems(["original", "4K (2160p)", "1080p", "720p", "480p"])
        el.addWidget(self.w.scale_combo, 0, 4)
        el.addWidget(InfoButton("Zielaufl\u00f6sung. 'original' = Aufl\u00f6sung bleibt unver\u00e4ndert."), 0, 5)

        # Dummy-Felder damit bestehender Code nicht bricht (werden nicht angezeigt)
        self.w.crf_spin = QSpinBox()
        self.w.crf_spin.setRange(0, 63)
        self.w.crf_spin.setValue({"h264": 22, "h265": 22, "av1": 28}.get(self.default_codec, 22))
        self.w.crf_spin.setVisible(False)
        self.w.preset_combo = QComboBox()
        if self.default_codec == "av1":
            self.w.preset_combo.addItems(["4", "5", "6", "7", "8", "9", "10", "11", "12"])
            self.w.preset_combo.setCurrentText("6")
        else:
            self.w.preset_combo.addItems(
                ["ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow"]
            )
            self.w.preset_combo.setCurrentText("medium")
        self.w.preset_combo.setVisible(False)
        root.addWidget(eq)

    def _build_encoder_options_section(self, root: QVBoxLayout) -> None:
        self.w.enc_grp = CollapsibleGroupBox(
            "⚙️ Encoder-Optionen (erweitert)",
            collapsed=True,
            settings=self.settings,
            section_id="convert/encoder_options",
        )
        self.w.enc_grp.setVisible(True)
        eo = QGridLayout()
        self.w.enc_grp.addLayout(eo)
        self.w.nvenc_p = self.enc_settings.build_nvenc_panel()
        self.w.qsv_p   = self.enc_settings.build_qsv_panel()
        self.w.amf_p   = self.enc_settings.build_amf_panel()
        self.w.x265_p  = self.enc_settings.build_x265_panel()
        for panel in (self.w.nvenc_p, self.w.qsv_p, self.w.amf_p, self.w.x265_p):
            eo.addWidget(panel, 0, 0)
            panel.setVisible(False)
        root.addWidget(self.w.enc_grp)

    def _build_options_section(self, root: QVBoxLayout) -> None:
        og = CollapsibleGroupBox(
            "🧰 Optionen",
            collapsed=False,
            settings=self.settings,
            section_id="convert/options",
        )
        ol = QGridLayout()
        og.addLayout(ol)
        self.w.strip_cb = QCheckBox("📦 Strip-Only (kein Re-Encode)")
        strip_tooltip = (
            "Sondermodus \u2013 Streams werden nur kopiert, kein Re-Encode.\n"
            "\n"
            "Es gelten die Regeln f\u00fcr Audio und Untertitel mit einer Ausnahme:\n"
            "  \u2022 Burn in wird bei keinem Untertitel durchgef\u00fchrt\n"
            "  \u2022 wurde f\u00fcr einen Untertitel Burn in ausgew\u00e4hlt wird der stream einfach per copy in den container mit eingef\u00fcgt\n"
            "\n"
            "F\u00fcr volle Regel-/Override-Semantik: normalen Converter nutzen."
        )
        self.w.strip_cb.setToolTip(strip_tooltip)
        self.w.over_cb  = QCheckBox("♻️ Original überschreiben")
        self.w.move_cb  = QCheckBox("📁 Nach Abschluss verschieben")
        self.w.shut_cb  = QCheckBox("🔴 Herunterfahren")
        self.w.autocrop_cb = QCheckBox("✂️ Auto-Crop")
        self.w.autocrop_cb.setChecked(self.settings.value(SET_KEY_AUTOCROP_ENABLED, True, type=bool))
        ol.addWidget(self.w.strip_cb, 0, 0)
        ol.addWidget(InfoButton(strip_tooltip), 0, 1)
        ol.addWidget(self.w.over_cb, 1, 0)
        ol.addWidget(InfoButton("Ersetzt die Quelldatei durch die konvertierte Version."), 1, 1)
        ol.addWidget(self.w.move_cb, 0, 2)
        ol.addWidget(InfoButton("Verschiebt konvertierte Dateien nach Abschluss automatisch."), 0, 3)
        ol.addWidget(self.w.shut_cb, 2, 0)
        ol.addWidget(InfoButton("PC herunterfahren nach Abschluss aller Jobs."), 2, 1)
        ol.addWidget(self.w.autocrop_cb, 1, 2)
        ol.addWidget(InfoButton("Erkennt schwarze Balken (letterbox) automatisch und schneidet sie ab."), 1, 3)

        self.w.imax_detect_cb = QCheckBox("🎬 IMAX Auto-Erkennung")
        self.w.imax_detect_cb.setChecked(self.settings.value(SET_KEY_IMAX_DETECT, False, type=bool))
        self.w.imax_detect_cb.setToolTip(
            "Analysiert die aktive Bildfläche im gewählten Sekundenraster.\n"
            "Wechselndes Seitenverhältnis > 15% Varianz → IMAX wird automatisch aktiviert."
        )
        ol.addWidget(self.w.imax_detect_cb, 2, 2)
        ol.addWidget(
            InfoButton(
                "IMAX-Erkennung: Analysiert per Cropdetect die aktive Bildfläche im Film.\n"
                "Top Gun: Maverick, Interstellar usw. wechseln zwischen Letterbox und höherem IMAX-Bild.\n"
                "Auto-Crop wird bei erkanntem IMAX automatisch f\u00fcr diese Datei deaktiviert.\n"
                "Kürzere Intervalle erkennen Wechsel zuverlässiger, verlängern aber die Voranalyse."
            ),
            2, 3,
        )

        self.w.preserve_dv_cb = QCheckBox("🌈 Dolby Vision erhalten")
        self.w.preserve_dv_cb.setChecked(True)
        if self.default_codec == "av1":
            dv_tip = (
                "AV1 Dolby Vision Profile 10 (Beta).\n"
                "Native Verarbeitung zunächst mit CPU/SVT-AV1 und FFmpeg-DV-Metadaten.\n"
                "Nicht unterstützte Encoder brechen sicher ab, statt DV still zu verlieren."
            )
        else:
            dv_tip = (
                "Wenn aktiviert: Dolby-Vision-Dateien werden über die DV-Pipeline\n"
                "verarbeitet (dovi_tool + MP4Box). DV-Metadaten bleiben erhalten.\n"
                "Wenn deaktiviert: DV wird entfernt; HDR10-Basis/Farbraum bleibt erhalten."
            )
        self.w.preserve_dv_cb.setToolTip(dv_tip)
        self.w.preserve_hdrplus_cb = QCheckBox("\u2728 HDR10+ erhalten")
        self.w.preserve_hdrplus_cb.setChecked(True)
        if self.default_codec == "av1":
            hdr_tip = (
                "AV1 HDR10+ (Beta).\n"
                "Native Verarbeitung zunächst über FFmpeg/libaom-av1 mit HDR10+-T.35-OBU.\n"
                "Nicht unterstützte Encoder brechen sicher ab, statt HDR10+ still zu verlieren."
            )
        else:
            hdr_tip = (
                "Wenn aktiviert: HDR10+-Dateien werden über die HDR10+-Pipeline\n"
                "verarbeitet (hdr10plus_tool). HDR10+-Metadaten bleiben erhalten.\n"
                "Wenn deaktiviert: HDR10+ wird ignoriert, Standard-H.265-Encode."
            )
        self.w.preserve_hdrplus_cb.setToolTip(hdr_tip)
        self.w.preserve_dv_info_btn      = InfoButton(dv_tip)
        self.w.preserve_hdrplus_info_btn = InfoButton(hdr_tip)
        ol.addWidget(self.w.preserve_dv_cb,           3, 0)
        ol.addWidget(self.w.preserve_dv_info_btn,     3, 1)
        ol.addWidget(self.w.preserve_hdrplus_cb,      3, 2)
        ol.addWidget(self.w.preserve_hdrplus_info_btn, 3, 3)

        # Profile liegen jetzt im einklappbaren Optionen-Bereich.
        # Vorteil: Die separate Profil-Zeile entfällt und spart vertikal Platz.
        self.w.save_prof = QPushButton("💾 Profil speichern")
        self.w.load_prof = QPushButton("📂 Profil laden")
        self.w.assist_prof = QPushButton("🧭 Profil-Assistent")
        profile_tip = "Profile speichern CRF, Preset, Encoder und Skalierung für Filme/TV/Anime."
        self.w.save_prof.setToolTip(profile_tip)
        self.w.load_prof.setToolTip("Lädt ein zuvor gespeichertes Profil.")
        self.w.assist_prof.setToolTip("Wählt ein empfohlenes Startprofil. Alle Werte bleiben danach manuell editierbar.")
        ol.addWidget(self.w.assist_prof, 4, 0, 1, 1)
        ol.addWidget(self.w.save_prof, 4, 1, 1, 1)
        ol.addWidget(self.w.load_prof, 4, 2, 1, 1)
        ol.addWidget(InfoButton(profile_tip), 4, 3)

        root.addWidget(og)

    def _build_profile_section(self, root: QVBoxLayout) -> None:
        """
        Profil-Buttons werden platzsparend im einklappbaren Optionen-Block aufgebaut.

        Die Methode bleibt bewusst bestehen, weil der Builder sie weiterhin aufruft.
        Dadurch müssen keine anderen Dateien angepasst werden.
        """
        return
