# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from .rules_dialog_storage import _load
from .rules_audio_tab_sections import AudioTabSectionsMixin
from .rules_audio_tab_channels import AudioTabChannelRulesMixin
from .rules_audio_tab_state import AudioTabStateMixin

class _AudioTab(AudioTabSectionsMixin, AudioTabChannelRulesMixin, AudioTabStateMixin, QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = _load("audio_rules")
        self._init_ui()

    def _init_ui(self):
        # Scrollbar weil viel Inhalt
        outer = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner)
        self._build_language_section(v)
        self._build_passthrough_section(v)
        self._build_extra_stereo_section(v)
        self._build_audio_processing_section(v)
        self._build_channel_rules_section(v)
        self._build_transcode_section(v)
        self._build_preview_section(v)
        scroll.setWidget(inner); outer.addWidget(scroll)
