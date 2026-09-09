# -*- coding: utf-8 -*-
from __future__ import annotations

# ---------------------------------------------------------------------------
# Regex-Hilfe Dialog (wird von _SeriesTab aufgerufen)
# ---------------------------------------------------------------------------

_REGEX_HELP_HTML = r"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"/>
<style>
body{font-family:Arial,sans-serif;font-size:13px;padding:16px;background:#fff;color:#222;}
h2{color:#0078d7;border-bottom:2px solid #0078d7;padding-bottom:4px;}
h3{color:#005fa3;margin-top:16px;}
table{border-collapse:collapse;width:100%;margin:8px 0;}
th{background:#e8f0fe;color:#1d4ed8;padding:7px;text-align:left;border:1px solid #c0d0f0;}
td{padding:7px;border:1px solid #ddd;vertical-align:top;}
code{background:#f0f4ff;border:1px solid #c0d0f0;border-radius:4px;
     padding:1px 5px;font-family:Consolas,monospace;color:#d63031;}
.note{background:#fff8e1;border-left:4px solid #f59e0b;padding:10px;margin:10px 0;border-radius:4px;}
.ok{background:#e8f5e9;border-left:4px solid #27ae60;padding:10px;margin:10px 0;border-radius:4px;}
</style></head><body>

<h2>📋 Serien-Erkennungsmuster – Anleitung</h2>

<div class="ok">
<strong>In den meisten Fällen brauchst du das nicht!</strong><br>
Die eingebauten Muster erkennen: S01E01, S01E01E02, S01E01E02E03,
S01E01-E02, 1x01, Spider-Man, Das A-Team usw. automatisch.
</div>

<h3>Wann brauche ich ein eigenes Muster?</h3>
<p>Nur wenn du ein ungewöhnliches Format hast, das beim Testen NICHT erkannt wird,
zum Beispiel: <code>Staffel 1 Folge 01</code> oder <code>Season01Episode01</code>.</p>

<h3>Die zwei Pflicht-Bestandteile</h3>
<table>
<tr><th>Bestandteil</th><th>Bedeutung</th><th>Erkennt</th></tr>
<tr><td><code>(?P&lt;season&gt;\d+)</code></td><td>Staffelnummer</td><td>01, 1, 12, 2024</td></tr>
<tr><td><code>(?P&lt;episode&gt;\d+)</code></td><td>Episodennummer</td><td>01, 1, 24</td></tr>
</table>
<p>Beide müssen im Muster enthalten sein. Alles andere ist optional.</p>

<h3>Fertige Muster zum Kopieren</h3>
<table>
<tr><th>Dateiname-Format</th><th>Muster zum Kopieren</th></tr>
<tr><td><code>Staffel 1 Folge 01</code></td>
    <td><code>(?i)Staffel\s*(?P&lt;season&gt;\d+)\s*Folge\s*(?P&lt;episode&gt;\d+)</code></td></tr>
<tr><td><code>Staffel01Folge01</code></td>
    <td><code>(?i)Staffel(?P&lt;season&gt;\d+)Folge(?P&lt;episode&gt;\d+)</code></td></tr>
<tr><td><code>Season 1 Episode 01</code></td>
    <td><code>(?i)Season\s*(?P&lt;season&gt;\d+)\s*Episode\s*(?P&lt;episode&gt;\d+)</code></td></tr>
<tr><td><code>1-01</code> (Staffel-Bindestrich-Folge)</td>
    <td><code>(?P&lt;season&gt;\d+)-(?P&lt;episode&gt;\d{2,})</code></td></tr>
<tr><td><code>Ep01</code> (keine Staffelnummer)</td>
    <td><code>(?i)Ep(?P&lt;episode&gt;\d+)</code></td></tr>
</table>

<h3>Zeichenerklärung</h3>
<table>
<tr><th>Zeichen</th><th>Bedeutung</th><th>Beispiel</th></tr>
<tr><td><code>(?i)</code></td><td>Groß/Kleinschreibung egal</td><td>S01 = s01 = S01</td></tr>
<tr><td><code>\\d+</code></td><td>Eine oder mehr Ziffern</td><td>1, 01, 123</td></tr>
<tr><td><code>\\d{2,}</code></td><td>Mindestens 2 Ziffern</td><td>01, 12 (nicht: 1)</td></tr>
<tr><td><code>\\s*</code></td><td>Beliebig viele Leerzeichen (auch kein)</td><td>"Staffel1" oder "Staffel 1"</td></tr>
<tr><td><code>\\s+</code></td><td>Mindestens ein Leerzeichen</td><td>"Staffel 1" (nicht "Staffel1")</td></tr>
<tr><td><code>(?P&lt;name&gt;...)</code></td><td>Benannte Gruppe</td><td>name muss season oder episode sein</td></tr>
</table>

<div class="note">
<strong>Tipp:</strong> Nach dem Hinzufügen → Dateinamen ins Testfeld eingeben → "🔍 Testen" klicken.
Erkannte Serien zeigen ✅, nicht erkannte zeigen ❌.
</div>

</body></html>"""


def _show_regex_help(parent=None) -> None:
    """Zeigt den Regex-Hilfe-Dialog."""
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QTextBrowser
    from .ui_helpers import install_persistent_window_geometry
    dlg = QDialog(parent)
    dlg.setWindowTitle("Serien-Muster schreiben – Hilfe")
    dlg.setMinimumSize(680, 540)
    install_persistent_window_geometry(dlg, "rules_regex_help")
    v = QVBoxLayout(dlg)
    browser = QTextBrowser()
    browser.setHtml(_REGEX_HELP_HTML)
    browser.setOpenExternalLinks(False)
    v.addWidget(browser)
    close_btn = QPushButton("Schließen")
    close_btn.clicked.connect(dlg.close)
    v.addWidget(close_btn)
    dlg.exec()
