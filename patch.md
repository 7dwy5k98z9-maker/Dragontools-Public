# DragonTools V9.8.2 – Technical Review Patch v4

Stand: 2026-09-13

Dieses Overlay ist **kumulativ**. Es enthält die Technical-Review-Patches v1–v3 und zusätzlich den abschließenden v4-Strukturblock für die nach v3 noch auffälligen Architektur-Hotspots.

## v4 – abgeschlossene Refactoring-Blöcke

### Release-Validierung

`core/release_validation.py` wurde von **318 auf 63 Zeilen** reduziert. Die Fassade routet nur noch den Validierungsmodus und formatiert Ergebnisse.

Ausgelagert wurden:

- `release_validation_source.py` – Source-/Repository-Vertrag
- `release_validation_build.py` – Build-/Packaging-Prüfungen
- `release_validation_app.py` – App-/Runtime-Prüfungen

Die bestehenden privaten `_check_*_environment`-Importpfade bleiben aus Kompatibilitätsgründen als Re-Exports erhalten.

### Timestamp-Candidate-Service

`worker/duration_timestamp_candidate_service.py` wurde von **259 auf 137 Zeilen** reduziert; `attempt()` umfasst noch **41 Zeilen**.

Ausgelagert wurden:

- `duration_timestamp_candidate_validation.py` – Kandidatenprüfung
- `duration_timestamp_candidate_archive.py` – Reject-/Archivierungslogik

Ein während der Regressionstests gefundener Kompatibilitätsfall wurde ebenfalls behoben: Minimal-Runtimes ohne `replace_file()` führen bei der Reject-Bereinigung nicht mehr zu `AttributeError`, sondern fallen sicher auf Cleanup zurück.

### Strip-Only-Pipeline

`worker/converter_strip.py` wurde von **207 auf 56 Zeilen** reduziert; `strip_only()` umfasst noch **31 Zeilen**.

Getrennte Bausteine:

- `converter_strip_runtime.py`
- `converter_strip_audio.py`
- `converter_strip_subtitles.py`
- `converter_strip_sidecars.py`

Die bisherige Monkeypatch-/Regel-Kompatibilität bleibt erhalten; Subtitle-Regeln werden zur Laufzeit über das Regelmodul aufgelöst und nicht früh gebunden.

### Audio-/Video-Time-Mapping

`core/audio_video_time_mapping.py` wurde von **206 auf 97 Zeilen** reduziert; `classify_time_mapping()` umfasst noch **54 Zeilen**.

Ausgelagert wurden:

- `audio_video_time_mapping_fit.py` – Modell-/Fit-Berechnung
- `audio_video_time_mapping_edges.py` – Rand-/Segmentbewertung

Damit sind Fit, Edge-Analyse und Klassifikation getrennte Verantwortlichkeiten.

### Quality-Worker

Die beiden Qt-Worker sind jetzt Lifecycle-Adapter statt Tool-/Metrik-Gottklassen:

- `quality_compare_thread.py`: **331 → 115 Zeilen**
- `quality_test_thread.py`: **335 → 97 Zeilen**

Neue Qt-freie Services:

- `quality_process_runner.py` – Toolausführung
- `quality_metrics_service.py` – SSIM-/VMAF-Ermittlung und Parsing
- `quality_compare_service.py` – Datei-zu-Datei-Vergleich
- `quality_test_service.py` – Encode-/Probe-/Metrik-Testablauf

Zusätzlich wurden direkte Service-Regressionstests ergänzt, damit die Fachlogik unabhängig von Qt getestet wird.

### ConverterStreamArgs

`worker/converter_stream_args.py` wurde von **384 auf 106 Zeilen** reduziert.

Ausgelagert wurden:

- `converter_audio_args.py`
- `converter_subtitle_args.py`
- `converter_video_filter_args.py`

Die bestehende Burn-in-Testbarkeit bleibt erhalten: `tempfile` und `run_tool` bleiben an der bisherigen Fassade patchbar.

### DVFinalMuxService

`worker/dv_final_mux_service.py` wurde von **343 auf 43 Zeilen** reduziert und ist jetzt eine reine Service-Fassade.

Getrennt wurden:

- `dv_track_preparation_service.py` – Audio-/Subtitle-Track-Vorbereitung
- `dv_final_output_service.py` – finaler Container-Mux
- `dv_final_metadata_verifier.py` – finale Metadaten-/Mux-Verifikation

### ConversionProgressPresenter

`gui/conversion_progress_presenter.py` wurde von **341 auf 102 Zeilen** reduziert.

Ausgelagert wurden:

- `conversion_progress_focus.py` – Auswahl/Fokus auf aktuelle Datei
- `conversion_progress_display.py` – Fortschritts-/ETA-Darstellung

Der Presenter bleibt die öffentliche GUI-Fassade, enthält aber keine vermischte Display-/Fokuslogik mehr.

### ISOThread

`worker/iso_thread.py` wurde von **336 auf 241 Zeilen** reduziert.

Ausgelagert wurden:

- `iso_input_processor.py` – per-input Orchestrierung
- `iso_processor_host_mixin.py` – öffentlicher Host-Vertrag für den Processor

Der Processor greift nicht mehr objektübergreifend auf private `_...`-Methoden des Threads zu. Gleichzeitig bleiben die bisherigen privaten Kompatibilitätshooks erhalten, sodass bestehende Tests/Caller sie weiterhin ersetzen können.

Die Option `auto_series_disc` bleibt ausdrücklich Eigentum des Threads. Die automatische Titelauswahl wird über `select_auto_titles()` an den Processor gegeben.

## Architektur-Messung nach v4

Die zuvor auffälligen Fassaden/Hotspots liegen jetzt bei:

| Modul | vorher | nachher | größte Funktion |
|---|---:|---:|---:|
| `core/release_validation.py` | 318 | 63 | `validate_release`: 17 |
| `worker/duration_timestamp_candidate_service.py` | 259 | 137 | `attempt`: 41 |
| `worker/converter_strip.py` | 207 | 56 | `strip_only`: 31 |
| `core/audio_video_time_mapping.py` | 206 | 97 | `classify_time_mapping`: 54 |
| `worker/quality_compare_thread.py` | 331 | 115 | 26 |
| `worker/converter_stream_args.py` | 384 | 106 | `text_burn_vf_args`: 30 |
| `worker/dv_final_mux_service.py` | 343 | 43 | 15 |
| `gui/conversion_progress_presenter.py` | 341 | 102 | `on_file_progress`: 14 |
| `worker/quality_test_thread.py` | 335 | 97 | 22 |
| `worker/iso_thread.py` | 336 | 241 | `__init__`: 51 |

Die Architekturtests prüfen zusätzlich, dass die neu ausgelagerten Fachservices Qt-frei bleiben und die Refactoring-Module im Release-Smoke-Vertrag enthalten sind.

## Bereits in v1–v3 enthaltene sicherheitskritische Fixes

Das v4-Overlay enthält weiterhin alle vorherigen Patches, insbesondere:

- sichere Serien-/Reboot-Identität beim Episode-Replacement
- Schutz gegen Öffnen/Zurückstempeln zukünftiger DB-Schemata
- einheitlicher `ProcessLifecycle`; Pause zählt nicht mehr gegen Timeout
- fail-closed Validierung des Audio-/Video-Matchers
- stärkere Cross-Volume-Move-Verifikation und eindeutige Staging-Dateien
- Job-Journal-Persistenz aus dem Progress-Presenter entfernt
- vollständige Zerlegung des Audio-/Video-Matchers
- weitere Entkopplung der DV-Pipeline
- Abbau der `ConverterThread`-Legacy-State-Aliase
- `core.paths` und `core.settings` nur noch als Kompatibilitätsfassaden; keine direkten Produktionsconsumer
- gezieltes Exception-Audit kritischer Parser-/Datei-/Move-/Validierungspfade
- Preflight-, Serien-/Film-Pfad-, Move-Recovery- und Audio-Regelmigrations-Refactorings

## Validierung

Der komplette Testbestand wurde wegen der Laufzeit in drei unabhängigen Blöcken ausgeführt:

- Block 1: **407 bestanden, 6 übersprungen, 1 bewusst ausgeklammert**
- Block 2: **451 bestanden**
- Block 3: **379 bestanden, 9 übersprungen, 3 bewusst ausgeklammert**

Gesamt:

- **1.237 Tests bestanden**
- **15 übersprungen**
- **4 bewusst nicht als Projektfehler gewertete Tests**
- `python -m compileall -q dragontools`: **OK**
- zusätzliche v4 Architektur-/Service-Regressionen: **grün**

Die vier bewusst ausgeklammerten Tests sind unverändert:

1. `test_patch5_release_contract_files_are_present`
2. `test_patch5_release_checks_accept_current_declared_environment`
3. `test_source_release_roundtrip_validates_cleanly`

Diese drei benötigen Release-/Requirements-/CI-Dateien, die laut Projektinhaber lokal vorhanden sind, aber im hochgeladenen Review-ZIP versehentlich fehlen.

4. `test_split_gui_runtime_dependencies_are_connected`

Dieser Test startet einen separaten Prozess mit echtem PyQt6. PyQt6 ist in der Linux-Prüfumgebung des Reviews nicht installiert.

## Stand nach dem geplanten Review-Refactoring

Die in `patch.md` von v3 ausdrücklich als nächste Refactoring-Kandidaten aufgeführten Blöcke sind mit v4 **abgearbeitet**:

- `release_validation`
- `duration_timestamp_candidate_service`
- `converter_strip`
- `audio_video_time_mapping`
- `quality_compare_thread`
- `converter_stream_args`
- `DVFinalMuxService`
- `ConversionProgressPresenter`
- `quality_test_thread`
- `ISOThread`

Damit ist der ursprünglich geplante Technical-Review-Patchzyklus abgeschlossen. Weitere Umbauten sollten erst nach einer neuen Gesamtvermessung des aktuellen v4-Stands priorisiert werden, statt alte Kandidatenlisten weiterzuverwenden.

## Installation

Das ZIP ist ein **kumulatives Overlay**. Den Inhalt über das vollständige lokale DragonTools-Projekt kopieren und vorhandene Dateien ersetzen.

Nicht im Review-ZIP vorhandene lokale Dateien – insbesondere die vom Projektinhaber erwähnten Requirements-/CI-Dateien – werden vom Overlay nicht gelöscht oder ersetzt.

`patch.md` liegt bewusst **direkt im ZIP-Root**, weil externe DragonTools-Workflows genau diesen Dateinamen abfragen.

## Lokale Nachprüfung des vollständigen Projektstands

Der vollständige private Projektstand enthält gegenüber dem ursprünglichen Review-ZIP weitere lokale Module und Tests. Die abschließende lokale Prüfung am 13.09.2026 ergab:

- **1.269 Tests bestanden**
- **2 reale DV/HDR-Integrationstests übersprungen**, weil externe Werkzeuge und Testmedien nicht konfiguriert sind
- `python -m compileall -q dragontools`: **OK**
- aktueller Umfang: **787 Python-Dateien**, **119.402 Gesamtzeilen**, **101.135 nichtleere/nicht reine Kommentarzeilen**
- Testpaket: **172 Python-Dateien**, **169 `test_*.py`**, **1.245 statisch erkennbare Testfunktionen**

Die oben dokumentierten 1.237 bestandenen, 15 übersprungenen und 4 bewusst ausgeklammerten Tests bleiben die historische Validierung des Review-Hosts; die lokale Nachprüfung ersetzt diese Zahlen nicht, sondern ergänzt sie für den vollständigen privaten Stand.
