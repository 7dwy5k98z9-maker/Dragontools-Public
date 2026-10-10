# DragonTools V9.9.0

DragonTools ist eine Windows-Anwendung zur Analyse, Konvertierung und Verwaltung von Video-, Audio- und Untertiteldateien. Profile und Regeln helfen bei wiederkehrenden Aufgaben. Die Vorschau zeigt die geplanten Änderungen vor der Verarbeitung.

## Verarbeitung und Medienprüfung

- Video, Audio und Untertitel werden anhand der gewählten Profile verarbeitet. Dolby Vision, HDR10+ und SDR→HDR besitzen eigene Einstellungen und Ausgabeprüfungen.
- Bei einer unplausiblen MKV-Laufzeit folgt auf den normalen Remux die Prüfung einer Timestamp-Reparatur anhand der verlässlichen Bildrate und Dauer des Originals.
- Untertitel lassen sich als interne Spuren oder Begleitdateien verwalten. Sprache, Titel und Default-/Forced-Kennzeichnungen werden bei der Ausgabe berücksichtigt.

## Renamer und Metadaten

- Filme und Serien erhalten Namensvorschläge aus TMDB oder TheTVDB. Der Metadaten-Browser unterstützt die manuelle Zuordnung von Titeln und Episoden.
- **Staffel prüfen** und **Serie prüfen** vergleichen erkannte Einträge mit ihrer gewählten Metadatenquelle. Die Tabelle zeigt vollständige und fehlende Staffeln, Specials und fehlende Folgen; sie lässt sich als CSV exportieren.
- Das Umbenennen läuft im Hintergrund. Dabei bleiben die Dateiendung und vorhandene Zieldateien geschützt. Der Videoinhalt wird für diese Namensänderung nicht vollständig eingelesen.

## Bedienung und Vorschau

Neben den Pfeilen der Warteschlange stehen die Schnellschalter **HDR+ Generator**, **SDR → HDR** und **Watch-Folder**. Der Regel-/Profil-Simulator und die Medieninfo zeigen den geplanten **Ausgabecontainer** anhand derselben Dateieinstellungen wie die Verarbeitung.

## Warteschlange und Dateiverwaltung

- Entfernte, abgeschlossene oder abgebrochene Dateien lassen sich wieder hinzufügen, sobald kein aktiver Auftrag dieselbe Datei verarbeitet.
- Wiederherstellung, Verschieben und Nachbearbeitung berücksichtigen Video und Begleitdateien gemeinsam. Die Journal-Wiederherstellung läuft beim Programmstart im Hintergrund.
- Beim Ersetzen eines Films werden vorhandene Trickplay-Daten vor dem Video gesichert. Fehlende optionale Trickplay-Daten verhindern das Verschieben nicht.

## Dokumentation und Windows-Paket

Die Hilfe beschreibt die Bedienung des aktuellen Programms. Das V9-Changelog ist nach technischen Fachbereichen und Unterpunkten gegliedert. Die Historien älterer Hauptversionen bleiben separat verfügbar.

Externe Medienwerkzeuge sind nicht im Git-Repository oder im öffentlichen Windows-Paket enthalten. Sie werden anhand von `TOOLS_INSTALLIEREN.txt` separat eingerichtet. Die Anwendung besteht aus der EXE und dem zugehörigen Ordner `Daten`; beide bleiben beim Entpacken zusammen.

Das öffentliche Paket und seine SHA-256-Prüfsumme stehen im [Release v9.9.0](https://github.com/7dwy5k98z9-maker/Dragontools-Releases/releases/tag/v9.9.0). Persönliche Einstellungen und externe Medienwerkzeuge gehören nicht zur öffentlichen Ausgabe.

## Voraussetzungen

- Windows 10 oder neuer
- Python 3.12 oder 3.13

Die CI prüft beide Python-Versionen unter Linux und Windows. Zusätzlich wird unter Windows eine eingefrorene `DragonToolsSmoke.exe` mit PyInstaller gebaut und über `--smoke-test` gestartet; HDRTVDM besitzt einen verpflichtenden CPU-Lifecycle-Test. Reale DV/HDR-Roundtrips laufen auf dem gelabelten self-hosted Windows-Runner bei `v*`-Release-Tags oder manuell.
- Git zum Klonen und Aktualisieren des Projekts
- FFmpeg und FFprobe für die grundlegende Medienanalyse und -verarbeitung
- weitere Werkzeuge abhängig von den verwendeten Funktionen

Die Python-Abhängigkeiten sind nach Einsatzzweck aufgeteilt:

- `requirements-runtime.txt`: Anwendung starten
- `requirements-optional.txt`: optionale Bildanalyse; bindet die Whisper-Abhängigkeiten ein
- `requirements-whisper.txt`: freigegebene `faster-whisper`-/CTranslate2-Versionen für Spracherkennung und EXE-Build
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

Für optionale Bildanalyse und Audio-Spracherkennung bei einem Quellstart zusätzlich:

```powershell
python -m pip install -r requirements-optional.txt
```

Beim offiziellen Windows-Build prüft `build_v9.bat` vor PyInstaller `faster_whisper` und `ctranslate2` **inklusive der freigegebenen Versionsgrenzen**. Fehlen die Pakete oder liegen sie außerhalb der Constraints, installiert/repariert der Builder ausschließlich `requirements-whisper.txt` per `pip` und prüft danach erneut. NumPy/OpenCV werden dabei nicht verändert. PyInstaller sammelt beide Whisper-Pakete anschließend explizit ein. Die fertige EXE installiert beim Benutzer **keine Python-Pakete**. Nur das konfigurierte Whisper-Modell wird beim ersten tatsächlichen Einsatz heruntergeladen und danach aus dem lokalen Cache verwendet.

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

Der eigenständige **Dragon HDR10+ Generator** ist ein DragonTools-Unterprojekt mit eigener EXE/CLI und wird im Projektumfang mitgezählt. Er wird bewusst getrennt vom Hauptprogramm gebaut, damit die Frameanalyse unabhängig getestet und auch direkt aus PowerShell genutzt werden kann. ComfyUI bleibt als optionaler lokaler SDR→HDR-AI-Dienst integriert. Als konkretes Modellprofil ist **HDRTVDM/LSN mit `method/params_3DM.pth`** für BT.709 → PQ/BT.2020 hinterlegt. Der Voll-Datei-Worker streamt CFR-Video frameweise über ComfyUI/HDRTVDM direkt in einen 10-Bit-PQ/BT.2020-Videostream und übernimmt danach die vorhandenen Audio-/Untertitelregeln; es wird keine komplette TIFF-/PNG-Sequenz materialisiert. Die benötigten Bridge-Nodes liegen unter `extras/comfyui/DragonTools_HDRTVDM`, eine genaue Installationsanleitung in `COMFYUI_HDR_SETUP.md`. AI-HDR wird nur bei expliziter BT.709-Colorimetry und vollständiger Readiness gestartet. Fehlen Colorimetry, ComfyUI/API, Modell, Nodes, Workflow oder eine unterstützte Framerate, wird der Grund geloggt und die Datei bleibt im normalen SDR-Encode. Fehler eines bereits gestarteten HDRTVDM-Jobs bleiben dagegen harte Auftragsfehler. Der bestehende FFmpeg/libplacebo-Pfad bleibt davon unberührt.

### Dragon HDR10+ Generator direkt per PowerShell

Der Generator akzeptiert einen normalen Video-Container wie MKV/MP4, prüft PQ/ST2084 und BT.2020, scannt jeden Frame zeitlich vollständig und schreibt nur die dynamische HDR10+-JSON. Injection und Remux sind bei direkter CLI-Nutzung separate Schritte.

```powershell
HDRPlusGenerator.exe analyze `
  --input "D:\Videos\Film.mkv" `
  --output "D:\Videos\Film_hdr10plus.json"
```

Optional können die Analysebreite, Szenenerkennung und konkrete FFmpeg-Pfade gesetzt werden:

```powershell
HDRPlusGenerator.exe analyze `
  --input "D:\Videos\Film.mkv" `
  --output "D:\Videos\Film_hdr10plus.json" `
  --analysis-width 512 `
  --scene-threshold 0.32 `
  --min-scene-frames 6 `
  --ffmpeg "C:\Tools\ffmpeg.exe" `
  --ffprobe "C:\Tools\ffprobe.exe"
```

Defaults: `analysis-width=256`, `scene-threshold=0.32`, `min-scene-frames=6`. Höhere Analysebreiten erhöhen die räumliche Messgenauigkeit, nicht die zeitliche Abtastrate; jeder Frame wird weiterhin analysiert. Die Ausgabe ist ein klassisches ST-2094-40-**Profile-A**-JSON. Der Generator erfindet bewusst keine Profile-B-Knee-/Bezier-Kurven.

In DragonTools kann die Erzeugung global oder per Datei (`HDR10+ erzeugen`) aktiviert werden. Der Bereich ist direkt über **Einstellungen → ✨ Dragon HDR10+ Generator** erreichbar; der EXE-Pfad bleibt zentral unter **Einstellungen → Werkzeugpfade**. Bei SDR→HDR wird erst der fertige PQ/BT.2020-HEVC-Stream erzeugt und danach analysiert. Bei einem vorhandenen HDR10-HEVC ohne HDR10+ kann derselbe Ablauf auch nach Strip-Only/Remux erfolgen, ohne das Video erneut zu encodieren.

## Alternative Werkzeugkonfiguration

Beim Start aus dem Quellcode sucht DragonTools Werkzeuge in dieser Reihenfolge:

1. in den innerhalb von DragonTools konfigurierten Werkzeugordnern,
2. im Windows-`PATH`,
3. in den bekannten Unterordnern von `third_party`.

Die Pfade können in DragonTools unter den Einstellungen für externe Werkzeuge ausgewählt werden. Das ist praktisch, wenn die Programme bereits an anderer Stelle installiert sind. Der öffentliche `build_v9.bat` erstellt das Paket ohne diese Medienwerkzeuge. Für den Build müssen sie daher nicht in `third_party` liegen; ihre Pfade werden für die spätere Medienverarbeitung eingerichtet.

## Empfohlene Ordnerstruktur

```text
Dragontools/
├── DragonToolsV9.py
├── build_v9.bat
├── dragontools/
├── dragon_hdr10plus_generator/
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

## Renamer: Staffel und Serie auf Vollständigkeit prüfen

Neben **Metadaten-Browser** stehen **Staffel prüfen** und **Serie prüfen**. Die Auswahl enthält nur erkannte Serien mit einer konkreten TMDB-/TheTVDB-Serien-ID. Im Popup können eine oder mehrere Staffeln beziehungsweise Serien angehakt werden; **Prüfen** fragt ihre jeweilige Metadatenquelle frisch ab und vergleicht die konkreten Folgennummern mit den Zuordnungen der aktuellen Renamer-Liste.

Die Tabelle zeigt vollständige Staffeln, vollständig fehlende Staffeln und einzelne fehlende Folgen. Specials erscheinen als **Staffel 0**. Mehrfachfolgen pro Datei werden berücksichtigt; doppelte Dateien zählen nicht mehrfach. Unterschiedliche Provider und Serien-IDs bleiben getrennt. Alle bei der Quelle gelisteten Folgen werden berücksichtigt, einschließlich angekündigter Folgen. Nicht erkannte Dateien werden nicht einer Serie zugerechnet. Fehlende Zugangsdaten, Abfragefehler oder uneindeutige Providerdaten erscheinen als **Nicht prüfbar**.

**CSV exportieren** speichert die Tabelle mit UTF-8-BOM und Semikolon-Trennzeichen für Tabellenprogramme. Die Funktion vergleicht die Renamer-Liste, keine vorhandene Mediathek außerhalb dieser Liste, und benennt keine Dateien um.


## Renamer: mehrstufige Suche und manuelle Korrektur

Der Film-/Serien-Renamer bewertet Metadatenkandidaten in konfigurierbaren Stufen. Standardmäßig wird zuerst die normale Mindestübereinstimmung von **60 %** verwendet. Gibt es dort keinen Kandidaten, folgen automatisch die Fallback-Stufen **45 %** und **30 %**. Alle drei Grenzwerte sind unter **Regeln → Renamer-Regeln** separat einstellbar. Treffer aus reduzierten Stufen werden sichtbar als Fallback markiert und bleiben prüfbedürftig; die letzte Stufe behandelt mehrere ähnlich schwache Kandidaten bewusst als mehrdeutig statt blind zu raten.

Konfigurierbare Releasegruppen werden nur an den Namensrändern entfernt: `STARS.Show.S01E01`, `[STARS] Show S01E01` und `Show.S01E01-STARS` können bereinigt werden, während ein echter Titel wie `A STARS Story` unangetastet bleibt. Zusätzlich werden `E05S06`/`E05 S06` als Staffel 6, Episode 5 erkannt. `EP01`/`EPISODE01` ohne Staffel bleibt absichtlich unvollständig und löst vor der Providerabfrage eine Staffelabfrage aus; DragonTools rät keine Staffel.

Wenn die automatische Typ-Erkennung falsch liegt, kann eine markierte Zeile gezielt **als Serie** oder **als Film** gesucht werden. Der Suchbegriff kann manuell geändert werden; außerdem lassen sich auf Wunsch alle Provider-Kandidaten ohne Fuzzy-Grenze anzeigen. Die Ergebnistabelle zeigt den tatsächlich gewählten Provider (**TMDB** oder **TheTVDB**) in einer eigenen Spalte.

Wenn der Metadatencache für eine Serienfolge nur einen generischen Platzhalter wie **Folge 10** enthält, fragt der Renamer den Provider einmal frisch am Cache vorbei ab. Liefert TMDB oder TheTVDB inzwischen einen echten Episodentitel, wird der Cache erneuert und der neue Zielname verwendet. Bei TheTVDB kann eine vorhandene Episode ohne brauchbaren Titel zusätzlich über die konfigurierte Fallback-Sprache ergänzt werden. Für finale Rename-/NFO-Läufe kann eine frisch geladene Serien-/Episodenliste innerhalb desselben Batches wiederverwendet werden, sodass zwanzig Folgen nicht zwanzig identische Providerabfragen auslösen. Serienfolgen bleiben dabei im Standard **Serienname - SXXEXX - Episodenname.ext**.

## Regel-/Profil-Simulator

Der Regel-/Profil-Simulator zeigt neben Quelle, Pipeline, HDR/DV, Audio, Untertiteln und Ziel jetzt auch die **berechnete Endauflösung**. Dabei wird dieselbe Downscale-only-Logik wie im Encode-Pfad verwendet. Wenn Auto-Crop aktiv ist und der konkrete Crop erst während der Medienverarbeitung ermittelt werden kann, kennzeichnet der Simulator die Auflösung ausdrücklich als **vor Auto-Crop** statt eine nicht bekannte endgültige Crop-Auflösung zu erfinden.

## Windows-Anwendung bauen

Nach dem abschließenden Verschieben wird die Dateiliste nach Bestätigung des Batch-Abschlussdialogs zuverlässig geleert. Die bis zum Ende gehaltene Startsperre wird während der Abschlussbereinigung nicht als neuer Startvorgang gewertet. Tatsächlich laufende Verschiebevorgänge und doppelte Starts bleiben gesperrt; fehlgeschlagene Dateien können weiterhin gezielt erneut eingereiht werden.

Installiere zunächst die Build-Abhängigkeiten:

```powershell
python -m pip install -r requirements-build.txt
```

Kontrolliere anschließend, dass alle externen Werkzeuge unter `third_party` vorhanden sind, und starte den Build aus einer Eingabeaufforderung im Projektordner:

```cmd
build_v9.bat
```

Im privaten Entwicklungsrepository erstellt der Builder ohne Argumente (auch beim Doppelklick) einen privaten Build: Die PDF-Datenschutzprüfung wird ausgelassen, sodass ein fehlendes `pypdf` den Build nicht blockiert. `build_v9.bat --private` wählt denselben Modus ausdrücklich. Alle übrigen Release-, Konfigurations- und EXE-Smoke-Prüfungen bleiben aktiv.

In dieser öffentlichen Arbeitskopie erstellt `build_v9.bat` auch ohne Argumente einen öffentlichen Build mit PDF-Datenschutzprüfung. `build_v9.bat --public` wählt den Modus ausdrücklich. Fehlt `pypdf` oder ist seine Version ungeeignet, installiert/repariert der Builder `pypdf>=5,<7` und prüft danach erneut. Externe Medienwerkzeuge werden weder benötigt noch mitgeliefert. Der private Entwicklungsbuilder verwendet ohne Argumente weiterhin den privaten Modus; seine übrigen Release- und EXE-Prüfungen bleiben aktiv.

Der fertige Build wird unter `dist/DragonToolsV9.9.0/` abgelegt. `build/` und `dist/` sind lokale Ausgaben und werden nicht in Git gespeichert.

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
