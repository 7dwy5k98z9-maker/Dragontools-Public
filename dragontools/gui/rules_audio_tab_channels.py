# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt6.QtWidgets import QComboBox, QGridLayout, QGroupBox, QLabel, QSpinBox, QVBoxLayout
from ..rules import audio_rules as _ar
from .info_button import InfoButton
from .rules_dialog_common import _hr

class AudioTabChannelRulesMixin:
    def _build_channel_rules_section(self, v: QVBoxLayout) -> None:
        # ── Kanal-Regeln ──────────────────────────────────────────────
        cr = self._data.get("channel_rules", {})
        cg = QGroupBox("Kanal-Regeln  –  wann wird kopiert, wann transkodiert, auf was?")
        cgl = QVBoxLayout(cg)
        cgl.addWidget(QLabel(
            "Für jede Kanal-Stufe kannst du festlegen:\n"
            "• Ab welcher Kanalzahl diese Stufe gilt\n"
            "• Welcher Ziel-Codec bei Transkodierung\n"
            "• Welche Bitrate bei Transkodierung verwendet wird\n"
            "• Welche Original-Bitraten ohne Neukodierung kopiert werden"
        ))
        cgl.addWidget(_hr())

        # Mono
        s10 = cr.get("mono", {}); sg1 = QGroupBox("Mono (1 Kanal)"); sg1l = QGridLayout(sg1)
        sg1l.addWidget(QLabel("Ziel-Codec:"), 0, 0)
        self.s10_codec = QComboBox(); self.s10_codec.addItems(["aac","eac3","ac3","copy"]); self.s10_codec.setCurrentText(s10.get("target_codec","aac"))
        sg1l.addWidget(self.s10_codec, 0, 1)
        sg1l.addWidget(QLabel("Max. Bitrate (kbps):"), 0, 2)
        self.s10_br = QSpinBox(); self.s10_br.setRange(32,1024); self.s10_br.setSingleStep(32); self.s10_br.setValue(int(s10.get("max_bitrate_k",128)))
        self.s10_br.setSuffix(" kbps"); sg1l.addWidget(self.s10_br, 0, 3)
        sg1l.addWidget(QLabel("→ Original bis"), 1, 0, 1, 2)
        sg1l.addWidget(QLabel("kbps kopieren, sonst auf Ziel transkodieren"), 1, 2, 1, 2)
        cgl.addWidget(sg1)

        # Stereo
        s20 = cr.get("stereo", {}); sg2 = QGroupBox("Stereo (2 Kanäle)"); sg2l = QGridLayout(sg2)
        sg2l.addWidget(QLabel("Ziel-Codec:"), 0, 0)
        self.s20_codec = QComboBox(); self.s20_codec.addItems(["aac","eac3","ac3","copy"]); self.s20_codec.setCurrentText(s20.get("target_codec","aac"))
        sg2l.addWidget(self.s20_codec, 0, 1)
        sg2l.addWidget(QLabel("Max. Ziel-Bitrate (kbps):"), 0, 2)
        self.s20_br = QSpinBox(); self.s20_br.setRange(64,1024); self.s20_br.setSingleStep(32); self.s20_br.setValue(int(s20.get("max_bitrate_k",192)))
        self.s20_br.setSuffix(" kbps"); sg2l.addWidget(self.s20_br, 0, 3)
        sg2l.addWidget(QLabel("Kopieren von:"), 1, 0)
        self.s20_copy_min_br = QSpinBox()
        self.s20_copy_min_br.setRange(0, 2048)
        self.s20_copy_min_br.setSingleStep(32)
        self.s20_copy_min_br.setValue(int(s20.get("copy_min_bitrate_k", 192)))
        self.s20_copy_min_br.setSuffix(" kbps")
        sg2l.addWidget(self.s20_copy_min_br, 1, 1)
        sg2l.addWidget(QLabel("bis:"), 1, 2)
        self.s20_copy_max_br = QSpinBox()
        self.s20_copy_max_br.setRange(0, 2048)
        self.s20_copy_max_br.setSingleStep(32)
        self.s20_copy_max_br.setValue(int(s20.get("copy_max_bitrate_k", 256)))
        self.s20_copy_max_br.setSuffix(" kbps")
        sg2l.addWidget(self.s20_copy_max_br, 1, 3)
        sg2l.addWidget(InfoButton(
            "Stereo-Spuren mit akzeptiertem Codec werden nur in diesem Bitratenbereich kopiert.\n"
            "Liegt die Bitrate außerhalb des Bereichs, wird auf den Ziel-Codec transkodiert.\n"
            "Die Max. Ziel-Bitrate ist dabei eine Obergrenze: niedrigere Quellbitraten werden nicht künstlich erhöht.\n\n"
            "Beispiel: Kopieren 192-256 kbps, Max. Ziel 192 kbps:\n"
            "AAC Stereo 196 kbps -> kopieren\n"
            "MP3 Stereo 128 kbps -> AAC 128 kbps\n"
            "MP3/AAC Stereo 320 kbps -> AAC 192 kbps"
        ), 1, 4)
        self.s20_copy_max_br.setMinimum(self.s20_copy_min_br.value())
        self.s20_copy_min_br.valueChanged.connect(self.s20_copy_max_br.setMinimum)
        cgl.addWidget(sg2)

        # 5.1
        s51 = cr.get("surround_51", {}); sg51 = QGroupBox("🔊🔊 5.1 Surround (3–6 Kanäle)"); sg51l = QGridLayout(sg51)
        sg51l.addWidget(QLabel("Ziel-Codec:"), 0, 0)
        self.s51_codec = QComboBox(); self.s51_codec.addItems(["eac3","ac3","aac","copy"]); self.s51_codec.setCurrentText(s51.get("target_codec","eac3"))
        sg51l.addWidget(self.s51_codec, 0, 1)
        sg51l.addWidget(QLabel("Max. Bitrate (kbps):"), 0, 2)
        self.s51_br = QSpinBox(); self.s51_br.setRange(128,2048); self.s51_br.setSingleStep(64); self.s51_br.setValue(int(s51.get("max_bitrate_k",640)))
        self.s51_br.setSuffix(" kbps"); sg51l.addWidget(self.s51_br, 0, 3)
        sg51l.addWidget(QLabel("Kopieren von:"), 1, 0)
        self.s51_copy_min_br = QSpinBox()
        self.s51_copy_min_br.setRange(0, 4096)
        self.s51_copy_min_br.setSingleStep(32)
        self.s51_copy_min_br.setValue(int(s51.get("copy_min_bitrate_k", 428)))
        self.s51_copy_min_br.setSuffix(" kbps")
        sg51l.addWidget(self.s51_copy_min_br, 1, 1)
        sg51l.addWidget(QLabel("bis:"), 1, 2)
        self.s51_copy_max_br = QSpinBox()
        self.s51_copy_max_br.setRange(0, 4096)
        self.s51_copy_max_br.setSingleStep(32)
        self.s51_copy_max_br.setValue(int(s51.get("copy_max_bitrate_k", 640)))
        self.s51_copy_max_br.setSuffix(" kbps")
        sg51l.addWidget(self.s51_copy_max_br, 1, 3)
        sg51l.addWidget(InfoButton(
            "5.1-Spuren mit akzeptiertem Codec werden nur in diesem Bitratenbereich kopiert.\n"
            "Liegt die Bitrate darunter oder darüber, wird auf Ziel-Codec und Ziel-Bitrate transkodiert.\n\n"
            "Beispiel: Kopieren 428-640 kbps:\n"
            "E-AC3 5.1 448 kbps -> kopieren\n"
            "E-AC3 5.1 256 kbps -> nach Regel transkodieren oder downmixen"
        ), 1, 4)
        self.s51_copy_max_br.setMinimum(self.s51_copy_min_br.value())
        self.s51_copy_min_br.valueChanged.connect(self.s51_copy_max_br.setMinimum)
        sg51l.addWidget(QLabel("Stereo-Downmix:"), 2, 0)
        self.s51_downmix_mode = QComboBox()
        self.s51_downmix_mode.addItem("Nie downmixen", "never")
        self.s51_downmix_mode.addItem("Immer downmixen", "always")
        self.s51_downmix_mode.addItem("Nur bis Bitrate", "below_bitrate")
        s51_mode = str(s51.get("downmix_mode", "never") or "never")
        s51_mode_idx = self.s51_downmix_mode.findData(s51_mode)
        self.s51_downmix_mode.setCurrentIndex(s51_mode_idx if s51_mode_idx >= 0 else 0)
        sg51l.addWidget(self.s51_downmix_mode, 2, 1)
        sg51l.addWidget(QLabel("Grenze:"), 2, 2)
        self.s51_downmix_br = QSpinBox()
        self.s51_downmix_br.setRange(64,2048)
        self.s51_downmix_br.setSingleStep(32)
        self.s51_downmix_br.setValue(int(s51.get("downmix_bitrate_k", 256)))
        self.s51_downmix_br.setSuffix(" kbps")
        sg51l.addWidget(self.s51_downmix_br, 2, 3)
        sg51l.addWidget(InfoButton(
            "Steuert, ob 3-6-Kanal-Spuren direkt auf Stereo heruntergerechnet werden.\n\n"
            "Nie downmixen: 5.1 bleibt erhalten oder wird als 5.1 transkodiert.\n"
            "Immer downmixen: 3-6 Kanäle werden auf Stereo reduziert.\n"
            "Nur bis Bitrate: Downmix nur, wenn die Quellbitrate bis einschließlich dieser Grenze liegt.\n\n"
            "Beispiel: E-AC3 5.1 256 kbps -> AAC 2.0 256 kbps bei Modus 'Nur bis Bitrate' und Grenze 256 kbps."
        ), 2, 4)
        self.s51_downmix_br.setEnabled(self.s51_downmix_mode.currentData() == "below_bitrate")
        self.s51_downmix_mode.currentIndexChanged.connect(
            lambda _idx: self.s51_downmix_br.setEnabled(self.s51_downmix_mode.currentData() == "below_bitrate")
        )
        cgl.addWidget(sg51)

        # 7.1
        s71 = cr.get("surround_71", {}); sg71 = QGroupBox("🔊🔊🔊 7.1 Surround (7+ Kanäle)"); sg71l = QGridLayout(sg71)
        sg71l.addWidget(QLabel("Ziel-Codec:"), 0, 0)
        self.s71_codec = QComboBox(); self.s71_codec.addItems(["eac3","ac3","aac","copy"]); self.s71_codec.setCurrentText(s71.get("target_codec","eac3"))
        sg71l.addWidget(self.s71_codec, 0, 1)
        sg71l.addWidget(QLabel("Max. Bitrate (kbps):"), 0, 2)
        self.s71_br = QSpinBox(); self.s71_br.setRange(256,4096); self.s71_br.setSingleStep(128); self.s71_br.setValue(int(s71.get("max_bitrate_k",640)))
        self.s71_br.setSuffix(" kbps"); sg71l.addWidget(self.s71_br, 0, 3)
        sg71l.addWidget(QLabel("Kopieren von:"), 1, 0)
        self.s71_copy_min_br = QSpinBox()
        self.s71_copy_min_br.setRange(0, 4096)
        self.s71_copy_min_br.setSingleStep(64)
        self.s71_copy_min_br.setValue(int(s71.get("copy_min_bitrate_k", 768)))
        self.s71_copy_min_br.setSuffix(" kbps")
        sg71l.addWidget(self.s71_copy_min_br, 1, 1)
        sg71l.addWidget(QLabel("bis:"), 1, 2)
        self.s71_copy_max_br = QSpinBox()
        self.s71_copy_max_br.setRange(0, 4096)
        self.s71_copy_max_br.setSingleStep(64)
        self.s71_copy_max_br.setValue(int(s71.get("copy_max_bitrate_k", 1536)))
        self.s71_copy_max_br.setSuffix(" kbps")
        sg71l.addWidget(self.s71_copy_max_br, 1, 3)
        sg71l.addWidget(InfoButton(
            "7.1-Spuren mit akzeptiertem Codec werden in diesem Bereich kopiert,\n"
            "wenn kein Downmix erzwungen ist.\n\n"
            "Beispiel: E-AC3 7.1 1536 kbps -> kopieren, wenn Downmix auf 'Nie' steht.\n"
            "Außerhalb des Bereichs greift die eingestellte Transkodierungs-/Downmix-Regel."
        ), 1, 4)
        self.s71_copy_max_br.setMinimum(self.s71_copy_min_br.value())
        self.s71_copy_min_br.valueChanged.connect(self.s71_copy_max_br.setMinimum)
        sg71l.addWidget(QLabel("Downmix:"), 2, 0)
        self.s71_downmix_mode = QComboBox()
        self.s71_downmix_mode.addItem("Nie downmixen", "never")
        self.s71_downmix_mode.addItem("Immer downmixen", "always")
        self.s71_downmix_mode.addItem("Nur bis Bitrate", "below_bitrate")
        s71_mode = str(s71.get("downmix_mode", "always") or "always")
        s71_mode_idx = self.s71_downmix_mode.findData(s71_mode)
        self.s71_downmix_mode.setCurrentIndex(s71_mode_idx if s71_mode_idx >= 0 else 1)
        sg71l.addWidget(self.s71_downmix_mode, 2, 1)
        sg71l.addWidget(QLabel("Ziel:"), 2, 2)
        self.s71_downmix_target = QComboBox()
        self.s71_downmix_target.addItem("5.1 (6 Kanäle)", "surround_51")
        self.s71_downmix_target.addItem("Stereo (2 Kanäle)", "stereo")
        s71_target = _ar.normalize_surround_71_downmix_target(
            s71.get("downmix_target", s71.get("target_channels", 6))
        )
        s71_target_idx = self.s71_downmix_target.findData(s71_target)
        self.s71_downmix_target.setCurrentIndex(s71_target_idx if s71_target_idx >= 0 else 0)
        sg71l.addWidget(self.s71_downmix_target, 2, 3)
        sg71l.addWidget(QLabel("Grenze:"), 3, 0)
        self.s71_downmix_br = QSpinBox()
        self.s71_downmix_br.setRange(64,4096)
        self.s71_downmix_br.setSingleStep(128)
        self.s71_downmix_br.setValue(int(s71.get("downmix_bitrate_k", s71.get("max_bitrate_k", 640))))
        self.s71_downmix_br.setSuffix(" kbps")
        sg71l.addWidget(self.s71_downmix_br, 3, 1)
        sg71l.addWidget(InfoButton(
            "Steuert, ob 7.1-/8-Kanal-Spuren reduziert werden.\n\n"
            "Nie downmixen: 7.1 bleibt erhalten, sofern der Zielcodec das kann.\n"
            "Immer downmixen: 7.1 wird auf das gewählte Ziel reduziert.\n"
            "Nur bis Bitrate: Downmix nur, wenn die Quellbitrate bis einschließlich dieser Grenze liegt.\n\n"
            "Wichtig: E-AC3 kann als fertige Quelle durchaus 7.1 enthalten und wird dann per Passthrough unverändert kopiert.\n"
            "Der FFmpeg-Encoder für E-AC3/AC3 unterstützt beim Neu-Encoding aber nur bis 5.1.\n"
            "Wenn E-AC3 oder AC3 als Zielcodec gewählt ist, begrenzt DragonTools deshalb automatisch auf maximal 5.1.\n"
            "Für echtes 7.1-Neu-Encoding bitte AAC als Zielcodec verwenden."
        ), 3, 2, 1, 2)
        self.s71_downmix_br.setEnabled(self.s71_downmix_mode.currentData() == "below_bitrate")
        self.s71_downmix_mode.currentIndexChanged.connect(
            lambda _idx: self.s71_downmix_br.setEnabled(self.s71_downmix_mode.currentData() == "below_bitrate")
        )
        cgl.addWidget(sg71)

        v.addWidget(cg)
