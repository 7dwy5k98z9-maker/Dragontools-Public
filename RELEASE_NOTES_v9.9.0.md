# DragonTools 9.9.0 – aktualisierter Stand

Stand: 08.10.2026. Diese Aktualisierung ergänzt die 29 Review-Schritte und die bisherigen Laufzeitkorrekturen.

## Korrekturen vom 08.10.2026

- Timestamp-Reparatur berücksichtigt die verlässliche Bildrate und Laufzeit des Originals. Ein erfolgloser Remux verhindert diese Prüfung nicht; unsichere Reparaturen bleiben gesperrt.
- Entfernte, abgeschlossene oder abgebrochene Dateien lassen sich erneut hinzufügen, sobald kein aktiver Auftrag mehr dieselbe Datei verarbeitet.
- Journal-Wiederherstellung läuft beim Start im Hintergrund. Abgeschlossene Verschiebevorgänge ohne ausstehendes Cleanup lösen keine erneute vollständige Dateiprüfung aus.
- Beim Einfügen von Untertiteln werden gültige Schriftanhänge auch dann akzeptiert und erhalten, wenn ffprobe keinen Codec-Namen für sie meldet.
- WebVTT wird zwischen MediaInfo und ffprobe korrekt zugeordnet. Die globale Spurposition bleibt unabhängig von der Untertitelanzahl.
- Strip-only schreibt die erwarteten Audiotitel, Sprachangaben sowie Default-/Forced-Kennzeichnungen und besteht dadurch die finale Ausgabeprüfung.

Die gezielte Abnahme der WebVTT-/Strip-only-Korrektur umfasst 95 bestandene Tests. Zusätzlich bestand eine echte betroffene Episode die Strip-only-Ausgabeprüfung; ihr Original blieb unverändert. Die Prüfung früherer Korrekturen wurde jeweils mit den betroffenen Regressionstests durchgeführt.

## Installation und Versionshinweis

Das Windows-Paket enthält die EXE und den erforderlichen Datenordner. Externe Medienwerkzeuge werden separat gemäß `TOOLS_INSTALLIEREN.txt` eingerichtet. Das vollständige ZIP entpacken und die EXE gemeinsam mit `Daten` belassen.

Die Anwendungsversion bleibt 9.9.0. Bereits installierte 9.9.0-Builds erhalten deshalb keinen automatischen Versionshinweis auf diesen aktualisierten Build.

## Abnahme des veröffentlichten Quellstands

- Vollständige Standardtestsuite: 5.234 bestanden, 18 übersprungen, 24 DV/HDR-Integrationstests abgewählt.
- Öffentliche Datenschutzprüfung einschließlich Dokumenten und Syntax-/Namensprüfung bestanden.
- Die zusätzliche Architektur-/Journal-/Statistik-Prüfung umfasst 940 bestandene Tests. Die Architekturgrenzen wurden eingehalten; der bestehende Schuldenkatalog blieb unverändert.
- Der frisch gebaute Windows-Build besteht alle 18 App-Bundle-Prüfungen und den Starttest der tatsächlichen EXE.
- Paketinhalt, kompilierte Anwendungsmodule, Ausschluss externer Medienwerkzeuge und ZIP-CRC wurden geprüft.

Der aktuelle Quellstand umfasst 1.304 Python-Dateien, 209.366 Gesamtzeilen, 176.898 Codezeilen und 375 Testdateien mit 3.326 statisch erkannten Testfunktionen. Die gezielten Testläufe werden nicht zusätzlich zur Gesamtsuite addiert.
