# DragonTools 9.9.0 – 10.10.2026

DragonTools verbindet Medienverarbeitung, Untertitelverwaltung und Benennung anhand von Metadaten. Das Windows-Paket enthält die Anwendung und die benötigten Laufzeitdateien. Externe Medienwerkzeuge werden separat installiert.

## Renamer und Serienbestand

### Umbenennen

Film- und Seriennamen werden im Hintergrund geändert. Die Dateiendung bleibt erhalten, vorhandene Zieldateien werden nicht überschrieben. Für eine reine Umbenennung wird der Videoinhalt nicht vollständig gelesen.

### Staffel und Serie prüfen

Die beiden Schaltflächen neben dem Metadaten-Browser vergleichen erkannte Renamer-Einträge mit ihrer gewählten Quelle TMDB oder TheTVDB. Die Auswahl fasst Serien und Staffeln zusammen. Das Ergebnis zeigt vollständige oder fehlende Staffeln, Specials und einzelne fehlende Folgen. Eine CSV-Datei ermöglicht die weitere Verwendung der Tabelle.

## Medienverarbeitung

### Laufzeit und Spurmetadaten

Bei einer unplausiblen MKV-Laufzeit wird zuerst ein normaler Remux versucht. Anschließend wird eine Timestamp-Reparatur anhand der verlässlichen Bildrate und Dauer des Originals geprüft. Audio- und Untertitelspuren behalten die geplanten Titel, Sprachangaben und Kennzeichnungen. WebVTT-Zuordnung und Schriftanhänge werden bei der Verarbeitung berücksichtigt.

### Warteschlange und Wiederherstellung

Dateien lassen sich erneut hinzufügen, sobald sie aus der Liste entfernt wurden und kein aktiver Auftrag sie mehr verarbeitet. Die Journal-Wiederherstellung läuft beim Start im Hintergrund. Beim Ersetzen eines Films werden vorhandene Trickplay-Daten vor dem Video gesichert; fehlende optionale Trickplay-Daten blockieren das Verschieben nicht.

## Dokumentation und Installation

### Hilfe und Changelog

Die Hilfe erläutert die Bedienung. Das V9-Changelog fasst die technische Entwicklung nach Fachbereichen und Unterpunkten zusammen. JSON- und Textfassung enthalten dieselben Informationen.

### Windows-Paket

Das vollständige ZIP entpacken und die EXE zusammen mit dem Ordner `Daten` belassen. `TOOLS_INSTALLIEREN.txt` beschreibt die getrennte Einrichtung der Medienwerkzeuge. Die SHA-256-Datei gehört zur gleichnamigen ZIP-Datei; für die lokale EXE liegt ebenfalls eine eigene Prüfsumme bei.

Die Anwendungsversion bleibt 9.9.0. Das vorhandene GitHub-Release wird mit dem aktuellen Paket aktualisiert.

## Prüfung der Veröffentlichung

### Quellstand

Die vollständige Standardtestsuite bestand mit 5286 erfolgreichen Fällen. 18 Fälle wurden übersprungen; 24 DV/HDR-Integrationstests waren in diesem Lauf nicht ausgewählt. Die Datenschutzprüfung einschließlich der öffentlichen Dokumente und die Release-Validierung des Quellstands bestanden.

### Windows-Anwendung

Die neue EXE bestand den Starttest. Alle 18 App-Bundle-Prüfungen waren erfolgreich. Die aktualisierte Hilfe und beide V9-Changelog-Fassungen sind im Paket enthalten. Kompilierte Anwendungsmodule, Ausschluss externer Medienwerkzeuge, ZIP-Inhalt und Prüfsummen wurden kontrolliert.
