# DragonTools HDRTVDM ComfyUI bridge

Optionaler ComfyUI-Node-Pack für das **extern installierte offizielle HDRTVDM-Repository**. HDRTVDM-Quellcode und Modellgewichte werden von DragonTools nicht weiterverteilt.

Erwartete externe Assets:

- Repository: `https://github.com/AndreGuo/HDRTVDM`
- empfohlen: `method/params_3DM.pth`
- Fallback: `method/params.pth`

Diesen Ordner nach `ComfyUI/custom_nodes/DragonTools_HDRTVDM` kopieren, `requirements.txt` mit ComfyUIs Python installieren und ComfyUI neu starten.

## Produktiver DragonTools-Pfad

`DragonHDRTVDMModelLoader` lädt das externe Modell. `DragonHDRTVDMVideoConvert` verarbeitet anschließend eine komplette CFR-Videodatei streamend:

```text
FFmpeg SDR decode/filter → RGB24 pipe → HDRTVDM → RGB48 PQ/BT.2020 pipe → FFmpeg 10-bit HDR encode
```

Dadurch werden keine kompletten Frame-Sequenzen auf Platte geschrieben. Crop/Scale/Burn-in werden vor der AI-Verarbeitung über die von DragonTools gelieferten FFmpeg-Argumente angewendet; der resultierende Videostream wird anschließend von DragonTools mit den vorhandenen Audio-/Untertitelregeln gemuxt.

Der Node erzeugt während der Verarbeitung ein JSON-Manifest mit Framezahl, Status, Laufzeit und – bei CUDA – Peak-VRAM. ComfyUI-Abbruch wird zwischen Frames/Batches geprüft und beendet die gestarteten FFmpeg-Prozesse.

Die älteren Nodes `DragonFrameSequenceLoader`, `DragonHDRTVDMConvert` und `DragonHDR16TiffWriter` bleiben für Debug-/Entwicklungstests erhalten, werden vom eingebauten Voll-Datei-Workflow aber nicht benötigt.

Aktuelle Grenze: eindeutig erkannte CFR-Quelle mit bekannter Framerate. VFR wird von DragonTools fail-closed abgelehnt.
