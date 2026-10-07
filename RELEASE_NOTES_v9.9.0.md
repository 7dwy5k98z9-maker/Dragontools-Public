# Dragon Tools V9.9.0

Stand: 08.10.2026. Diese Ausgabe enthält die aktuellen Korrekturen aller 29 Patch-/Review-Schritte und die anschließend behobenen Laufzeitfehler.

- Einzelne aktive Worker lassen sich bei paralleler Konvertierung über Rechtsklick auf die Videodatei pausieren und fortsetzen.
- Der Abschluss eines Verschiebevorgangs räumt die Warteschlange nach der Bestätigung wieder korrekt auf. Bereits verschobene Dateien bleiben nicht als vermeintlich vorhandene Aufträge zurück.
- Die Quell-RPU wird vor dem HEVC-Dolby-Vision-Encode schnell anhand vorhandener Metadaten oder Laufzeit × Bildrate auf plausible Länge geprüft. Eine vollständige Framezählung vor dem Encode entfällt. Offensichtlich zu kurze RPUs werden erkannt; der exakte Abgleich nach dem Encode bleibt bestehen.
- Patch 29 stärkt zusätzlich die ausgewählte Audio-/Untertitelspurübernahme, finale Medienverträge und sichere Filmersetzung.
- Die Review-Korrekturen betreffen unter anderem Prozesssteuerung, Watchfolder, Zielwahl, HDR, Audio, Untertitel, Metadaten, Mediathek, Recovery und sichere Dateitransaktionen.
- Der öffentliche Builder übernimmt die aktuelle Build- und Qt-/ICU-Prüfung. Seine PDF-Datenschutzprüfung ist standardmäßig aktiv; ein fehlendes oder ungeeignetes pypdf wird automatisch installiert/repariert.
- Hilfe, Änderungshistorie, Über-Ansicht, Word-Dokumentation und PDF-Handbuch wurden aus dem aktuellen Projektstand übernommen. Die Übersichten nennen auch die Testanzahl.

## Download

`DragonToolsV9.9.0-win64.zip` enthält die EXE und sämtliche für den Start benötigten Python-/Qt-Laufzeitdateien. Den gesamten ZIP-Inhalt entpacken und `DragonToolsV9.9.0.exe` starten.

Externe Medienwerkzeuge wie FFmpeg, MKVToolNix, dovi_tool oder MediaInfo sind nicht enthalten. `TOOLS_INSTALLIEREN.txt` beschreibt deren Einrichtung. Die benötigten Python-/Qt-Laufzeitbibliotheken sind enthalten.

Die SHA-256-Prüfsumme steht in `DragonToolsV9.9.0-win64.zip.sha256`.

## Prüfung

- 5.160 Standardtests bestanden, 27 übersprungen; 24 DV/HDR-Integrationstests abgewählt.
- Syntax-/Namensprüfung und öffentliche Datenschutzprüfung bestanden, einschließlich DOCX und PDF.
- Vier gezielte Fälle prüfen die zusätzliche öffentliche Datenschutzprüfung; echte eingebettete Zugangsdaten werden auch in Hilfsskripten erkannt und ihre Werte maskiert.
- Finale App-Bundle-Prüfung: 0 Fehler, 0 Warnungen.
- Starttest der tatsächlich gebauten EXE erfolgreich; Qt-Widgets, JPEG und OpenCV werden dabei praktisch geprüft.
- ZIP-CRC, Dateiinhalte, Ausschluss externer Medienwerkzeuge und SHA-256-Prüfsumme geprüft.

Der öffentliche Quellstand enthält 1.298 Python-Dateien, 208.363 Gesamtzeilen und 176.045 Codezeilen. Die Testpakete umfassen 376 Python-Dateien, davon 370 Testdateien mit 3.293 statisch erkannten Testfunktionen. Parametrisierte Tests erzeugen mehr ausgeführte Testfälle als statische Testfunktionen.
