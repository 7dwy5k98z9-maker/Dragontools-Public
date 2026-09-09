# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel,
    QVBoxLayout, QWidget,
)

from ..core.type_utils import _safe_float
from .info_button import InfoButton


class ConvertOverrideGroupBuilderMixin:
    @staticmethod
    def _build_processing_group(cv: QVBoxLayout, processing_mode_value: str) -> QComboBox:
        pg = QGroupBox("Verarbeitung")
        pl = QGridLayout(pg)
        pl.addWidget(QLabel("Modus:"), 0, 0)
        processing_combo = QComboBox()
        processing_combo.addItem("Global / normaler Lauf", "auto")
        processing_combo.addItem("Nur remuxen (Strip-Only)", "strip_only")
        processing_combo.setCurrentIndex(1 if processing_mode_value == "strip_only" else 0)
        pl.addWidget(processing_combo, 0, 1)
        pl.addWidget(
            InfoButton(
                "Global / normaler Lauf = die normalen Einstellungen des Starts gelten.\n"
                "Nur remuxen = diese Datei nutzt den bestehenden Strip-Only-Modus: "
                "Video wird kopiert, Audio und Untertitel folgen den Strip-Only-Regeln."
            ),
            0,
            2,
        )
        cv.addWidget(pg)
        return processing_combo

    @staticmethod
    def _build_audio_group(cv: QVBoxLayout, audio_mode_value: str):
        ag = QGroupBox("Audio")
        al = QGridLayout(ag)
        al.addWidget(QLabel("Modus:"), 0, 0)
        ac = QComboBox()
        ac.addItem("auto", "auto")
        ac.addItem("benutzerdefiniert", "custom")
        ac.setCurrentIndex(0 if audio_mode_value == "auto" else 1)
        al.addWidget(ac, 0, 1)
        al.addWidget(
            InfoButton("auto=Regeln anwenden. benutzerdefiniert=Spuren einzeln steuern."),
            0,
            2,
        )
        audio_status = QLabel("Analysiere Mediendaten …")
        al.addWidget(audio_status, 1, 0, 1, 3)
        audio_panel = QWidget()
        apl = QGridLayout(audio_panel)
        apl.setContentsMargins(0, 6, 0, 0)
        al.addWidget(audio_panel, 2, 0, 1, 3)
        audio_rows: list = []
        cv.addWidget(ag)
        return ac, audio_status, audio_panel, apl, audio_rows

    @staticmethod
    def _build_processing_mode_combo(current_mode: str) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Regeln übernehmen", "inherit")
        combo.addItem("Aktivieren", "on")
        combo.addItem("Deaktivieren", "off")
        idx = combo.findData(current_mode)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        return combo

    def _build_audio_processing_group(self, cv: QVBoxLayout, audio_drc_state: dict, audio_loudnorm_state: dict):
        apg = QGroupBox("Audio-Dynamik / Lautheit")
        apl2 = QGridLayout(apg)

        apl2.addWidget(QLabel("DRC / Nachtmodus:"), 0, 0)
        drc_mode_combo = self._build_processing_mode_combo(str(audio_drc_state.get("mode", "inherit")))
        apl2.addWidget(drc_mode_combo, 0, 1)
        drc_scale_spin = QDoubleSpinBox()
        drc_scale_spin.setRange(0.0, 4.0)
        drc_scale_spin.setSingleStep(0.1)
        drc_scale_spin.setDecimals(1)
        drc_scale_spin.setValue(max(0.0, min(4.0, _safe_float(audio_drc_state.get("scale"), 1.0))))
        apl2.addWidget(drc_scale_spin, 0, 2)
        apl2.addWidget(
            InfoButton(
                "DRC nutzt AC3/E-AC3-Dynamik-Metadaten und greift nur bei AC3/E-AC3-Quellen.\n"
                "Wenn DRC für diese Datei aktiv ist und die Quelle passt, verhindert DragonTools Stream-Copy,\n"
                "damit der Wert wirklich angewendet wird.\n\n"
                "0.0 volle Dynamik, 1.0 normal, 2.6-3.0 Nachtmodus, 3.1-4.0 extrem / nicht empfohlen."
            ),
            0,
            3,
        )

        apl2.addWidget(QLabel("Lautheitsnormalisierung:"), 1, 0)
        loudnorm_mode_combo = self._build_processing_mode_combo(
            str(audio_loudnorm_state.get("mode", "inherit"))
        )
        apl2.addWidget(loudnorm_mode_combo, 1, 1)
        loudnorm_i_spin = QDoubleSpinBox()
        loudnorm_i_spin.setRange(-40.0, -5.0)
        loudnorm_i_spin.setSingleStep(0.5)
        loudnorm_i_spin.setDecimals(1)
        loudnorm_i_spin.setSuffix(" LUFS")
        loudnorm_i_spin.setValue(
            max(-40.0, min(-5.0, _safe_float(audio_loudnorm_state.get("i"), -18.0)))
        )
        apl2.addWidget(loudnorm_i_spin, 1, 2)
        apl2.addWidget(
            InfoButton(
                "Codecübergreifende Lautheitsnormalisierung über FFmpeg loudnorm.\n"
                "Wenn aktiv, wird die betroffene Audiospur neu kodiert. Zielwert -18 LUFS ist ein guter\n"
                "Startwert für Serien/Filme, die insgesamt zu leise oder uneinheitlich wirken."
            ),
            1,
            3,
        )

        def _refresh_audio_processing_override() -> None:
            drc_scale_spin.setEnabled(drc_mode_combo.currentData() == "on")
            loudnorm_i_spin.setEnabled(loudnorm_mode_combo.currentData() == "on")

        drc_mode_combo.currentIndexChanged.connect(lambda _idx: _refresh_audio_processing_override())
        loudnorm_mode_combo.currentIndexChanged.connect(lambda _idx: _refresh_audio_processing_override())
        _refresh_audio_processing_override()
        cv.addWidget(apg)
        return drc_mode_combo, drc_scale_spin, loudnorm_mode_combo, loudnorm_i_spin

    @staticmethod
    def _build_subtitle_group(cv: QVBoxLayout, subtitle_mode_value: str, ov: dict):
        sg = QGroupBox("Untertitel")
        sl = QGridLayout(sg)
        sl.addWidget(QLabel("Modus:"), 0, 0)
        bc = QComboBox()
        bc.addItem("auto", "auto")
        bc.addItem("benutzerdefiniert", "custom")
        bc.setCurrentIndex(0 if subtitle_mode_value == "auto" else 1)
        sl.addWidget(bc, 0, 1)
        sl.addWidget(
            InfoButton("auto=Regeln anwenden. benutzerdefiniert=Spuren einzeln wählen."),
            0,
            2,
        )
        subtitle_status = QLabel("Analysiere Mediendaten …")
        sl.addWidget(subtitle_status, 1, 0, 1, 3)
        subtitle_panel = QWidget()
        spl = QGridLayout(subtitle_panel)
        spl.setContentsMargins(0, 6, 0, 0)
        sl.addWidget(subtitle_panel, 2, 0, 1, 3)
        subtitle_rows: list = []
        imax_cb = QCheckBox("IMAX (Auto-Crop deaktivieren)")
        imax_cb.setChecked(bool(ov.get("imax", False)))
        sl.addWidget(imax_cb, 3, 0, 1, 3)
        cv.addWidget(sg)
        return bc, subtitle_status, subtitle_panel, spl, subtitle_rows, imax_cb

    def _build_hdr_policy_group(self, cv: QVBoxLayout, ov: dict):
        from ..core.settings import (
            SET_KEY_PRESERVE_DV, SET_KEY_PRESERVE_HDRPLUS,
            SET_KEY_AV1_PRESERVE_DV, SET_KEY_AV1_PRESERVE_HDRPLUS,
        )
        from PyQt6.QtCore import QSettings as _QS

        ow = self.owner
        qs = _QS(ow.settings.organizationName(), ow.settings.applicationName())
        codec = str(getattr(ow, "default_codec", "h265") or "h265").lower()
        dv_key = SET_KEY_AV1_PRESERVE_DV if codec == "av1" else SET_KEY_PRESERVE_DV
        hdp_key = SET_KEY_AV1_PRESERVE_HDRPLUS if codec == "av1" else SET_KEY_PRESERVE_HDRPLUS
        global_dv = qs.value(dv_key, True, type=bool)
        global_hdp = qs.value(hdp_key, True, type=bool)

        hdr_grp = QGroupBox("DV / HDR10+ Policy (per Datei)")
        hdr_l = QGridLayout(hdr_grp)
        dv_combo = QComboBox()
        hdp_combo = QComboBox()
        for combo in (dv_combo, hdp_combo):
            combo.addItem("Global-Standard", None)
            combo.addItem("✅ Immer erhalten", True)
            combo.addItem("⛔ Ignorieren", False)

        def _set_combo(combo: QComboBox, key: str) -> None:
            val = ov.get(key)
            if val is None:
                combo.setCurrentIndex(0)
            elif bool(val):
                combo.setCurrentIndex(1)
            else:
                combo.setCurrentIndex(2)

        _set_combo(dv_combo, "preserve_dv")
        _set_combo(hdp_combo, "preserve_hdrplus")
        hdr_l.addWidget(QLabel("🎨 Dolby Vision:"), 0, 0)
        hdr_l.addWidget(dv_combo, 0, 1)
        hdr_l.addWidget(
            InfoButton(
                f"Global-Standard = globale Einstellung benutzen "
                f"(aktuell: {'erhalten' if global_dv else 'ignorieren'}).\n"
                "Immer erhalten = DV-Pipeline erzwingen, auch wenn global deaktiviert.\n"
                "Ignorieren = Standard-Encode erzwingen, DV-Metadaten gehen verloren."
            ),
            0,
            2,
        )
        hdr_l.addWidget(QLabel("✨ HDR10+:"), 1, 0)
        hdr_l.addWidget(hdp_combo, 1, 1)
        hdr_l.addWidget(
            InfoButton(
                f"Global-Standard = globale Einstellung benutzen "
                f"(aktuell: {'erhalten' if global_hdp else 'ignorieren'}).\n"
                "Immer erhalten = HDR10+-Pipeline erzwingen.\n"
                "Ignorieren = Standard-Encode erzwingen."
            ),
            1,
            2,
        )
        cv.addWidget(hdr_grp)
        return dv_combo, hdp_combo
