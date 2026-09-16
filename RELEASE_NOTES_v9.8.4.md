# DragonTools 9.8.4

## Highlights

- Crop-Normalisierung legt vor dem Encoding eine eindeutige, gerade 4:2:0-Geometrie fest. AutoCrop ist die verbindliche Quelle des physischen DV-Crops; Quell-RPU-Level-5 bleibt Diagnoseinformation.
- Konfigurierbare Releasegruppen und zusätzliche Episodenmuster im Renamer: `E05S06` sowie `EPxx` mit expliziter Staffelwahl vor der Providerabfrage.
- Hauptfenster und Renamer lassen sich schmaler skalieren. Spaltenbreite, Reihenfolge und Sichtbarkeit werden gespeichert.
- Zielordner können nachträglich geändert werden, solange der konkrete Verschiebeauftrag noch nicht begonnen hat. Staffelordner und Specials bleiben beim Serien-Rebase erhalten.

## Fehlerbehebungen und Stabilität

- Video und PGS/VobSub-Burn-in verwenden nach einer Normalisierung denselben Crop. Die RPU wird nach physischem Crop auf den Zielstream angepasst.
- Eine angenommene Zieländerung kann nicht mehr zwischen Zielermittlung und Move-Start verloren gehen. Das Move-Journal markiert den Auftrag vor dem Lesen des Ziels als laufend.
- Wird eine Konvertierung während der geöffneten Ordnerauswahl fertig, wird die Änderung am aktuellen Ausgangspfad gespeichert.
- Fehlgeschlagener oder leerer finaler RPU-Nachweis sperrt das Ersetzen auch bei exakt passender Videogeometrie. Frühere Bestätigungen werden zurückgenommen; eine irreführende Erfolgsmeldung entfällt.
- Das Original bleibt geschützt. Ein RPU-Diagnosekandidat wird mit CSV-/Textbericht ohne NFO/Trickplay archiviert; bei Archivfehler bleibt er am Arbeitsort erhalten.
- Die gestufte Geometrieprüfung unterscheidet kleine Abweichungen, manuell zu prüfende Kandidaten und Diagnosefälle. Ein anderer Hash einer nachgewiesenen RPU ist bei exakter Videogeometrie allein kein Fehler.

## Technische Änderungen

Crop-Geometrie, Zielpfadbearbeitung, Verifikationsarchivierung und Laufzeitreparatur sind in fokussierten Fachmodulen gekapselt. Regressionstests sichern die neuen Abläufe. Hilfe, Über-Statistik, CHANGELOG und Versionsnachtrag in DOCX/PDF wurden aktualisiert.

## Validierung und Grenzen

Privater und anonymisierter Public-Quellstand: jeweils **1.449 Tests bestanden, keine Fehler oder Skips**, einschließlich erforderlicher Qt- und realer DV/HDR-Integration. Die Tests ersetzen keine vollständige Hardware-Encoder-/Medienmatrix oder interaktive GUI-Abnahme. Der Windows-Neustartschutz ist keine garantierte Sperre gegen erzwungene Update-Neustarts.

## Installation und Update

1. ZIP und passende SHA-256-Datei gemeinsam herunterladen und die Prüfsumme prüfen.
2. Eigene Einstellungen und Regeln sichern; das ZIP in einen neuen Ordner entpacken.
3. `DragonToolsV9.8.4.exe` starten; der Ordner `Daten` muss bei der EXE bleiben.
4. Externe Medienwerkzeuge gemäß `TOOLS_INSTALLIEREN.txt` separat einrichten. Sie sind entsprechend der Public-Paketierung nicht im ZIP enthalten.

Ein Git-Push allein veröffentlicht noch kein GitHub Release. Die erzeugten Artefakte müssen dafür an das Release angehängt werden.
