# DragonTools 9.8.6 – was sich seit 9.8.2 getan hat

Wenn du bisher mit 9.8.2 gearbeitet hast, bringt dieses Update einiges mit: Du kannst Staffel und Episode im Renamer selbst korrigieren, Einstellungen auf mehrere Dateien gleichzeitig anwenden und neue Dateien über überwachte Ordner in die Warteschlange übernehmen. Dazu kommen neue Möglichkeiten für HDR, die Anbindung an Jellyfin und Werkzeuge, mit denen du deine Mediathek aufräumen kannst.

Auch an den weniger sichtbaren Stellen hat sich viel getan. Gerade bei parallelen Aufträgen, beschädigten Zeitstempeln und dem abschließenden Verschieben oder Ersetzen von Dateien gab es Korrekturen. Hier findest du die Änderungen aus 9.8.3 bis 9.8.6 zusammengefasst – einschließlich der letzten Ergänzungen vom 25. September 2026.

## Serien umbenennen: falsche Zuordnungen direkt korrigieren

Nicht jede Seriendatei kommt mit einem sauberen Namen wie `S03E07` an. Der Renamer versteht inzwischen weitere Schreibweisen, darunter `E05S06`, `EPxx` und einzelne Episodenangaben wie `E19`. Bei einem alleinstehenden `E19` wird zunächst Staffel 1 angenommen; diese Annahme wird angezeigt und lässt sich ändern.

Mit **„Staffel ändern“** und **„Episode ändern“** kannst du die Zuordnung für markierte Serienzeilen selbst festlegen. Wird eine Datei beispielsweise als `S01E19` erkannt, obwohl sie zu `S03E07` gehört, korrigierst du beide Werte direkt im Renamer. Anschließend startet die Metadatensuche erneut mit deiner Vorgabe. Die manuelle Episodenwahl bleibt auch bei einer erneuten Suche oder bei „Alle Treffer“ erhalten.

Die Bedienung wurde ebenfalls überarbeitet: Die 15 Aktionen sind jetzt auf drei Reihen mit jeweils fünf Schaltflächen verteilt. Das Hauptfenster und der Renamer lassen sich schmaler einstellen; Spaltenbreite, Reihenfolge und Sichtbarkeit werden gespeichert. Hinzu kommen konfigurierbare Releasegruppen und Verbesserungen bei der Online-Metadatensuche.

## Gleiche Einstellungen für mehrere Dateien

Du musst die Datei-Einstellungen nicht mehr für jeden Eintrag einzeln öffnen. Markiere mehrere Dateien in der Warteschlange und klicke mit der rechten Maustaste auf eine davon. Über **„Datei-Einstellungen für Auswahl (N) …“** kannst du die Einstellungen gemeinsam übernehmen.

Die angeklickte Datei dient dabei als Vorlage. Das betrifft unter anderem den Verarbeitungsmodus, Encoder-Overrides, Audio- und Untertiteleinstellungen sowie HDR-bezogene Vorgaben. Ein separat zugewiesenes Encoder-Profil bleibt dagegen für jede Datei erhalten.

Bereits laufende oder abgeschlossene Dateien werden nicht nachträglich verändert. Bei einer gemischten Auswahl werden die noch bearbeitbaren Einträge übernommen und die übrigen gesammelt gemeldet.

Ein Detail ist bei unterschiedlichen Dateien wichtig: Wenn du bestimmte Audio- oder Untertitelspuren über ihre Nummer auswählst, werden diese Nummern von der Vorlagendatei übernommen. Hat die nächste Datei eine andere Spurreihenfolge, solltest du sie getrennt einstellen.

## Mehr Möglichkeiten für HDR

DragonTools bietet jetzt eine Anbindung an **ComfyUI/HDRTVDM** für SDR→HDR sowie die Integration des **Dragon HDR10+ Generators**. Der Generatorbereich lässt sich auch direkt über einen eigenen Eintrag in den Einstellungen öffnen. Die benötigten externen Komponenten und Modelle müssen für den jeweiligen Ablauf eingerichtet sein; die Hilfe beschreibt die Vorbereitung.

Außerdem wurden die HDR-Erkennung, die Vorgaben pro Datei und der Strip-Only-Ablauf erweitert. Damit lassen sich unterschiedliche Ausgangsdateien gezielter behandeln.

Bei Dolby Vision wurde die Zusammenarbeit zwischen Bildbeschnitt und Metadaten verbessert. Video, eingebrannte PGS-/VobSub-Untertitel und die Anpassung der Dolby-Vision-Metadaten verwenden eine konsistentere Bildgeometrie. Zusätzliche Prüfungen sollen verhindern, dass eine Ausgabe ohne gültigen abschließenden Nachweis das Original ersetzt.

## Zeitstempel-Reparatur: genauer auf die Originaldatei schauen

Eine Videodatei kann mehrere leicht unterschiedliche Laufzeitangaben enthalten. Beispielsweise kann eine Untertitelspur etwas später enden als das eigentliche Bild. Bisher konnte eine solche längere Gesamtdauer dazu führen, dass eine technisch korrekte Videoreparatur abgelehnt wurde.

Die Reparatur betrachtet deshalb die Originaldatei jetzt getrennt: Containerdauer, Videodauer, Bildanzahl und die aus Bildrate und Bildanzahl berechnete Dauer werden als eigene Referenzen geführt. Im Protokoll erscheint dazu eine zusätzliche Zusammenfassung der Originalwerte.

Für verlustfreie Timestamp-Reparaturen mit vorhandener Originalreferenz gilt eine Toleranz von bis zu einer Sekunde für Video- und Containerdauer. Auch kleine Abweichungen von einem Bild werden gezielter berücksichtigt. Die Prüfung längerer Dateien erhält außerdem mehr Zeit zum vollständigen Zählen der Bilder.

Die tolerantere Dauerprüfung bedeutet nicht, dass fehlende Inhalte akzeptiert werden: Paketanzahl und Nutzdaten werden weiterhin zwischen Reparaturkandidat und defekter Ausgabe verglichen. Hinzu kommen Verbesserungen bei der Reparatur variabler Bildraten und beim Umgang mit Untertitel-Zeitstempeln.

## Jellyfin und überwachte Eingangsordner

Wenn du Jellyfin nutzt, kann DragonTools erfolgreiche Verschiebe- und Umbenennungsaktionen jetzt direkt an deinen Server melden. Dadurch muss nach solchen Änderungen nicht jedes Mal die komplette Mediathek neu eingelesen werden. Unterschiedliche Pfade auf deinem Rechner und auf dem Server lassen sich über Pfadzuordnungen berücksichtigen.

Die Verbindung ist optional und lässt sich in den Einstellungen testen. Ist Jellyfin vorübergehend nicht erreichbar, wird ein bereits erfolgreich verschobenes oder umbenanntes Video dadurch nicht nachträglich als fehlgeschlagener Dateiauftrag behandelt.

Mit **Watch-Foldern** kannst du außerdem Eingangsordner überwachen lassen. Neue Videos werden erst berücksichtigt, wenn Dateigröße und Änderungszeit über die eingestellte Wartezeit stabil bleiben. Unfertige Downloads mit Endungen wie `.part` oder `.tmp` werden übersprungen.

Je nach Regel kannst du Dateien nur einreihen oder einen automatischen Start vorsehen. Dabei gelten weiterhin die Bedingungen der Warteschlange und die Schutzprüfungen für den jeweiligen Ablauf. Ein Watch-Folder ist also keine pauschale Freigabe zum unbeaufsichtigten Verschieben oder Ersetzen von Dateien.

## Mediathek, Sprachen und Untertitel aufräumen

Die Mediathek hat eine Reparaturwarteschlange erhalten, über die sich unterstützte Korrekturen gesammelt bearbeiten lassen. Dazu gehören Erweiterungen bei der Erkennung von Audio- und Untertitelsprachen sowie bei der Korrektur von Track-Metadaten. Für die optionale lokale Audio-Spracherkennung wird faster-whisper verwendet; das ausgewählte Modell wird bei der ersten Verwendung heruntergeladen und anschließend lokal gespeichert.

Für PGS- und VobSub-Bilduntertitel gibt es eine optionale OCR-Verarbeitung mit Tesseract. Sie erzeugt einen bearbeitbaren SRT-Entwurf, den du vor der Übernahme prüfen und korrigieren kannst. Die ursprüngliche Bilduntertitelspur bleibt erhalten. Das ist gerade bei Namen, Satzzeichen oder schwer lesbaren Schriftarten hilfreich, weil eine Texterkennung dort Fehler machen kann. Tesseract und die passenden Sprachdaten müssen separat eingerichtet sein.

## Zuverlässigere Aufträge und Dateioperationen

Viele Korrekturen betreffen Situationen, die erst im laufenden Betrieb auffallen:

- **Parallele Aufträge:** Abbruch, Pause und Zeitüberschreitungen werden dem jeweiligen Hintergrundprozess genauer zugeordnet. Ein Problem in einem Auftrag soll keine fremden Aufträge beenden.
- **Fehler nach der Konvertierung:** Ein später Erfolgsschritt in der Nachbearbeitung darf einen vorherigen Fehler oder eine Warnung nicht einfach überschreiben und dadurch automatisches Verschieben wieder freigeben.
- **Abbrechen kurz vor dem Abschluss:** Vor dem endgültigen Übernehmen bestimmter Ausgaben und vor dem Löschen des Originals wird erneut auf einen Abbruch geprüft.
- **Unvollständige Dateioperationen:** Wiederherstellungsinformationen und Rückabwicklung wurden verbessert, auch wenn Begleitdateien oder bereits umbenannte Dateien beteiligt sind.
- **Zielordner ändern:** Solange der betreffende Verschiebeauftrag noch nicht begonnen hat, kannst du das Ziel nachträglich anpassen. Bei Serien bleiben Staffelordner und Specials bei der Neuzuordnung berücksichtigt.

Zusätzlich wurde der Schutz gespeicherter API-Zugangsdaten unter Windows verbessert. Hilfe, Änderungshistorie, Über-Dialog sowie DOCX- und PDF-Handbuch wurden auf den neuen Stand gebracht.

## Was im Download enthalten ist

Das öffentliche ZIP enthält DragonTools und die benötigten Python-/Qt-Laufzeitbibliotheken. **Externe Medienwerkzeuge wie FFmpeg, MKVToolNix, MakeMKV, MediaInfo oder MP4Box sind nicht enthalten.** Du richtest sie separat ein und wählst ihre Pfade in DragonTools aus. Die Datei `TOOLS_INSTALLIEREN.txt` liegt dem Paket bei und nennt die offiziellen Bezugsquellen.

Die öffentliche Paketierung wurde dafür korrigiert. Eine zusätzliche Inhaltsprüfung kontrolliert sowohl den Programmordner als auch das ZIP auf versehentlich mitgelieferte externe Werkzeuge. Für die enthaltenen Laufzeitbibliotheken gelten weiterhin deren jeweilige Lizenzen.

## So wechselst du von 9.8.2 auf 9.8.6

1. Sichere deine eigenen Einstellungen, Regeln und Profile.
2. Lade `DragonToolsV9.8.6-win64.zip` und die dazugehörige `.sha256`-Datei herunter und prüfe die Prüfsumme.
3. Entpacke das ZIP vollständig in einen neuen Ordner.
4. Starte `DragonToolsV9.8.6.exe`. Lass den Ordner `Daten` neben der EXE liegen.
5. Kontrolliere die Pfade zu deinen externen Werkzeugen. Für zusätzliche Funktionen wie OCR oder ComfyUI/HDRTVDM ist gegebenenfalls weitere Einrichtung nötig.

Falls du bereits ein früher bereitgestelltes 9.8.6-Paket verwendest: Das Paket wurde innerhalb derselben Versionsnummer überarbeitet. Dafür erscheint kein automatischer Hinweis auf eine höhere Version. Die folgende Prüfsumme kennzeichnet das hier beschriebene Paket.

**Datei:** `DragonToolsV9.8.6-win64.zip`

**Größe:** 203.612.001 Bytes, etwa 204 MB

**SHA-256:**

```text
48b9eac2d96cca064784e106a4452b6e845dfacdb37c3660af83b3c6dae90c76
```

## Was für diesen Stand geprüft wurde

Die zwölf gezielten Tests für die zuletzt ergänzten Zeitstempel-, Episoden- und Mehrfachauswahl-Korrekturen sind bestanden. Der abschließende Build-Check meldete keine Fehler oder Warnungen; auch die Prüfung auf private Marker, die ZIP-Integrität, die Prüfsumme und der Ausschluss externer Medienwerkzeuge waren erfolgreich. Das ist keine erneute vollständige Prüfung jeder Hardware- und Medienkombination.

Ein Abbruch wird weiterhin an den vorgesehenen Stellen verarbeitet und kann bereits abgeschlossene Dateioperationen nicht rückwirkend verhindern. Auch der Windows-Neustartschutz ist keine Garantie gegen einen erzwungenen Update-Neustart.
