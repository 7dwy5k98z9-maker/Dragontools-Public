# DragonTools – Release-/Refactoring-Review-Manifest

**Stand:** 2026-09-13
**App-Version:** 9.8.2
**Baseline:** `dragontools(20260912-165602).zip`
**Review-Stand:** `dragontools_20260913_postreview_hardening.zip`

> Dieses Dokument ist bewusst **nicht** die produktive `release_manifest.json`. Diese Datei ist in DragonTools ein Build-/Release-Vertrag. Das hochgeladene Quellpaket enthält u. a. `build_v9.bat` und weitere Release-Artefakte nicht; ein echtes Build-Manifest würde deshalb einen falschen vollständigen Release-Zustand deklarieren. Für gezielte Code-Reviews ist dieses separate Manifest gedacht.

## Validierung

- Block-12-Zielset für Audio/Video-Matcher, Online-Metadaten-Settings, Architekturgrenzen, Lifecycle und Release-Smoke: **101 bestanden, 1 hostbedingt abgewählt**.
- Der abgewählte CrashGuard-Paralleltest scheitert auf diesem Review-Dateisystem mit `OSError [Errno 5] Input/output error`; derselbe Fehler wurde gegen den **unveränderten Block-11-Stand reproduziert** und ist keine Block-12-Regression.
- `compileall` läuft vollständig sauber durch. Die sieben neuen Splitmodule sind im Release-Smoke registriert.
- Für die persistente Online-Metadaten-Konfiguration gibt es einen Qt-unabhängigen Roundtrip-Test; Save/Load aller Provider-, Sprach-, Cache- und Credential-Felder ist verlustfrei.
- PyQt6 ist auf dem Review-Host weiterhin nicht installiert. Die GUI-Fassaden konnten deshalb hier nicht real instanziiert werden; ihre Shutdown-/AST-Verträge und die vorhandenen Architekturtests sind jedoch grün.
- Unverändert fehlen im Source-Archiv die produktive `release_manifest.json` und `build_v9.bat`; das separate Review-Manifest bleibt daher bewusst **kein** Build-Manifest.

## Größte Entkopplungen seit der Baseline

| Datei | Vorher | Jetzt |
|---|---:|---:|
| `dragontools/core/media_library_db.py` | 510 | 187 |
| `dragontools/core/media_library_jellyfin.py` | 573 | 189 |
| `dragontools/gui/preflight_metadata.py` | 353 | 108 |
| `dragontools/core/media_library_repository.py` | 599 | 29 |
| `dragontools/worker/postprocess_service.py` | 519 | 16 |
| `dragontools/core/media_library_nfo_scan.py` | 412 | 127 |
| `dragontools/core/media_library_query.py` | 414 | 53 |
| `dragontools/worker/trickplay_service.py` | 452 | 239 |
| `dragontools/worker/dv_remux_components.py` | 533 | 44 |
| `dragontools/worker/dv_remux_thread.py` | 480 | 357 |
| `dragontools/gui/media_library_dialog_view.py` | 520 | 99 |
| `dragontools/core/settings_backup.py` | 442 | 33 |
| `dragontools/core/job_journal.py` | 463 | 208 |
| `dragontools/gui/drop_path_extractor.py` | 468 | 307 |
| `dragontools/core/rules_preview.py` | 417 | 94 |
| `dragontools/gui/preflight_series_widget.py` | 430 | 41 |
| `dragontools/gui/conversion_result_service.py` | 470 | 56 |
| `dragontools/worker/merge_thread.py` | 448 | 130 |
| `dragontools/gui/convert_widget_encoder_override.py` | 408 | 137 |
| `dragontools/worker/duration_repair_service.py` | 387 | 201 |
| `dragontools/worker/hdrplus_conversion.py` | 400 | 217 |
| `dragontools/gui/move_lifecycle_coordinator.py` | 359 | 72 |
| `dragontools/core/media_library_repository_items.py` | 373 | 41 |
| `dragontools/gui/audio_video_matcher_widget.py` | 368 | 32 |
| `dragontools/gui/online_metadata_dialog.py` | 367 | 27 |

## Mediathek-Datenbank: Performance, Migrationen und Serien-Lookup

Indexfreundlicher Serien-Lookup, reduzierte DB-Verbindungen/Writes, saubere Schema-Migrationen, Jellyfin-Normalisierung, asynchrone Mediathek-Suche und kürzere NFO-Schreibtransaktionen.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/core/media_library_db.py` | modified | Schmale DB-Fassade/öffentliche DB-API. | Kompatibilität der bisherigen Imports und Initialisierungsreihenfolge. |
| `dragontools/core/media_library_sqlite.py` | added | SQLite-Verbindungsaufbau und Low-Level-Helfer. | Read/Write-Verbindungen, WAL-Konfiguration, Thread-Nutzung. |
| `dragontools/core/media_library_schema.py` | added | Schema-Definitionen und Indexerstellung. | Indexreihenfolge, Spaltenabhängigkeiten, idempotente CREATE-Anweisungen. |
| `dragontools/core/media_library_migrations.py` | added | Schema-Migrationen für bestehende Datenbanken. | Legacy-Schemata, Reihenfolge Spalten vor Indizes, Datenmigration. |
| `dragontools/core/media_library_series_lookup.py` | added | Schneller indexierter Serien-Lookup. | normalized_title-Index, Legacy-Fallback, Query-Plan. |
| `dragontools/core/media_library_series_paths.py` | modified | Serienwurzel-Auflösung auf Basis DB/Pfadmapping. | Fast path vor Legacy-Fallback; Pfadsemantik unverändert. |
| `dragontools/core/media_library_path_mappings.py` | modified | Pfadmapping-Lesen mit optional wiederverwendeter Verbindung. | Keine unnötigen Connections; Mapping-Priorität unverändert. |
| `dragontools/core/media_library_jellyfin.py` | modified | Jellyfin-Import-Orchestrierung/Fassade. | Importtransaktion, Kompatibilität, Fehlerpfade. |
| `dragontools/core/media_library_jellyfin_source.py` | added | Lesen/Abbilden der Jellyfin-Quelldaten. | Jellyfin-Schema-Varianten und ID-Auflösung. |
| `dragontools/core/media_library_jellyfin_items.py` | added | Konvertierung Jellyfin-Items in DragonTools-Datensätze. | series_title -> normalized_title; Staffel/Episode/Typ. |
| `dragontools/core/media_library_jellyfin_streams.py` | added | Stream-/HDR-Konvertierung aus Jellyfin. | Sprachen, Codecs, HDR/DV und Streamtypen. |
| `dragontools/core/media_library_repository.py` | modified | Kompatibilitätsfassade für Repository-Funktionen. | Öffentliche Imports bleiben stabil. |
| `dragontools/core/media_library_repository_items.py` | added | Persistenz einzelner Medien/Streams. | Upsert-Semantik, active/exists_flag, Transaktionen. |
| `dragontools/core/media_library_repository_moves.py` | added | Move-/Replace-DB-Aktualisierung. | Episode-Identität, active=0/1, Ersatzlogik. |
| `dragontools/core/media_library_sidecars.py` | added | Sidecar-/NFO-Zustände. | Pfadauflösung und Statuskonsistenz. |
| `dragontools/core/media_library_query.py` | modified | Schmale Suchquery-Fassade. | Abwärtskompatible API. |
| `dragontools/core/media_library_query_fragments.py` | added | Wiederverwendbare SQL-Fragmente. | JOIN/CTE-Aliase und Parameterbindung. |
| `dragontools/core/media_library_query_scope_filters.py` | added | Scope-/Item-Type-Filter. | TV/Anime/Filme-Pfadfilter und SQL-Parameter. |
| `dragontools/core/media_library_query_presets.py` | added | Presetfilter für Codec/HDR/Audio usw. | EXISTS/Aggregat-Semantik und NULL-Fälle. |
| `dragontools/core/media_library_search_enrichment.py` | added | Gebündelte Stream-Anreicherung für Suchtreffer. | N+1-Vermeidung; Zuordnung media_id -> Streams. |
| `dragontools/core/media_library_search_service.py` | modified | Suchservice ohne unnötige Schema-Writes. | Read-only-Suche, Limits, Verbindungslifetime. |
| `dragontools/core/media_library_scan.py` | modified | Speicherpfad-Scan und DB-Aktualisierung. | Batchverhalten und Transaktionen. |
| `dragontools/core/media_library_nfo_scan.py` | modified | NFO-Scan-Orchestrierung. | Keine lange Writer-Transaktion während NAS-I/O. |
| `dragontools/core/media_library_nfo_paths.py` | added | NFO-/Medienpfadlogik. | Erreichbarkeit und mapped paths. |
| `dragontools/core/media_library_nfo_parser.py` | added | NFO-XML-Parsing. | Fehlerhafte/teilweise XML-Dateien. |
| `dragontools/core/media_library_nfo_inventory.py` | added | Kandidaten/Filesystem-Inventur. | NAS-I/O außerhalb DB-Schreibphase. |
| `dragontools/core/media_library_nfo_store.py` | added | Persistenz von NFO-Scan-Ergebnissen. | Batch-Commit und Issue-Ersetzung. |
| `dragontools/gui/media_library_search_worker.py` | added | QThread-Worker für SQLite-Suche. | Threadgrenzen, Cancel/Stale-Request-Verhalten. |
| `dragontools/gui/media_library_search_controller.py` | modified | Steuert asynchrone Suchrequests und Ergebnisübergabe. | Keine DB-Arbeit im GUI-Thread; Request-Generation. |
| `dragontools/tests/test_media_library_series_lookup_performance.py` | added | Regressionstest für Serien-Lookup/Query-Plan. | Repräsentativität der Legacy- und Fast-Path-Fälle. |
| `dragontools/tests/test_media_library.py` | modified | Erweiterte DB-/Migrations-/Importtests. | Legacy-DB, normalized_title, NFO/Query. |

## Metadaten, Preflight und NFO-Postprocessing

DB-first Preflight, frische Metadaten für finalen Rename/NFO-Lauf mit Batch-Wiederverwendung, Refresh generischer Episodentitel und verbesserter TVDB-Sprachfallback.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/gui/preflight_metadata.py` | modified | Schmale Preflight-Orchestrierung. | Ablauf Movie/Series und Thread-Grenzen. |
| `dragontools/gui/preflight_metadata_common.py` | added | Gemeinsame Preflight-Helfer/Sessiondaten. | Cache-Lifetime und gemeinsame Pfad-/DB-Daten. |
| `dragontools/gui/preflight_metadata_movie.py` | added | Film-Metadatenauflösung. | Mehrdeutige Ergebnisse/Jahre und Fehlerpfade. |
| `dragontools/gui/preflight_metadata_series.py` | added | Serien-Metadatenauflösung DB-first. | DB vor Directory-Scan; Jahr-Auflösung; Fallback. |
| `dragontools/gui/preflight_metadata_apply.py` | added | Überträgt Ergebnisse auf GUI-Modelle. | Thread-sichere Ergebnisanwendung. |
| `dragontools/core/online_metadata_service.py` | modified | Metadatenservice und Session-/Cache-Modi. | Persistent cache vs fresh-once Batch. |
| `dragontools/core/online_metadata_tvdb_transport.py` | modified | TVDB HTTP/Cache/Auth. | Cache vor Auth; force_refresh; Session-Wiederverwendung. |
| `dragontools/core/online_metadata_tvdb_episode_data.py` | added | Bewertung/Übernahme von Episodendaten. | Generische Titel erkennen; Sprachfallback-Merge. |
| `dragontools/core/online_metadata_tvdb_candidates.py` | modified | TVDB-Kandidatenauflösung. | Fallback auch bei leerem/generischem Titel. |
| `dragontools/core/online_metadata_tvdb_resolver.py` | modified | TVDB-Resolver. | DE->Fallback-Sprache, IDs, Episodentitel. |
| `dragontools/core/online_metadata_tvdb_helpers.py` | modified | TVDB-Helfer für lokalisierte Titel. | Generische Titel und Übersetzungspriorität. |
| `dragontools/core/online_metadata_tvdb_suggestions.py` | modified | TVDB-Suggestion-Pfade. | Cache/Refresh-Konsistenz. |
| `dragontools/core/online_metadata_tmdb_transport.py` | modified | TMDB Transport/Cache-Anpassungen. | Session-/force_refresh-Verhalten analog TVDB. |
| `dragontools/core/online_metadata_tmdb.py` | modified | TMDB Client-Anpassungen. | Kompatibilität der öffentlichen API. |
| `dragontools/core/online_metadata_tmdb_suggestions.py` | modified | TMDB Suggestions. | Batch-/Refresh-Semantik. |
| `dragontools/core/online_metadata_parsing.py` | modified | Metadaten-Parsing/Helfer. | Generische/fehlende Titel und Sprachwerte. |
| `dragontools/worker/postprocess_service.py` | modified | Kompatibilitätsfassade des Postprocessings. | Alte Importpfade. |
| `dragontools/worker/postprocess_config.py` | added | Postprocess-Konfiguration. | Settings-Mapping und Defaults. |
| `dragontools/worker/postprocess_models.py` | added | Postprocess-Datenmodelle. | Felder/immutability/Defaults. |
| `dragontools/worker/postprocess_metadata.py` | added | Gemeinsame Metadaten-Batchsession. | Eine frische Providerabfrage pro Serie/Batch statt pro Datei. |
| `dragontools/worker/postprocess_runner.py` | added | Einzeldatei-Postprocessing/NFO-Lauf. | Reihenfolge, Metadaten-IDs, Sidecars. |
| `dragontools/worker/postprocess_async.py` | added | Async-Koordinator. | Threading, gemeinsamer Session-Lifetime, Shutdown. |
| `dragontools/tests/test_online_metadata.py` | modified | Regressionstests Metadata Cache/TVDB-Fallback. | Leer/generisch, force_refresh, Sprachen. |
| `dragontools/tests/test_preflight_dialog_performance.py` | modified | Preflight-Performance/DB-first Regression. | Keine unnötigen Directory-Scans. |

## Refactoring Block 2: NFO, Suchquery, Trickplay

Große Module nach Parsing, Storage, Query-Building und FFmpeg/Commit-Verantwortung zerlegt.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/core/media_library_nfo_scan.py` | modified | NFO-Orchestrator (412 -> 127 Zeilen). | Orchestrierung darf keine Parser/Store-Details zurückholen. |
| `dragontools/core/media_library_query.py` | modified | Query-Fassade (414 -> 53 Zeilen). | Öffentliche Signaturen stabil halten. |
| `dragontools/worker/trickplay_service.py` | modified | Trickplay-Orchestrator (452 -> 239 Zeilen). | Generatorzustand und Ablauf. |
| `dragontools/worker/trickplay_models.py` | added | Trickplay-Settings/Modelle. | Defaults und Datentypen. |
| `dragontools/worker/trickplay_ffmpeg.py` | added | FFmpeg-Befehl/Hardware-Fallback. | Codec-/HW-Fallbacks und Argumente. |
| `dragontools/worker/trickplay_commit.py` | added | Commit/Rollback/Backup. | Atomarität und Cleanup. |
| `dragontools/worker/trickplay_concurrency.py` | added | Semaphore/Konkurrenzsteuerung. | Deadlocks und Freigabe bei Fehlern. |
| `dragontools/worker/trickplay_paths.py` | added | Pfade/Conflict-Policy. | Zielpfade und Existenzkonflikte. |
| `dragontools/tests/test_refactor_block2_architecture.py` | added | Architekturgrenzen Block 2. | Grenzwerte und Importstabilität. |

## Refactoring Block 3: DV-Remux und Mediathek-GUI

DV-Remux-Pipeline nach Prozess, Audio, Mux, Output und Job getrennt; Mediathek-Dialog in Tabs/Options/Contracts aufgeteilt.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/worker/dv_remux_components.py` | modified | Kompatibilitätsfassade (533 -> 44 Zeilen). | Re-Exports und Monkeypatch-Kompatibilität. |
| `dragontools/worker/dv_remux_process.py` | added | FFmpeg/ffprobe/Tool-Ausführung. | Timeout, ETA, Abbruch. |
| `dragontools/worker/dv_remux_audio.py` | added | Audiojob-Planung. | Track-Mapping, Sprachen, Codecs. |
| `dragontools/worker/dv_remux_muxers.py` | added | MP4Box/mkvmerge Wrapper. | Containerargumente und Fehlercodes. |
| `dragontools/worker/dv_remux_pipeline.py` | added | Video/Audio/Sub/Mux-Ablauf. | Stage-Reihenfolge und Fehlerpropagation. |
| `dragontools/worker/dv_remux_output.py` | added | Output/Größenprüfung/Commit/Cleanup. | Transaktionales Ersetzen und Rollback. |
| `dragontools/worker/dv_remux_job.py` | added | Eine vollständige DV-Remux-Dateitransaktion. | Sidecar Commit/Rollback und Resultstatus. |
| `dragontools/worker/dv_remux_thread.py` | modified | QThread/Queue/Lifecycle (480 -> 357 Zeilen). | Pause/Abort/Signals und JobRunner-Delegation. |
| `dragontools/gui/media_library_dialog_view.py` | modified | Schmale View-Komposition (520 -> 99 Zeilen). | Attribute-Contract für Controller. |
| `dragontools/gui/media_library_status_tab.py` | added | DB/Import/Export/NFO-Status-Tab. | Widget-Attribute und Signals. |
| `dragontools/gui/media_library_mapping_tab.py` | added | Pfadmapping-Tab. | Mapping-Widgets und Tabellenstruktur. |
| `dragontools/gui/media_library_search_tab.py` | added | Suchfilter/Ergebnistabelle. | Filterwerte, Tabellen-Spalten. |
| `dragontools/gui/media_library_sql_tab.py` | added | SQL-Editor/gespeicherte Queries. | Read-only/unsafe SQL Policy. |
| `dragontools/gui/media_library_dialog_options.py` | added | Suchoptionen/Scopes. | Werte müssen Controller/API entsprechen. |
| `dragontools/gui/media_library_dialog_contracts.py` | added | Action-Protocol. | Controller/View-Vertrag. |
| `dragontools/tests/test_refactor_block3_dv_media_view_architecture.py` | added | Architekturtests Block 3. | Fassaden-/Größengrenzen. |

## Refactoring Block 4: Backup, Job-Journal, Drag&Drop und Rules-Preview

Vier weitere Module wurden nach fachlichen Verantwortlichkeiten getrennt. Die bisherigen öffentlichen Importpfade bleiben erhalten; bei `job_journal.py` bleibt der zustandsbehaftete Writer absichtlich in der Fassade, damit bestehende Fail-closed-/Monkeypatch-Tests weiterhin die atomare Write-Grenze prüfen.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/core/settings_backup.py` | modified | Öffentliche Backup-Fassade (442 -> 33 Zeilen). | Re-Exports und `_iter_backup_files`-Kompatibilität für Diagnostic Package. |
| `dragontools/core/settings_backup_common.py` | added | Backupformat, JSON-Serialisierung, Sensitive-Key- und Pfadhelfer. | Bytes/QByteArray-Roundtrip, Key-Erkennung, Manifestvalidierung. |
| `dragontools/core/settings_backup_crypto.py` | added | AES-256-GCM/Scrypt für Secrets. | KDF-Grenzen, falsches Passwort, optionales `cryptography`. |
| `dragontools/core/settings_backup_export.py` | added | ZIP-Export und Backup-Inspektion. | Secret-Modi und kein Klartext-Secret im Default. |
| `dragontools/core/settings_backup_restore.py` | added | Transaktionaler Restore mit Rollback. | Settings-/Datei-Rollback, Legacy-v1, atomische Writes. |
| `dragontools/core/job_journal.py` | modified | Writer/Fassade (463 -> 208 Zeilen). | Durable Write vor Archiv-Löschung; Fehler bleiben fail-closed. |
| `dragontools/core/job_journal_storage.py` | added | Pfade, Listing, Lesen und manuelle Archivierung. | Parallele Runs, Legacy `active_run.json`, defekte JSONs. |
| `dragontools/core/job_journal_resume.py` | added | Resume-Plan, Statusnormalisierung und Summary. | retry_running/retry_failed, Deduplizierung und Counts. |
| `dragontools/gui/drop_path_extractor.py` | modified | MIME-Orchestrator/Fassade (468 -> 307 Zeilen). | Qt-Fallbackreihenfolge, Long-Path-Warnungen, Debug-Verhalten. |
| `dragontools/gui/drop_path_files.py` | added | Rekursives Video-Einsammeln. | Windows Long-Path-Walk und Filter. |
| `dragontools/gui/drop_path_decode.py` | added | URL/Text/FileNameW-Decoding. | UNC, `file://`, UTF-16, Windows-Pfadregex. |
| `dragontools/gui/drop_path_windows.py` | added | Shell CIDA/PIDL-Auflösung via ctypes. | x64-Pointertypen, `ILFree`, 32k Unicode-Puffer. |
| `dragontools/core/rules_preview.py` | modified | Preview-Orchestrator/Fassade (417 -> 94 Zeilen). | Pipeline-Kontext und stabile Ausgabeform. |
| `dragontools/core/rules_preview_audio.py` | added | Audio-Preview über produktiven `audio_plan`. | Preview/Worker-Entscheidungen identisch halten. |
| `dragontools/core/rules_preview_subtitles.py` | added | Subtitle-, Sidecar- und Burn-in-Preview. | DV/MP4, Copy vs Sidecar, text-to-SRT, Burn-Kandidaten. |
| `dragontools/core/rules_preview_video.py` | added | Quell-/Zielvideo-Preview. | Downscale-only, `strip_only`, gerade Breiten und HDR-Felder. |
| `dragontools/core/rules_preview_common.py` | added | Kleine Normalisierer. | Keine fachlichen Regelentscheidungen in Common-Helfern. |
| `dragontools/tests/test_refactor_block4_architecture.py` | added | Größen-/Smoke-/Importgrenzen. | Verhindert erneutes Zusammenwachsen. |

**Validierung Block 4:** gezielte Regressionstests sowie kompletter Lauf: **1159 bestanden, 18 übersprungen, 3 bekannte externe Fehler**. Beim ersten Volltest wurde ein echter Kompatibilitätsbruch gefunden (`diagnostic_package.py` importiert `_iter_backup_files`); der Re-Export wurde ergänzt und der Folgelauf ist an dieser Stelle sauber.

## Refactoring Block 5: Serien-Preflight, Conversion-Result und Merge-Worker

Die drei vereinbarten Monolithen sind jetzt reine Orchestrierungsfassaden. Beim Serien-Preflight wurden UI, Pfadplanung und Metadatenstatus getrennt; beim Conversion-Abschluss Datei-Ergebnisse, Worker-Ende und Run-Finalisierung; beim Merge Analyse, Kompatibilitätsplan und konkrete mkvmerge-Ausführung. Bestehende Klassen-/Methodenverträge bleiben erhalten.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/gui/preflight_series_widget.py` | modified | Schmale QWidget-Fassade (430 → 41 Zeilen). | Mixin-MRO mit QWidget, Init-State und unveränderte öffentliche Widgetmethoden. |
| `dragontools/gui/preflight_series_view.py` | added | UI-Aufbau, manuelle Suche und Preview. | Signalverbindungen, Release-Warnungen und Folder-Choice-Widget. |
| `dragontools/gui/preflight_series_paths.py` | added | Bereichs-/Pfadauflösung und Saisonziele. | Pfadsemantik, TV/Anime-Reihenfolge und Folder-Choice. |
| `dragontools/gui/preflight_series_metadata.py` | added | Metadatenjob, Hinweise und Ergebnisanwendung. | DB-/Folder-/Online-Priorität, manuelle Namensänderungen und Library-Warnungen. |
| `dragontools/gui/conversion_result_service.py` | modified | DI-Fassade (470 → 56 Zeilen). | Konstruktorvertrag und Controller-Verbindungen. |
| `dragontools/gui/conversion_result_file_events.py` | added | Datei-Ergebnisse, State, Sidecars/Postprocess und Journal. | Terminalstatus, blocked_move_inputs, Overrides und Pending-Postprocess. |
| `dragontools/gui/conversion_result_finish.py` | added | Worker-Ende, Abort und Move-Übergabe. | Abbruchpfade, UI-Reenable und Postprocess-Wartezustand. |
| `dragontools/gui/conversion_run_finalizer.py` | added | Summary, Journalabschluss, Retry und Shutdown. | summary_written-Guard, DV-Remux-Sonderfall, Retry-vor-Shutdown. |
| `dragontools/worker/merge_thread.py` | modified | QThread-/Run-Lifecycle (448 → 130 Zeilen). | Signals, Abort, Requestvalidierung und Legacy-Helper-Reexports. |
| `dragontools/worker/merge_common.py` | added | Pure Container/FPS/Stream-Signatur-Helfer. | Formatnamen, 0/0-FPS und Signaturstabilität. |
| `dragontools/worker/merge_analysis.py` | added | ffprobe/MediaAnalyzer-Auswertung. | Abort/Timeout, Containerabweichung und Fortschritt. |
| `dragontools/worker/merge_plan.py` | added | Lossless-Kompatibilitätsprüfung und Plan. | Codec/Auflösung/FPS/Audio/Subtitle-Gleichheit und MKV-Ziel. |
| `dragontools/worker/merge_executor.py` | added | mkvmerge-Ausführung und transaktionaler Commit. | Temp-Cleanup, Überschreibschutz, Timeout/Abort und Logger-Statistik. |
| `dragontools/tests/test_refactor_block5_runtime_architecture.py` | added | Architektur-/Smoke-/Kompatibilitätstests. | Fassadengrößen, Splitmodule und Legacy-Namen. |

**Validierung Block 5:** kompletter Lauf **1164 bestanden, 18 übersprungen, 3 bekannte externe Fehler**. Die Fehler sind weiterhin ausschließlich fehlendes PyQt6 im Review-System sowie die im Source-Archiv fehlenden Dateien `release_manifest.json` und `build_v9.bat`. Die Block-5-Zieltests sowie `compileall` laufen sauber.

## Refactoring Block 6: ISO-Widget und Parallel-Converter

Die beiden Block-6-Kandidaten wurden nach UI/Input/Runtime bzw. Queue/Control/Lifecycle getrennt. Die Qt-Fassaden behalten die öffentlichen Klassen und die Child-Worker-Erzeugung, damit Signal- und Monkeypatch-Verträge unverändert bleiben.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/gui/iso_widget.py` | modified | QWidget-Fassade (455 → 48 Zeilen). | Mixin-MRO, Init-State, `iter_shutdown_workers`. |
| `dragontools/gui/iso_widget_view.py` | added | Layout und Running-State. | Signalverbindungen, Serien-Disc-Default, Checkboxen. |
| `dragontools/gui/iso_widget_inputs.py` | added | Eingabe-/Zielpfad- und Titelauswahl. | Deduplizierung, analysierte Quelle, FileDialog. |
| `dragontools/gui/iso_widget_runtime.py` | added | Analyse/Extraktion, Worker-Slots und Handoff. | ISOThread-Optionen, Auto-Titel, Abort/Finish. |
| `dragontools/worker/parallel_converter_thread.py` | modified | Qt-Fassade/Child-Launcher (431 → 181 Zeilen). | Signals, Logger, Worker-Fabrik, Registry/Coordinator. |
| `dragontools/worker/parallel_converter_queue.py` | added | Queue, Reihenfolge, Overrides. | Remove/Add/Reorder und Displaypositionen. |
| `dragontools/worker/parallel_converter_control.py` | added | Pause/Resume/Abort/DV-Crop. | `nach_datei` zurücknehmen, aktive Worker. |
| `dragontools/worker/parallel_converter_lifecycle.py` | added | Start/Finish, Fortschritt, Diagnose, Cleanup. | Finish-Guards und Postprocess-Wartezustand. |
| `dragontools/tests/test_refactor_block6_iso_parallel_architecture.py` | added | Architektur-/Smoke-Guards. | Größenlimits, Mixin-Komposition, Qt-freie Worker-Helfer. |

**Validierung Block 6:** Zieltests **25/25 bestanden**; kompletter Lauf **1170 bestanden, 18 übersprungen, 3 bekannte externe Fehler**. `compileall` ist sauber. Beim ersten Volltest fehlte der explizite `iter_shutdown_workers`-Hook direkt auf der ISO-Fassade; der Lifecycle-Vertrag wurde wiederhergestellt und anschließend erneut vollständig getestet.

## Refactoring Block 7: MoveThread / Datenintegritäts-Lifecycle

Der Move-Worker wurde als eigener Sicherheitsblock behandelt. Routing, Speicherpfade, Pfadmapping und die transaktionale Dateioperation in `core.move_file_service` wurden **nicht fachlich verändert**. Ziel war ausschließlich, QThread-Lifecycle, Benutzersteuerung, Commit/Sidecars und Journal-/Batch-Ablauf klar zu trennen, ohne bestehende Recovery- und Replacement-Verträge zu brechen.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/worker/move_thread.py` | modified | QThread-Fassade (415 → 145 Zeilen): Signals, Initialzustand, Run-Rahmen. | Mixin-MRO, `finally`-Journalabschluss, Signals und Legacy-`os.replace`-Monkeypatch-Hook. |
| `dragontools/worker/move_runtime_control.py` | added | Pause/Resume/Abort, geplante Ziele und Benutzerentscheidungen. | Abort während `_ask`, Event-Cleanup, Pausenfreigabe und Lock um `planned_targets`. |
| `dragontools/worker/move_result_commit.py` | added | Service-Fabriken, Transferadapter, Sidecars, Report und Mediathek-Commit. | `MoveJournalWriteError` bleibt fail-closed; DB erst nach Companion-Commit; Replacement-Resultate. |
| `dragontools/worker/move_batch_lifecycle.py` | added | Journalstart/-finalisierung, BatchExecutor, Progress/ETA, Retry-Archiv und Shutdown. | Status `completed/incomplete/aborted`, Retry-Archivierung und Teilresultate bei Exceptions. |
| `dragontools/core/release_validation_smoke_modules.py` | modified | Block-7-Splitmodule im Paket-Smoke-Test registriert. | Gebautes Paket darf kein neues Modul vergessen. |
| `dragontools/tests/test_refactor_block7_move_architecture.py` | added | Größen-/Architektur-/Smoke-Guards. | QThread bleibt Fassade; destruktive Transferlogik bleibt außerhalb. |

**Validierung Block 7:** Move-/Recovery-/Sidecar-Zieltests **48 bestanden, 3 übersprungen**; `compileall` ist sauber. Der gesamte Testbestand wurde wegen eines Hängers im monolithischen Lauf in isolierten Dateigruppen ausgeführt: **1172 bestanden, 18 übersprungen, 6 fehlgeschlagen**. Drei Fehler sind die bereits bekannten Review-Umgebungsprobleme (PyQt6 sowie fehlende `release_manifest.json`/`build_v9.bat`). Drei weitere betreffen ausschließlich durable JSON-Schreibtests, weil das aktuelle Review-Dateisystem bei einem direkten `os.fsync()`-Probeaufruf sowohl unter `/tmp` als auch `/mnt/data` mit **`OSError [Errno 5] Input/output error`** antwortet. Diese drei Fehler treten damit bereits außerhalb von DragonTools auf und wurden nicht durch Block 7 verursacht.


## Refactoring Block 8: Encoder-Override und Duration-Repair

Der per-Datei Encoder-Override und die automatische Laufzeitreparatur wurden nach klaren Verantwortlichkeiten getrennt. Öffentliche Dialog-/Service-Verträge bleiben erhalten; die neue Fachlogik ist in fokussierten Modulen test- und reviewbar.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/gui/convert_widget_encoder_override.py` | modified | Dialog-Fassade (408 → 137 Zeilen). | `build_group`/`persist_group`/`edit_paths`, Owner-Vertrag und Ergebnisdialog. |
| `dragontools/gui/convert_widget_encoder_panels.py` | added | CPU/NVENC/QSV/AMF-Controls und Presetlisten. | Wertebereiche, Stack-Reihenfolge, AV1-CPU-Presets. |
| `dragontools/gui/convert_widget_encoder_controls.py` | added | Snapshot → Controls und Controls → Override-Dict. | Backend-Optionen strikt getrennt halten. |
| `dragontools/gui/convert_widget_encoder_state.py` | added | Qt-unabhängige Snapshot/Summary/Common-State-Logik. | Globalprofil und Skalierungs-Mapping. |
| `dragontools/gui/convert_widget_encoder_apply.py` | added | Queue-Anwendung des Overrides. | Worker-Ablehnung vor State-Commit; Preflight-Cache invalidieren. |
| `dragontools/worker/duration_repair_service.py` | modified | Kompatibilitätsfassade/Dependency-Wiring (387 → 201 Zeilen). | Historische Wrapper/Re-Exports und `subprocess.run`-Testvertrag. |
| `dragontools/worker/duration_repair_orchestrator.py` | added | Remux → Timestamp → Fail-closed/Archiv Ablauf. | Stage-Reihenfolge, Evidence-Weitergabe, Erfolgs-/Fehler-Outcomes. |
| `dragontools/worker/duration_repair_policy.py` | added | Zulässigkeit und fail-closed Status. | Nur geeignete MKV/MP4-Dauerfehler reparieren. |
| `dragontools/worker/duration_repair_archive.py` | added | Fehleroutput archivieren und eindeutige Zielnamen. | Replace bleibt an Runtime-Grenze; Archivierung erst nach endgültigem Fehlschlag. |
| `dragontools/core/release_validation_smoke_modules.py` | modified | Block-8-Module im Paket-Smoke registriert. | Keine Splitmodule im Build verlieren. |
| `dragontools/tests/test_refactor_block8_encoder_duration_architecture.py` | added | Architektur-/Größen-/Smoke-Guards. | Verhindert erneutes Anwachsen der Fassaden. |

**Validierung Block 8:** **92 betroffene Regressionstests bestanden**, `compileall` sauber. Der erste Fehler des monolithischen Gesamtlaufs liegt außerhalb dieses Blocks und reproduziert auf dem unveränderten Block-7-Archiv.


## Refactoring Block 9: HDR10+-Fassade, Move-GUI-Lifecycle und Mediathek-Repository-Items

Die drei nach Block 8 priorisierten Module wurden getrennt. Beim HDR10+-Pfad bleibt die bestehende Monkeypatch-/Tool-Grenze erhalten; beim Move-Lifecycle wurden regulärer Abschlusslauf und Zwischenverschieben voneinander getrennt; bei der Mediathek liegen SQL-Upsert und MediaInfo-Mapping nicht mehr im selben Repository-Modul.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/worker/hdrplus_conversion.py` | modified | HDR10+-Fassade (400 → 217 Zeilen). | Default-Encoderzustand, `execute`/`run`, pro Job gebundene Pipeline-Hooks und bestehende private Kompatibilitätsnamen. |
| `dragontools/worker/hdrplus_helper_services.py` | added | Zentrale Konstruktion der langlebigen HDR10+-Services. | Tool-Callbacks dynamisch/monkeypatchbar halten; keine Jobdaten in langlebigen Services speichern. |
| `dragontools/worker/hdrplus_helper_compat.py` | added | Legacy-/Testwrapper für Tool-, Encode-, Mux- und Cleanup-Aktionen. | Wrapper bleiben dünn; keine Pipeline-Policy zurück in den Compatibility-Layer. |
| `dragontools/gui/move_lifecycle_coordinator.py` | modified | Schmale Move-Lifecycle-Fassade (359 → 72 Zeilen). | Öffentliche Controller-API und Delegation an regulären/inkrementellen Lifecycle. |
| `dragontools/gui/move_regular_lifecycle.py` | added | Abschließender Move-Lauf nach Konvertierung. | Restored-Move-Kontext, Conflict-Mode, Signalverdrahtung, Finalize-/Shutdown-Semantik. |
| `dragontools/gui/move_incremental_lifecycle.py` | added | Zwischenverschieben während laufender Konvertierung. | Queue bleibt editierbar, fertige Outputs aus State entfernen, fremden/replacement MoveThread nicht überschreiben. |
| `dragontools/gui/move_lifecycle_helpers.py` | added | Pure ETA-/Report-/Output-Mapping- und Retire-Helfer. | Keine Qt-Abhängigkeit und stabile Video-vs-Sidecar-Semantik. |
| `dragontools/core/media_library_repository_items.py` | modified | Repository-Fassade für Einzeldatei-Snapshot (373 → 41 Zeilen). | Historische private Re-Exports für Scan/Jellyfin/Move bleiben stabil. |
| `dragontools/core/media_library_item_sql.py` | added | `media_items`-Upsert und atomarer Stream-Snapshot. | `ON CONFLICT(path)`, Defaults, Streamtyp-Normalisierung und DELETE→INSERT innerhalb der aufrufenden Transaktion. |
| `dragontools/core/media_library_media_info_mapper.py` | added | MediaInfo/Dateipfad → DB-Item und Streamzeilen. | Serienerkennung, HDR/DV-Felder, Fallback-Item, Sidecar-Streams und Bitrate. |
| `dragontools/core/release_validation_smoke_modules.py` | modified | Block-9-Splitmodule im Paket-Smoke registriert. | Gebautes Paket darf keines der neuen Module verlieren. |
| `dragontools/tests/test_refactor_block9_hdr_move_library_architecture.py` | added | Architektur- und In-Memory-Verhaltenstests für Block 9. | Fassadengrößen, Responsibility-Split, Move-Helfer, Mapper und SQL-Upsert. |

**Validierung Block 9:** **68 bestanden, 2 übersprungen** im betroffenen Regression-Set; `compileall` sauber. Das Mapping entspricht im direkten Block-8/Block-9-Vergleich exakt dem bisherigen Ergebnis. Der SQLite-Upsert wurde unabhängig von Host-Dateisystemproblemen in `:memory:` validiert. Die derzeitigen temp-Dateisystem-`disk I/O error`-Fehler reproduzieren bereits unverändert auf Block 8.

## Stability/Performance Block 10: Qt-Signal-Logging, Async-Postprocess und Source-Visual-Batching

Dieser Block ist bewusst **kein reines Refactoring**. Ausgangspunkt war der gemeldete Laufzeitfehler `TypeError: native Qt signal is not callable` nach bzw. während Trickplay. Der bereitgestellte `crash_state.json` zeigt als letzten Marker einen laufenden Trickplay-FFmpeg-Prozess. Der Marker allein beweist die Exception nicht, passt aber dazu, dass der Async-Postprocess bereits gestartet war, während die aufrufende Ebene noch Logging/Abschlussarbeit ausführte.

Die zentrale Fehlerursache lag an mehreren Grenzen in der Form `getattr(self.log, "info", self.log)(message)`: ein `pyqtBoundSignal` wird nicht wie eine Python-Funktion aufgerufen, sondern über `.emit(...)`. Zusätzlich konnte in `AsyncPostProcessCoordinator.submit()` der Future bereits laufen, bevor ein nachgeschalteter Loggingfehler den Aufrufer in einen synchronen Fallback brachte. Dadurch bestand ein echtes Risiko, NFO/Trickplay für dieselbe Datei **zweimal parallel** zu starten.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/worker/log_dispatch.py` | added | Fail-soft Adapter für DragonLogger, Worker-Logger, normale Callables und native Qt-Signale. | Qt-Signal nur via `.emit`; Level-Semantik; Logging darf Verarbeitung nicht abbrechen. |
| `dragontools/worker/trickplay_service.py` | modified | Sicheres Logging; Eingabepfad wird an den Tool-Lifecycle weitergegeben. | `_run()`-Vertrag unverändert; Trickplay-Erfolg darf nicht an Logging scheitern. |
| `dragontools/worker/postprocess_runner.py` | modified | NFO-/Trickplay-Postprocess nutzt zentralen Log-Adapter. | Ergebnisstatus unabhängig von Loggerform. |
| `dragontools/worker/postprocess_async.py` | modified | Exactly-once Scheduling und fail-soft Completion. | Nach erfolgreichem `executor.submit()` kein synchroner Doppelstart; Completion im `finally`; Shutdown-Lock. |
| `dragontools/worker/tool_process_lifecycle.py` | modified | Lifecycle-Logging via Adapter und konkreter `file_path` im CrashGuard-State. | Timeout-/Abort-Verhalten unverändert. |
| `dragontools/worker/tool_runner.py` | modified | `activity_file` für Diagnose; sichere Callback-/Fehlerlogs. | Rückgabewerte/Timeoutsemantik unverändert. |
| `dragontools/worker/source_visual_check.py` | modified | Orchestrierung/Fassade (379 → 225 Zeilen). | Blockierungsheuristik und private Kompatibilitätsseams erhalten. |
| `dragontools/worker/source_visual_sampling.py` | added | FFprobe-/FFmpeg-Sampling; mehrere Zeitfenster pro FFmpeg-Prozess. | Batchgröße, unabhängige Seeks, Temp-Cleanup, Fallback. |
| `dragontools/worker/source_visual_models.py` | added | Settings/Probe/Result-Modelle. | Defaults/Anzeigeverträge. |
| `dragontools/worker/source_visual_settings.py` | added | QSettings-Mapping. | Bounds und Defaults. |
| `dragontools/worker/source_visual_analysis.py` | added | Pure Bildheuristiken. | Heuristik unverändert zum alten Modul. |
| `dragontools/tests/test_postprocess_signal_logging.py` | added | Reproduziert das Qt-Signal-Verhalten und prüft exactly-once. | Signal-Testdouble verweigert direkten Aufruf explizit mit dem gemeldeten TypeError. |
| `dragontools/tests/test_source_visual_check.py` | modified | Gruppierung und Fallback. | 9 Samples -> 4/4/1; Batchfehler fällt nur für betroffene Gruppe zurück. |
| `dragontools/tests/test_refactor_block10_architecture.py` | added | Architekturgrenzen. | SourceVisual-Fassade bleibt klein; keine direkten `getattr(self.log...)`-Grenzen im Postprocess. |
| `dragontools/tests/test_stability_review_fixes.py` | modified | CrashGuard-Dateipfad. | Letzter Toolzustand enthält künftig die konkrete Videodatei. |

### Laufzeitwirkung der Quellbildprüfung

Die bisherige Quellbildprüfung startete bei 10-%-Intervall für neun Prüfpositionen **neun separate FFmpeg-Prozesse**; bei 5 % waren es bis zu 19. Das neue Sampling gruppiert standardmäßig vier unabhängig seekende Fenster pro Prozess. Im Erfolgsfall bedeutet das **9 → 3** bzw. **19 → 5** FFmpeg-Starts. Scheitert eine Gruppe, wird ausschließlich diese Gruppe über den alten Einzelprobe-Pfad wiederholt.

Lokaler Referenzbenchmark mit einem 60-s-H.264-Testvideo und neun Probe-Fenstern: **4,762 s → 1,966 s (~2,42× schneller)**. Die gelesenen Framegrößen und die daraus berechneten Heuristikergebnisse waren identisch. Auf NAS-Pfaden hängt der tatsächliche Gewinn zusätzlich von Latenz und Seek-Verhalten ab.

### Validierung Block 10

- `compileall`: **OK**.
- Gezieltes Block-10-Regressionsset: **58 bestanden, 1 übersprungen**.
- Zusätzliches Workflow-/Crash-Set: **13 bestanden**; sieben Durable-Write-Tests brechen auf diesem Review-Host bereits bei `os.fsync()` mit `OSError [Errno 5]` ab, bevor der jeweilige Recovery-Testpfad erreicht wird.
- Der im breiteren Lauf zuerst auftretende Cleanup/Rollback-Testfehler reproduziert **identisch auf dem unveränderten Block-9-Stand**.
- Der bekannte DV-Remux-Sidecar-Test reproduziert ebenfalls auf Block 9 und ist keine Block-10-Regression.
- PyQt6 ist im Review-Host nicht installiert. Der konkrete Qt-Fehler wird deshalb mit einem Signal-Testdouble nachgebildet, das direkten Aufruf absichtlich mit `TypeError: native Qt signal is not callable` verweigert und nur `.emit()` akzeptiert.

Wichtig für die Diagnose: `crash_state.json` ist weiterhin ein **Aktivitätsmarker**, kein Beweis, dass FFmpeg selbst abgestürzt ist. Block 10 macht ihn aussagekräftiger, weil Tool-Läufe nun die konkrete Eingabedatei eintragen.

## Refactoring Block 11: MediaAnalyzer-Streams und Renamer-Kandidaten

Nach Block 10 wurden die zwei zuvor objektiv priorisierten Fachmodule zerlegt. Der Schwerpunkt lag auf **klaren Verantwortlichkeiten bei unverändertem Außenvertrag**: `media_analyzer.py` und `movie_renamer.py` importieren weiterhin dieselben Namen aus den bisherigen Fassaden.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/core/media_analyzer_streams.py` | modified | Kompatibilitätsfassade **367 → 21 Zeilen**. | Re-Exports bleiben identisch; keine Fachlogik zurück in die Fassade. |
| `dragontools/core/media_analyzer_video_streams.py` | added | Video-Mapping, Bitrate-Fallback, HDR/DV-Validierung und VideoStream-Erzeugung. | MediaInfo/ffprobe-Priorität, kaputter BPS-Tag, HDR10+/DV-Flags. |
| `dragontools/core/media_analyzer_audio_streams.py` | added | AudioStream-Mapping. | Globaler ffprobe-Index, Sprache, Forced, Channel-Layout und Bitrate. |
| `dragontools/core/media_analyzer_subtitle_streams.py` | added | Subtitle-Codec-Normalisierung, Laufzeit/Eventzahl und SubtitleStream-Mapping. | Bestehende Codec-Prioritäten und MediaInfo/ffprobe-Fallbacks unverändert. |
| `dragontools/core/movie_renamer_candidates.py` | modified | Kompatibilitätsfassade **367 → 33 Zeilen**. | Bestehende private Importnamen für `movie_renamer.py` erhalten. |
| `dragontools/core/movie_renamer_candidate_resolvers.py` | added | Provider-/Resolver-Abfragen und Serien-Lookup-Pfad. | Umlautvarianten, Sprachfallback, Episode-Refresh und Provider-Fallbackreihenfolge. |
| `dragontools/core/movie_renamer_candidate_mapping.py` | added | Providerobjekte/Dictionaries → Movie-/SeriesRenameCandidate. | Generische Episodentitel, Aliasregel, Episode-ID und Confidence-Caps. |
| `dragontools/core/movie_renamer_candidate_scoring.py` | added | Textnormalisierung, Titelähnlichkeit, Film-/Serien-Scoring und Value-Parsing. | Angezeigte Sicherheit bleibt echte Titelähnlichkeit; Staffel/Folge nur als Abzug. |
| `dragontools/core/movie_renamer_candidate_order.py` | added | Providerpräferenz, Sortierung und Limit je Provider. | TheTVDB/TMDB-Abdeckung und Alias-Priorität. |
| `dragontools/core/release_validation_smoke_modules.py` | modified | Alle Block-11-Splitmodule im Paket-Smoke registriert. | Kein neues Modul darf beim Build fehlen. |
| `dragontools/tests/test_power_module_refactor.py` | modified | Neue Größen-/Qt-free-/Fassadengrenzen. | Verhindert erneutes Anwachsen beider Monolithen. |
| `dragontools/tests/test_refactor_block11_analyzer_renamer_architecture.py` | added | Block-11-Vertrags-/Architekturtests. | Stream-Fassade, Episodentitel-Fallback und Providerlimit. |

### Verhaltensvergleich Block 10 → Block 11

Ein separater Differentialtest hat repräsentative Video-/Audio-/Subtitle-Streams, Subtitle-Codec-/Dauer-Parsing, Film-/Serien-Scoring sowie Candidate-Mapping einmal gegen Block 10 und einmal gegen Block 11 ausgeführt. Die serialisierten Ergebnisse waren **byte-identisch**. Damit ist der Block als Strukturänderung validiert und enthält absichtlich keine neue Renamer-/Analyzer-Policy.

### Validierung Block 11

- `compileall`: **OK**.
- Gezieltes Analyzer-/Renamer-/Architektur-/Smoke-Regressionsset: **88/88 bestanden**.
- Direkter Block-10/Block-11-Differentialvergleich: **identisch**.
- Der im breiten Testlauf zuerst auftretende DV-Remux-Sidecar-Test schlägt unverändert auch auf Block 10 fehl und ist daher **keine Block-11-Regression**.
- SQLite-Dateitests und einzelne Durable-Write-Tests bleiben auf diesem Review-Host wegen des bereits dokumentierten `disk I/O error`/`fsync`-Hostproblems kein belastbarer Gesamttestindikator.

## Refactoring Block 12: Audio/Video-Matcher-GUI und Online-Metadaten-Dialog

Die zwei nach Block 11 priorisierten GUI-Monolithen wurden als Strukturblock zerlegt. Der Audio/Video-Matcher behält seine bestehende Worker-Klasse und den expliziten Main-Window-Shutdown-Vertrag; der Online-Metadaten-Dialog behält alle bisherigen QSettings-Schlüssel und Provider-/Cache-Defaults.

| Datei | Status | Aufgabe | Review-Fokus |
|---|---|---|---|
| `dragontools/gui/audio_video_matcher_widget.py` | modified | Schmale QWidget-Fassade **368 → 32 Zeilen**. | Mixin-MRO, Initialzustand und expliziter `iter_shutdown_workers`-Hook. |
| `dragontools/gui/audio_video_matcher_view.py` | added | UI-Aufbau und Running-State. | Signalverdrahtung, Button-Aktivierung und unveränderte UI-Defaults. |
| `dragontools/gui/audio_video_matcher_paths.py` | added | Datei-/Output-Dialoge, Auto-Zielname und Pfadvalidierung. | Keine Änderung an Video-Erweiterungen oder Output-Namensregel. |
| `dragontools/gui/audio_video_matcher_runtime.py` | added | Analyze/Refine/Create-Worker, Signalverdrahtung, Cancel/Finish. | Child-Worker-Lifetime und Shutdown-Discovery. |
| `dragontools/gui/audio_video_matcher_results.py` | added | Analyse-/Cut-Ergebnisse, Audiotrack-Auswahl und Create-Gating. | Fall A/B/C/D, unresolved Cuts und bevorzugte deutsche Audiospur. |
| `dragontools/gui/online_metadata_dialog.py` | modified | Schmale QDialog-Fassade **367 → 27 Zeilen**. | QSettings-Instanz, Geometry und Mixin-Komposition. |
| `dragontools/gui/online_metadata_dialog_view.py` | added | Provider-, Credential-, Sprach-/Cache-Gruppen und Secret-Sichtbarkeit. | Providerwerte `tmdb/thetvdb/both`, Passwort-Echo und Button-Signale. |
| `dragontools/gui/online_metadata_dialog_state.py` | added | Mapping Settings-State ↔ Dialog-Controls. | Defaults, bevorzugter Provider nur bei `both`, Trim/Save-Semantik. |
| `dragontools/gui/online_metadata_settings_state.py` | added | Qt-widget-unabhängiges persistentes Settings-Modell. | Alle bisherigen QSettings-Schlüssel, Typkonvertierung und `sync()`. |
| `dragontools/core/release_validation_smoke_modules.py` | modified | Block-12-Splitmodule im Paket-Smoke registriert. | Kein neues GUI-/State-Modul darf im Release fehlen. |
| `dragontools/tests/test_refactor_block12_matcher_metadata_architecture.py` | added | Fassaden-, Smoke-, Shutdown- und Settings-Roundtrip-Tests. | Verhindert erneutes Zusammenwachsen und Credential-/Provider-Verlust. |

### Validierung Block 12

- `compileall`: **OK**.
- Relevantes Audio/Video-Matcher-, Architektur-, Lifecycle- und Release-Set: **101 bestanden, 1 hostbedingt abgewählt**.
- Der abgewählte CrashGuard-Test scheitert mit demselben `Errno 5` bereits auf dem unveränderten Block-11-Paket; kein Block-12-Regressionssignal.
- Online-Metadaten-State Save→Load: **verlustfreier Roundtrip** für Provider, Preferred Provider, TMDB/TheTVDB Credentials, Sprachen und Cachewerte.
- PyQt6 fehlt auf dem Review-Host weiterhin; daher kein echter Dialog-/Widget-Instantiationstest in dieser Umgebung.


## Post-Review-Härtung 13.09.2026

Die vier Befunde aus dem anschließenden Kontrollreview wurden umgesetzt:

| Befund | Umsetzung | Review-Fokus |
|---|---|---|
| MoveJournal-Archivierung zu weich | `_archive_completed()` meldet den Fehlercallback und wirft anschließend `MoveJournalWriteError`; der Move-Worker zählt die fehlgeschlagene Finalisierung als Fehler. | Kein sauberer Erfolgszustand bei nicht finalisiertem Journal; GUI-Abschluss berücksichtigt `error_count`. |
| Release-Smoke unvollständig | Die 32 fehlenden Splitmodule aus Mediathek, Preflight, Postprocessing und Trickplay wurden in `REFACTOR_SMOKE_MODULES` ergänzt. | Alle 111 im Manifest als `added` markierten Produktivmodule sind jetzt in `_SMOKE_MODULES` enthalten. |
| Episodenrefresh fällt still zurück | Refresh-Exception wird mit Lookup-Datei, Exceptiontyp und Meldung geloggt; vorhandener `Folge XX`-Fallback bleibt erhalten. | Stabiler Fallback ohne stille Providerfehler. |
| EOF-Whitespace in `iso_widget.py` | Überzählige Leerzeile entfernt, Fassade/Shutdown-Hook unverändert. | `git diff --check`/Whitespace-Hygiene. |

Neue Regressionstests prüfen Archivierungsfehler + Callback, Worker-Fehlerzählung, Refresh-Logging und die vollständige Smoke-Liste.

## Objektive Vermessung nach Block 12

Produktiver Python-Bestand: **561 Module / 85,231 LOC**, Median **138 Zeilen/Modul**. Dateien ≥500 Zeilen: **0**, ≥400: **2**, ≥300: **56**, ≤100: **196**. Die beiden bisherigen 367/368-Zeilen-GUI-Monolithen sind jetzt Fassaden; UI-Aufbau, Pfade, Worker-Lifecycle, Ergebnisdarstellung und Settings-Persistenz sind getrennt.

### Top-40 Modulmetriken

| Datei | Zeilen | max. Funktion | max. Branches | max. Klasse | Methoden |
|---|---:|---:|---:|---:|---:|
| `dragontools/core/timeout_settings.py` | 475 | 27 | 7 | 6 | 0 |
| `dragontools/core/settings.py` | 406 | 20 | 6 | 0 | 0 |
| `dragontools/core/mediainfo_details.py` | 394 | 70 | 18 | 8 | 0 |
| `dragontools/core/move_journal.py` | 392 | 117 | 39 | 217 | 16 |
| `dragontools/core/tool_diagnostics.py` | 391 | 158 | 32 | 0 | 0 |
| `dragontools/core/paths.py` | 391 | 37 | 10 | 129 | 19 |
| `dragontools/gui/media_info_text_builder.py` | 382 | 85 | 27 | 0 | 0 |
| `dragontools/worker/audio_video_match_thread.py` | 382 | 65 | 11 | 353 | 17 |
| `dragontools/core/release_validation_package.py` | 380 | 34 | 9 | 0 | 0 |
| `dragontools/worker/converter_thread.py` | 374 | 50 | 8 | 311 | 31 |
| `dragontools/gui/media_library_dialog.py` | 368 | 43 | 5 | 332 | 51 |
| `dragontools/worker/duration_timing_analyzer.py` | 366 | 42 | 24 | 235 | 8 |
| `dragontools/worker/converter_stream_args.py` | 365 | 106 | 21 | 332 | 8 |
| `dragontools/gui/conversion_progress_presenter.py` | 364 | 47 | 15 | 337 | 20 |
| `dragontools/worker/process_control.py` | 362 | 97 | 31 | 0 | 0 |
| `dragontools/core/codec_profile_assistant.py` | 361 | 169 | 3 | 5 | 0 |
| `dragontools/core/online_metadata_tmdb_resolver.py` | 360 | 82 | 17 | 332 | 14 |
| `dragontools/worker/dv_remux_thread.py` | 357 | 67 | 9 | 301 | 17 |
| `dragontools/core/audio_video_frame_analysis.py` | 356 | 56 | 10 | 75 | 6 |
| `dragontools/gui/convert_widget_custom_widgets.py` | 356 | 117 | 4 | 135 | 15 |
| `dragontools/core/error_report.py` | 354 | 58 | 19 | 0 | 0 |
| `dragontools/worker/subtitle_sidecar_service.py` | 351 | 88 | 18 | 192 | 11 |
| `dragontools/gui/merge_widget.py` | 347 | 72 | 8 | 322 | 19 |
| `dragontools/worker/dv_final_mux_service.py` | 343 | 91 | 17 | 325 | 6 |
| `dragontools/gui/encoder_settings_ui.py` | 343 | 99 | 1 | 290 | 6 |
| `dragontools/core/logger_messages.py` | 342 | 74 | 31 | 330 | 15 |
| `dragontools/gui/settings_sections/media.py` | 341 | 231 | 8 | 332 | 5 |
| `dragontools/gui/movie_renamer_table_controller.py` | 340 | 80 | 26 | 299 | 25 |
| `dragontools/core/crash_guard.py` | 340 | 40 | 8 | 0 | 0 |
| `dragontools/gui/main_window_tabs.py` | 338 | 47 | 11 | 319 | 21 |
| `dragontools/worker/iso_thread.py` | 336 | 104 | 22 | 307 | 21 |
| `dragontools/worker/quality_test_thread.py` | 335 | 62 | 21 | 307 | 13 |
| `dragontools/core/movie_renamer_parsing.py` | 335 | 65 | 17 | 0 | 0 |
| `dragontools/core/config_migration.py` | 333 | 70 | 22 | 6 | 0 |
| `dragontools/worker/quality_compare_thread.py` | 331 | 131 | 30 | 303 | 12 |
| `dragontools/worker/tool_runner.py` | 331 | 103 | 16 | 23 | 4 |
| `dragontools/rules/subtitle_selection.py` | 330 | 72 | 15 | 0 | 0 |
| `dragontools/worker/dv_processing_pipeline.py` | 330 | 103 | 7 | 307 | 15 |
| `dragontools/worker/dv_pipeline_stages.py` | 328 | 70 | 16 | 264 | 23 |
| `dragontools/worker/hdrplus_pipeline_coordinator.py` | 320 | 58 | 11 | 262 | 14 |

### Nächste Struktur-/Review-Kandidaten

| Prio | Datei | Zeilen | Warum relevant |
|---:|---|---:|---|
| 1 | `dragontools/worker/process_control.py` | 362 | 97-Zeilen-Funktion und 31 Branches in Abort/Wait/Terminate-Prozesslogik. **Vor einem Split zuerst Sicherheitsreview**, weil Fehler Child-Prozesse hängen lassen oder zu aggressiv beenden können. |
| 2 | `dragontools/worker/audio_video_match_thread.py` | 382 | 353-Zeilen-QThread-Klasse mit Analyse, Cut-Refine, Audio-Sync, FFmpeg-Befehlen, Mux, Outputprüfung und Logging. Nach dem GUI-Split der natürliche nächste Matcher-Block. |
| 3 | `dragontools/core/tool_diagnostics.py` | 391 | 158-Zeilen-Funktion und 32 Branches; Tool-Probing, Auswertung und Berichtserzeugung sind eng gekoppelt und potenziell I/O-lastig. |
| 4 | `dragontools/core/move_journal.py` | 392 | 117-Zeilen-Funktion/39 Branches, aber hohe Datenintegritätsrelevanz. Nur nach separatem Recovery-/Durability-Review refactoren. |

`media_library_series_paths.py` bleibt trotz hoher Branch-Dichte bewusst außerhalb des nächsten Strukturblocks; die bestehende Speicherpfad-/Pfadmapping-Semantik soll nicht unnötig angefasst werden.

## Gezielte Review-Reihenfolge nach Block 12

Zuerst **`process_control.py` fachlich prüfen**, ohne sofort zu splitten. Danach bietet sich `audio_video_match_thread.py` als zusammenhängender Strukturblock an, weil die GUI-Seite jetzt sauber getrennt ist. `tool_diagnostics.py` ist ein guter niedriger-riskanter Folgeblock. `move_journal.py` sollte weiterhin als eigener Datenintegritätsblock behandelt werden.
