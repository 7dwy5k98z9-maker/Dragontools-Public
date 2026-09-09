# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from .info_button import InfoButton


@dataclass
class EncoderSettingsWidgets:
    encoder_combo: object | None = None
    scale_combo: object | None = None
    preset_combo: object | None = None
    crf_spin: object | None = None
    strip_cb: object | None = None
    over_cb: object | None = None
    move_cb: object | None = None
    shut_cb: object | None = None
    autocrop_cb: object | None = None
    imax_detect_cb: object | None = None
    preserve_dv_cb: object | None = None
    preserve_hdrplus_cb: object | None = None
    enc_grp: object | None = None
    nvenc_p: object | None = None
    qsv_p: object | None = None
    amf_p: object | None = None
    x265_p: object | None = None
    nv_preset: object | None = None
    nv_cq: object | None = None
    nv_bf: object | None = None
    nv_bref: object | None = None
    nv_la: object | None = None
    nv_lookahead_level: object | None = None
    nv_multipass: object | None = None
    nv_aq: object | None = None
    nv_spatial: object | None = None
    nv_temporal: object | None = None
    qsv_preset: object | None = None
    qsv_q: object | None = None
    qsv_la_depth: object | None = None
    amf_qp: object | None = None
    amf_qual: object | None = None
    x265_crf: object | None = None
    x265_preset: object | None = None
    x265_tune: object | None = None
    x265_aqm: object | None = None
    x265_aqs: object | None = None
    x265_psy: object | None = None
    x265_psyrdoq: object | None = None
    x265_bf: object | None = None
    x265_la: object | None = None


class EncoderSettingsUI:
    def __init__(self, *, default_codec: str) -> None:
        self._default_codec = default_codec
        self.widgets = EncoderSettingsWidgets()

    def bind_main_widgets(
        self,
        *,
        encoder_combo,
        scale_combo,
        preset_combo,
        crf_spin,
        strip_cb,
        over_cb,
        move_cb,
        shut_cb,
        autocrop_cb,
        imax_detect_cb,
        preserve_dv_cb,
        preserve_hdrplus_cb,
        enc_grp,
        nvenc_p,
        qsv_p,
        amf_p,
        x265_p,
    ) -> None:
        self.widgets.encoder_combo = encoder_combo
        self.widgets.scale_combo = scale_combo
        self.widgets.preset_combo = preset_combo
        self.widgets.crf_spin = crf_spin
        self.widgets.strip_cb = strip_cb
        self.widgets.over_cb = over_cb
        self.widgets.move_cb = move_cb
        self.widgets.shut_cb = shut_cb
        self.widgets.autocrop_cb = autocrop_cb
        self.widgets.imax_detect_cb = imax_detect_cb
        self.widgets.preserve_dv_cb = preserve_dv_cb
        self.widgets.preserve_hdrplus_cb = preserve_hdrplus_cb
        self.widgets.enc_grp = enc_grp
        self.widgets.nvenc_p = nvenc_p
        self.widgets.qsv_p = qsv_p
        self.widgets.amf_p = amf_p
        self.widgets.x265_p = x265_p

    def build_nvenc_panel(self):
        from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QComboBox, QSpinBox, QCheckBox

        w = QWidget()
        np = QGridLayout(w)
        np.addWidget(QLabel("🧩 Preset:"), 0, 0)
        self.widgets.nv_preset = QComboBox()
        self.widgets.nv_preset.addItems(["p1", "p2", "p3", "p4", "p5", "p6", "p7"])
        self.widgets.nv_preset.setCurrentText("p6")
        np.addWidget(self.widgets.nv_preset, 0, 1)
        np.addWidget(InfoButton("p1=schnell/schlechter, p7=langsam/besser. p4 ist guter Kompromiss."), 0, 2)
        np.addWidget(QLabel("🎚️ CQ:"), 0, 3)
        self.widgets.nv_cq = QSpinBox()
        self.widgets.nv_cq.setRange(0, 63)
        self.widgets.nv_cq.setValue(23)
        np.addWidget(self.widgets.nv_cq, 0, 4)
        np.addWidget(InfoButton(
            "CQ (Constant Quality): Qualitätsziel für NVENC.\n"
            "0 = beste Qualität / größte Datei, 63 = schlechteste Qualität.\n"
            "Empfohlen: 18–28. CQ 23 ist ein guter Ausgangspunkt.\n"
            "Anders als CRF (CPU) steuert CQ den internen Quantizer direkt."
        ), 0, 5)
        np.addWidget(QLabel("🎞️ B-Frames:"), 1, 0)
        self.widgets.nv_bf = QSpinBox()
        self.widgets.nv_bf.setRange(0, 8)
        self.widgets.nv_bf.setValue(4)
        np.addWidget(self.widgets.nv_bf, 1, 1)
        np.addWidget(InfoButton("B-Frames verbessern Kompression. 4 ist Standard für NVENC."), 1, 2)
        np.addWidget(QLabel("🔗 B-Ref-Mode:"), 1, 3)
        self.widgets.nv_bref = QComboBox()
        self.widgets.nv_bref.addItems(["disabled", "each", "middle"])
        self.widgets.nv_bref.setCurrentText("middle")
        np.addWidget(self.widgets.nv_bref, 1, 4)
        np.addWidget(InfoButton("'middle': jeder 2. B-Frame als Referenz – beste Qualität. 'disabled': kompatibel."), 1, 5)
        np.addWidget(QLabel("🔮 Lookahead:"), 2, 0)
        self.widgets.nv_la = QSpinBox()
        self.widgets.nv_la.setRange(0, 64)
        self.widgets.nv_la.setValue(32)
        np.addWidget(self.widgets.nv_la, 2, 1)
        np.addWidget(InfoButton(
            "Lookahead: Anzahl zukünftiger Frames, die NVENC bei der Bitrate-Entscheidung\n"
            "vorausschaut. Höhere Werte = bessere Qualität, leicht höherer VRAM-Verbrauch.\n"
            "0 = deaktiviert. 8–32 empfohlen. Maximaler Effekt bei 32."
        ), 2, 2)
        np.addWidget(QLabel("📶 AQ-Stärke:"), 2, 3)
        self.widgets.nv_aq = QSpinBox()
        self.widgets.nv_aq.setRange(1, 15)
        self.widgets.nv_aq.setValue(8)
        np.addWidget(self.widgets.nv_aq, 2, 4)
        np.addWidget(InfoButton(
            "AQ-Stärke (Adaptive Quantization Strength): Wie stark AQ die\n"
            "Bitrateverteilung beeinflusst. Nur wirksam wenn Spatial AQ aktiv.\n"
            "1 = schwach, 15 = stark. Empfohlen: 6–10.\n"
            "Zu hohe Werte können Blocking-Artefakte erzeugen."
        ), 2, 5)
        np.addWidget(QLabel("🎯 Lookahead-Level:"), 3, 0)
        self.widgets.nv_lookahead_level = QComboBox()
        self.widgets.nv_lookahead_level.addItem("Auto", "auto")
        for value in range(0, 4):
            self.widgets.nv_lookahead_level.addItem(str(value), str(value))
        np.addWidget(self.widgets.nv_lookahead_level, 3, 1)
        np.addWidget(InfoButton(
            "NVENC Lookahead-Level: zusätzliche Qualitäts-/Entscheidungsstufe für Lookahead.\n"
            "Zulässiger FFmpeg/NVENC-Bereich: 0–3.\n"
            "Auto übergibt keinen Parameter und nutzt den FFmpeg/NVENC-Standard.\n"
            "Höhere Werte können die Kompression verbessern, kosten aber zusätzliche Analyseleistung."
        ), 3, 2)
        np.addWidget(QLabel("🔁 Multipass:"), 3, 3)
        self.widgets.nv_multipass = QComboBox()
        self.widgets.nv_multipass.addItem("Auto/Default", "auto")
        self.widgets.nv_multipass.addItem("disabled", "disabled")
        self.widgets.nv_multipass.addItem("qres", "qres")
        self.widgets.nv_multipass.addItem("fullres", "fullres")
        np.addWidget(self.widgets.nv_multipass, 3, 4)
        np.addWidget(InfoButton(
            "NVENC Multipass: bessere Bitverteilung für Offline-Encoding.\n"
            "Auto/Default übergibt keinen Parameter. qres ist schneller, fullres kann effizienter sein,\n"
            "braucht aber mehr Zeit und Ressourcen."
        ), 3, 5)
        self.widgets.nv_spatial = QCheckBox("📡 Spatial AQ")
        self.widgets.nv_spatial.setChecked(True)
        np.addWidget(self.widgets.nv_spatial, 4, 0)
        np.addWidget(InfoButton(
            "Spatial AQ: Verteilt mehr Bits auf räumlich komplexe Bereiche\n"
            "(z. B. detaillierte Texturen, Gras, Rauschen).\n"
            "Verbessert die Qualität in schwierigen Szenen spürbar.\n"
            "Empfehlung: aktiviert."
        ), 4, 2)

        self.widgets.nv_temporal = QCheckBox("⏱️ Temporal AQ")
        self.widgets.nv_temporal.setChecked(True)
        np.addWidget(self.widgets.nv_temporal, 4, 3)
        np.addWidget(InfoButton(
            "Temporal AQ: Verteilt mehr Bits auf zeitlich wichtige Frames\n"
            "(z. B. Szenen mit wenig Bewegung, wo Qualitätsverluste auffallen).\n"
            "Kann zusammen mit Spatial AQ aktiviert werden.\n"
            "Empfehlung: aktiviert – kaum Mehraufwand, merkliche Qualitätsverbesserung."
        ), 4, 5)
        return w

    def build_qsv_panel(self):
        from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QComboBox, QSpinBox

        w = QWidget()
        qp = QGridLayout(w)
        qp.addWidget(QLabel("🧩 Preset:"), 0, 0)
        self.widgets.qsv_preset = QComboBox()
        self.widgets.qsv_preset.addItems(["veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        qp.addWidget(self.widgets.qsv_preset, 0, 1)
        qp.addWidget(InfoButton(
            "QSV Preset: Steuert Geschwindigkeit vs. Qualität der Intel Quick Sync Encodierung.\n"
            "veryfast = schnell, schlechtere Kompression.\n"
            "veryslow = langsam, bessere Kompression.\n"
            "Empfohlen: 'medium' bis 'slow' für gute Balance."
        ), 0, 2)
        qp.addWidget(QLabel("🎚️ Q:"), 0, 3)
        self.widgets.qsv_q = QSpinBox()
        self.widgets.qsv_q.setRange(0, 63)
        self.widgets.qsv_q.setValue(23)
        qp.addWidget(self.widgets.qsv_q, 0, 4)
        qp.addWidget(InfoButton(
            "Q (Quantizer / ICQ-Qualität): Qualitätsziel für Intel QSV.\n"
            "0 = beste Qualität / größte Datei, 63 = schlechteste Qualität.\n"
            "Empfohlen: 18–28. 23 ist ein guter Ausgangspunkt.\n"
            "Entspricht dem CRF-Wert bei Software-Encodern."
        ), 0, 5)
        qp.addWidget(QLabel("🔮 Lookahead-Tiefe:"), 1, 0)
        self.widgets.qsv_la_depth = QSpinBox()
        self.widgets.qsv_la_depth.setRange(1, 100)
        self.widgets.qsv_la_depth.setValue(40)
        qp.addWidget(self.widgets.qsv_la_depth, 1, 1)
        qp.addWidget(InfoButton(
            "Lookahead ist bei Intel QSV immer aktiv.\n"
            "Die Tiefe legt fest, wie viele Frames vorausgeschaut werden.\n"
            "Das verbessert die Bitratenverteilung bei Szenenübergängen und Bewegung.\n"
            "Empfehlung: 20–60, Standard: 40."
        ), 1, 2)
        return w

    def build_amf_panel(self):
        from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QComboBox, QSpinBox

        w = QWidget()
        ap = QGridLayout(w)
        ap.addWidget(QLabel("🎚️ CRF/QP:"), 0, 0)
        self.widgets.amf_qp = QSpinBox()
        self.widgets.amf_qp.setRange(0, 63)
        self.widgets.amf_qp.setValue(23)
        ap.addWidget(self.widgets.amf_qp, 0, 1)
        ap.addWidget(InfoButton("Qualitätsfaktor (QP). Niedriger = besser/größer. 18-26 empfohlen."), 0, 2)
        ap.addWidget(QLabel("🏁 Qualität:"), 0, 3)
        self.widgets.amf_qual = QComboBox()
        self.widgets.amf_qual.addItems(["speed", "balanced", "quality"])
        self.widgets.amf_qual.setCurrentText("balanced")
        ap.addWidget(self.widgets.amf_qual, 0, 4)
        ap.addWidget(InfoButton("speed=schnell, quality=beste AMD-Qualität, balanced=Kompromiss."), 0, 5)
        return w

    def build_x265_panel(self):
        from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QComboBox, QSpinBox, QDoubleSpinBox

        w = QWidget()
        xp = QGridLayout(w)
        xp.addWidget(QLabel("🎚️ CRF:"), 0, 0)
        self.widgets.x265_crf = QSpinBox()
        self.widgets.x265_crf.setRange(0, 63)
        self.widgets.x265_crf.setValue({"h264": 22, "h265": 22, "av1": 28}.get(self._default_codec, 22))
        self.widgets.x265_crf.valueChanged.connect(lambda v: self.widgets.crf_spin.setValue(v))
        xp.addWidget(self.widgets.x265_crf, 0, 1)
        xp.addWidget(InfoButton("Qualitätsfaktor: niedriger = besser/größer. H265: 18-28 empfohlen. AV1: 25-35."), 0, 2)
        xp.addWidget(QLabel("🧩 Preset:"), 0, 3)
        self.widgets.x265_preset = QComboBox()
        if self._default_codec == "av1":
            self.widgets.x265_preset.addItems(["4", "5", "6", "7", "8", "9", "10", "11", "12"])
            self.widgets.x265_preset.setCurrentText("6")
        else:
            self.widgets.x265_preset.addItems(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
            self.widgets.x265_preset.setCurrentText("medium")
        self.widgets.x265_preset.currentTextChanged.connect(lambda t: self.widgets.preset_combo.setCurrentText(t))
        xp.addWidget(self.widgets.x265_preset, 0, 4)
        xp.addWidget(InfoButton("Geschwindigkeit vs. Kompression. Bei SVT-AV1 sind kleinere Zahlen langsamer und effizienter."), 0, 5)
        xp.addWidget(QLabel("🎛️ Tune:"), 1, 0)
        self.widgets.x265_tune = QComboBox()
        self.widgets.x265_tune.addItems(["none", "grain", "animation", "ssim", "psnr"])
        xp.addWidget(self.widgets.x265_tune, 1, 1)
        xp.addWidget(InfoButton("'grain': Film-Körnigkeit erhalten. 'animation': für Anime."), 1, 2)
        xp.addWidget(QLabel("🧠 AQ-Mode:"), 1, 3)
        self.widgets.x265_aqm = QComboBox()
        self.widgets.x265_aqm.addItems(["0", "1", "2", "3"])
        self.widgets.x265_aqm.setCurrentText("2")
        xp.addWidget(self.widgets.x265_aqm, 1, 4)
        xp.addWidget(InfoButton(
            "AQ-Mode (Adaptive Quantization): verteilt Bits innerhalb des Bildes intelligenter.\n"
            "0 = aus, 1 = Basis, 2 = Auto-Variance, 3 = Auto-Variance mit dunklen Szenen.\n"
            "Empfohlen für x265: 2. Für schwierige dunkle Quellen kann 3 sinnvoll sein."
        ), 1, 5)
        xp.addWidget(QLabel("📶 AQ-Stärke:"), 2, 0)
        self.widgets.x265_aqs = QDoubleSpinBox()
        self.widgets.x265_aqs.setRange(0, 3)
        self.widgets.x265_aqs.setSingleStep(0.1)
        self.widgets.x265_aqs.setValue(1.0)
        xp.addWidget(self.widgets.x265_aqs, 2, 1)
        xp.addWidget(InfoButton(
            "AQ-Stärke: bestimmt, wie stark x265 Bits zugunsten komplexer Bildbereiche verschiebt.\n"
            "0 = aus/kaum Wirkung, 1.0 = guter Standard, höhere Werte können Details retten,\n"
            "aber bei Übertreibung unruhiger wirken."
        ), 2, 2)
        xp.addWidget(QLabel("🔍 psy-rd:"), 2, 3)
        self.widgets.x265_psy = QDoubleSpinBox()
        self.widgets.x265_psy.setRange(0, 5)
        self.widgets.x265_psy.setSingleStep(0.1)
        self.widgets.x265_psy.setValue(2.0)
        xp.addWidget(self.widgets.x265_psy, 2, 4)
        xp.addWidget(InfoButton(
            "psy-rd: psychovisuelle Detailgewichtung. Höher hält sichtbare Struktur stärker fest,\n"
            "kann aber mehr Bitrate kosten. 2.0 ist ein guter Qualitätsstandard für x265."
        ), 2, 5)
        xp.addWidget(QLabel("🔎 psy-rdoq:"), 3, 0)
        self.widgets.x265_psyrdoq = QDoubleSpinBox()
        self.widgets.x265_psyrdoq.setRange(0, 50)
        self.widgets.x265_psyrdoq.setSingleStep(0.5)
        self.widgets.x265_psyrdoq.setValue(1.0)
        xp.addWidget(self.widgets.x265_psyrdoq, 3, 1)
        xp.addWidget(InfoButton(
            "psy-rdoq: psychovisuelle Quantisierung. 1.0 ist ein sicherer Standard.\n"
            "Zu hohe Werte können künstlich wirken oder die Datei unnötig vergrößern."
        ), 3, 2)
        xp.addWidget(QLabel("🎞️ B-Frames:"), 3, 3)
        self.widgets.x265_bf = QSpinBox()
        self.widgets.x265_bf.setRange(0, 16)
        self.widgets.x265_bf.setValue(8)
        xp.addWidget(self.widgets.x265_bf, 3, 4)
        xp.addWidget(InfoButton(
            "B-Frames verbessern die Kompression, weil Frames bidirektional referenziert werden.\n"
            "8 ist für x265 ein guter Standard. Weniger kann etwas kompatibler/schneller sein."
        ), 3, 5)
        xp.addWidget(QLabel("🔮 Lookahead:"), 4, 0)
        self.widgets.x265_la = QSpinBox()
        self.widgets.x265_la.setRange(0, 250)
        self.widgets.x265_la.setValue(40)
        xp.addWidget(self.widgets.x265_la, 4, 1)
        xp.addWidget(InfoButton(
            "Lookahead: x265 analysiert kommende Frames für bessere Szenen- und Bitratenentscheidungen.\n"
            "40 ist ein guter Standard. Höhere Werte können minimal effizienter sein, aber langsamer."
        ), 4, 2)
        return w
