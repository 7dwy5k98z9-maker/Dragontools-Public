# DragonTools V9.8.2

DragonTools ist eine Windows-Anwendung zur Analyse, Konvertierung und Verwaltung von Video-, Audio- und Untertiteldateien. Das Projekt bündelt die benötigten Drittanbieterprogramme nicht im Git-Repository. Sie müssen separat von den jeweiligen Projektseiten heruntergeladen werden.

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

## Sichere Timestamp-Reparatur

Bei einer unplausiblen Ausgabelaufzeit versucht DragonTools zuerst einen verlustfreien Container-Remux. Für eindeutig erkannte MKV-Timestampfehler folgt eine Reparatur mit dem FFmpeg-`setts`-Bitstreamfilter; steht dieser Filter nicht zur Verfügung oder scheitert der Versuch, kann DragonTools auf einen ebenfalls verlustfreien `+genpts`-Remux ausweichen.

Jeder Reparaturkandidat wird vor dem Ersetzen erneut auf Laufzeit, Lesbarkeit, Video-, Audio- und Untertitelspuren sowie Attachments geprüft. FFprobe und MediaInfo dienen dabei als voneinander unabhängige Gegenprüfung. Ein Werkzeugfehler, ein Streamverlust oder widersprüchliche Ergebnisse verwerfen den Kandidaten. Die Quelldatei wird in diesem Fall weder ersetzt noch anschließend verschoben.

## Jellyfin-Mediathek importieren

DragonTools liest aktuelle Jellyfin-Datenbanken mit `BaseItems` und `MediaStreamInfos` ausschließlich als Quelle und erzeugt daraus eine eigene funktionale SQLite-Mediathek. Übernommen werden Filme, Serien, Staffeln, vorhandene Episoden und sonstige Videodateien einschließlich Pfad, Dateigröße, Laufzeit, Container, Auflösung, Video- und Gesamtbitrate, Video-Codec, Profil, Pixelformat, Bittiefe, Bildrate, Bildratenmodus, Frameanzahl, Farbraum, Transferfunktion, Farbprimärwerte, HDR/SDR, HDR10+ und Dolby Vision. Für Audio und Untertitel werden unter anderem Sprache, Codec, Kanäle, Kanalbelegung, Bitrate, Forced-Status, Streamdauer und vorhandene Eventanzahlen gespeichert. Seit Schema 6 werden zusätzlich Originaltitel, Provider-IDs (z. B. TMDB/TheTVDB/IMDb), Genres, Tags, Studios, Collections/Filmreihen und schlanke Personenbeziehungen importiert. Personen werden einmalig gespeichert und nur mit den Medien verknüpft; Biografien, Bilder und andere Personendetails werden nicht übernommen. Playlists und reine Metadatenpfade bleiben ausgeschlossen.

Vor dem Import wird ein konsistenter Read-only-Snapshot einschließlich vorhandener WAL-Daten erzeugt und mit SQLite geprüft. Eine beschädigte oder unvollständig kopierte Jellyfin-Datenbank ersetzt die vorhandene DragonTools-Mediathek nicht. Gleichwertige Windows-/UNC-Pfade werden beim Neuaufbau nur einmal übernommen.

Neue und bestehende DragonTools-Mediatheken werden kompatibel auf Schema 6 gebracht. Zusätzlich zum vollständigen Speicherpfad-Scan gibt es einen leichten NFO-Scan, der ausschließlich bereits bekannte Mediathek-Pfade prüft und weder MediaInfo noch ffprobe noch einen rekursiven NAS-Scan startet. Er speichert NFO-Status, Pfad, Typ und Zeitstempel und unterscheidet unter anderem `present`, `missing`, `unreachable`, `invalid` und `unreadable`. Ein offline gegangener NAS-/Share-Pfad wird als `unreachable` behandelt; vorhandene NFO-Prüfdaten bleiben erhalten. Aus NFOs gelesene Titel, Staffel/Folge, Jahr und Provider-IDs werden getrennt gespeichert und mit der Mediathek verglichen, ohne deren Metadaten zu überschreiben. Die NFO-Erstellung selbst verwendet weiterhin die Online-Metadatenabfrage und nicht die Mediathek-DB. Die Suche unterstützt gespeicherte GUI-/SQL-Abfragen; eine eingebaute SQL-Hilfe zeigt Tabellen, Spalten, Datentypen und Beispielabfragen. Trefferlisten bleiben in der GUI aus Performancegründen begrenzt; der CSV-Export führt dieselbe zuletzt ausgeführte Suche ohne Anzeigelimit aus und exportiert alle passenden Datensätze. CSV-Exporte enthalten die erweiterten technischen und NFO-bezogenen Felder.

## Renamer: mehrstufige Suche und manuelle Korrektur

Der Film-/Serien-Renamer bewertet Metadatenkandidaten in konfigurierbaren Stufen. Standardmäßig wird zuerst die normale Mindestübereinstimmung von **60 %** verwendet. Gibt es dort keinen Kandidaten, folgen automatisch die Fallback-Stufen **45 %** und **30 %**. Alle drei Grenzwerte sind unter **Regeln → Renamer-Regeln** separat einstellbar. Treffer aus reduzierten Stufen werden sichtbar als Fallback markiert und bleiben prüfbedürftig; die letzte Stufe behandelt mehrere ähnlich schwache Kandidaten bewusst als mehrdeutig statt blind zu raten.

Wenn die automatische Typ-Erkennung falsch liegt, kann eine markierte Zeile gezielt **als Serie** oder **als Film** gesucht werden. Der Suchbegriff kann manuell geändert werden; außerdem lassen sich auf Wunsch alle Provider-Kandidaten ohne Fuzzy-Grenze anzeigen. Die Ergebnistabelle zeigt den tatsächlich gewählten Provider (**TMDB** oder **TheTVDB**) in einer eigenen Spalte.

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
