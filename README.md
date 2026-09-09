# DragonTools V9.8.1

DragonTools ist eine Windows-Anwendung zur Analyse, Konvertierung und Verwaltung von Video-, Audio- und Untertiteldateien. Das Projekt bündelt die benötigten Drittanbieterprogramme nicht im Git-Repository. Sie müssen separat von den jeweiligen Projektseiten heruntergeladen werden.

Veröffentlicht und gepflegt von **Dragon Developer**.

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
git clone https://github.com/7dwy5k98z9-maker/Dragontools-Public.git
cd Dragontools-Public
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

Nicht jede Funktion benötigt alle Werkzeuge. Fehlende optionale Werkzeuge deaktivieren oder begrenzen nur die zugehörigen Arbeitsabläufe. Das öffentliche Windows-Paket enthält diese Drittanbieterprogramme nicht. Installiere nur die Werkzeuge, die du für deine Arbeitsabläufe brauchst, und wähle ihre Pfade anschließend in DragonTools aus.

## Alternative Werkzeugkonfiguration

Beim Start aus dem Quellcode sucht DragonTools Werkzeuge in dieser Reihenfolge:

1. in den innerhalb von DragonTools konfigurierten Werkzeugordnern,
2. im Windows-`PATH`,
3. in den bekannten Unterordnern von `third_party`.

Die Pfade können in DragonTools unter den Einstellungen für externe Werkzeuge ausgewählt werden. Das ist praktisch, wenn die Programme bereits an anderer Stelle installiert sind. Alternativ können die Programme in der oben beschriebenen `third_party`-Struktur liegen.

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

## Windows-Anwendung bauen

Installiere zunächst die Build-Abhängigkeiten:

```powershell
python -m pip install -r requirements-build.txt
```

Kontrolliere anschließend, dass alle externen Werkzeuge unter `third_party` vorhanden sind, und starte den Build aus einer Eingabeaufforderung im Projektordner:

```cmd
build_v9.bat
```

Der fertige Build wird unter `dist/DragonToolsV9.8.1/` abgelegt. Der öffentliche Build enthält DragonTools und seine Python-Laufzeit, aber keine externen Medienprogramme. `build/` und `dist/` sind lokale Ausgaben und werden nicht in Git gespeichert.

## Fertige Windows-Version

Wer DragonTools nur verwenden möchte, kann unter [GitHub Releases](https://github.com/7dwy5k98z9-maker/Dragontools-Releases/releases) das Paket `DragonToolsV9.8.1-win64.zip` herunterladen. Python und Git werden dafür nicht benötigt.

Nach dem Entpacken wird `DragonToolsV9.8.1.exe` gestartet. Die Datei `TOOLS_INSTALLIEREN.txt` im Programmpaket erklärt, welche externen Werkzeuge benötigt werden und wo sie erhältlich sind. Vor dem Start sollte die veröffentlichte SHA-256-Prüfsumme kontrolliert werden.

## Programm-Updates über GitHub

DragonTools prüft nach dem Programmstart verzögert und ohne Blockierung der Oberfläche, ob im vorgesehenen öffentlichen Release-Repository eine neuere Version bereitsteht. Die Prüfung kann außerdem jederzeit über **Hilfe → Nach Updates suchen** gestartet werden.

Bei einer neueren Version zeigt DragonTools die Versionsnummer und die Release-Hinweise an. Erst nach Zustimmung wird die GitHub-Downloadseite im Browser geöffnet. Es werden weder Dateien automatisch ersetzt noch Updates ohne Nachfrage installiert.

Solange noch keine öffentliche Releasequelle vorhanden ist, bleibt die automatische Prüfung still. Die private Quellcode-Historie und persönliche Zugangsdaten werden für die Updateprüfung nicht benötigt und nicht übertragen.

Die fertigen Programmpakete werden künftig ausschließlich als [GitHub Releases](https://github.com/7dwy5k98z9-maker/Dragontools-Releases/releases) bereitgestellt. Der Quellcode und die Downloads bleiben dadurch sauber voneinander getrennt.

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

## Datenschutz der Veröffentlichung

Diese öffentliche Fassung besitzt eine eigene Git-Historie. Persönliche Namen, lokale Benutzerpfade, private Servernamen sowie Autoren- und Bearbeitungsmetadaten in Word- und PDF-Dateien wurden entfernt oder durch neutrale Angaben ersetzt. Vor jedem öffentlichen Push kann die Prüfung mit `python scripts/check_public_privacy.py` wiederholt werden.

## Lizenz

Für DragonTools wurde noch keine Open-Source-Lizenz erteilt. Eine Lizenz wird nicht automatisch erzeugt, weil MIT, GPL und andere Modelle sehr unterschiedliche Rechte und Pflichten festlegen. Bis zu einer bewussten Lizenzentscheidung bleibt der Quelltext urheberrechtlich geschützt; die öffentliche Sichtbarkeit allein erteilt keine zusätzliche Nutzungserlaubnis.
