# DragonTools V9.8.2 – Dokumentationsabgleich nach Technical Review Patch v4

Stand: 13.09.2026

Aktualisiert wurden:

- `README.md`
- `help.html`
- `Aenderungshistorie/CHANGELOG.json`
- `Aenderungshistorie/CHANGELOG.txt`
- `dragontools/core/project_info.py` (`Hilfe -> Über`)
- `dragontools/tests/test_project_info.py`

Dokumentiert sind insbesondere der migrationssichere/indexierte Mediathek-Lookup, die asynchrone Mediathek-Suche, DB-first Preflight, frische Metadaten-Batchsessions, TheTVDB-Fallback bei generischen Episodentiteln, der Qt-Signal-/Trickplay-Fix, exactly-once Async-Postprocessing, Quellbild-Batching, die Refactoring-Blöcke 1–12 und der kumulative Technical Review Patch v4.

Aktuelle vermessene Release-Fallbackwerte (vollständiger Quellstand einschließlich bekanntem Einstiegspunkt):

- 787 Python-Dateien
- 119.402 Gesamtzeilen
- 101.135 nichtleere/nicht reine Kommentarzeilen
- 172 Python-Dateien im Testpaket
- 169 `test_*.py`
- 1.245 statisch erkennbare Testfunktionen

Validierung des Dokumentations-/About-Patches:

- `test_project_info.py` + `test_changelog.py`: 5/5 bestanden
- `compileall` für die geänderten Python-Dateien: OK
- `CHANGELOG.json`: valides Format 1 und über DragonTools-Changelog-Loader lesbar
- `help.html`: mit Python-HTMLParser lesbar; neue Abschnitte/Projektzahlen vorhanden

DOCX-Dokumentation und PDF-Handbuch wurden im anschließenden v4-Dokumentationslauf auf denselben Architektur- und Projektstand synchronisiert und visuell gegengeprüft.

## Nachreview 13.09.2026

- Move-Journal-Archivierungsfehler fail-closed gehärtet und im Move-Worker als Fehlerzustand sichtbar gemacht.
- Release-Smoke um die 32 zuvor fehlenden Splitmodule ergänzt; alle 111 im Review-Manifest als neu markierten Produktivmodule sind jetzt Pflichtbestandteil.
- Renamer-Refreshfehler bei generischen Episodentiteln werden geloggt, ohne den sicheren Fallback zu verlieren.
- Formatfund in `gui/iso_widget.py` bereinigt.

## Technical Review Patch v4

- Release-Validierung, Timestamp-Kandidatenprüfung und -archivierung, Strip-Only, Audio-/Video-Time-Mapping, Qualitätsvergleich und -test, Streamargumente, finaler DV-Mux, Conversion-Fortschritt und ISO-Eingabeverarbeitung in fokussierte Services getrennt.
- Fassaden, Monkeypatch-Punkte und bisherige Kompatibilitätshooks bleiben erhalten.
- Vollständiger lokaler Testlauf: 1.269 bestanden, 2 reale DV/HDR-Integrationstests mangels konfigurierter Werkzeuge/Testmedien übersprungen.
- `python -m compileall -q dragontools`: OK.
