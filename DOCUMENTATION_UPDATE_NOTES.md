# DragonTools V9.8.2 – Dokumentationsabgleich nach Refactoring Block 12

Stand: 12.09.2026

Aktualisiert wurden:

- `README.md`
- `help.html`
- `Aenderungshistorie/CHANGELOG.json`
- `Aenderungshistorie/CHANGELOG.txt`
- `dragontools/core/project_info.py` (`Hilfe -> Über`)
- `dragontools/tests/test_project_info.py`

Dokumentiert sind insbesondere der migrationssichere/indexierte Mediathek-Lookup, die asynchrone Mediathek-Suche, DB-first Preflight, frische Metadaten-Batchsessions, TheTVDB-Fallback bei generischen Episodentiteln, der Qt-Signal-/Trickplay-Fix, exactly-once Async-Postprocessing, Quellbild-Batching und die Refactoring-Blöcke 1–12.

Aktuelle vermessene Release-Fallbackwerte (vollständiger Quellstand einschließlich bekanntem Einstiegspunkt):

- 729 Python-Dateien
- 118.048 Gesamtzeilen
- 100.141 nichtleere/nicht reine Kommentarzeilen
- 167 Python-Dateien im Testpaket
- 164 `test_*.py`
- 1.223 statisch erkennbare Testfunktionen

Validierung des Dokumentations-/About-Patches:

- `test_project_info.py` + `test_changelog.py`: 5/5 bestanden
- `compileall` für die geänderten Python-Dateien: OK
- `CHANGELOG.json`: valides Format 1 und über DragonTools-Changelog-Loader lesbar
- `help.html`: mit Python-HTMLParser lesbar; neue Abschnitte/Projektzahlen vorhanden

Das hochgeladene PDF-Handbuch wurde bewusst nicht verändert, weil der Auftrag README, Help, Changelog und den programmseitigen Über-Dialog umfasst. Das Handbuch sollte in einem eigenen Dokumentationslauf separat synchronisiert und neu als PDF erzeugt werden.

## Nachreview 13.09.2026

- Move-Journal-Archivierungsfehler fail-closed gehärtet und im Move-Worker als Fehlerzustand sichtbar gemacht.
- Release-Smoke um die 32 zuvor fehlenden Splitmodule ergänzt; alle 111 im Review-Manifest als neu markierten Produktivmodule sind jetzt Pflichtbestandteil.
- Renamer-Refreshfehler bei generischen Episodentiteln werden geloggt, ohne den sicheren Fallback zu verlieren.
- Formatfund in `gui/iso_widget.py` bereinigt.
