# DragonTools V9.8.3 Stabilitäts-Patch

Quellabnahme: 14.09.2026. Basis: 9.8.2-Stand inklusive Review-Patches bis v12. Öffentlicher Stand: 15.09.2026.

## Umgesetzte Korrekturen

1. Cleanup-Warnungen und Fehler bleiben terminal erhalten. Hintergrund-Nachbearbeitung darf daraus keinen Erfolg machen; Auto-Move bleibt für solche Ergebnisse gesperrt.

2. Nachbearbeitungsaufträge besitzen eigene Prozess-Slots. Timeout, Abbruch und Pause verwenden die konkrete Prozessinstanz; ein lokaler Auftrag darf keinen parallelen Auftrag beenden. Ein ausdrücklich angeforderter Batch-Abbruch gilt weiterhin für den gesamten Batch.

3. Normaler MP4-Remux prüft Abbruch erneut nach Sidecar-Arbeit und unmittelbar in der finalen Dateitransaktion. Vor dem Commit eingegangene Abbrüche erhalten das Original und rollen Sidecars zurück. Ein unvollständiger Rollback bewahrt Staging und Journal zur Recovery.

Abbruch ist kooperativ: Ein bereits abgeschlossenes atomares Dateisystem-Replace kann nicht rückwirkend verhindert werden. Die Prüfung liegt unmittelbar vor dem Commit und beim Containerwechsel nochmals vor dem Original-Cleanup; bei einem dort erkannten Abbruch wird die Installation zurückgerollt. Bereits sicher installierte Ausgaben werden nicht blind gelöscht.

## Regressionen und Validierung

`test_stability_983.py` prüft Statusreihenfolge und konkurrierende Callback-Abschlüsse, GUI-Move-Sperren, echte Prozessisolation, Pause-Zuordnung und Abbruch während der finalen Transaktion einschließlich Sidecar-Rollback.

Vollständiger lokaler Testlauf mit der vorhandenen .venv: 1390 bestanden, 0 fehlgeschlagen, 0 übersprungen. Enthalten sind 20 neue Stabilitäts-Regressionsfälle und beide realen DV/HDR-Roundtrips. Qt- und DV/HDR-Integration waren ausdrücklich erforderlich, nicht optional übersprungen. Weitere Validierungsergebnisse und Dateiprüfsummen stehen in PATCH_MANIFEST.json.

Der öffentliche Quellstand ist anonymisiert und dient als Grundlage des 9.8.3-Windows-Builds. Die Tests ersetzen keine vollständige Hardware-Encoder-/Medienmatrix. Der Windows-Neustartschutz ist keine garantierte Sperre gegen erzwungene Update-Neustarts; in diesem Patch wurde er nicht verändert.
