# DragonTools V9.8.2 – Post-Review-Härtung 13.09.2026

## Umgesetzte Befunde

1. **MoveJournal-Archivierung fail-closed**
   - Archivierungsfehler melden weiterhin den konfigurierten Fehlercallback.
   - Danach wird `MoveJournalWriteError` geworfen.
   - Der Move-Worker zählt eine fehlgeschlagene Journal-Finalisierung als Fehler und die GUI meldet keinen pauschalen sauberen Move-Abschluss mehr.

2. **Release-Smoke vervollständigt**
   - Die 32 bislang fehlenden Splitmodule aus Mediathek, Preflight, Postprocessing und Trickplay wurden ergänzt.
   - Gegenprobe zum Review-Manifest: **111/111** als neu markierte Produktivmodule befinden sich jetzt in `_SMOKE_MODULES`.

3. **Renamer-Episodenrefresh nicht mehr still**
   - Scheitert der erzwungene Refresh bei `Folge XX`/generischem Episodentitel, bleibt der sichere Fallback erhalten.
   - Lookup-Datei, Exceptiontyp und Fehlermeldung werden geloggt.

4. **ISO-Widget Formatbereinigung**
   - Überzählige Leerzeile am Dateiende entfernt.
   - `iter_shutdown_workers()` bleibt unverändert als expliziter Lifecycle-Hook auf der Fassade.

## Validierung

- Gezieltes Regression-Set: **48/48 bestanden**.
- `compileall`: erfolgreich.
- Python-Paket-Smoke auf dem gepatchten Quellstand: **OK**.
- Manifest-vs.-Smoke-Abgleich: **111 hinzugekommene Produktivmodule, 0 fehlend**.
- `git diff --no-index --check`: keine Whitespace-Fehler.
- Der bekannte Review-Hostfehler `os.fsync() -> OSError [Errno 5]` bleibt bei älteren durable-write-Tests reproduzierbar und ist nicht durch diesen Patch entstanden. Der neue Archivierungs-Regressionsfall ist bewusst host-fsync-unabhängig aufgebaut.
