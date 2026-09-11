# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QDoubleSpinBox, QLineEdit, QScrollArea, QVBoxLayout, QWidget,
)

from .info_button import InfoButton
from .rules_dialog_storage import _load
from .rules_language_editor import _LanguagePriorityEditor
from ..core.lang_codes import LANGUAGE_CHOICES, canonical_lang
from ..rules.subtitle_rules import DEFAULT_PREFERRED_SUBTITLE_FORMATS


class _SubtitleTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = _load("subtitle_rules"); self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner)

        lg = QGroupBox("Untertitel-Sprachen")
        ll = QVBoxLayout(lg)
        self.language_editor = _LanguagePriorityEditor(
            priority=self._data.get("language_priority") or (
                list(self._data.get("preferred_languages", [])) + list(self._data.get("fallback_languages", []))
            ),
            max_languages=int(self._data.get("max_languages", 1) or 1),
            tracks_per_language=int(self._data.get("tracks_per_language", 1) or 1),
            fallback_policy=self._data.get("fallback_if_no_priority_match", "keep_none"),
            fallback_options=[
                ("keep_none", "Keine zusätzlichen Untertitel übernehmen"),
                ("keep_first", "Ersten passenden Untertitel übernehmen"),
                ("keep_all", "Alle passenden Untertitel übernehmen"),
            ],
            max_label="Max. Untertitel-Sprachen behalten:",
            tracks_label="Max. Untertitel je Sprache:",
        )
        ll.addWidget(self.language_editor)
        v.addWidget(lg)

        bg = QGroupBox("Burn-In Regeln"); bl = QVBoxLayout(bg)
        burn = self._data.get("burn_in_rules", {})
        self.auto_burn  = QCheckBox("Forced-Untertitel automatisch einbrennen"); self.auto_burn.setChecked(burn.get("auto_burn_forced", True))
        self.ask_ambig  = QCheckBox("Bei mehreren Kandidaten nachfragen");        self.ask_ambig.setChecked(burn.get("ask_if_ambiguous", True))
        self.no_burn_nde= QCheckBox("Kein Burn-In wenn keine passende Audio-Sprache vorhanden ist")
        self.no_burn_nde.setChecked(burn.get("never_burn_if_no_audio_language", burn.get("never_burn_if_no_german_audio", False)))
        burn_grid = QGridLayout()
        burn_grid.addWidget(QLabel("Burn-In-Sprache:"), 0, 0)
        self.burn_lang = QComboBox()
        for code, name in LANGUAGE_CHOICES:
            self.burn_lang.addItem(f"{name} ({code})", code)
        burn_lang = canonical_lang(burn.get("burn_language") or (self.language_editor.priority()[:1] or ["de"])[0]) or "de"
        idx = self.burn_lang.findData(burn_lang)
        self.burn_lang.setCurrentIndex(idx if idx >= 0 else 0)
        burn_grid.addWidget(self.burn_lang, 0, 1)
        burn_grid.addWidget(QLabel("Wenn nicht vorhanden:"), 1, 0)
        self.burn_fallback = QComboBox()
        self.burn_fallback.addItem("Nichts einbrennen", "none")
        self.burn_fallback.addItem("Nächste Sprache aus Priorität versuchen", "next_priority")
        idx = self.burn_fallback.findData(burn.get("burn_fallback", "none"))
        self.burn_fallback.setCurrentIndex(idx if idx >= 0 else 0)
        burn_grid.addWidget(self.burn_fallback, 1, 1)
        bl.addLayout(burn_grid)
        for cb, tip in [
            (self.auto_burn,   "Forced-Untertitel (z.B. fremdsprachige Passagen) werden direkt ins Bild gebrannt.\nNicht entfernbar nach dem Encoding – für maximale Kompatibilität."),
            (self.ask_ambig,   "Wenn mehrere automatische Forced-Kandidaten gefunden werden, wird kein Auto-Burn gewählt. So wird im Batch-Betrieb keine mehrdeutige Auswahl still geraten."),
            (self.no_burn_nde, "Blockiert automatisches Forced-Burn-In, wenn keine Audiospur in der Burn-In-Sprache vorhanden ist. Manuelle File-Overrides können weiterhin gezielt Burn-In erzwingen."),
        ]:
            row_b = QHBoxLayout(); row_b.addWidget(cb); row_b.addWidget(InfoButton(tip)); row_b.addStretch()
            bl.addLayout(row_b)
        plaus = burn.get("forced_plausibility", {}) if isinstance(burn.get("forced_plausibility"), dict) else {}
        pg = QGroupBox("Forced-Plausibilitätsprüfung")
        pl = QGridLayout(pg)
        self.forced_plaus_enabled = QCheckBox("Forced-Untertitel vor Burn-In auf Full-Sub-Verdacht prüfen")
        self.forced_plaus_enabled.setChecked(bool(plaus.get("enabled", True)))
        pl.addWidget(self.forced_plaus_enabled, 0, 0, 1, 3)
        pl.addWidget(QLabel("Warnung ab:"), 1, 0)
        self.forced_warn_epm = QDoubleSpinBox()
        self.forced_warn_epm.setRange(0.0, 50.0)
        self.forced_warn_epm.setDecimals(1)
        self.forced_warn_epm.setSingleStep(0.5)
        self.forced_warn_epm.setSuffix(" Events/Min")
        self.forced_warn_epm.setValue(float(plaus.get("warn_events_per_minute", 3.0)))
        pl.addWidget(self.forced_warn_epm, 1, 1)
        pl.addWidget(QLabel("Burn-In blockieren ab:"), 2, 0)
        self.forced_block_epm = QDoubleSpinBox()
        self.forced_block_epm.setRange(0.0, 50.0)
        self.forced_block_epm.setDecimals(1)
        self.forced_block_epm.setSingleStep(0.5)
        self.forced_block_epm.setSuffix(" Events/Min")
        self.forced_block_epm.setValue(float(plaus.get("block_events_per_minute", 5.0)))
        pl.addWidget(self.forced_block_epm, 2, 1)
        pl.addWidget(InfoButton(
            "Ein Event ist ein Untertitelblock mit eigenem Zeitstempel.\n"
            "0-3 Events/Minute gelten als normal für Forced-Subs.\n"
            "3-5 Events/Minute erzeugen eine Warnung.\n"
            "Über 5 Events/Minute wird Auto-Burn-In blockiert; "
            "die Spur wird stattdessen zusätzlich behalten bzw. als Sidecar exportiert."
        ), 1, 2, 2, 1)
        bl.addWidget(pg)
        v.addWidget(bg)

        kg = QGroupBox("Welche Untertitel behalten?"); kl = QVBoxLayout(kg)
        keep = self._data.get("keep_rules", {})
        selected_default = keep.get(
            "keep_selected_languages",
            keep.get("keep_all_german", True) or keep.get("keep_english_fallback", False),
        )
        self.kf = QCheckBox("Forced-Untertitel zusätzlich behalten")
        self.kf.setChecked(keep.get("keep_forced", True))
        self.ks = QCheckBox("Untertitel der Sprachliste behalten")
        self.ks.setChecked(bool(selected_default))
        self.kr = QCheckBox("Normale Untertitel behalten")
        self.kr.setChecked(keep.get("keep_regular", True))
        self.k_no_burn = QCheckBox("Untertitel der Sprachliste nur behalten, wenn kein Forced-Burn-In erfolgt")
        self.k_no_burn.setChecked(keep.get("keep_if_no_burn_only", keep.get("keep_german_if_no_burn", False)))

        for cb, tip in [
            (self.kf, "Kompatible Forced-Untertitel werden im Auto-Modus als zusätzliche Keep-/Export-Kandidaten berücksichtigt."),
            (self.ks, "Normale Untertitel werden anhand der Untertitel-Sprachliste ausgewählt und durch die maximale Anzahl begrenzt."),
            (self.kr, "Wenn deaktiviert, werden nur Forced-Untertitel behalten, sofern der Forced-Haken aktiv ist."),
            (self.k_no_burn, "Die Untertitel der Sprachliste werden nur beibehalten, wenn kein Forced-Untertitel eingebrannt wird."),
        ]:
            row_k = QHBoxLayout(); row_k.addWidget(cb); row_k.addWidget(InfoButton(tip)); row_k.addStretch()
            kl.addLayout(row_k)
        v.addWidget(kg)

        fg = QGroupBox("Bevorzugte Formate (Reihenfolge = Priorität)"); fl = QVBoxLayout(fg)
        self.fmts = QLineEdit(", ".join(self._data.get("preferred_formats", DEFAULT_PREFERRED_SUBTITLE_FORMATS)))
        fl.addWidget(QLabel("Codec-Namen kommagetrennt:")); fl.addWidget(self.fmts)
        v.addWidget(fg)
        self.fp = QCheckBox("Forced-Untertitel bevorzugen"); self.fp.setChecked(self._data.get("force_priority", True))
        row_fp = QHBoxLayout(); row_fp.addWidget(self.fp)
        row_fp.addWidget(InfoButton(
            "Sortiert Keep-/Export-Kandidaten so, dass Forced-Untertitel vor "
            "sonstigen passenden Untertiteln einsortiert werden."
        ))
        row_fp.addStretch()
        v.addLayout(row_fp)

        # ────────────────────────────────────────────────────────────
        #
        # ────────────────────────────────────────────────────────────
        # Alle Optionen in diesem Tab sind produktiv verdrahtet.
        v.addWidget(QLabel(
            "<i>Alle Untertitel-Regeln in diesem Tab sind jetzt produktiv aktiv.</i>"
        ))

        mp4_grp = QGroupBox("MP4 – Untertitel-Ausgabe"); mp4_l = QVBoxLayout(mp4_grp)
        self.mp4_sidecars = QCheckBox("MP4-Sidecars aktivieren")
        self.mp4_sidecars.setChecked(
            self._data.get(
                "mp4_sidecars_enabled",
                self._data.get("dv_extract_external_subs", True),
            )
        )
        row_mp4 = QHBoxLayout(); row_mp4.addWidget(self.mp4_sidecars)
        row_mp4.addWidget(InfoButton(
            "Gilt für alle MP4-Ausgaben: Standard-Encoding, Strip/Remux, HDR10+, AV1 und Dolby Vision.\n\n"
            "Aktiv: Alle vom Untertitel-Regelwerk ausgewählten MP4-Untertitel werden wie bisher\n"
            "als externe Sidecars gespeichert.\n\n"
            "Deaktiviert: Textbasierte Untertitel (z. B. SRT, ASS/SSA, WebVTT) werden nach\n"
            "mov_text/tx3g konvertiert und intern in der MP4 gespeichert. PGS/SUP und\n"
            "VobSub/DVD-Sub bleiben aus Kompatibilitätsgründen externe Sidecars.\n\n"
            "MKV speichert die ausgewählten Untertitel weiterhin intern und wird von dieser\n"
            "Option nicht beeinflusst."
        ))
        row_mp4.addStretch()
        mp4_l.addLayout(row_mp4)
        v.addWidget(mp4_grp)

        sidecar_grp = QGroupBox("Zusätzliche Sidecars"); sidecar_l = QVBoxLayout(sidecar_grp)
        self.additional_sidecars = QCheckBox("Ausgewählte Untertitel zusätzlich als Sidecar speichern")
        self.additional_sidecars.setChecked(bool(self._data.get("additional_sidecars_enabled", False)))
        row_extra = QHBoxLayout(); row_extra.addWidget(self.additional_sidecars)
        row_extra.addWidget(InfoButton(
            "Legt die vom Untertitel-Regelwerk ausgewählten Untertitel zusätzlich neben der "
            "fertigen Videodatei ab.\n\n"
            "Bei MKV bleiben die Untertitel weiterhin intern erhalten. Bei MP4 ergänzt diese "
            "Option die bestehende MP4-Policy, wenn du zusätzlich externe Dateien möchtest."
        ))
        row_extra.addStretch()
        sidecar_l.addLayout(row_extra)

        self.text_to_srt_sidecar = QCheckBox("Text-Untertitel zusätzlich als SRT-Sidecar speichern")
        self.text_to_srt_sidecar.setChecked(bool(
            self._data.get(
                "text_to_srt_sidecar_enabled",
                self._data.get("ass_to_srt_sidecar_enabled", False),
            )
        ))
        row_ass = QHBoxLayout(); row_ass.addWidget(self.text_to_srt_sidecar)
        row_ass.addWidget(InfoButton(
            "Erzeugt für ausgewählte textbasierte Untertitel zusätzlich eine SRT-Datei, "
            "wenn FFmpeg das Quellformat lesen kann.\n\n"
            "Das gilt z. B. für ASS/SSA, SubRip/SRT, mov_text/tx3g, WebVTT und einfache Textsubs. "
            "Formatierungen, Positionierung und WebVTT-/ASS-Spezialdaten können dabei technisch "
            "nicht vollständig erhalten bleiben; Text und Zeitstempel werden übernommen."
        ))
        row_ass.addStretch()
        sidecar_l.addLayout(row_ass)
        v.addWidget(sidecar_grp)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def get_data(self) -> dict:
        language_data = self.language_editor.data()
        language_priority = language_data["language_priority"]
        burn_language = self.burn_lang.currentData() or (language_priority[:1] or ["de"])[0]
        has_german = "de" in language_priority
        has_english_fallback = "en" in language_priority[1:]
        return {
            **language_data,
            "preferred_languages": language_priority[:1] or ["de"],
            "fallback_languages":  language_priority[1:] or ["en"],
            "force_priority":      self.fp.isChecked(),
            "preferred_formats":   [l.strip() for l in self.fmts.text().split(",") if l.strip()],
            "burn_in_rules":       {
                "auto_burn_forced": self.auto_burn.isChecked(),
                "burn_language": burn_language,
                "burn_fallback": self.burn_fallback.currentData(),
                "ask_if_ambiguous": self.ask_ambig.isChecked(),
                "never_burn_if_no_audio_language": self.no_burn_nde.isChecked(),
                "never_burn_if_no_german_audio": self.no_burn_nde.isChecked() and burn_language == "de",
                "forced_plausibility": {
                    "enabled": self.forced_plaus_enabled.isChecked(),
                    "warn_events_per_minute": round(float(self.forced_warn_epm.value()), 1),
                    "block_events_per_minute": round(
                        max(float(self.forced_warn_epm.value()), float(self.forced_block_epm.value())),
                        1,
                    ),
                },
            },
            "keep_rules":          {
                "keep_forced": self.kf.isChecked(),
                "keep_selected_languages": self.ks.isChecked(),
                "keep_regular": self.kr.isChecked(),
                "keep_if_no_burn_only": self.k_no_burn.isChecked(),
                "keep_all_german": self.ks.isChecked() and has_german,
                "keep_german_if_no_burn": self.k_no_burn.isChecked() and has_german,
                "keep_english_fallback": self.ks.isChecked() and has_english_fallback,
            },
            "mp4_sidecars_enabled": self.mp4_sidecars.isChecked(),
            "additional_sidecars_enabled": self.additional_sidecars.isChecked(),
            "text_to_srt_sidecar_enabled": self.text_to_srt_sidecar.isChecked(),
        }


# ===========================================================================
# TAB 4: Untertitel-Flags
# ===========================================================================
