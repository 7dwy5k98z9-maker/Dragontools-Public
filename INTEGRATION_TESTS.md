# DragonTools Integrationstests

Die normale Testsuite darf ohne reale Dolby-Vision-/HDR10+-Werkzeuge laufen. Zwei Marker trennen die externen Integrationspfade vom restlichen Testbestand.

## Media-Integration

`media_integration` erzeugt kleine lokale FFmpeg-Fixtures und prueft echte Container-/Streamvertraege. FFmpeg und FFprobe muessen im `PATH` liegen. Fehlen sie, werden diese Tests kontrolliert uebersprungen.

```bat
python -m pytest -m media_integration
```

## Dolby Vision / HDR10+

`dv_hdr_integration` prueft reale Extract-/Inject-/Mux-/Verify-Roundtrips. Die Tests erwarten FFmpeg/FFprobe sowie `dovi_tool`, `hdr10plus_tool` und MP4Box. Die Tools koennen ueber `PATH` oder explizit ueber folgende Variablen bereitgestellt werden:

```text
DRAGONTOOLS_FFMPEG
DRAGONTOOLS_FFPROBE
DRAGONTOOLS_DOVI_TOOL
DRAGONTOOLS_HDR10PLUS_TOOL
DRAGONTOOLS_MP4BOX
```

Lokaler strikter Lauf:

```bat
set DRAGONTOOLS_REQUIRE_DV_HDR_INTEGRATION=1
python -m pytest -m dv_hdr_integration
```

Mit `DRAGONTOOLS_REQUIRE_DV_HDR_INTEGRATION=1` wird eine fehlende Toolumgebung als Testfehler behandelt, statt die Tests still zu ueberspringen.

## Qt/GUI

CI und vollstaendige lokale Abnahmen koennen `DRAGONTOOLS_REQUIRE_QT_TESTS=1` setzen. Dann fuehren fehlendes PyQt6 oder pytest-qt zum Abbruch der Testsitzung.

```bat
set QT_QPA_PLATFORM=offscreen
set DRAGONTOOLS_REQUIRE_QT_TESTS=1
python -m pytest -m "not dv_hdr_integration"
```


## AV1 HDR10+ / Dolby Vision Profile 10

Die AV1-Metadatenpfade sind Beta und werden in der normalen Suite ueber Routing-, Capability- und Kommando-Vertraege getestet. Fuer reale Medienabnahmen sollten mindestens je eine AV1-DV10- und AV1-HDR10+-Datei durch den kompletten Encode-/Mux-/Verify-Pfad laufen.

- AV1 Dolby Vision: CPU/SVT-AV1, finales Dolby Vision Profile 10 muss nach dem Mux erneut erkannt werden.
- AV1 HDR10+: CPU/libaom-av1, finales HDR10+ muss nach dem Mux erneut erkannt werden. Der Pfad ist deutlich langsamer als SVT-AV1.
- Quelle mit DV + HDR10+ und beiden aktivierten Erhaltungsoptionen: AV1-DV10 hat Prioritaet, HDR10+ wird bewusst nicht erhalten und muss als INFO im Kurzlog erscheinen.
- Ein expliziter per-Datei-Override auf AV1-HDR10+ darf die automatische DV-Prioritaet bewusst uebersteuern.


## Verifizierter V9.7-Release-Stand (06.09.2026)

Der finale Source-Stand wurde nach dem Abschlussreview vollständig über alle 131 Testdateien in isolierten Batches ausgeführt. Diese Batch-Abnahme vermeidet testübergreifenden globalen Zustand und ist in der aktuellen Linux-Prüfungsumgebung reproduzierbarer als ein einzelner monolithischer pytest-Prozess. Die früheren 1,0-Sekunden-Inactivity-Tests wurden ausschließlich testseitig robuster gemacht, damit langsamer Interpreter-Start die Inaktivitätslogik nicht verfälscht. Die Produktiv-Timeouts wurden dabei nicht verändert.

```text
979 passed
15 skipped
0 failed
```

Von den 15 Skips betreffen in dieser Prüfungsumgebung 13 PyQt6/pytest-qt und 2 die nicht konfigurierte reale `dovi_tool`/`hdr10plus_tool`/MP4Box-Integration. Für die endgültige Windows-Buildfreigabe müssen deshalb zusätzlich der strikte Qt-Lauf und der strikte reale DV/HDR-Lauf in der Zielumgebung ausgeführt werden.

Empfohlene finale Windows-Abnahme:

```bat
set QT_QPA_PLATFORM=offscreen
set DRAGONTOOLS_REQUIRE_QT_TESTS=1
set DRAGONTOOLS_REQUIRE_DV_HDR_INTEGRATION=1
python -m pytest
```
