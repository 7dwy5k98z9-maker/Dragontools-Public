# -*- coding: utf-8 -*-
from __future__ import annotations

import re

from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

from .info_button import InfoButton
from .rules_dialog_storage import _load
from .rules_regex_help import _show_regex_help
from ..rules.move_rules import parse_series_match_details


class _SeriesTab(QWidget):
    """
    Serien-Erkennung per Beispiele statt rohen Regex.
    Du gibst Dateinamen ein – die App lernt daraus und zeigt ob sie erkannt werden.
    Für Experten: Erweiterte Muster weiterhin editierbar.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        data = _load("move_rules")
        self._patterns = list(data.get("series_patterns", []))
        self._init_ui(data)

    def _init_ui(self, data):
        v = QVBoxLayout(self)

        # ── Einfache Eingabe per Beispiele ────────────────────────────
        easy_grp = QGroupBox("🟢 Einfach: Dateinamen eingeben – Test zeigt ob erkannt")
        el = QVBoxLayout(easy_grp)
        el.addWidget(QLabel(
            "Trage hier deine Dateinamen ein (einen pro Zeile).\n"
            "Klicke dann auf '\U0001F50D Testen' um zu sehen ob und wie sie erkannt werden.\n"
            "Funktioniert sofort – du musst nichts über Regex wissen!"
        ))
        self.ex_edit = QTextEdit()
        examples = data.get("series_test_examples", [
            "Stargate - S01E01E02 - Tor zum Universum.mkv",
            "Spider-Man - S01E01 - Titel.mkv",
            "Die Simpsons - S05E10 - Homer und Apu.mkv",
            "Interstellar.2014.mkv",
        ])
        self.ex_edit.setPlainText("\n".join(examples))
        self.ex_edit.setMinimumHeight(120)
        self.ex_edit.setPlaceholderText(
            "Beispiele:\nShow - S01E01 - Titel.mkv\n"
            "Serie S01E01E02 Doppelfolge.mkv\nFilm.2023.mkv"
        )
        el.addWidget(self.ex_edit)
        tb = QPushButton("🔍 Testen – werden diese Dateinamen erkannt?")
        tb.setMinimumHeight(32); tb.setStyleSheet("font-weight:bold;")
        tb.clicked.connect(self._test)
        el.addWidget(tb)
        self.res = QTextEdit(); self.res.setReadOnly(True); self.res.setMinimumHeight(140)
        self.res.setStyleSheet("font-family:Consolas,monospace;font-size:11px;")
        el.addWidget(self.res)
        v.addWidget(easy_grp)

        # ── Erweitert: rohe Muster ─────────────────────────────────────
        fr = QFrame(); fr.setFrameShape(QFrame.Shape.HLine); v.addWidget(fr)
        adv_grp = QGroupBox("🔧 Erweitert: Eigene Erkennungsmuster (nur wenn Testen fehlschlägt)")
        al = QVBoxLayout(adv_grp)
        al.addWidget(QLabel(
            "Die eingebauten Muster erkennen bereits: S01E01, S01E01E02, S01E01E02E03,\n"
            "S01E01-E02, S01 E01, 1x01, 1x01x02, Spider-Man, Das A-Team usw.\n\n"
            "Nur hinzufügen wenn du ein Format hast das NICHT erkannt wird,\n"
            "z.B.: 'Staffel 1 Folge 01'"
        ))
        self.pat_list = QListWidget(); self.pat_list.setMaximumHeight(100)
        for p in self._patterns: self.pat_list.addItem(QListWidgetItem(p))
        br = QHBoxLayout()
        ab = QPushButton("➕ Muster hinzufügen"); ab.clicked.connect(self._add)
        db = QPushButton("➖ Entfernen"); db.clicked.connect(self._del)
        hb = QPushButton("❓ Wie schreibe ich ein Muster?")
        hb.clicked.connect(lambda: _show_regex_help(self))
        hb.setStyleSheet("color:#0078d7;")
        br.addWidget(ab); br.addWidget(db); br.addWidget(hb)
        br.addWidget(InfoButton(
            "Muster sind reguläre Ausdrücke.\n"
            "Pflicht: (?P<season>\\d+) und (?P<episode>\\d+)\n"
            "Klicke '❓ Wie schreibe ich ein Muster?' für eine ausführliche Anleitung."
        ))
        al.addWidget(self.pat_list); al.addLayout(br)
        v.addWidget(adv_grp)

        # ── Ordner-Struktur ──────────────────────────────────────────
        sg = QGroupBox("Ordner-Struktur (Ziel-Verzeichnispfade)"); sl = QGridLayout(sg)
        sl.addWidget(QLabel("Serien:"), 0, 0)
        self.ser_s = QLineEdit(data.get("folder_structure", {}).get("series", "{tv_root}/{series_name}/Staffel {season:02d}/"))
        sl.addWidget(self.ser_s, 0, 1)
        sl.addWidget(QLabel("Filme:"), 1, 0)
        self.mov_s = QLineEdit(data.get("folder_structure", {}).get("movie", "{film_root}/{title} ({year})/"))
        sl.addWidget(self.mov_s, 1, 1)
        sl.addWidget(QLabel("Anime:"), 2, 0)
        self.ani_s = QLineEdit(data.get("folder_structure", {}).get("anime", "{anime_root}/{series_name}/Staffel {season:02d}/"))
        sl.addWidget(self.ani_s, 2, 1)
        v.addWidget(sg)

    def _add(self):
        txt, ok = QInputDialog.getText(self, "Muster hinzufügen",
            "Format: Erkennungsmuster mit benannten Gruppen\n\n"
            "Beispiel für 'Staffel 1 Folge 01':\n"
            "(?i)Staffel\\s*(?P<season>\\d+)\\s*Folge\\s*(?P<episode>\\d+)\n\n"
            "Pflicht: (?P<season>\\d+) und (?P<episode>\\d+) müssen enthalten sein.")
        if ok and txt.strip():
            if "(?P<season>" not in txt or "(?P<episode>" not in txt:
                QMessageBox.warning(self, "Ungültig",
                    "Das Muster muss (?P<season>\\d+) und (?P<episode>\\d+) enthalten.")
                return
            try: re.compile(txt.strip()); self.pat_list.addItem(QListWidgetItem(txt.strip()))
            except re.error as e: QMessageBox.warning(self, "Ungültiger Ausdruck", f"Regex-Fehler:\n{e}")

    def _del(self):
        for item in self.pat_list.selectedItems(): self.pat_list.takeItem(self.pat_list.row(item))

    def _test(self):
        examples = [l.strip() for l in self.ex_edit.toPlainText().splitlines() if l.strip()]
        if not examples:
            self.res.setPlainText("Keine Beispiele eingegeben. Bitte Dateinamen in das Textfeld oben eingeben.")
            return
        lines = []
        ok_count = err_count = 0
        for name in examples:
            r = parse_series_match_details(name)
            if r:
                ok_count += 1
                eps_str = ", ".join(str(e) for e in r["episodes"])
                lines.append(
                    f"✅ {name}\n"
                    f"   Serie: \"{r['series'] or '(kein Name)'}\""
                    f"  |  Staffel {r['season']:02d}"
                    f"  |  Episode(n): {eps_str}"
                )
            else:
                err_count += 1
                lines.append(f"🎬 {name}\n   → wird als Film/Sonstiges behandelt")
        summary = f"Ergebnis: {ok_count} als Serie erkannt, {err_count} als Film/Sonstiges\n"
        summary += "─" * 55 + "\n"
        self.res.setPlainText(summary + "\n\n".join(lines))

    def get_data(self) -> dict:
        return {
            "series_patterns": [self.pat_list.item(i).text() for i in range(self.pat_list.count())],
            "series_test_examples": [l.strip() for l in self.ex_edit.toPlainText().splitlines() if l.strip()],
            "folder_structure": {"series": self.ser_s.text(), "movie": self.mov_s.text(), "anime": self.ani_s.text()},
        }


# ===========================================================================
# TAB 2: Audio-Regeln (vollständig klickbar)
# ===========================================================================
