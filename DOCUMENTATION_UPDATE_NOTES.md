# DragonTools V9.8.4 – Versionsabschluss

Stand: 16.09.2026. Aktive Versionsquelle, Build-Spezifikation/-Hinweise, Release-Metadaten, README, Hilfe und Über-Dialog stehen auf 9.8.4. Projektstatistiken wurden aus dem privaten Quellstand neu berechnet. CHANGELOG und patch.md enthalten den Versionsabschluss. Das vorhandene DOCX-Handbuch erhält aktualisierte Titel-/Build-Angaben und einen Versionsnachtrag; das PDF wird daraus mit LibreOffice erzeugt. Die vollständige Funktionsreferenz und ihre älteren datierten Prüfberichte bleiben erhalten.

## Historischer Dokumentationsabgleich 9.8.3

Stand: 15.09.2026

Der frühere V9.8.2-Abgleich bleibt im Anschluss als technische Historie erhalten. Für V9.8.3 wurden Help, Handbuch, Über-Dialog und Änderungshistorie erneut gegen den aktuellen Quellstand geprüft und synchronisiert.

- Das aktuelle Handbuch basiert auf der V9.8.3-DOCX-Fassung; der Vergleich mit dem älteren 421-Seiten-Handbuch ergab keinen pauschalen Inhaltsverlust. Die geringere Seitenzahl entstand überwiegend durch kompakteren Satz. Veraltete Aussagen, die V9.7/V9.8.2 noch als aktuellen Stand bezeichneten, wurden historisch eingeordnet.
- `help.html` dokumentiert den V9.8.3-Stabilitätsstand, den GUI-Breitenfix und die frei konfigurierbaren Renamer-Spalten.
- Hilfe -> Über verwendet `APP_VERSION = 9.8.3` und aktuelle Projektstatistiken/Fallbackwerte.
- `Aenderungshistorie/CHANGELOG.json` und `.txt` sind fachbereichsorientiert aufgebaut; Version und Datum stehen direkt am jeweiligen Änderungspunkt. Die V9.8.3-Release-Notes wurden in die passenden Fachbereiche eingearbeitet.
- Der GUI-Nachpatch begrenzt die Mindestbreite der Haupt-Tab-Leiste, verteilt die Renamer-Aktionen auf mehrere Zeilen und macht Renamer-Spalten frei skalierbar, ein-/ausblendbar und persistent.

## Historischer V9.8.2-Abgleich nach Technical Review Patch v4

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

## 2026-09-15 - Renamer: Releasegruppen und Episodenmuster

- Renamer-Regelschema 3 dokumentiert; neue Liste für explizite Releasegruppen ergänzt.
- Releasegruppen werden nur an Anfang/Ende eines Namens gefiltert, damit echte Titelbestandteile nicht entfernt werden.
- Zusätzliche Serienmuster `E05S06` / `E05 S06` dokumentiert.
- `EP01` / `EPISODE01` verlangt eine explizite Staffelwahl vor der Providerabfrage; Staffel 0 ist zulässig.
- Help, technisches DOCX und kategorisierte Änderungshistorie wurden synchronisiert.
