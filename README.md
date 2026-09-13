# DragonTools V9.8.2

DragonTools ist eine Windows-Anwendung zur Analyse, Konvertierung und Verwaltung von Video-, Audio- und Untertiteldateien. Das Projekt bündelt die benötigten Drittanbieterprogramme nicht im Git-Repository. Sie müssen separat von den jeweiligen Projektseiten heruntergeladen werden.


## Aktueller Entwicklungsstand – 13.09.2026

Der aktuelle V9.8.2-Stand wurde nach den Datenbank-/Metadaten-Patches in zwölf größeren Refactoring- und Stabilitätsblöcken weiter zerlegt. Ziel war nicht, nur Dateien kleiner zu machen, sondern GUI, Orchestrierung, Datenbankzugriff, Dateisystem-I/O, externe Tools und reine Fachlogik klarer voneinander zu trennen. Bestehende Importpfade bleiben dort über schmale Kompatibilitätsfassaden erhalten, wo Worker, Tests oder andere Module darauf angewiesen sind.

Wichtige Änderungen des aktuellen Stands:

- **Mediathek:** migrationssichere Schema-Reihenfolge, indexfreundlicher Serien-Lookup über `normalized_title`, korrigierte Jellyfin-Normalisierung, weniger unnötige SQLite-Verbindungen/Writes und eine asynchrone Mediathek-Suche außerhalb des GUI-Threads.
- **Preflight und Metadaten:** Film-/Serienpfade werden bei aktivierter Mediathek zuerst über SQLite aufgelöst. Persistenter Suchcache und frische Batch-Metadaten sind getrennt; finale Renamer-/NFO-Läufe können aktuelle Providerdaten einmal pro Serie/Batch laden und anschließend wiederverwenden.
- **Renamer:** generische Episodentitel wie `Folge 10` oder `Episode 10` gelten nicht als endgültige Metadaten. Sie lösen bei Bedarf eine frische Abfrage aus; TheTVDB kann bei vorhandener Episode ohne brauchbaren deutschen Titel auf die Fallback-Sprache zurückgreifen.
- **Trickplay/Postprocessing:** Logging akzeptiert normale Logger, Callables und native Qt-Signale. Ein bereits gestarteter Async-Postprocess wird nach einem Loggingfehler nicht noch einmal synchron gestartet; NFO/Trickplay bleiben damit exactly-once geplant.
- **Abschlussreview:** Move-Journal-Archivierungsfehler sind fail-closed, Journal-Finalisierungsfehler zählen im Move-Worker als Fehler, der Release-Smoke verlangt alle im Refactoring-Manifest neu eingeführten Produktivmodule und ein gescheiterter Episodenrefresh wird mit Ursache geloggt statt still auf `Folge XX` zurückzufallen.
- **Quellbildprüfung:** mehrere Prüfpositionen werden gebündelt. Bei 10-%-Intervallen sinkt die Zahl der FFmpeg-Starts im Normalfall von 9 auf 3, bei 5 % von 19 auf 5; nur eine fehlgeschlagene Gruppe fällt auf Einzelproben zurück.
- **Modulstruktur:** große Bereiche wie Mediathek, NFO-Scan, Trickplay, DV-Remux, Backup/Restore, Journal, Preflight, Merge, ISO, Parallel-Converter, MoveThread, Encoder-Override, Duration-Repair, HDR10+, MediaAnalyzer, Renamer-Kandidaten, Audio/Video-Matcher und Online-Metadaten-Dialog sind in fokussierte Fachmodule aufgeteilt.

Der aktuell vermessene Quellstand umfasst **729 Python-Dateien einschließlich `DragonToolsV9.py`**, rund **118.227 Gesamtzeilen** und **100.301 nichtleere/nicht reine Kommentarzeilen**. Im Testpaket liegen **167 Python-Dateien**, davon **164 `test_*.py`** mit **1.224 statisch erkennbaren Testfunktionen**. In einem Package-only-Archiv ohne Einstiegspunkt werden entsprechend 728 Python-Dateien gezählt.

## Voraussetzungen

- Windows 10 oder neuer
- Python 3.12 oder 3.13
- Git zum Klonen und Aktualisieren des Projekts
- FFmpeg und FFprobe für die grundlegende Medienanalyse und -verarbeitung
- weitere Werkzeuge abhängig von den verwendeten Funktionen

Die Python-Abhängigkeiten sind nach Einsatzzweck aufgeteilt:

- `requirements-runtime.txt`: Anwendung starten
- `requirements-optional.txt`: optionale Bildanalyse
- `requirements-test.txt`: Tests ausführen
- `requirements-build.txt`: vollständigen Windows-Build erstellen

## Projekt herunterladen und starten

```powershell
git clone https://github.com/7dwy5k98z9-maker/Dragontools.git
cd Dragontools
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-runtime.txt
python DragonToolsV9.py
```

Für die optionale Bildanalyse zusätzlich:

```powershell
python -m pip install -r requirements-optional.txt
```

## Externe Werkzeuge

Die Programme werden bewusst nicht mit diesem Repository verteilt. Lade sie ausschließlich von den verlinkten Projektseiten herunter und beachte ihre jeweiligen Lizenzen und Nutzungsbedingungen.

| Werkzeug | Verwendung in DragonTools | Offizielle Downloadquelle | Erwarteter Speicherort |
| --- | --- | --- | --- |
| FFmpeg und FFprobe | Medienanalyse, Konvertierung, Remuxing und zahlreiche Kernfunktionen | [FFmpeg Download](https://ffmpeg.org/download.html) – unter Windows einen dort verlinkten Windows-Build verwenden | `third_party/FFmpeg/ffmpeg.exe` und `third_party/FFmpeg/ffprobe.exe` |
| MKVToolNix | MKV-Remuxing, Extraktion und Bearbeitung von Track-Metadaten | [MKVToolNix Downloads](https://mkvtoolnix.download/downloads.html) – portable 64-Bit-Ausgabe empfohlen | kompletter Inhalt unter `third_party/MKVToolNix/`, darunter `mkvmerge.exe`, `mkvextract.exe`, `mkvinfo.exe` und `mkvpropedit.exe` |
| MediaInfo CLI | Erweiterte Medien-, HDR- und Dolby-Vision-Erkennung | [MediaInfo für Windows](https://mediaarea.net/en/MediaInfo/Download/Windows) – die 64-Bit-CLI-Ausgabe wählen | `third_party/Mediainfo/MediaInfo.exe` |
| GPAC / MP4Box | MP4-Muxing und MP4-Timestamp-Reparatur | [GPAC Downloads](https://gpac.io/downloads/gpac-nightly-builds/) – stabilen Windows-64-Bit-Build verwenden | `third_party/GPAC/mp4box.exe` |
| dovi_tool | Dolby-Vision-RPU extrahieren, bearbeiten und injizieren | [dovi_tool Releases](https://github.com/quietvoid/dovi_tool/releases) – `x86_64-pc-windows-msvc` für übliche 64-Bit-PCs | `third_party/dovi_tool/dovi_tool.exe` |
| hdr10plus_tool | HDR10+-Metadaten extrahieren und injizieren | [hdr10plus_tool Releases](https://github.com/quietvoid/hdr10plus_tool/releases) – `x86_64-pc-windows-msvc` für übliche 64-Bit-PCs | `third_party/hdr10plus_tool/hdr10plus_tool.exe` |
| HandBrake | Externes Konvertierungswerkzeug und HandBrake-Profile | [HandBrake Downloads](https://handbrake.fr/downloads.php) | kompletter Programmordner unter `third_party/HandBrake/`, mit `HandBrake.exe` oder `HandBrakeCLI.exe` |
| MakeMKV | ISO-, DVD- und Blu-ray-Workflows | [MakeMKV Download](https://www.makemkv.com/download/) | kompletter Programmordner unter `third_party/MakeMKV/`, mit `makemkvcon64.exe` oder `makemkvcon.exe` |
| Rename My TV Series | Optionales externes Werkzeug zur Serienumbenennung | [Rename My TV Series 2](https://www.tweaking4all.com/home-theatre/rename-my-tv-series-v2/) | kompletter Programmordner unter `third_party/rmts/`, mit `RenameMyTVSeries.exe` |

Nicht jede Funktion benötigt alle Werkzeuge. Fehlende optionale Werkzeuge deaktivieren oder begrenzen nur die zugehörigen Arbeitsabläufe. Der vollständige EXE-Build erwartet hingegen sämtliche oben genannten Ordner und Programme.

## Alternative Werkzeugkonfiguration

Beim Start aus dem Quellcode sucht DragonTools Werkzeuge in dieser Reihenfolge:

1. in den innerhalb von DragonTools konfigurierten Werkzeugordnern,
2. im Windows-`PATH`,
3. in den bekannten Unterordnern von `third_party`.

Die Pfade können in DragonTools unter den Einstellungen für externe Werkzeuge ausgewählt werden. Das ist praktisch, wenn die Programme bereits an anderer Stelle installiert sind. Für `build_v9.bat` müssen sie trotzdem in der oben beschriebenen `third_party`-Struktur vorhanden sein.

## Empfohlene Ordnerstruktur

```text
Dragontools/
├── DragonToolsV9.py
├── build_v9.bat
├── dragontools/
├── Handbuch/
├── Bilder/
├── icon/
└── third_party/
    ├── FFmpeg/
    │   ├── ffmpeg.exe
    │   └── ffprobe.exe
    ├── MKVToolNix/
    ├── MakeMKV/
    ├── GPAC/
    │   └── mp4box.exe
    ├── HandBrake/
    ├── Mediainfo/
    │   └── MediaInfo.exe
    ├── dovi_tool/
    │   └── dovi_tool.exe
    ├── hdr10plus_tool/
    │   └── hdr10plus_tool.exe
    └── rmts/
        └── RenameMyTVSeries.exe
```

## Tests

```powershell
python -m pip install -r requirements-test.txt
python -m pytest -m "not dv_hdr_integration"
```

Die echten Dolby-Vision-/HDR10+-Integrationstests benötigen zusätzlich `dovi_tool`, `hdr10plus_tool` und MP4Box sowie geeignete Testmedien.


## Architektur und Laufzeitverhalten

DragonTools folgt im aktuellen Stand einer Fassaden-/Fachmodul-Struktur. Öffentliche Widgets, Worker und Core-Einstiegspunkte bleiben klein und delegieren an Module mit klarer Verantwortung. Das ist insbesondere bei sicherheitskritischen Bereichen wie Move/Replace, Output-Commit, Backup/Restore und Duration-Repair wichtig, weil Dateisystemoperationen und Datenbankänderungen dadurch separat geprüft werden können.

Einige Laufzeitregeln sind bewusst festgelegt:

- SQLite-Suchen laufen ohne unnötige Schema-Writes; die GUI-Suche wird in einem Worker ausgeführt und übergibt nur die Ergebnisse an den GUI-Thread.
- Serien-Lookups nutzen zuerst den indexierten `normalized_title`; langsame Legacy-Vergleiche sind nur Fallback für alte oder inkonsistente Datenbanken.
- NFO-Scans führen NAS-/XML-I/O außerhalb langer SQLite-Schreibtransaktionen aus und committen Ergebnisse in kurzen Batches.
- Online-Metadaten unterscheiden zwischen längerlebigem Suchcache und einem frischen Batch-Cache für finale Verarbeitung. Mehrere Folgen derselben Serie können dadurch eine frisch geladene Episodenliste gemeinsam verwenden.
- Externe Tool-Prozesse laufen über zentrale Timeout-/Abort-/Lifecycle-Grenzen. Diagnosemarker enthalten nach Möglichkeit die konkrete Mediendatei statt nur den Prozessnamen.

## Trickplay und asynchrones Postprocessing

Jellyfin-NFO und Trickplay laufen nach erfolgreicher Medienverarbeitung als Postprocessing. Trickplay wird transaktional über eine Partial-Struktur erzeugt und erst nach erfolgreichem Abschluss committed; bei Problemen bleibt ein vorhandener Bestand geschützt bzw. wird zurückgerollt.

Der aktuelle Async-Koordinator behandelt einen erfolgreich an den ThreadPool übergebenen Auftrag als eindeutig gestartet. Ein Fehler in Logging oder GUI-Signalweitergabe darf deshalb keinen zweiten synchronen NFO-/Trickplay-Lauf derselben Datei auslösen. Native PyQt-Signale werden über `.emit(...)` angesprochen; der frühere Fehler `TypeError: native Qt signal is not callable` wird damit an der zentralen Logging-Grenze verhindert.

`crash_state.json` ist primär ein **Aktivitätsmarker** für den zuletzt überwachten Toolzustand. Eine vorhandene Datei mit `active: true` beweist für sich allein keinen FFmpeg-Absturz. Für echte unbehandelte Ausnahmen sind die Crash-/ErrorReports maßgeblich.

## Sichere Timestamp-Reparatur

Bei einer unplausiblen Ausgabelaufzeit versucht DragonTools zuerst einen verlustfreien Container-Remux. Für eindeutig erkannte MKV-Timestampfehler folgt eine Reparatur mit dem FFmpeg-`setts`-Bitstreamfilter; steht dieser Filter nicht zur Verfügung oder scheitert der Versuch, kann DragonTools auf einen ebenfalls verlustfreien `+genpts+igndts`-Remux ausweichen.

Jeder Reparaturkandidat wird vor dem Ersetzen erneut auf Laufzeit, Lesbarkeit, Video-, Audio- und Untertitelspuren sowie Attachments geprüft. FFprobe und MediaInfo dienen dabei als voneinander unabhängige Gegenprüfung. Ein Werkzeugfehler, ein Streamverlust oder widersprüchliche Ergebnisse verwerfen den Kandidaten. Die Quelldatei wird in diesem Fall weder ersetzt noch anschließend verschoben. Verworfene Timestamp-Kandidaten werden, soweit möglich, unter `Archiv\Timestamp_Reparatur` abgelegt, damit fehlerhafte Reparaturversuche später nachvollzogen werden können.

## Jellyfin-Mediathek importieren

DragonTools liest aktuelle Jellyfin-Datenbanken mit `BaseItems` und `MediaStreamInfos` ausschließlich als Quelle und erzeugt daraus eine eigene funktionale SQLite-Mediathek. Übernommen werden Filme, Serien, Staffeln, vorhandene Episoden und sonstige Videodateien einschließlich Pfad, Dateigröße, Laufzeit, Container, Auflösung, Video- und Gesamtbitrate, Video-Codec, Profil, Pixelformat, Bittiefe, Bildrate, Bildratenmodus, Frameanzahl, Farbraum, Transferfunktion, Farbprimärwerte, HDR/SDR, HDR10+ und Dolby Vision. Für Audio und Untertitel werden unter anderem Sprache, Codec, Kanäle, Kanalbelegung, Bitrate, Forced-Status, Streamdauer und vorhandene Eventanzahlen gespeichert. Seit Schema 6 werden zusätzlich Originaltitel, Provider-IDs (z. B. TMDB/TheTVDB/IMDb), Genres, Tags, Studios, Collections/Filmreihen und schlanke Personenbeziehungen importiert. Personen werden einmalig gespeichert und nur mit den Medien verknüpft; Biografien, Bilder und andere Personendetails werden nicht übernommen. Playlists und reine Metadatenpfade bleiben ausgeschlossen.

Vor dem Import wird ein konsistenter Read-only-Snapshot einschließlich vorhandener WAL-Daten erzeugt und mit SQLite geprüft. Eine beschädigte oder unvollständig kopierte Jellyfin-Datenbank ersetzt die vorhandene DragonTools-Mediathek nicht. Gleichwertige Windows-/UNC-Pfade werden beim Neuaufbau nur einmal übernommen.

Neue und bestehende DragonTools-Mediatheken werden kompatibel auf Schema 6 gebracht. Migrationen ergänzen fehlende Spalten vor davon abhängigen Indizes. Der Serien-Lookup nutzt zuerst den indexierten normalisierten Serientitel; ältere `series_title`-/`title`-Vergleiche bleiben nur als Legacy-Fallback. Die GUI-Suche läuft asynchron und reichert Streamdaten gebündelt an, damit große Bestände die Oberfläche nicht durch wiederholte Einzelabfragen blockieren. Zusätzlich zum vollständigen Speicherpfad-Scan gibt es einen leichten NFO-Scan, der ausschließlich bereits bekannte Mediathek-Pfade prüft und weder MediaInfo noch ffprobe noch einen rekursiven NAS-Scan startet. Er speichert NFO-Status, Pfad, Typ und Zeitstempel und unterscheidet unter anderem `present`, `missing`, `unreachable`, `invalid` und `unreadable`. Ein offline gegangener NAS-/Share-Pfad wird als `unreachable` behandelt; vorhandene NFO-Prüfdaten bleiben erhalten. Aus NFOs gelesene Titel, Staffel/Folge, Jahr und Provider-IDs werden getrennt gespeichert und mit der Mediathek verglichen, ohne deren Metadaten zu überschreiben. Die NFO-Erstellung selbst verwendet weiterhin die Online-Metadatenabfrage und nicht die Mediathek-DB. Die Suche unterstützt gespeicherte GUI-/SQL-Abfragen; eine eingebaute SQL-Hilfe zeigt Tabellen, Spalten, Datentypen und Beispielabfragen. Trefferlisten bleiben in der GUI aus Performancegründen begrenzt; der CSV-Export führt dieselbe zuletzt ausgeführte Suche ohne Anzeigelimit aus und exportiert alle passenden Datensätze. CSV-Exporte enthalten die erweiterten technischen und NFO-bezogenen Felder.

## Renamer: mehrstufige Suche und manuelle Korrektur

Der Film-/Serien-Renamer bewertet Metadatenkandidaten in konfigurierbaren Stufen. Standardmäßig wird zuerst die normale Mindestübereinstimmung von **60 %** verwendet. Gibt es dort keinen Kandidaten, folgen automatisch die Fallback-Stufen **45 %** und **30 %**. Alle drei Grenzwerte sind unter **Regeln → Renamer-Regeln** separat einstellbar. Treffer aus reduzierten Stufen werden sichtbar als Fallback markiert und bleiben prüfbedürftig; die letzte Stufe behandelt mehrere ähnlich schwache Kandidaten bewusst als mehrdeutig statt blind zu raten.

Wenn die automatische Typ-Erkennung falsch liegt, kann eine markierte Zeile gezielt **als Serie** oder **als Film** gesucht werden. Der Suchbegriff kann manuell geändert werden; außerdem lassen sich auf Wunsch alle Provider-Kandidaten ohne Fuzzy-Grenze anzeigen. Die Ergebnistabelle zeigt den tatsächlich gewählten Provider (**TMDB** oder **TheTVDB**) in einer eigenen Spalte.

Wenn der Metadatencache für eine Serienfolge nur einen generischen Platzhalter wie **Folge 10** enthält, fragt der Renamer den Provider einmal frisch am Cache vorbei ab. Liefert TMDB oder TheTVDB inzwischen einen echten Episodentitel, wird der Cache erneuert und der neue Zielname verwendet. Bei TheTVDB kann eine vorhandene Episode ohne brauchbaren Titel zusätzlich über die konfigurierte Fallback-Sprache ergänzt werden. Für finale Rename-/NFO-Läufe kann eine frisch geladene Serien-/Episodenliste innerhalb desselben Batches wiederverwendet werden, sodass zwanzig Folgen nicht zwanzig identische Providerabfragen auslösen. Serienfolgen bleiben dabei im Standard **Serienname - SXXEXX - Episodenname.ext**.

## Regel-/Profil-Simulator

Der Regel-/Profil-Simulator zeigt neben Quelle, Pipeline, HDR/DV, Audio, Untertiteln und Ziel jetzt auch die **berechnete Endauflösung**. Dabei wird dieselbe Downscale-only-Logik wie im Encode-Pfad verwendet. Wenn Auto-Crop aktiv ist und der konkrete Crop erst während der Medienverarbeitung ermittelt werden kann, kennzeichnet der Simulator die Auflösung ausdrücklich als **vor Auto-Crop** statt eine nicht bekannte endgültige Crop-Auflösung zu erfinden.

## Windows-Anwendung bauen

Installiere zunächst die Build-Abhängigkeiten:

```powershell
python -m pip install -r requirements-build.txt
```

Kontrolliere anschließend, dass alle externen Werkzeuge unter `third_party` vorhanden sind, und starte den Build aus einer Eingabeaufforderung im Projektordner:

```cmd
build_v9.bat
```

Der fertige Build wird unter `dist/DragonToolsV9.8.2/` abgelegt. `build/` und `dist/` sind lokale Ausgaben und werden nicht in Git gespeichert.

## Programm-Updates über GitHub

DragonTools prüft nach dem Programmstart verzögert und ohne Blockierung der Oberfläche, ob im vorgesehenen öffentlichen Release-Repository eine neuere Version bereitsteht. Die Prüfung kann außerdem jederzeit über **Hilfe → Nach Updates suchen** gestartet werden.

Bei einer neueren Version zeigt DragonTools die Versionsnummer und die Release-Hinweise an. Erst nach Zustimmung wird die GitHub-Downloadseite im Browser geöffnet. Es werden weder Dateien automatisch ersetzt noch Updates ohne Nachfrage installiert.

Ist GitHub nicht erreichbar oder liefert die Releasequelle keine gültige Version, bleibt die automatische Prüfung still. Die private Quellcode-Historie und persönliche Zugangsdaten werden dafür weder benötigt noch übertragen. Ein ausgetauschtes Paket mit derselben Versionsnummer wird nicht als neueres Update erkannt; dafür ist eine höhere Versionsnummer erforderlich.

## Projekt aktualisieren

Lokale Änderungen sollten vor dem Aktualisieren gespeichert oder committed werden. Danach kann der aktuelle Stand abgerufen werden:

```powershell
git pull
```

Eigene Änderungen werden so gespeichert und hochgeladen:

```powershell
git add -A
git commit -m "Änderungen kurz beschreiben"
git push
```

## Hinweise

- API-Schlüssel, Passwörter, lokale Einstellungen und persönliche Daten gehören nicht in Git.
- Die Drittanbieterprogramme werden durch `.gitignore` ausgeschlossen.
- Große fertige Programmpakete gehören später in einen GitHub Release und nicht direkt in die Git-Historie.
- Medien dürfen nur im Rahmen der jeweils geltenden Rechte und Gesetze verarbeitet werden.
