# DragonTools V9.8.4

Stand: 16.09.2026. Normalisierter FFmpeg-AutoCrop ist die verbindliche physische DV-Crop-Quelle. Finaler RPU-Nachweis schützt das Original auch bei exakter Geometrie. Zieländerungen während laufender Aufträge sind an der Move-Transaktionsgrenze abgesichert. Renamer unterstützt Releasegruppen, E05S06 und EPxx mit Staffelwahl; Fenster und Spalten sind flexibel skalierbar.

857 Python-Dateien, 128.481 Gesamtzeilen und 108.628 Codezeilen (nichtleer, keine reinen Kommentarzeilen). Testpaket: 191 Python-Dateien, 188 test_*.py und 1.397 statisch erkannte Testfunktionen.

Die folgenden datierten Patch-Berichte dokumentieren die Entwicklung bis zum heutigen Abschluss. Frühere Angaben zu noch nicht erfolgten Commits/Pushes beziehen sich auf den jeweiligen Zwischenstand.

# DragonTools V9.8.3 Stabilitäts-Patch

## Nachreview: finaler RPU-Nachweis – 16.09.2026

- Ein fehlgeschlagener finaler RPU-Nachweis wird vor der Geometrieentscheidung ausgewertet und sperrt das Ersetzen unabhängig von der Pixelabweichung.
- Frühere DV-/Crop-Bestätigungen werden beim erneuten RPU-Nachweis zurückgesetzt; eine fehlgeschlagene Extraktion erhält keine abschließende Metadaten-Erfolgsmeldung.
- Der Kandidat bleibt als Diagnosearchiv mit CSV/TXT ohne NFO-/Trickplay-Nachbearbeitung erhalten. Ist das Archiv nicht verfügbar, wird der Kandidat am Arbeitsort geschützt.
- Hashabweichungen einer nachgewiesenen RPU bei exakter Videogeometrie bleiben absichtlich nicht blockierend.
- Neue Regressionen prüfen fehlgeschlagene/leere RPU-Extraktion bei 0/1/2/4/6 Pixeln, Originalschutz, Archivfehler und die Zielschlüsseländerung während des Ordnerdialogs.
- Validierung dieses Nachreviews: 106 gezielte Tests bestanden; vollständige Suite mit erforderlichen Qt-/DV-/HDR-Integrationen außerhalb der Sandbox: 1449 bestanden, 0 fehlgeschlagen, 0 übersprungen (59,23 s). Alle 12 neuen parametrisierten Testfälle zusätzlich separat bestanden. Syntaxprüfung: 857 Python-Dateien; Import-Smoke: 183 Module; CHANGELOG-JSON gültig.
- Der erste Gesamtlauf innerhalb der Sandbox hatte 1448 bestandene Tests und einen Fehler beim realen Windows-Prozessabbruch. Der unveränderte Test besteht außerhalb der Sandbox. Neue Tests sind Ruff-sauber; die Produktivdateien bestehen die gezielte Prüfung E9/F63/F7/F82. Bereits vorhandene breite Exception-Grenzen und Format-Hinweise bleiben außerhalb dieses Patches bestehen.
- Dieses Nachreview enthält keinen Versionswechsel, Commit, Push, Public-Sync oder Build. DOCX/PDF und Release-Statistiken wurden in diesem gezielten Patch nicht neu erzeugt; das bleibt Teil des Versions-/Dokumentationsabschlusses.

Stand: 14.09.2026. Basis: privater 9.8.2-Stand inklusive Review-Patches bis v12.

## Umgesetzte Korrekturen

1. Cleanup-Warnungen und Fehler bleiben terminal erhalten. Hintergrund-Nachbearbeitung darf daraus keinen Erfolg machen; Auto-Move bleibt für solche Ergebnisse gesperrt.

2. Nachbearbeitungsaufträge besitzen eigene Prozess-Slots. Timeout, Abbruch und Pause verwenden die konkrete Prozessinstanz; ein lokaler Auftrag darf keinen parallelen Auftrag beenden. Ein ausdrücklich angeforderter Batch-Abbruch gilt weiterhin für den gesamten Batch.

3. Normaler MP4-Remux prüft Abbruch erneut nach Sidecar-Arbeit und unmittelbar in der finalen Dateitransaktion. Vor dem Commit eingegangene Abbrüche erhalten das Original und rollen Sidecars zurück. Ein unvollständiger Rollback bewahrt Staging und Journal zur Recovery.

Abbruch ist kooperativ: Ein bereits abgeschlossenes atomares Dateisystem-Replace kann nicht rückwirkend verhindert werden. Die Prüfung liegt unmittelbar vor dem Commit und beim Containerwechsel nochmals vor dem Original-Cleanup; bei einem dort erkannten Abbruch wird die Installation zurückgerollt. Bereits sicher installierte Ausgaben werden nicht blind gelöscht.

## Regressionen und Validierung

`test_stability_983.py` prüft Statusreihenfolge und konkurrierende Callback-Abschlüsse, GUI-Move-Sperren, echte Prozessisolation, Pause-Zuordnung und Abbruch während der finalen Transaktion einschließlich Sidecar-Rollback.

Vollständiger lokaler Testlauf mit der vorhandenen .venv: 1390 bestanden, 0 fehlgeschlagen, 0 übersprungen. Enthalten sind 20 neue Stabilitäts-Regressionsfälle und beide realen DV/HDR-Roundtrips. Qt- und DV/HDR-Integration waren ausdrücklich erforderlich, nicht optional übersprungen. Weitere Validierungsergebnisse und Dateiprüfsummen stehen in PATCH_MANIFEST.json.

Keine Public-/Release-Synchronisierung, keine Git-Commits/-Pushes und kein EXE-Build. Die Tests ersetzen keine vollständige Hardware-Encoder-/Medienmatrix.

## Abschlussreview und GUI-Nachpatch – 15.09.2026

Nach dem Stabilitäts-Patch wurde die Hauptfensterbreite erneut geprüft. Die übergroße Mindestbreite entstand aus zwei zusammenwirkenden GUI-Quellen: der aufsummierten Mindestbreite der Haupt-Tab-Leiste und der einzeiligen Renamer-Aktionsleiste. Zusätzlich waren die bisherigen Tabellen-Resize-Modi für lange Dateinamen unnötig breit.

Umgesetzt:

- Die Haupt-Tab-Leiste darf horizontal schrumpfen; Scrollbuttons und Text-Elide bleiben bei knapper Breite aktiv und ihre `minimumSizeHint()` wird nicht mehr auf die Summe aller Tab-Titel hochgereicht.
- Die 13 Renamer-Aktionen sind auf mehrere Zeilen verteilt.
- Renamer-Spalten verwenden interaktive, frei verstellbare Breiten statt einer Mischung aus `ResizeToContents` und `Stretch`.
- Über `⚙ Spalten` lassen sich Spalten einzeln ein-/ausblenden. Reihenfolge, Breite und Sichtbarkeit werden per `QSettings` gespeichert.
- In der Standardansicht sind `OK`, `Typ` und `Hinweise` ausgeblendet; Quelldatei, Vorschlag/Match und Provider bleiben im Fokus.
- Help, Handbuch, Über-Informationen und die fachbereichsorientierte Änderungshistorie wurden auf diesen Stand synchronisiert.

Finale gezielte Prüfung auf dem Review-Host: 10/10 relevante Architektur-, Changelog- und Projektinfo-Tests bestanden; `compileall` erfolgreich; Source-Release-Prüfung mit 0 Fehlern. Die vier gemeldeten Warnungen betreffen den bewusst nicht mitgelieferten `dist`-Build sowie private Namensmarker in der privaten Projektfassung und sind für die hier geprüfte Quellfreigabe keine Funktionsfehler.

## Renamer-Erweiterung 15.09.2026

- Renamer-Regelschema 3 mit konfigurierbarer Releasegruppen-Liste.
- Releasegruppen werden exakt und nur an Anfang/Ende des Release-Namens entfernt.
- `E05S06` und `E05 S06` werden als Staffel 6 / Episode 5 erkannt.
- `EP01`/`EPISODE01` wird als Serie erkannt; ohne Staffel erfolgt vor der Providerabfrage eine explizite Staffelwahl. Staffel 0 ist zulässig.
- Staffelabfragen werden für dieselbe Serie im selben Ordner gruppiert, damit Serienbatches nicht für jede Folge einzeln fragen.
- Neue Regressionstests sichern Releasegruppen, flexible Episodenmuster, fehlende Staffel und Provider-Call-Guard ab.


## AutoCrop-Autorität und Zielpfad-Race-Fixes – 16.09.2026

- Bei Dolby Vision ist FFmpeg-AutoCrop jetzt die alleinige Quelle des physischen Video-Crops. Quell-RPU-Level-5 wird nur diagnostisch protokolliert und darf den Bildausschnitt nicht mehr vergrößern, verkleinern oder verschieben.
- Ein AutoCrop wird bei Bedarf selbst auf 4:2:0-Geometrie normalisiert; danach verwenden Video-Encoding und PGS/VobSub-Burn-in exakt diesen Crop. `-filter_complex`-Graphen werden bei einer Normalisierung in-place aktualisiert.
- Nach dem physischen Crop wird die RPU für den bereits gecroppten Zielstream auf Level 5 = 0/0/0/0 angepasst und verifiziert.
- Move-Race 1 geschlossen: Die konkrete Datei wird vor dem Lesen/Routen des Ziels im Move-Journal als `running` markiert. Eine danach eintreffende Zieländerung wird abgelehnt statt bestätigt und anschließend ignoriert.
- Move-Race 2 geschlossen: Nach dem Ordnerdialog wird der aktuelle Planned-Target-Schlüssel erneut ermittelt. Wechselt eine Datei während des Dialogs vom Input- auf den Output-Pfad, landet die bestätigte Änderung am aktuellen Schlüssel.
- Journal-Erzeugung und Runtime-Zielupdate verwenden denselben Planned-Target-Lock, sodass auch die Recovery-Metadaten keinen Zwischenstand verlieren.
- Neue Regressionen decken AutoCrop 1606 vs. Quell-RPU 1607, PGS-`filter_complex`, die Move-Transaktionsgrenze und die erneute Zielschlüsselauflösung ab.
