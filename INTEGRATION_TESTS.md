# Dragon Tools – Integrationstests

Dieses Dokument beschreibt die realen Qt- sowie DV/HDR-Integrationstests des Quellprojekts. Die normale Anwendung benötigt **keine laufende Testüberwachung**. Die Tests dienen der Entwicklung und Release-Prüfung.

## Standardtests

```powershell
python -m pip install -r requirements-test.txt
$env:QT_QPA_PLATFORM = "offscreen"
$env:DRAGONTOOLS_REQUIRE_QT_TESTS = "1"
python -m pytest -m "not dv_hdr_integration"
```

`DRAGONTOOLS_REQUIRE_QT_TESTS=1` sorgt dafür, dass fehlendes PyQt6/pytest-qt nicht still als Skip behandelt wird. Der GitHub-Workflow führt diese Suite bei Push/Pull-Request auf Windows und Linux aus. Zusätzlich prüft Ruff Syntax- und Undefined-Name-Fehler (`E9,F821,F822,F823`).

## Reale Dolby-Vision-/HDR10+-Roundtrips

Die Tests in `dragontools/tests/test_real_dv_hdr_integration.py` erzeugen kleine synthetische HEVC-Teststreams. Es werden keine urheberrechtlich geschützten Testvideos benötigt. Geprüft werden:

- Dolby Vision: RPU erzeugen → injizieren → extrahieren → MP4Box muxen → erneut extrahieren und Hash vergleichen.
- HDR10+: Metadaten injizieren → extrahieren/verifizieren.
- Dragon-Tools-Pfade über `DVRpuService`, `DVMP4BoxMuxer`, `HDR10PlusBitstreamService` und den zentralen ToolRunner.

Benötigt werden `ffmpeg`, `ffprobe`, `dovi_tool`, `hdr10plus_tool` und `MP4Box`. Die Werkzeuge können über PATH, die bekannten Dragon-Tools-Werkzeugordner oder explizit über folgende Variablen bereitgestellt werden:

```text
DRAGONTOOLS_FFMPEG
DRAGONTOOLS_FFPROBE
DRAGONTOOLS_DOVI_TOOL
DRAGONTOOLS_HDR10PLUS_TOOL
DRAGONTOOLS_MP4BOX
```

Strikter lokaler Lauf unter Windows:

```powershell
$env:DRAGONTOOLS_REQUIRE_QT_TESTS = "1"
$env:DRAGONTOOLS_REQUIRE_DV_HDR_INTEGRATION = "1"
python -m pytest -m dv_hdr_integration
```

Im GitHub-Workflow wird dieser reale Medienlauf bewusst nur manuell (`workflow_dispatch`) auf dem dafür vorgesehenen self-hosted Windows-Runner mit Label `dragontools-media` gestartet. Das ist eine Release-/Entwicklungsprüfung, keine dauerhafte Überwachung des normalen Konverterbetriebs.

## Move-/Jellyfin-Härtung (Patch AD)

### Transienter Move-Source-Fall

Bei einem Zwischenmove darf ein kurzzeitig nicht erreichbarer Output nicht mehr aus dem Session-State verschwinden. Im Log muss stattdessen eine Warnung mit `bleibt für späteres Verschieben vorgemerkt` erscheinen. Der spätere/finale Move prüft die Quelle erneut.

Für die Diagnose enthält der Warnblock Quelle, echten Dateisystemfehler, Elternordnerstatus, Größe, geplantes Ziel und bekannte Companion-Dateien. Ein erneutes Auftreten sollte daher mit dem vollständigen Dragon-Tools-Log dokumentiert werden; ein manueller Workaround ist für die Ursachenanalyse nicht mehr nötig.

### Zwei direkte Jellyfin-Fallbacks

Wenn zwei Episoden fast gleichzeitig einen Targeted-Refresh-Fehler auslösen, darf nur **ein** `/Library/Refresh` gestartet werden. Der zweite Worker muss entweder den auf Jellyfin bereits laufenden Scan erkennen oder den unmittelbar zuvor von Dragon Tools gestarteten Scan wiederverwenden.

Erwartetes Log-Muster:

```text
⚠️ Gezielte Jellyfin-Aktualisierung fehlgeschlagen; vollständiger Scan gestartet: ...
⚠️ Gezielte Jellyfin-Aktualisierung fehlgeschlagen; bereits laufender vollständiger Scan wird weiterverwendet: ...
```

Ein Fallback ist absichtlich eine Warnung; ein `✅` ist nur für den erfolgreichen Targeted-Refresh bzw. einen explizit konfigurierten Full-Refresh vorgesehen.

## ComfyUI + HDRTVDM Vorbereitung (Patch AI; durch Patch AL erweitert)

Patch AI führte API-, Modell-, Node- und Workflow-Readiness zunächst fail-closed ein. Der damalige TIFF-/Vorbereitungsstand ist historisch und wird ab Patch AL durch den unten beschriebenen ausführbaren Voll-Datei-Streaming-Worker ersetzt. Eine echte AI-HDR-Abnahme benötigt weiterhin Windows + NVIDIA-GPU + lokale ComfyUI/HDRTVDM-Installation und ist daher nicht Bestandteil des normalen CI-Laufs.

## ComfyUI + HDRTVDM Voll-Datei-Abnahme (Patch AL)

Ab Patch AL ist der ComfyUI/HDRTVDM-Pfad nicht mehr nur Readiness-Vorbereitung, sondern als Voll-Datei-Worker ausführbar. Die Bridge aus `extras/comfyui/DragonTools_HDRTVDM` muss deshalb auf der Testinstallation **aktualisiert** und ComfyUI neu gestartet werden.

Automatisiert geprüft werden unter anderem:

- CFR-Quelle wird bei vollständiger Readiness als angewendetes ComfyUI-Backend gewählt,
- VFR/unklare Framerate startet kein AI-HDR und fällt mit klarer Warnung auf normalen SDR-Encode zurück,
- Voll-Datei-Workflow enthält `DragonHDRTVDMVideoConvert`,
- Pfade mit Leerzeichen/Umlauten und JSON-Argumentlisten werden unverändert übertragen,
- Job-Abbruch adressiert genau die von DragonTools erzeugte `prompt_id`,
- Standardpipeline übernimmt danach Video per `-c:v copy` und wendet bestehende Audio-/Untertitelregeln an,
- fehlende Colorimetry bzw. ComfyUI-Readiness wird klar geloggt und führt kontrolliert zum normalen SDR-Encode,
- Fehler eines bereits gestarteten ComfyUI-HDR-Jobs bleiben harte Auftragsfehler ohne automatischen SDR-Neustart,
- optionaler CPU/PyTorch-Smoke führt mit realem FFmpeg einen kompletten kurzen Stream durch und prüft PQ/BT.2020-Signalisierung.

Für die reale RTX-4080-Abnahme eine kurze vollständige SDR-BT.709-CFR-Datei durch denselben normalen Workflow verarbeiten. Kein separater Testmodus ist nötig. Prüfen/protokollieren:

- ComfyUI-/PyTorch-/CUDA-Version,
- Checkpoint `params_3DM.pth`,
- Input-/Output-Framezahl,
- Peak-VRAM und Laufzeit,
- 10-Bit-Ausgabe, BT.2020, SMPTE ST2084,
- keine temporäre Vollbildsequenz auf Platte,
- Audio-/Untertitelregeln und Burn-in,
- Benutzerabbruch/Cleanup,
- visuelle temporale Stabilität.

Der eingebaute Workflow nutzt zunächst Batchgröße 1 / FP16. Größere Batches oder 2160p-Tiling werden erst nach der realen 16-GB-RTX-4080-Messung festgelegt.

## SDR→HDR Einstellungen / ComfyUI-Autostart / Override (Patch AP)

Zusätzlich zu den Patch-AL-Voll-Datei-Tests wird automatisiert geprüft:

- `sdr_hdr` wird als echtes Tri-State-Per-Datei-Override normalisiert,
- `Aktiv` kann global deaktiviertes SDR→HDR nur für die gewählte Quelle einschalten,
- `Deaktivieren` kann eine einzelne Quelle trotz global aktivem SDR→HDR ausnehmen,
- ein explizit konfigurierter ComfyUI-Launcher hat Vorrang,
- bei einer erkannten Portable-Installation mit `ComfyUI/main.py` wird `run_nvidia_gpu.bat` gefunden,
- `main.py` allein wird nicht fälschlich als vollständiger Launcher gestartet,
- nach Autostart wird die API innerhalb der konfigurierten Frist wiederholt geprüft,
- bei global deaktiviertem SDR→HDR, aber vorhandenem per-Datei-Override `Aktiv`, wird die ComfyUI-Runtime trotzdem vorbereitet,
- der direkte Hauptmenüeintrag `🌈 SDR → HDR / ComfyUI` bleibt vorhanden.
- der direkte Hauptmenüeintrag `✨ Dragon HDR10+ Generator` öffnet ausschließlich den Generator-Einstellungsbereich; der Tool-Pfad bleibt unter `Werkzeugpfade` zentral verwaltet.

Für einen realen Portable-Test ComfyUI vor dem DragonTools-Start schließen, Auto-Start aktivieren, `run_nvidia_gpu.bat` konfigurieren und einen geeigneten BT.709-CFR-Auftrag mit SDR→HDR starten. Im Log muss zuerst der Launcher-Start und danach die erfolgreiche API-Erkennung erscheinen; ein bereits laufendes ComfyUI darf nicht erneut gestartet werden.

## Dragon HDR10+ Generator 0.2.0 / Patch AQ

Der eigenständige Generator gehört fachlich zum DragonTools-Projekt, wird aber separat als CLI/EXE gebaut. Die automatisierten Foundation-Tests liegen unter `dragon_hdr10plus_generator/tests/` und prüfen Probe-Vertrag, PQ/BT.2020-Grenzen, Szenenerkennung und ST-2094-40-Profile-A-JSON.

Direkter Test des Generator-Unterprojekts:

```powershell
python -m pytest dragon_hdr10plus_generator/tests -q
```

Manueller Realtest mit einer kurzen PQ/BT.2020-Datei:

```powershell
HDRPlusGenerator.exe analyze `
  --input "D:\Test\hdr10_test.mkv" `
  --output "D:\Test\hdr10_test_hdr10plus.json"
```

Zu prüfen sind:

- stdout enthält genau ein JSON-Ergebnisobjekt mit `success=true`, Frame-/Szenenzahl und `profile=A`,
- die Zieldatei enthält `JSONInfo.HDR10plusProfile = A`, `SceneInfo` und `SceneInfoSummary`,
- `SequenceFrameIndex` ist lückenlos und stimmt mit der dekodierten Framezahl überein,
- eine SDR-/BT.709-Quelle wird mit `SOURCE_NOT_PQ` abgewiesen,
- eine PQ-Quelle mit explizit anderem Primärfarbraum wird fail-closed abgewiesen,
- `--analysis-width` verändert nur die räumliche Analyseoberfläche; zeitlich wird weiterhin jeder Frame gescannt.

DragonTools-Integration zusätzlich mit zwei Pfaden prüfen:

1. **SDR→HDR→HDR10+:** geeignete SDR-BT.709-CFR-Datei mit ComfyUI/HDRTVDM verarbeiten, HDR10+-Generator global oder per Datei aktivieren und danach am finalen PQ/BT.2020-HEVC-Output HDR10+ nachweisen.
2. **HDR10 ohne HDR10+ / Strip-Only:** vorhandene PQ/BT.2020-HEVC-Datei ohne HDR10+ mit `HDR10+ erzeugen = Aktiv` remuxen. Das Video darf nicht neu encodiert werden; Generatoranalyse, `hdr10plus_tool`-Injection, finaler Mux und Endverifikation müssen durchlaufen.

Die Generator-JSON allein ist noch keine finale Medienausgabe. Für den DragonTools-End-to-End-Test gehört immer die anschließende Injection mit `hdr10plus_tool`, der finale MKV/MP4-Mux und die semantische Nachprüfung dazu.


## Help-Struktur und direkter HDR10+-Generator-Zugriff (Patch AU)

Statisch und im GUI-Smoketest prüfen:

- `Einstellungen → 🌈 SDR → HDR / ComfyUI` öffnet nur `sdr_hdr`,
- `Einstellungen → ✨ Dragon HDR10+ Generator` öffnet nur `hdr10plus_generator`,
- die Help-Datei enthält eigenständige Kapitel `SDR → HDR mit ComfyUI / HDRTVDM`, `Dragon HDR10+ Generator` und `HDR-Erkennung, Datei-Overrides & Strip-Only`,
- das Inhaltsverzeichnis verlinkt alle drei Kapitel und die nachfolgenden Kapitelnummern bleiben fortlaufend,
- Projektstatistik/Über-Dialog zählen DragonTools und den eigenständigen Generator gemeinsam, ohne `build`/`dist` zu zählen.
