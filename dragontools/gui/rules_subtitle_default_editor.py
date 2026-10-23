"""Controls for default subtitle conditions and independent language ranks."""
from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout

from ..core.lang_codes import LANGUAGE_CHOICES, lang_display
from ..rules.subtitle_default_config import normalize_default_subtitle
from .rules_language_editor import _LanguagePriorityEditor


class _SubtitleDefaultEditor(QGroupBox):
    def __init__(self, settings, *, language_priority, parent=None):
        super().__init__("Default-Untertitel definieren", parent)
        default = normalize_default_subtitle(settings, language_priority=language_priority)
        layout = QVBoxLayout(self)
        self.always = QCheckBox("Immer")
        self.audio_differs = QCheckBox("Wenn Audio von der gewählten Sprache abweicht")
        self.always.setChecked(default['mode'] == 'always')
        self.audio_differs.setChecked(default['mode'] in {'audio_differs', 'legacy'})
        layout.addWidget(self.always)
        layout.addWidget(self.audio_differs)
        row = QHBoxLayout()
        row.addWidget(QLabel("Audio-Vergleichssprache:"))
        self.audio_language = QComboBox()
        self.audio_language.addItem("Rang 1 der Audio-Sprachliste", "audio_priority")
        for code, name in LANGUAGE_CHOICES:
            self.audio_language.addItem(f"{name} ({code})", code)
        language = default['audio_language']
        index = self.audio_language.findData(language)
        if index < 0:
            self.audio_language.addItem(f"{lang_display(language)} ({language})", language)
            index = self.audio_language.count() - 1
        self.audio_language.setCurrentIndex(index)
        row.addWidget(self.audio_language, 1)
        layout.addLayout(row)
        layout.addWidget(QLabel("Untertitelsprache für Default – Reihenfolge = Rang:"))
        self.languages = _LanguagePriorityEditor(
            priority=default['language_priority'], fallback_options=[],
            max_label='', tracks_label='', priority_only=True, show_ranks=True,
        )
        layout.addWidget(self.languages)
        hint = QLabel(
            "Die erste verfügbare Sprache der Rangliste wird Standard. "
            "Es werden nur zur Übernahme ausgewählte Untertitel berücksichtigt.\n"
            "Unbekannte Audiosprache zählt als abweichend. "
            "Beide Haken aus: vorhandene Standardmarkierung beibehalten."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.always.toggled.connect(lambda checked: self._toggle(self.audio_differs, checked))
        self.audio_differs.toggled.connect(lambda checked: self._toggle(self.always, checked))
        self._update_enabled()

    def _toggle(self, other, checked):
        if checked:
            other.setChecked(False)
        self._update_enabled()

    def _update_enabled(self):
        self.audio_language.setEnabled(self.audio_differs.isChecked())
        self.languages.setEnabled(self.always.isChecked() or self.audio_differs.isChecked())

    def data(self):
        mode = 'always' if self.always.isChecked() else 'audio_differs' if self.audio_differs.isChecked() else 'preserve'
        return {
            'mode': mode,
            'audio_language': self.audio_language.currentData(),
            'language_priority': self.languages.priority(),
        }
