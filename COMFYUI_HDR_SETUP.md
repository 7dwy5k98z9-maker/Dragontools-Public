# DragonTools – ComfyUI/HDRTVDM SDR→HDR Setup

## Empfohlenes Modell für RTX 4080 16 GB

DragonTools verwendet als erstes ausführbares ComfyUI-SDR→HDR-Profil **HDRTVDM / LSN**.

Empfohlener Checkpoint:

- Repository: `https://github.com/AndreGuo/HDRTVDM`
- Modell: `method/params_3DM.pth`
- Fallback/Alternative: `method/params.pth`
- Lizenz des HDRTVDM-Quellcodes: MPL-2.0

Das Profil ist für **SDR/BT.709 → HDR/WCG mit PQ/BT.2020** vorgesehen. `params_3DM.pth` ist der DragonTools-Default. Die tatsächliche Geschwindigkeit und Peak-VRAM-Auslastung werden erst auf der realen RTX 4080 gemessen; DragonTools behauptet dafür keine auf anderer Hardware extrapolierten Werte.

## 1. ComfyUI installieren

Empfohlen: offizielle **ComfyUI Windows Portable – NVIDIA**.

Beispiel:

```text
C:\AI\ComfyUI_windows_portable\
```

ComfyUI lokal starten. Standardadresse:

```text
http://127.0.0.1:8188
```

## 2. HDRTVDM installieren

Repository herunterladen/klonen, zum Beispiel:

```powershell
git clone https://github.com/AndreGuo/HDRTVDM.git C:\AI\HDRTVDM
```

Mindestens benötigt:

```text
C:\AI\HDRTVDM\method\network.py
C:\AI\HDRTVDM\method\params_3DM.pth
```

Wichtig: In DragonTools wird bei **HDRTVDM Repository** der Repository-Root eingetragen, also `C:\AI\HDRTVDM`, nicht `...\HDRTVDM\method`.

Bei einem expliziten Checkpoint wird die konkrete Datei angegeben, z. B.:

```text
C:\AI\HDRTVDM\method\params_3DM.pth
```

Bleibt das Checkpoint-Feld leer, sucht DragonTools zuerst `method\params_3DM.pth` und danach `method\params.pth`.

## 3. DragonTools-ComfyUI-Bridge installieren/aktualisieren

Aus **diesem Patch** den kompletten Ordner

```text
extras\comfyui\DragonTools_HDRTVDM
```

nach

```text
<ComfyUI>\ComfyUI\custom_nodes\DragonTools_HDRTVDM
```

kopieren. Wenn dort bereits eine ältere Patch-AI/AJ/AK-Version liegt, den Ordner **ersetzen/aktualisieren**. Der Voll-Datei-Worker benötigt den neuen Node `DragonHDRTVDMVideoConvert`.

Danach mit der Python-Umgebung von ComfyUI die Zusatzabhängigkeiten installieren. Bei Portable zum Beispiel:

```powershell
<ComfyUI>\python_embeded\python.exe -m pip install -r <ComfyUI>\ComfyUI\custom_nodes\DragonTools_HDRTVDM\requirements.txt
```

ComfyUI anschließend **neu starten**.

Für den produktiven Voll-Datei-Pfad prüft DragonTools über `/object_info` mindestens:

```text
DragonHDRTVDMModelLoader
DragonHDRTVDMVideoConvert
```

Die älteren Frame-/TIFF-Nodes bleiben nur als Debug-/Entwicklungswerkzeuge enthalten.

## 4. DragonTools-Einstellungen

Der Bereich ist direkt über **Einstellungen → 🌈 SDR → HDR / ComfyUI** erreichbar und bleibt zusätzlich im globalen Einstellungsfenster unter Video vorhanden.
Der HDR10+-Generator besitzt zusätzlich einen eigenen Direkteintrag **Einstellungen → ✨ Dragon HDR10+ Generator**; sein EXE-Pfad wird weiterhin zentral unter **Werkzeugpfade** gepflegt.

```text
SDR→HDR aktivieren:             ja/nein
Backend:                         ComfyUI / AI HDR
ComfyUI API:                     http://127.0.0.1:8188
ComfyUI automatisch starten:     ja
ComfyUI Startdatei:              C:\...\ComfyUI_windows_portable\run_nvidia_gpu.bat
Start-Wartezeit:                 30 s
AI-HDR-Modell:                   HDRTVDM LSN / params_3DM.pth
HDRTVDM Repository:              C:\AI\HDRTVDM
HDRTVDM Checkpoint:              leer oder konkrete params_3DM.pth
ComfyUI Workflow:                leer
```

Ist die ComfyUI-API beim Auftragsstart bereits erreichbar, startet DragonTools keinen zweiten Prozess. Ist sie nicht erreichbar und Auto-Start ist aktiviert, wird die konfigurierte `.bat`, `.cmd` oder `.exe` gestartet und die API bis zur eingestellten Frist wiederholt geprüft. Für die Portable-Version ist `run_nvidia_gpu.bat` die empfohlene Startdatei. Wenn kein expliziter Launcher eingetragen ist, versucht DragonTools bei einer erkannten Portable-Installation die üblichen `run_nvidia_gpu*.bat`-Launcher automatisch zu finden. `ComfyUI\main.py` allein ist bewusst kein Launcher, weil dafür Interpreter und Startparameter fehlen.

Bei leerem Workflow verwendet DragonTools den eingebauten HDRTVDM-Voll-Datei-Workflow. Ein eigenes API-JSON bleibt möglich, muss aber den DragonTools-Voll-Datei-Vertrag erfüllen (`{{INPUT_VIDEO}}`, `{{OUTPUT_VIDEO}}`, `{{MANIFEST_PATH}}` sowie die benötigten HDRTVDM-Nodes). Ein normaler ComfyUI-Frontend-/Testworkflow mit einem statischen `Load Image` wie `banner.png` ist dafür ungeeignet. Solche Workflows werden beim HDRTVDM-Profil abgewiesen und DragonTools fällt automatisch auf den eingebauten Voll-Datei-Workflow zurück, statt den Job mit `Media input missing` an ComfyUI zu senden.

### Per-Datei-Override

SDR→HDR muss nicht global für alle Quellen aktiviert sein. Im Datei-Override unter **HDR Policy (per Datei)** stehen für `🌈 SDR → HDR` drei Zustände bereit:

```text
Global-Standard   globale SDR→HDR-Einstellung übernehmen
Aktiv             SDR→HDR nur für diese Datei anfordern
Deaktivieren      diese Datei bewusst SDR lassen
```

Bei `Aktiv` werden weiterhin das global gewählte Backend, Repository, Checkpoint und die ComfyUI-Verbindung verwendet. Dadurch kann SDR→HDR global ausgeschaltet bleiben und nur für ausgewählte Queue-Dateien aktiviert werden.

### Welche Einstellungen beeinflussen die HDR-Qualität?

Der HDRTVDM-Pfad besitzt aktuell bewusst keinen künstlichen „HDR-Stärke“-Regler. Die relevanten Qualitäts-/Look-Faktoren sind:

- **Checkpoint:** größter modellseitiger Einfluss. Standard ist `params_3DM.pth`; `params.pth` und `params_DaVinci.pth` können explizit gewählt werden und erzeugen je nach Training einen anderen HDR-Look.
- **Encoderqualität:** CQ/CRF/QP, Preset und Codec des normalen DragonTools-Encoders bestimmen die Kompressionsqualität des erzeugten HDR-Videostreams und gelten auch für HDRTVDM. Diese Parameter werden daher nicht doppelt im ComfyUI-Bereich geführt.
- **FP16/FP32:** betrifft primär Rechenaufwand, Speicherverbrauch und numerische Präzision, nicht einen kreativen HDR-Look. Der eingebaute Workflow bleibt deshalb zunächst auf FP16.
- **Batchgröße:** beeinflusst Durchsatz und VRAM, nicht die gewünschte Bildcharakteristik. Standard bleibt 1.
- **BT.2020 / PQ / 10 Bit:** sind Teil des fest definierten HDR10-Ausgabevertrags und werden nicht als freie Qualitätsregler angeboten.
- **Kontrast-Recovery:** gehört ausschließlich zum alternativen FFmpeg/libplacebo-Backend und wirkt nicht auf HDRTVDM/ComfyUI.

Ein zusätzlicher pauschaler Brightness-/Contrast-/„HDR Strength“-Regler nach dem neuronalen Netz würde die trainierte Abbildung verändern und kann Highlights oder Gamut unkontrolliert verschieben. Er wird deshalb erst dann ergänzt, wenn dafür eine validierte HDR-Nachbearbeitung mit Mess-/Clipping-Grenzen definiert ist.

## 5. Aktueller ausführbarer Workflow

Für eine geeignete SDR-BT.709-CFR-Quelle läuft der normale DragonTools-Auftrag vollständig durch:

```text
Quelle
→ vorhandene DragonTools-Bildfilter (z. B. Crop / Scale / Burn-in)
→ FFmpeg decodiert SDR nach RGB-Frames
→ Frames werden per Pipe an den DragonTools-ComfyUI-Node geliefert
→ HDRTVDM verarbeitet Frame/Batch auf der GPU
→ PQ/BT.2020-RGB wird direkt per Pipe an FFmpeg zurückgegeben
→ vorhandener DragonTools-Encoder erzeugt 10-Bit HDR10/PQ
→ Original-Audio/Untertitel werden nach den bestehenden Regeln gemuxt
→ normale DragonTools-Outputvalidierung
```

Es wird **keine komplette PNG-/TIFF-Sequenz auf Platte geschrieben**. Dadurch bleibt der Voll-Datei-Betrieb auch bei langen Filmen handhabbar.

Der eingebaute Workflow startet bewusst mit:

```text
batch_size = 1
precision = fp16
GPU = cuda
```

Das ist der sichere Startpunkt für die RTX 4080 16 GB. Erst die reale Hardwaremessung entscheidet, ob eine größere Batchgröße sinnvoll ist.

## 6. Preflight-Fallback und Laufzeitfehler

Wenn ComfyUI als Backend ausgewählt und SDR→HDR aktiviert wurde, startet DragonTools AI-HDR nur bei **eindeutig erkannter BT.709-Colorimetry** und vollständiger ComfyUI/HDRTVDM-Readiness.

Fehlen beispielsweise Colorimetry, API, Repository, Checkpoint, benötigte Custom Nodes oder ein gültiger Workflow, wird der Grund klar geloggt und die Datei normal als SDR weiterverarbeitet. DragonTools kennzeichnet dabei ausdrücklich, dass **keine HDR-Ausgabe erzeugt wird**.

Erst wenn ein HDRTVDM-Job tatsächlich gestartet wurde und während der Ausführung scheitert, bleibt der Pfad fail-closed: Der Auftrag bricht ab und wird nicht automatisch als SDR neu gestartet.

Der FFmpeg/libplacebo-Backendpfad bleibt davon unabhängig und unverändert nutzbar.

## 7. Timing-Grenze

Der erste ausführbare HDRTVDM-Worker akzeptiert aktuell nur eindeutig erkannte **CFR-Quellen** mit bekannter Framerate. Bei VFR bzw. unbekannter Framerate wird AI-HDR nicht gestartet; DragonTools protokolliert den Grund und verarbeitet die Datei normal als SDR weiter.

Der Grund ist die framegenaue Zuordnung zwischen Decoder → AI → finalem Encoder. Eine spätere VFR-Unterstützung benötigt einen Timestamp-Vertrag statt einer festen CFR-Framerate und wird nicht durch implizite Frame-Duplikation/-Drops vorgetäuscht.

## 8. Abbruch und temporäre Dateien

DragonTools merkt sich die von ihm gestartete ComfyUI-`prompt_id`. Beim Benutzerabbruch wird gezielt dieser Job abgebrochen. Der Custom Node prüft ComfyUIs Interruptzustand zwischen Frames/Batches und beendet seine FFmpeg-Unterprozesse.

Das video-only HDR-Zwischenergebnis und Manifest liegen in einem temporären DragonTools-Ordner neben dem Ziel und werden nach erfolgreichem Mux oder beim Verlassen des Jobs entfernt.

## 9. Reale RTX-4080-Abnahme

Für den ersten echten Lauf zunächst eine kurze **vollständige Testdatei** verwenden. Es gibt keinen separaten Testmodus; kurze und lange Dateien laufen über denselben Codepfad.

Zu protokollieren:

```text
Quellauflösung / FPS / CFR
Checkpoint
Ausgabecodec / Encoder
verarbeitete Frames
Gesamtzeit
Frames pro Sekunde
Peak-VRAM
Output-Pixelformat
BT.2020 Primaries
SMPTE ST2084 / PQ
Audio-/Untertitel-Mux
visuelle Stabilität / Flicker
```

DragonTools schreibt die vom Node gemessene Peak-CUDA-Speichernutzung und Framezahl ins Manifest und protokolliert sie nach erfolgreichem Job.

### Gemessener Praxiswert

Ein realer 1080p-Test mit `params_3DM.pth` auf einer NVIDIA RTX 4080 SUPER 16 GB lag bei ungefähr **4:1 Konvertierungsdauer zu Filmdauer** (z. B. rund 70 Minuten Rechenzeit für 17:49 Minuten Video). Dabei lagen die beobachtete GPU-Auslastung typischerweise bei etwa 85–90 % und der VRAM-Bedarf bei ungefähr 4,3–4,4 GB. Diese Werte sind ein Praxisbeispiel, keine feste Leistungszusage; Auflösung, Quelle, Modell, Batchgröße und Hardware können deutlich abweichen.

## 10. HDR10+

ComfyUI/HDRTVDM erzeugt **das HDR-Bild**, nicht die HDR10+-Metadaten.

Die Zielarchitektur bleibt:

```text
SDR
→ ComfyUI + HDRTVDM
→ finaler HDR10/PQ-Bildstrom
→ Dragon HDR10+ Generator
→ ST-2094-40 JSON
→ hdr10plus_tool
→ HDR10+
```

Der eigenständige **Dragon HDR10+ Generator 0.2.0** ist weiterhin als eigene EXE/CLI getrennt, gehört aber zum DragonTools-Projekt. Er scannt den finalen PQ/BT.2020-Stream framegenau, erkennt Szenen und schreibt ein `hdr10plus_tool`-kompatibles ST-2094-40-**Profile-A**-JSON. DragonTools übernimmt danach Injection, Remux und Endverifikation.

Ist unter **Einstellungen → ✨ Dragon HDR10+ Generator** die Erzeugung aktiviert – oder wurde sie für eine einzelne Datei per Override `HDR10+ erzeugen = Aktiv` eingeschaltet – läuft die Kette nach erfolgreichem SDR→HDR automatisch weiter. Analysiert wird ausdrücklich **der bereits erzeugte HDR-Output**, nicht die ursprüngliche SDR-Quelle. Für geeignete vorhandene HDR10-HEVC-Dateien ohne HDR10+ kann derselbe Generator auch nach Strip-Only/Remux verwendet werden, ohne das Video erneut zu encodieren.

Die Generator-CLI kann unabhängig von DragonTools aus PowerShell genutzt werden:

```powershell
HDRPlusGenerator.exe analyze `
  --input "D:\Videos\Film.mkv" `
  --output "D:\Videos\Film_hdr10plus.json"
```

Standardwerte: `analysis-width=256`, `scene-threshold=0.32`, `min-scene-frames=6`. Mit `--analysis-width 512` oder `1024` lässt sich die räumliche Analyseauflösung erhöhen; zeitlich wird unabhängig davon weiterhin jeder Frame analysiert.

## Windows: Manifest-Zugriffsfehler bei laufender DragonTools-Konvertierung

Falls eine ältere Version des Custom Nodes mit

```text
[WinError 5] Zugriff verweigert: hdrtvdm_manifest.json.tmp -> hdrtvdm_manifest.json
```

abbricht, ist noch die alte Manifest-Schreiblogik installiert. Aktualisiere den kompletten Ordner

```text
extras/comfyui/DragonTools_HDRTVDM/
```

nach

```text
ComfyUI/custom_nodes/DragonTools_HDRTVDM/
```

und starte ComfyUI vollständig neu. Die aktuelle Version verwendet für die ephemere Progress-Datei keinen Windows-anfälligen Rename/Replace mehr und reduziert die Schreibfrequenz zusätzlich auf höchstens etwa zwei Manifest-Updates pro Sekunde.
