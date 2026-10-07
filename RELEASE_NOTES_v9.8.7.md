# DragonTools 9.8.7

Stand: 02.10.2026. Öffentliche Fassung unter dem Entwicklernamen **Dragon Developer**.

## Änderungen seit dem bisherigen öffentlichen Stand 9.8.6

- Aktualisierter Renamer mit Metadaten-Browser, manueller Staffel-/Episodenwahl und sicherer Jahreszuordnung.
- Steuerung der parallelen Verarbeitung und zusätzliche Dateieinstellungen in der Konvertierungsoberfläche.
- Watchfolder mit manueller Übernahme, sicherem Shutdown und verbesserter Queue-Zuordnung.
- PGS-Untertitel mit Display-Set-Parser, OCR-Preroll und einem zusätzlichen MKVToolNix-Extraktionsweg.
- Move-Only berücksichtigt vorhandene Untertitel-, NFO- und Trickplay-Begleitdateien.
- Erweiterte DV/HDR10+-Prüfung, kontrollierte Teilbild-Reparatur, begrenzte Nachbearbeitung und Diagnosearchive bei Fehlern.
- Verbesserte Timestamp-, Backup-, Prozess- und Dateitransaktionsprüfungen.
- Versionsdaten, Änderungshistorie und das 377-seitige technische Handbuch sind auf 9.8.7 aktualisiert.

Die vollständige Änderungshistorie liegt im öffentlichen Quellrepository und im Programm vor.

## Öffentliche Paketierung

Das Paket wurde frisch aus dem anonymisierten öffentlichen Quellstand gebaut. Es enthält die Anwendung und die benötigten Python-/Qt-Laufzeitbibliotheken. Externe Medienwerkzeuge, lokale Einstellungen, persönliche Zugangsdaten, private Entwicklungsarchive und Dateien aus `third_party` werden nicht mitgeliefert. Externe Werkzeuge werden gemäß `TOOLS_INSTALLIEREN.txt` separat installiert.

Persönliche Angaben wurden aus Quelltext, Dokumentation und Handbuch entfernt. Zusätzlich wurden die kompilierten Anwendungsmodule auf private Namen und Entwicklerpfade geprüft.

## Prüfung und bekannte Grenzen

- 45 gezielte Release-, Versions-, Paketierungs- und Datenschutztests bestanden.
- Die integrierte App-Bundle-Validierung meldet 0 Fehler und 0 Warnungen.
- Die finale Windows-EXE besteht den Frozen-Runtime-Smoke mit echter Qt-Initialisierung.
- Das Release-ZIP wird auf CRC-Integrität, ausgeschlossene Werkzeuge und seine SHA-256-Prüfsumme geprüft.
- Der vollständige Testlauf ist nicht vollständig grün: sieben Fehler und ein zugehöriger Qt-Teardown-Fehler sind auch im unveränderten privaten Quellstand reproduzierbar. Betroffen sind vier Architekturgrenzen, eine veraltete GUI-Testattrappe, eine Untertitelschema-Erwartung und ein vom Arbeitsverzeichnis abhängiger Testpfad. Diese vorhandenen Abweichungen wurden für den Repository-Abgleich nicht durch Produktänderungen oder gelockerte Architekturgrenzen verdeckt.
- Eine vollständige interaktive GUI-Abnahme und reale DV/HDR-/Hardware-Encoder-Roundtrips wurden nicht durchgeführt.

## Dateien und Installation

- `artifacts/DragonToolsV9.8.7-win64.zip`
- `artifacts/DragonToolsV9.8.7-win64.zip.sha256`

Die beiden Dateien werden ausschließlich lokal abgelegt und bleiben gemäß bestehender `.gitignore` außerhalb der Git-Historie. Es wird kein GitHub Release angelegt oder veröffentlicht.

ZIP-Prüfsumme prüfen, in einen neuen Ordner entpacken und `DragonToolsV9.8.7.exe` zusammen mit dem Ordner `Daten` belassen. Eigene Einstellungen und Regeln vor dem Wechsel sichern.
