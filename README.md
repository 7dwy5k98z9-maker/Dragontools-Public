# DragonTools V9.9.0

> Stand 08.10.2026: Dragon Tools V9.9.0 übernimmt die Korrekturen der 29 Patch-/Review-Schritte, die automatische TheTVDB-Token-Erneuerung und den gezielten Fallback bei beschädigter Dolby-Vision-RPU. Die Fachkapitel erläutern die wirksamen Datei-Profile, sichere Ausgabeinstallation, abbrechbare Quellbildprüfung und konsistente Pipeline-Verträge. Einzelne Worker: Rechtsklick → pausieren/fortsetzen. Die technische Historie steht in `PATCH.md`.

DragonTools ist eine Windows-Anwendung zur Analyse, Konvertierung und Verwaltung von Video-, Audio- und Untertiteldateien. Das Projekt bündelt die benötigten Drittanbieterprogramme nicht im Git-Repository. Sie müssen separat von den jeweiligen Projektseiten heruntergeladen werden.


## Korrekturen vom 08.10.2026

- Timestamp-Reparatur berücksichtigt die verlässliche Bildrate und Laufzeit des Originals. Ein erfolgloser Remux verhindert diese Prüfung nicht; unsichere Reparaturen bleiben gesperrt.
- Entfernte, abgeschlossene oder abgebrochene Dateien lassen sich erneut hinzufügen, sobald kein aktiver Auftrag mehr dieselbe Datei verarbeitet.
- Journal-Wiederherstellung läuft beim Start im Hintergrund. Abgeschlossene Verschiebevorgänge ohne ausstehendes Cleanup lösen keine erneute vollständige Dateiprüfung aus.
- Beim Einfügen von Untertiteln werden gültige Schriftanhänge auch dann akzeptiert und erhalten, wenn ffprobe keinen Codec-Namen für sie meldet.
- WebVTT wird zwischen MediaInfo und ffprobe korrekt zugeordnet. Die globale Spurposition bleibt unabhängig von der Untertitelanzahl.
- Strip-only schreibt die erwarteten Audiotitel, Sprachangaben sowie Default-/Forced-Kennzeichnungen und besteht dadurch die finale Ausgabeprüfung.

Die gezielte Abnahme der WebVTT-/Strip-only-Korrektur umfasst 95 bestandene Tests. Zusätzlich bestand eine echte betroffene Episode die Strip-only-Ausgabeprüfung; ihr Original blieb unverändert. Die Prüfung früherer Korrekturen wurde jeweils mit den betroffenen Regressionstests durchgeführt.

### Veröffentlichungsprüfung vom 08.10.2026

Die aktuelle Standardtestsuite besteht mit **5.234 bestandenen Tests**, 18 übersprungenen Fällen und 24 abgewählten DV/HDR-Integrationstests. Datenschutz-, Syntax-, Architektur-, Paket- und EXE-Startprüfung bestanden. Der neue Quellstand umfasst 1.304 Python-Dateien und 375 Testdateien mit 3.326 statisch erkannten Testfunktionen. Die folgenden Inventar- und Abnahmeangaben vom 07.10.2026 beschreiben den ursprünglichen 9.9.0-Stand; aktuelle Release-Hinweise stehen in `RELEASE_NOTES_v9.9.0.md`.

## Stand 9.9.0 – 08.10.2026

**Release-Schwerpunkte V9.9.0:** 29 abgeschlossene Review-Schritte, einzeln steuerbare Worker, aufgenommene Dateioptionen, verlässliche Zielwahl, geprüfte Spurmetadaten und wiederholbare Recovery bei späten Fehlern. TheTVDB-Token-Erneuerung, Quell-RPU-Fallback und asynchrone Quellbildprüfung bleiben enthalten.

Normalisierter FFmpeg-AutoCrop ist die verbindliche physische DV-Crop-Quelle. Finaler RPU-Nachweis schützt das Original auch bei exakter Geometrie. Zieländerungen während laufender Aufträge sind an der Move-Transaktionsgrenze abgesichert. Renamer unterstützt Staffel-, Episoden- und Jahreskorrekturen. Queue-Reihenfolgeaktionen sind in Haupt- und Zoomfenster verfügbar; der HDR10+-Generator ist gegen fehlende Farbraumdaten und hängende Analyseprozesse gehärtet.

- Cleanup-Warnungen und Fehler bleiben terminal erhalten. Hintergrund-Nachbearbeitung darf daraus keinen Erfolg machen; Auto-Move bleibt für solche Ergebnisse gesperrt.
- Nachbearbeitungsaufträge besitzen eigene Prozess-Slots. Timeout, Abbruch und Pause verwenden die konkrete Prozessinstanz; ein lokaler Auftrag darf keinen parallelen Auftrag beenden. Ein ausdrücklich angeforderter Batch-Abbruch gilt weiterhin für den gesamten Batch.
- Normaler MP4-Remux prüft Abbruch erneut nach Sidecar-Arbeit und unmittelbar in der finalen Dateitransaktion. Vor dem Commit eingegangene Abbrüche erhalten das Original und rollen Sidecars zurück. Ein unvollständiger Rollback bewahrt Staging und Journal zur Recovery.
- Die Haupt-Tab-Leiste und der Renamer erzwingen keine überbreite Mindestgröße mehr. Renamer-Aktionen sind mehrzeilig angeordnet; Tabellenspalten lassen sich frei skalieren, ein-/ausblenden und persistent speichern. OK, Typ und Hinweise sind in der Standardansicht ausgeblendet.
- Renamer-Regeln Schema 3 ergänzt eine eigene Releasegruppen-Liste: bekannte Gruppen wie `STARS` können am Anfang/Ende des Release-Namens gefiltert werden. Serienmuster `E05S06` werden als Staffel 6 / Episode 5 erkannt; bei `EP01` ohne Staffel fragt DragonTools vor der Providerabfrage ausdrücklich nach der Staffel.
- SDR→HDR über ComfyUI/HDRTVDM ist als Voll-Datei-Pfad nutzbar, kann ComfyUI bei Bedarf automatisch starten und lässt sich pro Datei über den Override aktivieren/deaktivieren. Ein gemessener 1080p-Praxiswert auf einer RTX 4080 SUPER liegt bei ungefähr **4:1 Konvertierungsdauer zu Filmdauer**; das ist ein Richtwert, keine Leistungszusage.
- Der **Dragon HDR10+ Generator 0.2.0** analysiert vorhandene PQ/BT.2020-Videos framegenau, erzeugt ein `hdr10plus_tool`-kompatibles ST-2094-40-Profile-A-JSON und ist sowohl direkt per CLI als auch aus DragonTools nutzbar. DragonTools kann HDR10+ nach SDR→HDR sowie bei geeigneten HDR10-HEVC-Remux-/Strip-Only-Ausgaben erzeugen, injizieren und final verifizieren.
- Source-Releases besitzen jetzt einen einzigen kanonischen Inventarvertrag: BAT und Python-Packager verwenden dieselbe Implementierung. Python-Quellen werden im Public-ZIP ebenfalls anonymisiert und AST-basiert auf hart codierte Secrets geprüft; die In-Process-Bytecode-Ausnahme gilt nur für tatsächlich geladene DragonTools-Module. Private Snapshot-/Review-Artefakte bleiben aus öffentlichen Source-ZIPs heraus; der finale Windows-Build startet nach PyInstaller die tatsächlich gebaute DragonTools-EXE mit einem echten Qt-`QApplication`-Smoke.
- Der HDR10+-Scanner speichert seine 64 Szenenerkennungs-Histogrammbins pro Frame kompakt als `uint32` statt als Python-Floattupel. Bei 2 h/24 fps sinkt allein dieser Histogrammanteil rechnerisch von rund 344 MiB auf rund 55 MiB; die Distanzberechnung bleibt mathematisch gleich.
- Die HDR-Einstellungen sind direkt erreichbar: **Einstellungen → 🌈 SDR → HDR / ComfyUI** sowie **Einstellungen → ✨ Dragon HDR10+ Generator**. Die Help-Datei besitzt dafür eigene Kapitel zu SDR→HDR/HDRTVDM, dem Generator sowie HDR-Erkennung/Datei-Overrides/Strip-Only.
- Der Renamer besitzt einen **🌐 Metadaten-Browser**: Serien und Filme können ohne vorher importierte Datei direkt bei TMDB/TheTVDB gesucht werden. Serienfolgen lassen sich per Drag & Drop oder Automatik auf Episoden abbilden; 1–4 aufeinanderfolgende Episoden pro Datei werden als `S01E01E02...` übernommen. Die Zuordnung wird anschließend als normaler Renamer-Vorschlag übernommen und erst dort endgültig ausgeführt.
- Rechts neben den Queue-Pfeilen stehen Schnellschalter für **HDR+ Generator**, **SDR → HDR** und **Watch-Folder**. Ein synchroner Start-Lock plus Queue-/Worker-Deduplizierung schützt zusätzlich gegen reentrante Doppelstarts derselben Datei.
- Im Converter steht zusätzlich **„Watchfolder durchsuchen“** bereit. Der manuelle Sofortscan durchsucht alle aktivierten Watch-Regeln auch bei ausgeschalteter Automatik, ergänzt nur noch nicht verarbeitete/nicht bereits eingereihte Dateien und startet im Leerlauf keinen neuen Batch. Bei laufender Konvertierung werden Treffer über die bestehende Live-Queue nachgereicht.
- Regel-/Profil-Simulator und Medieninfo/DragonTools-Reiter verwenden für den angezeigten **Ausgabecontainer** dieselben Einstellungen wie die reale Pipeline. `DV → MKV` und `Standard → MP4` werden daher nicht mehr durch historische Defaultcontainer falsch angezeigt.

Abbruch ist kooperativ: Ein bereits abgeschlossenes atomares Dateisystem-Replace kann nicht rückwirkend verhindert werden. Die Prüfung liegt unmittelbar vor dem Commit und beim Containerwechsel nochmals vor dem Original-Cleanup; bei einem dort erkannten Abbruch wird die Installation zurückgerollt. Bereits sicher installierte Ausgaben werden nicht blind gelöscht.

Aktueller Quellstand vom 07.10.2026: **1.298 Python-Dateien/Programme, 208.363 Gesamtzeilen und 176.045 Codezeilen (nichtleer, keine reinen Kommentarzeilen). Testpakete: 376 Python-Dateien, davon 370 test_*.py mit 3.293 statisch erkannten Testfunktionen. Produktivcode ohne Tests: 922 Dateien, 129.338 Gesamtzeilen und 111.387 Codezeilen.** Inventar pro Datei: `PROJECT_INVENTORY_9.9.0.json`.

| Testübersicht | Anzahl |
|---|---:|
| Testdateien | 370 |
| Statisch erkannte Testfunktionen | 3.293 |
| Bestandene Testfälle der Gesamtsuite (Abnahme Patch 29) | 5.152 |
| Bestandene native DV/HDR-Testfälle | 23 |
| Bestandene Testfälle insgesamt | **5.175** |

Abnahme vom 07.10.2026: 14 Tests im allgemeinen Lauf und 2 im nativen Lauf übersprungen. Die beiden Läufe prüfen getrennte Fälle; zusätzliche Fokus- und Exportprüfungen werden nicht nochmals zur Gesamtzahl addiert. Parametrisierte Testfälle erklären den Unterschied zur Zahl statischer Testfunktionen.

### Verhalten nach den Review-Patches

**Einstellungen und Backups:** Einstellungen werden vor dem Speichern vollständig validiert; versteckte Dialogbereiche werden nicht unbeabsichtigt mitgeschrieben. Nicht entschlüsselbare DPAPI-Secrets bleiben erhalten. Backup-Restore prüft Format, Typen und Secret-Verfügbarkeit vor Änderungen und schreibt Dateien mit atomarem Austausch. Fehlgeschlagene Profilpersistenz veröffentlicht keinen neuen In-Memory-Stand. Timeout-Einstellungen behalten vorhandene Sekundenwerte.

**Prozesse und Diagnose:** Timeout und Sofortabbruch beenden den zum Auftrag gehörenden Prozessbaum. Leere Logpfade, Symlinks und Junctions werden vor destruktiven Hilfsoperationen abgewiesen. Parallele Logs und Berichte erhalten getrennte Dateinamen; Diagnosepakete maskieren Zugangsdaten und prüfen die Herkunft der eingelesenen Dateien. Ein nicht verfügbares Tool oder ein fehlgeschlagener Prozessstart wird als Fehler gemeldet.

**Primärvideo und HDR Erkennung:** Analyse und Pipelinewahl beziehen sich auf die primäre Videospur. FFmpeg-Streamindex und Matroska-Tracknummer bleiben getrennte Kennungen. HDR10+ oder Dolby Vision auf einer zweiten Videospur schaltet die primäre Pipeline nicht um. BT.2020-Primaries allein beweisen kein HDR. Unplausible Einheiten, fehlende Probewerte und widersprüchliche DV-Profile werden konservativ ausgewertet; der Medienvertrag prüft auch das erwartete DV-Profil.

**Vorschau und Datei Overrides:** Preflight, Regelvorschau, Medieninfo und Worker verwenden die wirksamen Einstellungen pro Datei. Globale Werte, zugewiesenes Encoderprofil und direkte Datei-Overrides werden in derselben Priorität zusammengeführt. DV-/HDR10+-Erhalt, Generatoranforderung und Container dürfen dadurch nicht auseinanderlaufen. Ungültige Container werden sichtbar abgelehnt. Verspätete Metadatenantworten überschreiben keine neuere Benutzereingabe.

**Encode Planung und Bildproben:** Unbekannte Pipelinebezeichnungen werden als Fehler beendet. Auto-Crop, IMAX und Frame-Probes übernehmen keine Ergebnisse eines fehlgeschlagenen Tools. Eine nicht mehr vorhandene Bilduntertitel-Auswahl brennt keine andere Spur ersatzweise ein. Windows-Pfadvarianten führen zum selben Datei-Override; Encoderregler und gespeicherte Optionen werden vor dem Einsatz auf gültige Werte geprüft.

**Laufsteuerung und Übergabe:** Der Start-Lock bleibt beim Übergang von Konvertierung zu Verschieben aktiv; auch Move-Only besitzt einen Doppelstartschutz. Aktive Ergebnis- und Recovery-Zustände bleiben beim Bearbeiten der Queue erhalten. Fehlgeschlagene Workerstarts lösen reservierte Zustände kontrolliert auf. Logging- und Benachrichtigungsfehler dürfen ein verifiziertes Medienergebnis nicht in einen falschen Abschlusszustand versetzen. Pause steuert auch den aktiven Move-Worker.

**Dolby Vision und beschädigte RPU:** DV-Erhalt verlangt finale RPU-Evidenz im tatsächlichen Bitstream und eine verlässliche Frame-Parität; Containersignalisierung allein genügt nicht. Bei der Quell-RPU-Extraktion in STEP 3/7 können eindeutig unbrauchbare RPUs oder die dovi_tool-Signatur Invalid RPU last byte den konfigurierten einmaligen Neuplanungsversuch auslösen. Nur Dolby Vision wird für diese Datei deaktiviert. HDR10+-Policy, Audio, Untertitel und Encoderprofil bleiben erhalten. Dieselbe Signatur bei Injection oder Verifikation sowie andere DV-Fehler bleiben harte Fehler.

**DV Remux und finale Installation:** DV-Remux verwendet die ausgewählte Videospur und die zum jeweiligen Tool passende Trackkennung. Finale Verifikation prüft die echte RPU sowie erwartete Track- und Default-Flags. MOV_TEXT wird für MKV als SRT geplant. Unbekannte Container werden abgelehnt. Ein rechtzeitig erkannter Abbruch verhindert den finalen Commit; bei einem Verifikationsfehler bleibt ein brauchbarer Kandidat für Diagnose und Wiederaufnahme erhalten.

**HDR10 Plus Erzeugung und Verifikation:** Der HDR10+-Postprozess erzeugt, injiziert und verifiziert Metadaten im fertigen Output. Planner und Generator prüfen denselben PQ-/BT.2020-Quellvertrag. JSON-Struktur, Frameanzahl, Generatorausgabe und injizierter Bitstream müssen zusammenpassen. Bei einem Pflichtfehler bleibt der Job fehlgeschlagen; verwertbare Video-, JSON- und Bitstream-Kandidaten bleiben erhalten. AV1 übernimmt bildabhängige HDR10+-Metadaten nach Bildänderungen nicht ungeprüft.

**SDR zu HDR Auftragszuordnung:** ComfyUI-Output und Manifest müssen zum aktuellen Auftrag gehören; ein alter erfolgreicher Output bestätigt keinen neuen Job. Nach einem Fehler der History/API wird ein bereits gesendeter Auftrag kontrolliert abgebrochen. Auch der letzte Encoder- oder Mux-Schritt erhält die wirksamen Einstellungen des jeweiligen Datei-Overrides.

**Audio und Synchronität:** Audioplan, FFmpeg-Mapping, Tracktitel und Default-Flags beschreiben dieselben ausgewählten Streams. Ein Abbruch während der Abschlussprüfung verhindert den Audio-Mux-Commit. Kanal-, Sprach- und Codecentscheidungen werden konservativ normalisiert. Bereits geprüfte Quellen werden bei einem fehlgeschlagenen Staging- oder Installationsschritt nicht überschrieben.

**Untertitel und OCR:** Untertitel behalten eindeutige Streamzuordnung, Sprache und Flags. Die MP4-Policy unterscheidet interne Textspuren von externen Bilduntertiteln; MOV_TEXT wird bei MKV-Zielen konvertiert. Ein fehlgeschlagener PGS-/VobSub-OCR-Lauf entfernt keine originale Bilduntertitelspur. Pflicht-Sidecars müssen vollständig erzeugt sein, bevor ein Auftrag als erfolgreich veröffentlicht wird. Lange Hilfsprozesse verwenden denselben Abbruch- und Timeoutvertrag wie der Job.

**Output und Reparatur:** Der finale Soll-/Ist-Vergleich prüft Video, dynamische HDR-Metadaten, Audio, Untertitel, Dauer und geplanten Container. Reparaturkandidaten werden getrennt erzeugt und erneut verifiziert. Unsichere Timestamp- oder Frame-Ergebnisse werden nicht als Erfolg installiert. Ein Pflichtfehler nach dem Encode schützt verwertbare Kandidaten vor generischem Cleanup und sperrt Auto-Move sowie den Erfolgsstatus.

**NFO und Nachbearbeitung:** Vorbereitete NFO-Dateien werden erst nach erfolgreicher Konvertierung und Verifikation committed. Nachbearbeitung, Trickplay und Jellyfin-Refresh bleiben an den tatsächlichen Ergebnis- und Zielpfad gebunden. Ein fehlgeschlagener Pflichtschritt darf weder einen zweiten asynchronen Auftrag auslösen noch einen zuvor fehlgeschlagenen Medienjob nachträglich als Erfolg melden.

**Verschieben und Wiederaufnahme:** Move prüft Zielkonflikte, Sidecars, Journale und Pfadidentität an der Transaktionsgrenze. Der im Preflight bestätigte Zielpfad bleibt maßgeblich. Datenträgerübergreifende Transfers werden vollständig gestaged und verifiziert, bevor die Quelle entfernt wird. Abbruch, fehlgeschlagener Rollback und ausstehendes Cleanup bleiben im Journal sichtbar; Recovery darf keinen unvollständigen Transfer als abgeschlossen behandeln.

**Watch Folder und parallele Queue:** Watch-Intake und Live-Queue ordnen Dateien und Profile eindeutig zu und verhindern Doppelstarts. Bereits manuell eingereihte Dateien werden nicht nachträglich als Watch-Aufträge übernommen. Geänderte Worker-Limits starten nur zulässige wartende Jobs; bei Pause und Abbruch kommen keine neuen hinzu. Journale und Wiederaufnahme behalten den richtigen Auftrag und den tatsächlichen Bearbeitungszustand. Bei mehreren aktiven Workern öffnet ein Rechtsklick auf die laufende Videodatei „Worker pausieren“ beziehungsweise „Worker fortsetzen“. Nur der zugehörige Worker wird angehalten; andere Worker laufen weiter. Die pausierte Datei belegt ihren Worker-Platz weiter. Eine globale Pause hat Vorrang, und alte Menüaktionen können keinen neuen Auftrag steuern.

**ISO Merge und MP4 Remux:** ISO-Import, Merge und normaler MP4-Remux verwenden geprüfte Toolresultate und getrennte Staging-Ausgaben. Der normale MP4-Copy-Pfad lehnt dynamisches HDR ab, wenn dessen Erhalt nicht nachgewiesen werden kann. Genau eine geplante Videospur wird übernommen. Audiozeitversatz bleibt erhalten; Abbruch vor der Installation schützt das Original und kontrolliert zugehörige Sidecars.

**Renamer und Episodenzuordnung:** Namensparser, Staffelkorrektur, Episodenmapping und Vorschlagsanzeige verwenden denselben Datensatz. Ungültige Episodenwerte und mehrdeutige Zuordnungen werden nicht still ausgeführt. Benutzerauswahl und manuelle Korrekturen bleiben erhalten; die endgültige Dateiumbenennung erfolgt erst nach bestätigtem Vorschlag.

**Online Metadaten und TheTVDB Token:** Ein optional manuell hinterlegtes TheTVDB-Bearer-Token wird zunächst verwendet. Fehlt es oder wird es als nicht autorisiert abgelehnt, fordert DragonTools mit gültigem API-Key und optionalem Subscriber-PIN ein neues Token an, speichert es über die Secret-/DPAPI-Verwaltung und wiederholt den fehlgeschlagenen Request genau einmal. Parallele Clients teilen einen Refresh-Lock und können ein bereits erneuertes Token übernehmen. Speicherfehler werden protokolliert; ein gültiges neues Token bleibt für die Sitzung nutzbar. Transiente Providerfehler werden nicht als dauerhafter Kein-Treffer-Cache gespeichert; Provider-IDs und Titelidentität werden vor automatischer Übernahme geprüft.

**Mediathek und SQLite:** Mediathek-Schema, Migration, Scan und Suche erhalten die plattformgerechte Pfadidentität. Normalisierte Pfadschlüssel verhindern doppelte Datensätze für dieselbe Windows-Datei. Stream-Snapshots werden zusammen mit dem Mediendatensatz aktualisiert; NFO-Import und Fix Queue prüfen Datenherkunft und Quelländerungen. Bestehende Datenbanken werden vor darauf aufbauenden Abfragen migrationssicher ergänzt.

**Hauptfenster und Tab Lebenszyklus:** Mindestens ein Haupt-Tab bleibt sichtbar. Beim Start wird die vollständige Tab-Liste vor der Sichtbarkeitsprüfung angelegt; sind alle Tabs gespeichert ausgeblendet, wird bevorzugt der Standardcodec-Tab wieder geöffnet und gespeichert. Geladene versteckte Tabs erhalten neue Einstellungen. MediaInfo- und Quellbild-Worker nehmen am globalen Shutdown teil; spätere Startcallbacks sind an den Fenster-Lebenszyklus gebunden. Nicht geladene entfernte Tab-Widgets werden freigegeben.

**Datei-Profile und verbindlicher Zielordner:** Die im Preflight ausgewählte Serienfassung und der geplante Zielordner bleiben nach dem Schließen des Dialogs verbindlich. Titel, Jahr und Medienbereich gehören zur Auswahl; Änderungen verwerfen alte Auflösungen. Dateioptionen, Profile und Warteschlangeneinträge werden tief aufgenommen. Ungültige CRF-/Trackwerte werden vor dem Start abgewiesen; spätere GUI-Änderungen verändern laufende Aufträge nicht.

**Qualität, Quellbildprüfung und Matcher:** Die Quellbildprüfung läuft im Hintergrund und lässt sich bei Tool-Aufrufen abbrechen. Qualitätssuche und Auswertung prüfen tatsächlich erzeugte Dateien und die maßgebliche Ausgabegeometrie; temporäre Ergebnisse gehören zum jeweiligen Auftrag. Der Matcher unterscheidet Offset, Drift und Schnittbereiche. Zusätzliche Zielbereiche ohne passende deutsche Audioentsprechung werden nicht unsicher automatisch zugeordnet.

**Release und Datenschutzprüfung:** Version 9.9.0 ist zentral definiert. Öffentliche Quellarchive prüfen private Pfade und Secret-Literale in Text, Python, DOCX und PDF; ihre Archivinstallation schützt vorhandene Dateien. Build- und CI-Anforderungen verwenden denselben Laufzeitvertrag. Ein Windows-Smoke prüft echte Qt-Widgets, JPEG und OpenCV. Die Source-Abnahme ist keine vollständige Hardware- oder Tool-Bundle-Abnahme; dokumentierte optionale Komponenten benötigen gesonderte Nachweise.

**Auftragsbesitz und Abschluss der Nachbearbeitung:** Die asynchrone Nachbearbeitung gilt erst als abgeschlossen, wenn auch ihre registrierten terminalen Rückmeldungen abgearbeitet sind. Gleichzeitig Wartende sehen denselben Abschluss beziehungsweise Fehler. Defaults und Dateioptionen werden vor externen Erkennungen tief aufgenommen. Metadatenanwendung, Geometrieplanung und Move-Ergebnis besitzen klare gemeinsame Grenzen; die dokumentierten Architekturgrenzen wurden nicht zur Umgehung von Prüfungen erhöht.

**Spurverträge und Container-Metadaten:** Preflight, Planung und Laufzeit verwenden dieselben effektiven Container- und Dateioptionen. Audio-/Untertitel-Titel, Sprache sowie Default-/Forced-Auswahl werden nach dem Mux zurückgelesen. MKV-Audio-Forced und MP4-Untertitel-Forced werden passend zum Container gesetzt; eine Audio-Forced-Auswahl wird in MP4 nicht als Untertitelrolle ausgegeben. MP4-Metadaten werden am eigenen Kandidaten vor der rein lesenden Verifikation abgeschlossen. Quell-Streamindizes bleiben von Output-Spur-IDs getrennt.

**Fehler, Wiederaufnahme und Recovery-Dateien:** Scheitert ein Pflichtschritt nach erfolgreicher Videoverifikation, bleibt der brauchbare Kandidat erhalten und der Auftrag im Fehlerstatus. Das gilt auch beim späten Abbruch. Gesperrte Sidecar-Rollbacks behalten Journal, Staging und Backups und lassen sich nach Freigabe wiederholen. Vorbereitete NFO-Dateien behalten einen Besitzer bis zur sicheren Bereinigung. Beim Verschieben wird der Identitätsnachweis vor dem Hardlink gespeichert; ohne passenden gespeicherten Nachweis bleiben Quelle und Ziel bei Recovery erhalten.

**Abschlussprüfung und dokumentierte Grenzen:** Bei der dokumentierten Abnahme nach Patch 28 wurden alle damaligen Patch-/Review-Schritte nacheinander mit Bericht und geprüftem Projekt-ZIP abgeschlossen. Die finale Prüfung umfasst die eingeschränkte Pairwise-Vertragsmatrix, reale FFmpeg-Dateien, native DV/HDR10+-Rückleseprüfungen und längere parallele Queue-Abläufe mit Umordnen, einzelner Pause und verspäteten Rückmeldungen. AV1-DV/HDR10+-Beta-Pfade sind gesonderte Planungsnachweise; nicht jede Matrixkombination wurde nativ kodiert. Test-Skips und fehlende optionale Hardware-/Online-/Generator-EXE-Abnahmen sind in PATCH_28_REPORT.md ausdrücklich aufgeführt.

**Frühe DV Prüfung und sichere Filmersetzung:** Vor einem HEVC-Dolby-Vision-Encode wird die vollständig gelesene Quell-RPU schnell anhand vorhandener Frame-Metadaten oder einer Schätzung aus Videodauer und Bildrate auf plausible Länge geprüft. Eine vollständige Quellvideozählung entfällt. Kleine Abweichungen werden toleriert; der exakte RPU-/Frame-Abgleich nach dem Encode bleibt verbindlich. Der AV1-DV-Pfad prüft weiterhin die tatsächlich vorhandenen und gelesenen RPU-Daten. Offensichtlich unbrauchbare RPUs können ausschließlich für diese Datei einen erneuten Plan ohne Dolby Vision auslösen. Die Option steht unter Einstellungen → Quellbildprüfung → Dolby Vision – Quell-RPU und ist standardmäßig eingeschaltet. HDR10+, Audio-, Untertitel-, Qualitäts- und Dateioptionen bleiben erhalten. Bei ausgeschalteter Fallback-Option führen unbrauchbare RPUs zu einem Fehler. Spur-/Toolfehler und Abbruch lösen keinen Wechsel ohne DV aus. Fehlt eine brauchbare Framezahl für den schnellen Vergleich, wird dies protokolliert und der exakte Abgleich nach dem Encode bleibt erforderlich. Vor und nach dem Encode werden getrennte Prüfergebnisse protokolliert. MKV-Muxer übernehmen aus jeder Audio-/Untertitelquelle nur ausdrücklich ausgewählte Spuren; nicht ausgewählte gleiche Untertitel blockieren eine eindeutig ausgewählte PGS-Spur nicht. Der fertige Medienvertrag wird vor dem Ersetzen geprüft. Filmersetzung und Matching verwenden dieselbe Normalisierung für Unicode, Bindestriche, Apostrophe und Dateinamen. Jahr, Edition, vorhandene Metadata-IDs und Mehrdeutigkeit schützen verschiedene Filme. Vorbereitete Identität und Ziel bleiben verbindlich; gescheiterte Dateitausche bewahren den guten Altbestand und Recovery-Dateien. PATCH_29_REPORT.md erläutert Prüfungen und Grenzen.

**V9.8.6 Patch BH:** Bei Dolby-Vision-Jobs wird der Encode-Slot direkt nach erfolgreichem HEVC-Encode freigegeben. DV/HDR10+-Injection und Final-Mux der vorherigen Datei können dadurch parallel zum Encode der nächsten Queue-Datei weiterlaufen, ohne die konfigurierte Zahl gleichzeitiger Encodes zu überschreiten. Der Dragon HDR10+ Generator meldet während langer Bildanalysen regelmäßig Frames, Prozent, Analyse-FPS, Laufzeit und ETA.

**V9.8.6 Patch BJ:** Fehlschlägt nach bereits erzeugter HDR10+-JSON die DV/HDR10+-Injection oder der finale HDR10+-Nachweis, wird der Kandidat vor dem temporären Cleanup in ein eigenes `Archiv/...__DV_HDR10PLUS_FAILED__...`-Diagnosepaket verschoben. Gesichert werden der finale MKV/MP4-Kandidat bzw. der weitest fortgeschrittene HEVC-Stream, die erzeugte HDR10+-JSON, die Verify-JSON und – sofern vorhanden – die tatsächlich verwendete sowie weitere RPU-Varianten. Das Original bleibt unangetastet.

**V9.8.6 Patch BP:** Der optionale FFmpeg/libplacebo-SDR→HDR-Pfad verwendet jetzt dieselbe encoderabhängige 10-bit-Filterformat-Policy wie DV/HDR10: CPU/libx265 bleibt planar in `yuv420p10le`, Hardwareencoder verwenden `p010le`. DV-P5-Verbose-Logs melden das tatsächlich aktive Pixelformat statt pauschal `p010le`; die bewusst gesetzten x265-Parameter `bframes=8` und `rc-lookahead=40` bleiben unverändert.

**V9.8.6 Patch BI:** DV/HDR-Nachbearbeitung besitzt jetzt ein separates Limit von vier schweren Postprocessing-Jobs. Die Encode-Slot-Freigabe verwendet ein eigenes Ereignis statt des historischen `🧩`-NFO/Trickplay-Status. Bildzahlen werden als strukturierte Nachweise mit Herkunft und Verlässlichkeit geführt: tatsächliche FFmpeg-Encode-Frames und vollständig analysierte HDR10+-Frames sind verlässlich; `FPS × Dauer` bleibt ausschließlich eine gekennzeichnete Fortschrittsschätzung. Im normalen DV/HDR10+-Ablauf wird kein zusätzlicher `ffprobe -count_frames`-Vollscan mehr gestartet.

**V9.8.6 Patch BS/BT:** Der Converter besitzt einen synchronen `start_reserved`-Schutz gegen das kurze Startfenster vor `QThread.isRunning()`. Der Renamer wurde um den provider-expliziten Metadaten-Browser mit Film-/Seriensuche, Staffel-/Episodenansicht, Ordner-Drop und 1–4-fach-Folgen erweitert. Preview und Medieninfo übernehmen den tatsächlich konfigurierten Standard-/DV-Ausgabecontainer.

**V9.8.6 Patch BU:** Asynchrone Metadatenabfragen sperren jetzt alle semantischen Mapping-Aktionen, alte Episodenzeilen werden vor Serien-/Staffelwechsel sofort verworfen und verspätete Suchergebnisse sind zusätzlich an den gestarteten Medientyp gebunden. Bei Filmen wird der bewusst aktivierte Treffer festgehalten; ein später markierter Suchtreffer kann die Zuordnung nicht unbemerkt ändern. Auto-Zuordnung überschreibt keine vorhandene Filmzuordnung, und nicht fortlaufende Provider-Episoden erzeugen eine sichtbare Warnung statt einer unbehandelten Qt-Slot-Exception.

## Historischer Entwicklungsstand 9.8.2 – 13.09.2026

Der damalige V9.8.2-Stand wurde nach den Datenbank-/Metadaten-Patches in zwölf größeren Refactoring- und Stabilitätsblöcken und anschließend mit dem kumulativen Technical Review Patch v4 weiter zerlegt. Ziel war nicht, nur Dateien kleiner zu machen, sondern GUI, Orchestrierung, Datenbankzugriff, Dateisystem-I/O, externe Tools und reine Fachlogik klarer voneinander zu trennen. Bestehende Importpfade bleiben dort über schmale Kompatibilitätsfassaden erhalten, wo Worker, Tests oder andere Module darauf angewiesen sind.

Wichtige Änderungen dieses historischen Stands:

- **Mediathek:** migrationssichere Schema-Reihenfolge, indexfreundlicher Serien-Lookup über `normalized_title`, korrigierte Jellyfin-Normalisierung, weniger unnötige SQLite-Verbindungen/Writes und eine asynchrone Mediathek-Suche außerhalb des GUI-Threads.
- **Preflight und Metadaten:** Film-/Serienpfade werden bei aktivierter Mediathek zuerst über SQLite aufgelöst. Persistenter Suchcache und frische Batch-Metadaten sind getrennt; finale Renamer-/NFO-Läufe können aktuelle Providerdaten einmal pro Serie/Batch laden und anschließend wiederverwenden.
- **Renamer:** generische Episodentitel wie `Folge 10` oder `Episode 10` gelten nicht als endgültige Metadaten. Sie lösen bei Bedarf eine frische Abfrage aus; TheTVDB kann bei vorhandener Episode ohne brauchbaren deutschen Titel auf die Fallback-Sprache zurückgreifen.
- **Trickplay/Postprocessing:** Logging akzeptiert normale Logger, Callables und native Qt-Signale. Ein bereits gestarteter Async-Postprocess wird nach einem Loggingfehler nicht noch einmal synchron gestartet; NFO/Trickplay bleiben damit exactly-once geplant.
- **Abschlussreview:** Move-Journal-Archivierungsfehler sind fail-closed, Journal-Finalisierungsfehler zählen im Move-Worker als Fehler, der Release-Smoke verlangt alle im Refactoring-Manifest neu eingeführten Produktivmodule und ein gescheiterter Episodenrefresh wird mit Ursache geloggt statt still auf `Folge XX` zurückzufallen.
- **Quellbildprüfung:** mehrere Prüfpositionen werden gebündelt. Bei 10-%-Intervallen sinkt die Zahl der FFmpeg-Starts im Normalfall von 9 auf 3, bei 5 % von 19 auf 5; nur eine fehlgeschlagene Gruppe fällt auf Einzelproben zurück.
- **Modulstruktur:** große Bereiche wie Mediathek, NFO-Scan, Trickplay, DV-Remux, Backup/Restore, Journal, Preflight, Merge, ISO, Parallel-Converter, MoveThread, Encoder-Override, Duration-Repair, HDR10+, MediaAnalyzer, Renamer-Kandidaten, Audio/Video-Matcher und Online-Metadaten-Dialog sind in fokussierte Fachmodule aufgeteilt.
- **Technical Review Patch v4:** Release-Validierung, Timestamp-Kandidatenprüfung, Strip-Only, Audio-/Video-Time-Mapping, Qualitätsvergleich und -test, Streamargumente, finaler DV-Mux, Conversion-Fortschritt sowie ISO-Eingabeverarbeitung besitzen getrennte Fachservices. Die bisherigen Fassaden und Kompatibilitätshooks bleiben erhalten.

Der aktuell vermessene Quellstand umfasst **787 Python-Dateien einschließlich `DragonToolsV9.py`**, rund **119.402 Gesamtzeilen** und **101.135 nichtleere/nicht reine Kommentarzeilen**. Im Testpaket liegen **172 Python-Dateien**, davon **169 `test_*.py`** mit **1.245 statisch erkennbaren Testfunktionen**. In einem Package-only-Archiv ohne Einstiegspunkt werden entsprechend 786 Python-Dateien gezählt. Die lokale Abschlussprüfung am 13.09.2026 ergab **1.269 bestandene und 2 übersprungene Tests**; die beiden Skips benötigen reale DV/HDR-Testmedien und externe Werkzeuge.

## Öffentliche Ausgabe – 08.10.2026

Frische Abnahme dieser öffentlichen Ausgabe: **5.160 bestandene, 27 übersprungene Standardtests; 24 DV/HDR-Integrationstests wurden abgewählt.** Die übersprungenen Fälle benötigen optionale Komponenten, externe Medienwerkzeuge oder Betriebssystemfunktionen. Zusätzlich bestehen Datenschutzprüfung, Syntaxprüfung, Werkzeug-Ausschlussprüfung und der Starttest der fertig gebauten EXE.

Diese Ausgabe übernimmt den aktuellen Stand von 9.9.0 einschließlich aller 29 Review-Schritte, des korrigierten Warteschlangenabschlusses nach dem Verschieben und der schnellen HEVC-Dolby-Vision-RPU-Plausibilitätsprüfung. Die EXE wird mit ihren Python-/Qt-Laufzeitdateien als vollständiges Windows-Paket veröffentlicht. Externe Medienwerkzeuge sind nicht enthalten. Paket und SHA-256-Prüfsumme stehen im [Release v9.9.0](https://github.com/7dwy5k98z9-maker/Dragontools-Releases/releases/tag/v9.9.0).

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
