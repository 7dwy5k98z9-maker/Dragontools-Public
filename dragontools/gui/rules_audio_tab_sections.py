# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout)
from .info_button import InfoButton
from .rules_language_editor import _LanguagePriorityEditor
from ..rules import audio_rules as _ar

class AudioTabSectionsMixin:
    def _build_language_section(self, v: QVBoxLayout) -> None:
        # ── Sprachen ─────────────────────────────────────────────────
        lg = QGroupBox("Audio-Sprachen")
        ll = QVBoxLayout(lg)
        self.language_editor = _LanguagePriorityEditor(
            priority=self._data.get("language_priority") or (
                list(self._data.get("preferred_languages", [])) + list(self._data.get("fallback_languages", []))
            ),
            max_languages=int(self._data.get("max_languages", self._data.get("max_tracks", 1)) or 1),
            tracks_per_language=int(self._data.get("tracks_per_language", 1) or 1),
            fallback_policy=self._data.get("fallback_if_no_priority_match", "keep_all"),
            fallback_options=[
                ("keep_all", "Alle Audiospuren übernehmen"),
                ("keep_first", "Erste Audiospur übernehmen"),
                ("keep_none", "Keine Audiospur übernehmen"),
            ],
            max_label="Max. Sprachen übernehmen:",
            tracks_label="Max. Tonspuren je Sprache:",
        )
        ll.addWidget(self.language_editor)
        self.ignore_commentary_cb = QCheckBox("Kommentarspuren überspringen")
        self.ignore_commentary_cb.setChecked(bool(self._data.get("ignore_commentary_tracks", True)))
        self.ignore_descriptive_cb = QCheckBox("Audiodeskription überspringen")
        self.ignore_descriptive_cb.setChecked(bool(self._data.get("ignore_descriptive_audio", True)))
        opt_row = QHBoxLayout()
        opt_row.addWidget(self.ignore_commentary_cb)
        opt_row.addWidget(self.ignore_descriptive_cb)
        opt_row.addStretch()
        ll.addLayout(opt_row)
        v.addWidget(lg)

    def _build_passthrough_section(self, v: QVBoxLayout) -> None:
        # ── Passthrough ───────────────────────────────────────────────
        pg = QGroupBox("Passthrough-Codecs (werden direkt kopiert wenn Bitrate OK)"); pl = QVBoxLayout(pg)
        row_p = QHBoxLayout()
        row_p.addWidget(QLabel("Diese Codecs werden NICHT transkodiert, solange die Bitrate unter der Grenze liegt:"))
        row_p.addWidget(InfoButton(
            "Codecs die direkt kopiert werden dürfen.\n"
            "AAC, AC3, E-AC3 sind container-kompatibel und verlustfrei kopierbar.\n"
            "Entferne einen Codec wenn er immer transkodiert werden soll."
        ))
        pl.addLayout(row_p)
        self.pass_edit = QLineEdit(", ".join(self._data.get("passthrough_codecs", ["aac","ac3","eac3"])))
        pl.addWidget(self.pass_edit)
        v.addWidget(pg)

    def _build_extra_stereo_section(self, v: QVBoxLayout) -> None:
        # ── Zusatz-Stereo-Downmix ─────────────────────────────────────
        xsg = QGroupBox("🎧 Zusatz-Stereo-Downmix")
        xsl = QGridLayout(xsg)
        self.extra_stereo_cb = QCheckBox(
            "Zusatz-Stereo-Spur hinzufügen (für alle Mehrkanal-Spuren die in die Datei kommen)"
        )
        self.extra_stereo_cb.setChecked(self._data.get("extra_stereo", False))
        xsl.addWidget(self.extra_stereo_cb, 0, 0, 1, 3)
        xsl.addWidget(InfoButton(
            "Wenn aktiv: Jede Mehrkanal-Audiospur (>2 Kanäle), die in die neue Datei kommt,\n"
            "wird zusätzlich als separate Stereo-Spur mit dem gewählten Codec hinzugefügt.\n\n"
            "Beispiel: DE 5.1 → Datei enthält DE 5.1 + DE Stereo\n"
            "Beispiel: DE 5.1, EN 5.1 → Datei enthält DE 5.1 + DE Stereo + EN 5.1 + EN Stereo\n\n"
            "Nützlich für Geräte die kein Surround unterstützen aber Stereo-Fallback brauchen.\n"
            "Ist die Originalspur bereits Mono/Stereo, wird KEINE zusätzliche Spur erzeugt."
        ), 0, 3)
        xsl.addWidget(QLabel("Codec Stereo-Spur:"), 1, 0)
        self.extra_stereo_codec = QComboBox()
        self.extra_stereo_codec.addItems(["aac", "eac3", "ac3"])
        self.extra_stereo_codec.setCurrentText(self._data.get("extra_stereo_codec", "aac"))
        xsl.addWidget(self.extra_stereo_codec, 1, 1)
        xsl.addWidget(InfoButton(
            "Codec der zusätzlichen Stereo-Spur.\n"
            "AAC ist am kompatibelsten und passt zu den normalen Stereo-Regeln.\n"
            "E-AC3 oder AC3 sind sinnvoll, wenn du einheitlich Dolby-Spuren bevorzugst."
        ), 1, 2)
        xsl.addWidget(QLabel("Bitrate Stereo-Spur:"), 2, 0)
        self.extra_stereo_br = QSpinBox()
        self.extra_stereo_br.setRange(64, 640)
        self.extra_stereo_br.setSingleStep(32)
        self.extra_stereo_br.setValue(int(self._data.get("extra_stereo_bitrate_k", 256)))
        self.extra_stereo_br.setSuffix(" kbps")
        xsl.addWidget(self.extra_stereo_br, 2, 1)
        xsl.addWidget(InfoButton(
            "Bitrate der zusätzlichen Stereo-Spur in kbps.\n"
            "Empfehlung: 192-256 kbps für AAC oder EAC3 Stereo."
        ), 2, 2)
        self.extra_stereo_br.setEnabled(self.extra_stereo_cb.isChecked())
        self.extra_stereo_codec.setEnabled(self.extra_stereo_cb.isChecked())
        self.extra_stereo_cb.toggled.connect(self.extra_stereo_br.setEnabled)
        self.extra_stereo_cb.toggled.connect(self.extra_stereo_codec.setEnabled)
        v.addWidget(xsg)

    def _build_audio_processing_section(self, v: QVBoxLayout) -> None:
        # ── Audio-Dynamik / Lautheit ──────────────────────────────────
        ap = _ar.normalize_audio_processing_config(self._data)
        self._audio_processing_lra = float(ap.get("loudnorm_lra", 11.0))
        self._audio_processing_tp = float(ap.get("loudnorm_tp", -1.5))
        ag = QGroupBox('Audio-Dynamik / Lautheit')
        al = QGridLayout(ag)
        self.drc_cb = QCheckBox('DRC / "Normalisierung" / Nachtmodus aktivieren')
        self.drc_cb.setChecked(bool(ap.get("drc_enabled", False)))
        al.addWidget(self.drc_cb, 0, 0, 1, 2)
        al.addWidget(InfoButton(
            "DRC nutzt die Dynamic-Range-Control-Metadaten von AC3/E-AC3.\n"
            "Das ist HandBrake-ähnlicher Nachtmodus: leise Anteile werden angehoben,\n"
            "kurze laute Spitzen werden abgefedert.\n\n"
            "Wichtig: Greift nur bei AC3/E-AC3-Quellen und nur wenn die Audiospur dekodiert\n"
            "und neu kodiert wird. DragonTools verhindert dafür automatisch Stream-Copy,\n"
            "wenn DRC bei einer passenden Quelle aktiv ist."
        ), 0, 2)
        al.addWidget(QLabel("DRC-Stärke:"), 1, 0)
        self.drc_scale = QDoubleSpinBox()
        self.drc_scale.setRange(0.0, 4.0)
        self.drc_scale.setSingleStep(0.1)
        self.drc_scale.setDecimals(1)
        self.drc_scale.setValue(float(ap.get("drc_scale", 1.0)))
        al.addWidget(self.drc_scale, 1, 1)
        drc_hint = QLabel(
            "0.0 aus / volle Dynamik | 0.1-0.9 gering | 1.0 normal | "
            "1.1-1.5 leicht | 1.6-2.0 mittel | 2.1-2.5 stark | "
            "2.6-3.0 Nachtmodus | 3.1-4.0 extrem / nicht empfohlen"
        )
        drc_hint.setWordWrap(True)
        al.addWidget(drc_hint, 2, 0, 1, 3)

        self.loudnorm_cb = QCheckBox("Allgemeine Lautheitsnormalisierung aktivieren")
        self.loudnorm_cb.setChecked(bool(ap.get("loudnorm_enabled", False)))
        al.addWidget(self.loudnorm_cb, 3, 0, 1, 2)
        al.addWidget(InfoButton(
            "Loudnorm misst und korrigiert die wahrgenommene Lautheit über FFmpeg.\n"
            "Das funktioniert codecübergreifend, erzwingt aber ebenfalls eine Neukodierung\n"
            "der betroffenen Audiospur.\n\n"
            "Empfehlung: ausgeschaltet lassen und nur gezielt nutzen, wenn Serien/Filme\n"
            "sehr unterschiedliche Lautstärken haben."
        ), 3, 2)
        al.addWidget(QLabel("Ziel-Lautheit:"), 4, 0)
        self.loudnorm_i = QDoubleSpinBox()
        self.loudnorm_i.setRange(-40.0, -5.0)
        self.loudnorm_i.setSingleStep(0.5)
        self.loudnorm_i.setDecimals(1)
        self.loudnorm_i.setSuffix(" LUFS")
        self.loudnorm_i.setValue(float(ap.get("loudnorm_i", -18.0)))
        al.addWidget(self.loudnorm_i, 4, 1)

        def _refresh_audio_processing_enabled():
            self.drc_scale.setEnabled(self.drc_cb.isChecked())
            self.loudnorm_i.setEnabled(self.loudnorm_cb.isChecked())

        self.drc_cb.toggled.connect(lambda _on: _refresh_audio_processing_enabled())
        self.loudnorm_cb.toggled.connect(lambda _on: _refresh_audio_processing_enabled())
        _refresh_audio_processing_enabled()
        v.addWidget(ag)

    def _build_transcode_section(self, v: QVBoxLayout) -> None:
        # ── Immer-Transkodieren ───────────────────────────────────────
        tg = QGroupBox("Immer transkodieren  –  diese Codecs werden NIE kopiert"); tl = QVBoxLayout(tg)
        tl.addWidget(QLabel(
            "Diese Codecs sind verlustfrei oder container-inkompatibel und werden immer\n"
            "zum Ziel-Codec der jeweiligen Kanal-Stufe (oben) transkodiert:"
        ))

        trans = self._data.get("transcode_rules", {})
        self._trans_checks: dict[str, QCheckBox] = {}
        self._trans_codecs: dict[str, QComboBox] = {}

        known = {
            "truehd":     "TrueHD (Dolby Atmos verlustfrei)",
            "dts-hd ma":  "DTS-HD Master Audio",
            "dts-hd hra": "DTS-HD High Resolution",
            "dts":        "DTS (Core)",
            "flac":       "FLAC (verlustfrei)",
            "pcm":        "PCM (unkomprimiert)",
            "mp2":        "MP2 (veraltet)",
            "mp3":        "MP3 (veraltet)",
        }
        for codec, label in known.items():
            row = QHBoxLayout()
            cb = QCheckBox(label); cb.setChecked(codec in trans)
            self._trans_checks[codec] = cb
            cc = QComboBox(); cc.addItems(["eac3","ac3","aac"])
            cc.setCurrentText(trans.get(codec, {}).get("target_codec", "eac3") if isinstance(trans.get(codec), dict) else "eac3")
            cc.setFixedWidth(80); cc.setEnabled(codec in trans)
            self._trans_codecs[codec] = cc
            cb.toggled.connect(lambda on, c=cc: c.setEnabled(on))
            row.addWidget(cb); row.addWidget(QLabel("→")); row.addWidget(cc); row.addStretch()
            tl.addLayout(row)

        v.addWidget(tg)

    def _build_preview_section(self, v: QVBoxLayout) -> None:
        # ── Vorschau ─────────────────────────────────────────────────
        prev_g = QGroupBox("Vorschau: Wie wird mein Audio behandelt?"); prev_l = QVBoxLayout(prev_g)
        prev_l.addWidget(QLabel("Codec eingeben und Kanäle / Bitrate einstellen:"))
        p_row = QHBoxLayout()
        p_row.addWidget(QLabel("Codec:"))
        self.p_codec = QLineEdit("truehd"); self.p_codec.setFixedWidth(120); p_row.addWidget(self.p_codec)
        p_row.addWidget(QLabel("Kanäle:"))
        self.p_ch = QSpinBox(); self.p_ch.setRange(1,8); self.p_ch.setValue(6); self.p_ch.setFixedWidth(60); p_row.addWidget(self.p_ch)
        p_row.addWidget(QLabel("Bitrate (kbps):"))
        self.p_br = QSpinBox(); self.p_br.setRange(0,9999); self.p_br.setValue(0); self.p_br.setFixedWidth(80)
        self.p_br.setSpecialValueText("Original"); p_row.addWidget(self.p_br)
        p_row.addStretch()
        prev_l.addLayout(p_row)
        prev_btn = QPushButton("🔍 Prüfen"); prev_btn.clicked.connect(self._preview); prev_l.addWidget(prev_btn)
        self.prev_res = QLabel(""); self.prev_res.setWordWrap(True)
        self.prev_res.setStyleSheet("padding:6px;border:1px solid #c0c0c0;border-radius:3px;background:#f9f9f9;")
        prev_l.addWidget(self.prev_res)
        v.addWidget(prev_g)
