# DragonTools 9.8.6

## Überblick

Version 9.8.6 bündelt den seit 9.8.4 erweiterten Funktionsstand und gleicht Versionsanzeige, Build-Metadaten, Hilfe, Handbuch und Änderungshistorie ab. Die Release-Aktualisierung selbst verändert keine bestehenden Verarbeitungsabläufe.

## Enthaltener Funktionsstand

- Erweiterte HDR-Unterstützung mit ComfyUI/HDRTVDM, Dragon HDR10+ Generator sowie HDR-Erkennung, Datei-Overrides und Strip-Only.
- VFR-Original-Timeline-Reparatur und zusätzliche Sicherheitsprüfungen für Untertitel-, DV-, HDR10+- und Move-Abläufe.
- Jellyfin-Integration, Watch-Folder, Mediathek-Reparatur, Sprach- und Track-Metadaten sowie erweiterte Online-Metadaten-Suche.
- Optionale lokale faster-whisper/CTranslate2-Nutzung, OCR-Unterstützung und ergänzte Werkzeugdiagnose.
- Aktualisierte Hilfe mit 66 Hauptpunkten sowie synchronisiertes DOCX- und PDF-Handbuch.

## Paket und Installation

Das Windows-Paket heißt `DragonToolsV9.8.6-win64.zip`. Die daneben veröffentlichte Datei `DragonToolsV9.8.6-win64.zip.sha256` enthält die zugehörige SHA-256-Prüfsumme.

Zum Aktualisieren das ZIP in einen neuen Ordner entpacken und die EXE zusammen mit ihrem Ordner `Daten` belassen. Eigene Einstellungen und Regeln vor dem Wechsel sichern.

## Bekannte Grenzen

Externe Medienwerkzeuge und optionale Modelle werden entsprechend der bestehenden Public-Paketierung separat eingerichtet. Automatisierte Prüfungen ersetzen keine vollständige Hardware-Encoder-, Medien- und interaktive GUI-Abnahme.

## Nachtrag vom 25.09.2026 – Patches BA bis BC

- Timestamp-Reparaturen nutzen getrennte Originalreferenzen für Video und Container; verlustfreie Reparaturen erhalten die angepasste Dauertoleranz bei weiterhin unveränderten Paket- und Nutzdatenprüfungen.
- Serienepisoden können zusätzlich zur Staffel manuell geändert werden; die Renamer-Werkzeugleiste ist in drei Reihen mit je fünf Aktionen angeordnet.
- Datei-Einstellungen lassen sich auf mehrere markierte Queue-Dateien anwenden; separate Encoder-Profile bleiben pro Datei erhalten.
- Alle 12 gezielten Regressionstests bestehen. Das Windows-Paket wurde aus dem erneut anonymisierten Stand gebaut und validiert.

Das ZIP wurde innerhalb der Version 9.8.6 ersetzt; die neue Prüfsumme ist maßgeblich. Bereits installierte 9.8.6-Versionen erhalten deshalb keinen automatischen Updatehinweis.

## Public-Paketierung ohne externe Werkzeuge (25.09.2026)

Der Public-Build bindet keine Dateien aus `third_party` ein. Externe Medienwerkzeuge werden separat installiert; `TOOLS_INSTALLIEREN.txt` liegt im Paket. `scripts/check_public_bundle.py` prüft Build-Ordner und ZIP auf ausgeschlossene Werkzeugdateien und nichtleere `Programme`-/`third_party`-Verzeichnisse. Diese Prüfung muss auch nach jedem erneuten Abgleich mit dem privaten Projekt bestehen. Die benötigten Python-/Qt-Laufzeitbibliotheken bleiben enthalten; dies ist keine pauschale Lizenzfreigabe für diese Bibliotheken.
