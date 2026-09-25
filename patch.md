# Dragon Tools – Patchprotokoll für Version 9.8.5

**Ausgangsbasis:** Dragon Tools 9.8.4  
**Zielversion:** Dragon Tools 9.8.5  
**Status:** laufende Entwicklung  
**Letzte Aktualisierung:** 21.09.2026

Dieses Dokument wird mit jedem Patch fortlaufend ergänzt. Es trennt bewusst zwischen **bereits umgesetzten Änderungen** und **geplanten Folgepatches**. Nur Einträge unter „Umgesetzte Patches“ gelten als Bestandteil des aktuell gepatchten Projektstands.

---

## Umgesetzte Patches

### Patch A – Sichere Untertitel-Injection mit korrektem Forced-Status

**Status:** umgesetzt und getestet  
**Bereich:** Untertitel / FFmpeg-Injection / MP4-MOV / MKV-Fallback  
**Ziel:** Zwei Fehler beseitigen, durch die neu eingefügte Untertitel entweder ihren Forced-Status verlieren oder Metadaten versehentlich auf einen bereits vorhandenen Untertitel geschrieben werden konnten.

#### Geänderte Module

- `dragontools/subtitle/injector.py`
- `dragontools/gui/subtitle_widget_workers.py`
- `dragontools/tests/test_patch_a_subtitle_injection.py` *(neu)*

#### Funktionale Änderungen

1. **Forced-Status wird im FFmpeg-Pfad übernommen**
   - Der in der GUI gewählte Forced-Status wird jetzt auch an `inject_with_ffmpeg()` weitergegeben.
   - Das betrifft insbesondere MP4/M4V/MOV-Injection sowie den FFmpeg-Fallback bei MKV.
   - Der neu eingefügte Untertitel erhält explizit entweder `forced` oder `0` als Disposition.

2. **Korrekte Adressierung des neu eingefügten Subtitle-Tracks**
   - Beim MKV-FFmpeg-Fallback werden vorhandene Untertitel weiterhin übernommen.
   - Vor der Injection wird deshalb mit `ffprobe` die Anzahl bereits vorhandener Subtitle-Streams ermittelt.
   - Sprache und Forced-Disposition werden anschließend gezielt auf den **neu angehängten** Subtitle-Stream geschrieben.
   - Beispiel: Sind bereits zwei Untertitel vorhanden, erhält der neue Track seine Metadaten über `s:s:2` statt fälschlich über `s:s:0`.

3. **Sicheres Fehlerverhalten bei nicht bestimmbarer Stream-Anzahl**
   - Kann die Anzahl vorhandener Subtitle-Streams nicht zuverlässig bestimmt werden, wird die FFmpeg-Injection abgebrochen.
   - Dragon Tools verändert in diesem Fall nicht auf Verdacht den ersten vorhandenen Subtitle-Track.
   - Der Abbruch wird über das vorhandene Logging sichtbar gemacht.

4. **ffprobe-Pfad wird sauber aufgelöst**
   - Ein explizit konfigurierter `ffprobe`-Pfad wird verwendet.
   - Ist keiner übergeben, wird `ffprobe` aus dem konfigurierten FFmpeg-Pfad abgeleitet.

#### Stabilitätsverbesserungen

- Verhindert falsche Sprach-Tags auf bereits vorhandenen Untertiteln.
- Verhindert falsche Forced-Flags auf bereits vorhandenen Untertiteln.
- Verhindert, dass der Benutzer in der GUI „Forced“ auswählt, die erzeugte MP4/MOV-Datei diesen Status aber verliert.
- Der MKV-FFmpeg-Fallback arbeitet bei unbekannter Stream-Situation jetzt **fail-closed** statt potenziell destruktiv weiterzulaufen.

#### Regressionstests

Neu hinzugefügte Tests prüfen:

- MP4-Injection mit Sprache und `forced=True`.
- MKV-FFmpeg-Fallback mit mehreren bereits vorhandenen Subtitle-Tracks.
- Explizites Entfernen/Nichtsetzen des Forced-Flags bei `forced=False`.
- Sicheren Abbruch, wenn `ffprobe` die vorhandene Subtitle-Anzahl nicht bestimmen kann.
- Ableitung des `ffprobe`-Pfads aus einem konfigurierten FFmpeg-Pfad.

**Fokussierter Patch-Test:** 27/27 Tests bestanden.  
**Breiter Regressionstest:** 1411 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Umgebungsfehler.  
Die vier verbleibenden Fehler sind bereits vor Patch A vorhanden bzw. durch das Review-Paket bedingt: ein Headless-Test benötigt PyQt6; drei Release-/CI-Tests erwarten Repository-Dateien außerhalb des gelieferten Teilarchivs (`release_manifest.json`, `build_v9.bat`, `.github`). Es wurde keine neue Regression durch Patch A festgestellt.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für die spätere Dokumentation von 9.8.5 sollte festgehalten werden:

- Untertitel-Injection übernimmt den Forced-Status jetzt auch bei FFmpeg/MP4/MOV korrekt.
- Der MKV-FFmpeg-Fallback adressiert neu eingefügte Subtitle-Tracks zuverlässig, auch wenn bereits mehrere Untertitel vorhanden sind.
- Unsichere Stream-Zuordnungen führen zu einem sicheren Abbruch statt zu potenziell falschen Metadatenänderungen.


### Patch B – Robustes Lazy-Loading und persistente GUI-Fehlerdiagnose

**Status:** umgesetzt und getestet  
**Bereich:** MainWindow / Lazy-Loading / GUI-Diagnose / Fehler-Recovery  
**Ziel:** Fehler bei der erstmaligen Initialisierung eines Tabs dürfen weder als erfolgreich geladener Tab gecacht werden noch für die laufende Sitzung dauerhaft unzugänglich bleiben. Gleichzeitig muss der vollständige Fehler auch in der EXE nachvollziehbar bleiben.

#### Geänderte bzw. neue Module

- `dragontools/gui/main_window_tabs.py`
- `dragontools/gui/tab_lazy_loading.py` *(neu)*
- `dragontools/core/gui_error_report.py` *(neu)*
- `dragontools/tests/test_patch_b_lazy_tab_loading.py` *(neu)*

#### Funktionale Änderungen

1. **Fehlgeschlagene Tabs bleiben erneut ladbar**
   - Exceptions aus den eigentlichen Tab-Factorys werden nicht mehr innerhalb von `_create_tab_widget()` in ein normales `QLabel` umgewandelt.
   - Der Lazy-Loading-Lifecycle erkennt den Initialisierungsfehler explizit.
   - `_tab_widgets[key]` bleibt bei einem Fehler auf `None`; ein Fehlerwidget gilt damit ausdrücklich **nicht** als erfolgreich geladener Tab.
   - Ein späterer erneuter Initialisierungsversuch ist dadurch möglich.

2. **„Erneut versuchen“-Funktion im betroffenen Tab**
   - Statt eines dauerhaft gecachten Fehlerlabels erscheint eine dedizierte Fehleransicht.
   - Sie zeigt Fehlertyp und Fehlermeldung und bietet den Button **„Erneut versuchen“**.
   - Der Retry sucht den Tab über seinen stabilen Tab-Key neu und hängt deshalb nicht an einem möglicherweise veralteten Index, falls Tabs zwischenzeitlich verschoben wurden.

3. **Ein defekter Tab bleibt vom restlichen MainWindow isoliert**
   - Der Austausch zwischen Placeholder, Fehlerwidget und echtem Tab-Widget blockiert temporär `currentChanged`-Signale.
   - Dadurch wird kein rekursiver Lazy-Load beim Ersetzen des Tab-Inhalts ausgelöst.
   - Entfernte Placeholder-/Fehlerwidgets werden per `deleteLater()` zur Bereinigung freigegeben.
   - Andere Tabs bleiben weiterhin benutzbar, auch wenn die Initialisierung eines einzelnen Tabs scheitert.

4. **Persistenter GUI-Fehlerbericht mit vollständigem Traceback**
   - Lazy-Tab-Fehler werden zusätzlich mit `logger.exception()` protokolliert.
   - Unabhängig von einer sichtbaren Konsole wird ein eigener Diagnosebericht im normalen Dragon-Tools-Loggingbaum geschrieben:
     - `Logging/<Jahr>/<Monat>/ErrorReports/GUI/`
   - Der Bericht enthält:
     - Dragon-Tools-Version,
     - Zeitpunkt,
     - Tab-Key,
     - Tab-Name,
     - Exception-Typ,
     - Fehlermeldung,
     - vollständigen Python-Traceback.
   - Der Pfad des erzeugten Fehlerberichts wird direkt im Fehler-Tab angezeigt.

5. **Architekturgrenzen bleiben erhalten**
   - Fehlerwidget und kleine Tab-Lifecycle-Helfer wurden bewusst in `gui/tab_lazy_loading.py` ausgelagert.
   - `MainWindowTabsMixin` bleibt innerhalb des bestehenden Größenlimits.
   - Der ausgelagerte Helper ruft keine privaten MainWindow-Methoden über Objektgrenzen auf; der Retry-Callback wird im Mixin selbst gebunden.

#### Stabilitätsverbesserungen

- Ein einmaliger Import-/Initialisierungsfehler macht einen Tab nicht mehr bis zum Programmneustart dauerhaft unbrauchbar.
- Temporäre Fehler können direkt aus derselben Sitzung erneut versucht werden.
- Fehler während des Start-Tabs bleiben fail-soft und müssen nicht das gesamte MainWindow beenden.
- Vollständige Tracebacks bleiben auch in einer gebauten EXE persistent verfügbar.
- Rekursive `currentChanged`-Ladevorgänge beim Austauschen des Tab-Inhalts werden vermieden.
- Wiederholte Fehlversuche hinterlassen keine unbegrenzt angesammelten alten Placeholder-/Fehlerwidgets.

#### Regressionstests

Neu hinzugefügte Patch-B-Tests prüfen:

- Persistenten GUI-Fehlerbericht mit Tab-Metadaten und vollständigem Traceback.
- Dass `_create_tab_widget()` Constructor-/Import-Exceptions nicht mehr verschluckt.
- Dass ein fehlgeschlagener Tab im Cache auf `None` bleibt und retrybar ist.
- Dass der Retry den aktuellen Index über den stabilen Tab-Key bestimmt.
- Dass der Tab-Austausch Signale blockiert und das vorherige Widget freigibt.
- Bestehende MainWindow-Architekturverträge einschließlich Modulgrößen und privater Objektgrenzen.

**Fokussierter Patch-/MainWindow-Test:** 16/16 Tests bestanden.  
**Gesamter Regressionstest (in vier Gruppen):** 1416 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Umgebungsfehler.  
Die vier verbleibenden Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; drei Release-/CI-Verträge benötigen Dateien außerhalb des gelieferten Teilarchivs (`release_manifest.json`, `build_v9.bat`, `.github`). Es wurde keine neue Regression durch Patch B festgestellt.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für die spätere Dokumentation von 9.8.5 sollte festgehalten werden:

- Tabs können nach einem Initialisierungsfehler direkt über **„Erneut versuchen“** neu geladen werden.
- Fehlerhafte Tab-Initialisierungen blockieren nicht mehr dauerhaft den Tab für die laufende Sitzung.
- GUI-Initialisierungsfehler erzeugen jetzt persistente Diagnoseberichte mit vollständigem Traceback unter `ErrorReports/GUI`.
- Die Fehlerdiagnose ist damit insbesondere in der EXE deutlich nachvollziehbarer.

### Patch C – Queue-Performance, Queue-Steuerung und persistierte Reihenfolge

**Status:** umgesetzt und getestet  
**Bereich:** Konverter-Queue / Live-Queue / Parallel-Queue / Job-Journal / Crash-Recovery  
**Ziel:** Duplikatprüfungen bei großen Queues deutlich effizienter machen und die Warteschlange gezielt per Schaltflächen steuern, ohne laufende Jobs zu verschieben oder die Reihenfolge bei einer Wiederaufnahme zu verlieren.

#### Geänderte bzw. neue Module

- `dragontools/gui/convert_widget_file_queue.py`
- `dragontools/gui/file_list_queue_index.py` *(neu)*
- `dragontools/gui/queue_ordering.py` *(neu, Qt-unabhängig)*
- `dragontools/gui/convert_widget_queue_reorder_actions.py` *(neu)*
- `dragontools/gui/convert_widget_queue_actions.py`
- `dragontools/gui/convert_widget_layout_runtime.py`
- `dragontools/gui/convert_widget_composition.py`
- `dragontools/gui/convert_widget_runtime_ui.py`
- `dragontools/gui/convert_queue_window.py`
- `dragontools/gui/convert_widget_queue_remove.py`
- `dragontools/worker/converter_queue_state.py`
- `dragontools/worker/parallel_converter_state.py`
- `dragontools/worker/parallel_converter_queue.py`
- `dragontools/core/job_journal.py`
- `dragontools/core/job_journal_resume.py`
- `dragontools/tests/test_patch_c_queue_ordering.py` *(neu)*
- `dragontools/tests/test_patch_c_job_journal_queue_order.py` *(neu)*
- `dragontools/tests/test_convert_widget_queue_actions_architecture.py`

#### Funktionale Änderungen

1. **O(1)-Duplikatprüfung in der sichtbaren Datei-Queue**
   - `FileListWidget` verwendet jetzt einen dauerhaft gepflegten Dictionary-Index mit normalisierten `path_compare_key()`-Schlüsseln.
   - Beim Hinzufügen einer Datei muss nicht mehr für jeden neuen Eintrag die komplette vorhandene Queue erneut normalisiert und durchsucht werden.
   - Index und Liste bleiben bei Add, Remove, Clear, Rebuild und Reorder synchron.

2. **Effizientere Duplikatprüfung auch in den Worker-Queues**
   - `ConverterQueueState` pflegt einen eigenen Schlüsselindex für wartende Dateien.
   - Die Parallel-Queue pflegt ebenfalls ein `file_keys`-Set über `ParallelQueueState`.
   - Live-Adds während einer laufenden Konvertierung benötigen dadurch keine vollständige lineare Queue-Prüfung mehr.

3. **Neue Queue-Steuerung per Buttons**
   - Im Konverter und im separaten Queue-Fenster stehen vier Reorder-Aktionen zur Verfügung:
     - `⤒` Auswahl direkt hinter aktuell laufende Jobs setzen,
     - `↑` Auswahl eine Position nach oben,
     - `↓` Auswahl eine Position nach unten,
     - `⤓` Auswahl ganz nach unten.
   - Die vorhandene Drag-&-Drop-Sortierung bleibt erhalten.

4. **Mehrfachauswahl bleibt stabil**
   - Mehrere markierte Dateien behalten beim Verschieben ihre interne Reihenfolge.
   - Beispiel: `E, F, G` bleibt auch nach `⤒` oder `⤓` in genau dieser Reihenfolge.

5. **Laufende Jobs sind gegen Reordering geschützt**
   - Aktuell laufende Dateien werden von den neuen Button-Aktionen nicht verschoben.
   - Wird eine laufende Datei selbst per internem Drag&Drop ausgewählt, wird der Drag abgewiesen.
   - Wird versucht, eine wartende Datei per Drag&Drop über eine aktive Datei zu ziehen und dadurch deren Position zu verschieben, wird die ursprüngliche Reihenfolge wiederhergestellt.
   - Bei paralleler Verarbeitung werden mehrere aktive Jobs berücksichtigt.

6. **Reorder funktioniert weiterhin über die bestehende Worker-API**
   - Es wurde kein zusätzliches High/Medium/Low-Prioritätssystem eingeführt.
   - Die sichtbare Queue-Reihenfolge bleibt die Priorität.
   - Die bestehende Worker-Methode `reorder_waiting_files()` bleibt die verbindliche Schnittstelle für wartende Jobs.

7. **Queue-Reihenfolge wird im Job-Journal persistiert**
   - Neue Journale enthalten `queue_order`.
   - Jede manuelle Reihenfolgeänderung während eines laufenden Jobs aktualisiert diese Reihenfolge atomar.
   - Live neu hinzugefügte Dateien werden gleichzeitig als `queued` in das Journal aufgenommen.
   - Bewusst entfernte wartende Dateien werden bei einer Crash-Wiederaufnahme nicht mehr versehentlich wieder eingereiht.
   - Alte Journale ohne `queue_order` bleiben vollständig kompatibel und verwenden weiterhin die bisherige Dateireihenfolge.

8. **Architekturgrenzen bleiben erhalten**
   - Die neue Index-/Reorder-Logik wurde aus `convert_widget_file_queue.py` in `file_list_queue_index.py` ausgelagert.
   - Dadurch bleibt `convert_widget_file_queue.py` mit 311 Zeilen unter dem festgelegten Architektur-Limit von 340 Zeilen.
   - Die eigentliche Reihenfolgelogik liegt Qt-unabhängig in `gui/queue_ordering.py` und ist direkt testbar.

#### Stabilitäts- und Performanceverbesserungen

- Große Ordnerimporte skalieren bei der GUI-Duplikatprüfung nicht mehr quadratisch mit der vorhandenen Queue-Größe.
- Spätere Watch-Folder können denselben schnellen Queue-Index verwenden.
- Live-Adds in laufende Single- und Parallel-Worker vermeiden unnötige vollständige Queue-Scans.
- Mehrfachauswahl kann nicht versehentlich beim Verschieben umgedreht werden.
- Aktive Jobs bleiben visuell und fachlich vor Reordering geschützt.
- Manuell sortierte Warteschlangen behalten ihre Reihenfolge auch nach einem Crash/Resume.
- Entfernte wartende Dateien werden durch das Job-Journal nicht wieder ungewollt hergestellt.

#### Regressionstests

Neu bzw. erweitert getestet werden:

- `↑` / `↓` mit Mehrfachauswahl.
- `⤒` direkt hinter einen bzw. mehrere aktive Jobs.
- `⤓` bei Mehrfachauswahl.
- Schutz aktiver Jobs vor Button-Reordering.
- Persistenz einer manuell geänderten Queue-Reihenfolge im Job-Journal.
- Live neu hinzugefügte Dateien im Journal.
- Entfernte wartende Dateien bleiben bei Resume entfernt.
- Rückwärtskompatibilität alter Journale ohne `queue_order`.
- bestehende Parallel-Queue-, Converter-Queue- und Architekturverträge.
- Größenlimit des refaktorierten `convert_widget_file_queue.py`.

**Fokussierter finaler Patch-C-Test:** 65/65 Tests bestanden.  
**Breiter Regressionstest in Testblöcken:** 1425 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Umgebungsfehler.  
Die vier verbleibenden Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; drei Release-/CI-Verträge benötigen Dateien außerhalb des gelieferten Teilarchivs (`release_manifest.json`, `build_v9.bat`, `.github`). Es wurde keine neue Regression durch Patch C festgestellt.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für die spätere Dokumentation von 9.8.5 sollte festgehalten werden:

- Die Queue besitzt neue Schaltflächen zum schnellen Verschieben markierter Dateien nach oben, unten, direkt hinter laufende Jobs oder ans Ende.
- Mehrfachauswahl behält dabei ihre Reihenfolge.
- Aktive Dateien können nicht versehentlich verschoben werden.
- Queue-Duplikatprüfungen wurden für große Dateiimporte und Live-Adds deutlich effizienter gemacht.
- Die manuell geänderte Queue-Reihenfolge wird jetzt im Job-Journal gespeichert und bei einer Wiederaufnahme berücksichtigt.


### Patch D – Robuste TMDB-/TheTVDB-Abfragen mit Retry/Backoff

**Status:** umgesetzt und getestet  
**Bereich:** Online-Metadaten / TMDB / TheTVDB / Renamer / Provider-Fallback  
**Ziel:** Kurzzeitige Provider-/Netzwerkfehler automatisch abfangen, permanente Zugangsfehler nicht sinnlos wiederholen und im Mehrprovider-Betrieb zuverlässig zwischen „kein Treffer“ und „alle Provider technisch fehlgeschlagen“ unterscheiden.

#### Geänderte bzw. neue Module

- `dragontools/core/online_metadata_retry.py` *(neu)*
- `dragontools/core/online_metadata_http.py` *(neu)*
- `dragontools/core/online_metadata_tmdb_transport.py`
- `dragontools/core/online_metadata_tvdb_transport.py`
- `dragontools/core/online_metadata_service.py`
- `dragontools/tests/test_patch_d_online_metadata_retry.py` *(neu)*

#### Funktionale Änderungen

1. **Gemeinsame Retry-Strategie für TMDB und TheTVDB**
   - Temporäre Fehler werden jetzt providerübergreifend nach derselben Policy behandelt.
   - Eine Online-Operation erhält maximal **3 Gesamtversuche**.
   - Zwischen den Versuchen wird exponentielles Backoff verwendet:
     - nach Versuch 1 ungefähr `0,5 s` plus leichter Jitter,
     - nach Versuch 2 ungefähr `1,0 s` plus leichter Jitter.
   - Die Retry-Hilfe liegt zentral in `online_metadata_retry.py`; TMDB und TheTVDB duplizieren diese Logik nicht.

2. **Nur tatsächlich temporäre Fehler werden wiederholt**
   - Retry-fähige HTTP-Statuscodes:
     - `408 Request Timeout`,
     - `425 Too Early`,
     - `429 Too Many Requests`,
     - `500 Internal Server Error`,
     - `502 Bad Gateway`,
     - `503 Service Unavailable`,
     - `504 Gateway Timeout`.
   - Zusätzlich retrybar:
     - temporäre URL-/Verbindungsfehler,
     - Timeouts,
     - ungültige JSON-Antworten eines Providers.
   - Andere HTTP-Fehler werden nicht blind wiederholt.

3. **Authentifizierungsfehler brechen sofort ab**
   - `401` und `403` werden als `OnlineMetadataAuthError` klassifiziert.
   - Ungültige/abgelehnte TMDB- oder TheTVDB-Zugangsdaten verursachen keinen unnötigen zweiten oder dritten Request.

4. **`Retry-After` bei Rate-Limits wird berücksichtigt**
   - HTTP `429` liest den `Retry-After`-Header aus.
   - Unterstützt werden sowohl Sekundenwerte als auch HTTP-Datumsangaben.
   - Der Provider-Wert wird mindestens eingehalten, wenn er länger ist als das normale Backoff.

5. **TheTVDB-Login ist ebenfalls retryfähig**
   - Nicht nur normale TheTVDB-GET-Abfragen, sondern auch `/login` nutzt die neue Retry-Policy.
   - Ein kurzzeitig nicht erreichbarer Login-Endpunkt führt damit nicht sofort zum Abbruch des Renamer-Laufs.
   - Ein echter `401/403`-Loginfehler bleibt weiterhin ein sofortiger Authentifizierungsfehler.

6. **TMDB-Authentifizierungsfehler werden jetzt explizit klassifiziert**
   - Auch TMDB `401/403` werden als Zugangsdatenfehler behandelt statt nur als allgemeiner HTTP-Fehler.
   - Dadurch erhält die GUI einen fachlich passenderen Fehlerzustand.

7. **„Kein Treffer“ wird im Mehrprovider-Betrieb von Provider-Ausfall getrennt**
   - `CompositeMetadataClient` zählt erfolgreiche Providerantworten getrennt von Fehlern.
   - Antwortet mindestens ein konfigurierte Provider technisch erfolgreich, darf ein leeres Ergebnis weiterhin korrekt „kein Treffer“ bedeuten.
   - Scheitern dagegen **alle** tatsächlich angesprochenen Provider technisch, wird ein zusammengefasster `OnlineMetadataError` mit den Providerfehlern ausgelöst.
   - Dadurch kann der Renamer einen Provider-/Netzwerkfehler anzeigen, statt ihn fälschlich wie einen nicht vorhandenen Film/eine nicht vorhandene Serie aussehen zu lassen.

8. **Preflight bleibt fail-soft und lokal unabhängig**
   - Die vorhandene lokale DB- und Ordnersuche des Preflight wurde nicht verändert.
   - Online-Metadaten bleiben dort ein Zusatz/Fallback und blockieren die lokale Auflösung bei einem Provider-Ausfall nicht.

#### Stabilitätsverbesserungen

- Kurze TMDB-/TheTVDB-Aussetzer führen deutlich seltener zu scheinbar leeren Renamer-Ergebnissen.
- Rate-Limits werden serverkonform behandelt, statt unmittelbar als endgültiger Fehler zu enden.
- Fehlerhafte API-Zugangsdaten verursachen keine unnötigen Wiederholungen.
- Mehrprovider-Konfigurationen verschlucken nicht mehr still alle Providerfehler, wenn wirklich kein Provider erreichbar war.
- Die HTTP-Fehlerklassifizierung ist aus den Provider-Transportmodulen ausgelagert und zentral testbar.
- Bestehende Cache- und Fresh-Session-Logik bleibt unverändert; ein erfolgreicher Retry wird anschließend normal gecacht.

#### Regressionstests

Neu bzw. erweitert getestet werden:

- maximal drei Gesamtversuche bei temporären Fehlern,
- exponentielles Backoff ohne reale Wartezeit im Test,
- `Retry-After` hat Vorrang vor kürzerem Standard-Backoff,
- HTTP `429` wird als retrybarer Fehler klassifiziert,
- HTTP `401` wird als nicht retrybarer Authentifizierungsfehler klassifiziert,
- TMDB-GET kann nach zwei temporären Fehlern beim dritten Versuch erfolgreich werden,
- TheTVDB-Login kann nach temporären Fehlern erfolgreich wiederholt werden,
- permanente `OnlineMetadataError` werden nicht erneut ausgeführt,
- Mehrprovider-Suche meldet einen Fehler, wenn alle Provider scheitern,
- Mehrprovider-Suche liefert weiterhin korrekt „kein Treffer“, wenn mindestens ein Provider erfolgreich leer antwortet,
- bestehende Online-Metadaten- und Architekturtests,
- Produktionscode-Vertrag ohne Runtime-`assert`.

**Fokussierter Patch-D-/Online-Metadaten-Test:** 49/49 relevante Tests bestanden.  
**Gesamter Regressionstest in Testgruppen:** 1433 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Umgebungsfehler.  
Die vier verbleibenden Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; ein CI-Vertrag erwartet die im Teilarchiv fehlende `.github`-Struktur; zwei Versions-/Build-Verträge erwarten `release_manifest.json` bzw. `build_v9.bat` außerhalb des gelieferten Teilarchivs. Es wurde keine neue Regression durch Patch D festgestellt.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für die spätere Dokumentation von 9.8.5 sollte festgehalten werden:

- TMDB- und TheTVDB-Abfragen wiederholen temporäre Netzwerk-/Serverfehler jetzt automatisch bis zu drei Gesamtversuche.
- HTTP-Rate-Limits berücksichtigen `Retry-After`.
- Authentifizierungsfehler werden sofort und eindeutig gemeldet.
- Der Renamer kann jetzt zwischen einem echten „kein Treffer“ und einem vollständigen Provider-/Netzwerkausfall unterscheiden.
- Die lokale Preflight-DB-/Ordnersuche bleibt von Online-Ausfällen unabhängig.



### Patch E – Konfigurierbare und wiederaufnehmbare SxxExx-Episoden-Ersetzung

**Status:** umgesetzt und getestet  
**Bereich:** Verschieben / Serienfolgen / SxxExx-Konflikte / Einstellungen / Move-Journal / Recovery  
**Ziel:** Die bisher automatisch ausgeführte Ersetzung einer anders benannten Zieldatei mit identischer Staffel-/Episodenkennung steuerbar machen, ohne das bestehende Verhalten normaler Namens- oder Containerkonflikte zu verändern.

#### Geänderte bzw. neue Module

- `dragontools/core/episode_replacement_policy.py` *(neu)*
- `dragontools/core/move_file_service.py`
- `dragontools/core/move_journal.py`
- `dragontools/core/move_journal_resume.py`
- `dragontools/core/settings_storage.py`
- `dragontools/gui/settings_sections/safety.py`
- `dragontools/gui/move_request_dialogs.py`
- `dragontools/gui/move_regular_lifecycle.py`
- `dragontools/gui/move_incremental_lifecycle.py`
- `dragontools/gui/convert_widget_recovery.py`
- `dragontools/gui/main_window_recovery.py`
- `dragontools/worker/move_thread.py`
- `dragontools/worker/move_result_commit.py`
- `dragontools/worker/move_batch_lifecycle.py`
- `dragontools/tests/test_patch_e_episode_replacement_policy.py` *(neu)*

#### Funktionale Änderungen

1. **Neue Einstellung für reine SxxExx-Konflikte**
   - Unter **Einstellungen → Verschieben – Konfliktverhalten** steht zusätzlich die Auswahl **„SxxExx-Ersetzung“** zur Verfügung.
   - Drei Modi sind möglich:
     - **Automatisch ersetzen**
     - **Vor Ersetzung nachfragen**
     - **Nie automatisch ersetzen**
   - Die Einstellung wird über `move/episode_replacement_mode` persistent gespeichert.

2. **Bestehendes Verhalten bleibt nach dem Update erhalten**
   - Der Default ist weiterhin **„Automatisch ersetzen“**.
   - Ein Update auf 9.8.5 verändert damit bestehende Installationen nicht still auf einen interaktiven oder blockierenden Modus.
   - Benutzer können das Verhalten danach bewusst auf Rückfrage oder vollständiges Blockieren umstellen.

3. **Die neue Policy greift nur bei reinen Episodenidentitäts-Konflikten**
   - Dragon Tools unterscheidet jetzt zwischen:
     - normalen Ziel-/Namens-/Containerkonflikten und
     - Konflikten, die nur aufgrund derselben `SxxExx`-Identität erkannt werden, obwohl der Episodentitel bzw. Dateistem abweicht.
   - Beispiel für die neue Policy:
     - vorhanden: `Serie - S01E03 - Alter Titel.mkv`
     - neu: `Serie - S01E03 - Neuer Titel.mp4`
   - Normale Konflikte wie `Film.mkv ↔ Film.mp4` oder derselbe Episoden-Dateistem bleiben unter dem bisherigen Konfliktverhalten und werden durch die neue Option nicht umdefiniert.

4. **Modus „Automatisch ersetzen“**
   - Entspricht dem bisherigen Verhalten.
   - Die alte Episode wird weiterhin transaktional gesichert und erst nach erfolgreichem Commit verworfen.
   - Zugehörige veraltete `.nfo`- und `.trickplay`-Artefakte derselben Episodenidentität werden weiterhin gemeinsam behandelt.
   - Bestehende Replacement-Reminder und Move-Reports bleiben erhalten.

5. **Modus „Vor Ersetzung nachfragen“**
   - Vor einem reinen SxxExx-Austausch erscheint eine Benutzerabfrage mit:
     - Episodenkennung,
     - vorhandener Datei bzw. vorhandenen Dateien,
     - neu einzusetzender Datei.
   - **Ja** führt den bestehenden sicheren Replacement-Pfad aus.
   - **Nein** überspringt nur diese Datei; vorhandenes Video, NFO und Trickplay bleiben unverändert.
   - Ein abgebrochener/fehlender Dialog wird sicher wie eine nicht erteilte Freigabe behandelt.

6. **Modus „Nie automatisch ersetzen“**
   - Eine anders benannte Datei mit identischer `SxxExx`-Identität wird nicht verschoben.
   - Bestehende Zieldateien und Begleitartefakte werden nicht angefasst.
   - Der Vorgang wird als übersprungener Konflikt geloggt und kann später bewusst anders behandelt werden.

7. **Specials und Mehrfachfolgen bleiben präzise**
   - `S00Exx` verwendet dieselbe Replacement-Policy wie normale Staffeln.
   - Eine Einzelfolge `S01E03` kollidiert weiterhin nicht fälschlich mit einer Mehrfachfolge `S01E03E04`.
   - Die vorhandene exakte Episodenlisten-Logik bleibt unverändert.

8. **Move-Journal und Crash-Recovery speichern die Entscheidungspolitik mit**
   - Neue Move-Journale enthalten zusätzlich `episode_replacement_mode`.
   - Bei einer Move-Wiederaufnahme wird exakt der Modus des ursprünglichen Laufs wiederhergestellt.
   - Eine zwischenzeitlich geänderte Programmeinstellung verändert damit nicht rückwirkend die Sicherheitsentscheidung eines bereits begonnenen Move-Laufs.
   - Alte Journale ohne dieses Feld bleiben kompatibel und verwenden das bisherige automatische Verhalten.

9. **Policy-Logik ist Qt-unabhängig ausgelagert**
   - Normalisierung, Erkennung reiner SxxExx-Konflikte und Aufbau der Benutzeranfrage liegen in `core/episode_replacement_policy.py`.
   - `MoveFileService.move()` bleibt unter dem bestehenden Architektur-Limit und enthält keine GUI-Abhängigkeit.

#### Stabilitäts- und Sicherheitsverbesserungen

- Automatische Ersetzungen aufgrund gleicher Episodennummer können jetzt vollständig verhindert oder bestätigt werden.
- Ein Ablehnen der Ersetzung verändert weder bestehende Videodateien noch NFO-/Trickplay-Artefakte.
- Die Änderung beeinflusst normale Konfliktmodi nicht unbeabsichtigt.
- Die Sicherheitsentscheidung bleibt über Crash-/Resume-Läufe hinweg konsistent.
- Das bisherige automatische Verhalten bleibt als kompatibler Default erhalten, wodurch das Update keine überraschenden Workflow-Unterbrechungen erzeugt.
- Die bestehende transaktionale Backup-/Rollback-Logik für bestätigte Ersetzungen bleibt vollständig erhalten.

#### Regressionstests

Neu hinzugefügte Patch-E-Tests prüfen:

- kompatiblen Default **„Automatisch ersetzen“**,
- automatische SxxExx-Ersetzung einschließlich alter NFO-Artefakte,
- vollständiges Überspringen im Modus **„Nie“** ohne Veränderung vorhandener Dateien,
- bestätigte und abgelehnte Rückfrage,
- Inhalt der an die GUI übergebenen Replacement-Anfrage,
- Abgrenzung zu normalen Same-Stem-/Containerkonflikten,
- `S00`-Specials,
- präzise Behandlung von Mehrfachfolgen,
- Persistenz von `episode_replacement_mode` im Move-Journal und Resume-Plan.

**Neue Patch-E-Tests:** 9/9 bestanden.  
**Fokussierte Move-/Journal-/Replacement-Suite:** 42/42 Tests bestanden.  
**Gesamter Regressionstest in fünf Testgruppen:** 1442 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Umgebungsfehler.  
Die vier verbleibenden Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; ein CI-Vertrag erwartet die im Teilarchiv fehlende `.github`-Struktur; zwei Versions-/Build-Verträge erwarten `release_manifest.json` bzw. `build_v9.bat` außerhalb des gelieferten Teilarchivs. Es wurde keine neue Regression durch Patch E festgestellt.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für die spätere Dokumentation von 9.8.5 sollte festgehalten werden:

- Automatische Episoden-Ersetzungen aufgrund identischer `SxxExx`-Kennungen sind jetzt konfigurierbar.
- Verfügbar sind **automatisch ersetzen**, **vorher nachfragen** und **nie automatisch ersetzen**.
- Standard bleibt aus Kompatibilitätsgründen das bisherige automatische Verhalten.
- Die Einstellung betrifft nur anders benannte Dateien, die allein aufgrund derselben Episodenidentität kollidieren; normale Dateikonflikte verwenden weiterhin den normalen Konfliktmodus.
- Die gewählte Policy wird im Move-Journal gespeichert und bei einer Wiederaufnahme beibehalten.

#### Migration / neue Abhängigkeiten

- Keine neue externe Abhängigkeit.
- Keine Datenbankmigration.
- Bestehende Einstellungen benötigen keine Migration; fehlt der neue Schlüssel, wird `auto` verwendet.


### Patch F – Optionale Jellyfin-API-Integration nach Move und Renamer

**Status:** umgesetzt und getestet  
**Bereich:** Jellyfin / Einstellungen / Move / Renamer / Pfad-Mapping / Hintergrundaktualisierung  
**Ziel:** Jellyfin nach erfolgreichen Dateiänderungen gezielt und ressourcenschonend über die betroffenen Medienpfade informieren, ohne einen erfolgreichen Dragon-Tools-Dateijob von der Erreichbarkeit des Jellyfin-Servers abhängig zu machen.

#### Geänderte bzw. neue Module

- `dragontools/core/jellyfin_api.py` *(neu)*
- `dragontools/core/jellyfin_refresh_service.py` *(neu)*
- `dragontools/core/settings_jellyfin.py` *(neu)*
- `dragontools/core/media_library_path_mappings.py`
- `dragontools/core/settings.py`
- `dragontools/core/release_validation_package.py`
- `dragontools/gui/jellyfin_connection_test.py` *(neu)*
- `dragontools/gui/jellyfin_refresh_dispatch.py` *(neu)*
- `dragontools/gui/settings_sections/jellyfin.py` *(neu)*
- `dragontools/gui/settings_sections/__init__.py`
- `dragontools/gui/settings_dialog.py`
- `dragontools/gui/main_window_menus.py`
- `dragontools/gui/main_window_settings_actions.py`
- `dragontools/gui/move_regular_lifecycle.py`
- `dragontools/gui/move_incremental_lifecycle.py`
- `dragontools/gui/movie_renamer_actions.py`
- `dragontools/tests/test_patch_f_jellyfin_api.py` *(neu)*
- Architektur-/Release-Tests für die neuen Module wurden erweitert.

#### Funktionale Änderungen

1. **Separater Jellyfin-API-Bereich in den Einstellungen**
   - Die Integration ist standardmäßig deaktiviert und vollständig optional.
   - Konfigurierbar sind Server-URL, persönlicher API-Key, Aktualisierung nach Move, Aktualisierung nach Renamer, Aktualisierungsmodus und optionaler Full-Scan-Fallback.
   - Ein eigener Menüpunkt **„Jellyfin API“** öffnet direkt diesen Einstellungsbereich.

2. **Nicht blockierender Verbindungstest**
   - Der Button **„Verbindung testen“** prüft die Verbindung in einem eigenen Qt-Thread.
   - Bei Erfolg werden Servername, Jellyfin-Version und – sofern geliefert – das Server-Betriebssystem angezeigt.
   - Der GUI-Thread wird während des Netzwerkzugriffs nicht blockiert.

3. **Gezielte Pfadmeldung als Standardmodus**
   - Nach einem erfolgreichen Move werden nur erfolgreich installierte Videodateien an Jellyfin gemeldet.
   - Die Integration verwendet Jellyfins Media-Update-Endpunkt und meldet Pfade als `Created`, `Modified` oder `Deleted`.
   - Dadurch muss nicht nach jedem Dragon-Tools-Job die komplette Jellyfin-Mediathek gescannt werden.

4. **Korrekte Behandlung von Episoden-Ersetzungen**
   - Wird durch die Patch-E-Logik eine vorhandene Episode ersetzt, meldet Dragon Tools die ersetzten alten Pfade zuerst als `Deleted`.
   - Der neu installierte Zielpfad wird danach als `Created` gemeldet.
   - Damit werden SxxExx-Ersetzungen nicht nur im Dragon-Tools-Move-Journal, sondern auch gegenüber Jellyfin konsistent beschrieben.

5. **Renamer-Integration**
   - Erfolgreiche Umbenennungen melden den alten Pfad als `Deleted` und den neuen Pfad als `Created`.
   - Fehlgeschlagene Einzeldateien eines Renamer-Batches werden nicht als erfolgreiche Änderungen an Jellyfin gemeldet.

6. **Bestehende Mediathek-Pfad-Mappings werden rückwärts verwendet**
   - Vorhandene Zuordnungen wie `Z:\\Serien -> /TVSerien` können jetzt auch in Gegenrichtung verwendet werden.
   - Bei mehreren möglichen Zuordnungen gewinnt der längste lokale Prefix.
   - Gibt es kein Mapping, bleibt der lokale Pfad unverändert. Dies unterstützt Installationen, bei denen Dragon Tools und Jellyfin denselben Pfad sehen.

7. **Full-Library-Scan bleibt Option/Fallback**
   - Alternativ kann direkt ein vollständiger Jellyfin-Bibliotheksscan gestartet werden.
   - Optional kann nach einer fehlgeschlagenen gezielten Pfadmeldung automatisch auf einen Full Scan zurückgefallen werden.
   - Dieser Fallback ist standardmäßig deaktiviert, damit ein temporärer Pfad-/API-Fehler nicht ungefragt einen großen Mediatheksscan startet.

8. **Best-Effort-Hintergrundverarbeitung**
   - Jellyfin-Aktualisierungen laufen nach dem erfolgreichen Dateiabschluss in einem separaten Hintergrundthread.
   - Ein Jellyfin-Fehler macht einen bereits erfolgreichen Move oder Rename **nicht nachträglich zu einem fehlgeschlagenen Medienjob**.
   - Erfolg und Fehler werden über das vorhandene Dragon-Tools-Logging bzw. den Renamer-Status sichtbar gemacht.

9. **Robuster Jellyfin-HTTP-Client**
   - Authentifizierung verwendet den modernen `MediaBrowser`-Authorization-Header.
   - Temporäre HTTP-/Netzwerkfehler werden maximal drei Mal versucht.
   - `Retry-After` bei HTTP 429 wird berücksichtigt.
   - `401/403` werden sofort als Zugangs-/Berechtigungsfehler gemeldet.
   - Serveradressen ohne Schema werden als `http://` normalisiert; optionale Jellyfin-Base-Pfade bleiben erhalten.

#### Stabilitätsverbesserungen

- Jellyfin ist kein Teil des transaktionalen Datei-Commits; ein Serverausfall gefährdet daher keine bereits erfolgreich installierte Mediendatei.
- Nur erfolgreiche Video-Moves werden gemeldet; Sidecars und fehlgeschlagene/abgebrochene Moves lösen keine falschen Medienmeldungen aus.
- Doppelte Pfadmeldungen innerhalb eines Refresh-Batches werden entfernt.
- Ersetzungen und Renames melden sowohl entfernte als auch neu entstandene Pfade.
- Der vollständige Library-Scan wird nicht automatisch zum Standard und verursacht dadurch keine unnötigen großen Scans.
- Neue Jellyfin-Module sind Bestandteil der Release-Paketvalidierung.
- `release_validation_package.py` bleibt trotz der zusätzlichen Module innerhalb des bestehenden Architektur-Limits von 380 Zeilen.

#### Regressionstests

Neu bzw. erweitert getestet werden:

- Normalisierung von Jellyfin-Serveradressen inklusive Base-Pfad.
- moderner Authorization-Header und Systeminformationen.
- maximal drei Versuche bei temporären HTTP-Fehlern.
- kein Retry bei 401.
- `Retry-After` bei 429.
- deduplizierte Media-Update-Payloads.
- Full-Library-Scan-Endpunkt.
- Rückwärts-Mapping mit längstem lokalen Prefix.
- erfolgreiche Move-Pfade und Ausschluss fehlgeschlagener/Sidecar-Einträge.
- Patch-E-Episodenersetzung mit `Deleted` + `Created`.
- Renamer mit `Deleted` + `Created`.
- gezielter Standardmodus, Full-Scan-Modus und optionaler Fallback.
- Settings-/MainWindow-/Facade-/Release-Architekturverträge.

**Fokussierter Jellyfin-Test:** 14/14 Tests bestanden.  
**Jellyfin + Architektur-/Release-Verträge:** 39/39 Tests bestanden.  
**Gesamter Regressionstest in vier Testblöcken:** 1457 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Teilarchivfehler.  
Die vier verbleibenden Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; ein CI-Vertrag erwartet die im Teilarchiv fehlende `.github`-Struktur; zwei Versions-/Build-Verträge erwarten `release_manifest.json` und `build_v9.bat` außerhalb des gelieferten Projektpakets. Es wurde keine neue Regression durch Patch F festgestellt.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für die spätere Dokumentation von 9.8.5 sollte festgehalten werden:

- Dragon Tools besitzt jetzt eine optionale direkte Jellyfin-API-Anbindung.
- Erfolgreiche Moves und Renamer-Änderungen können Jellyfin automatisch gemeldet werden.
- Standard ist eine gezielte Pfadaktualisierung; ein vollständiger Library-Scan bleibt optional.
- Bestehende Mediathek-Pfad-Mappings werden für Jellyfin-Meldungen rückwärts verwendet.
- Episoden-Ersetzungen melden alte Pfade als gelöscht und den neuen Pfad als erstellt.
- Jellyfin-Ausfälle beeinflussen den Erfolg des eigentlichen Medienjobs nicht.

#### Migration / neue Abhängigkeiten

- Keine neue externe Python-Abhängigkeit; HTTP-Zugriffe verwenden die Standardbibliothek.
- Keine Datenbankmigration.
- Die Integration ist nach dem Update standardmäßig deaktiviert und muss vom Benutzer mit eigener Server-URL und eigenem API-Key eingerichtet werden.


### Patch G – Watch-Folder und sichere automatische Queue-Verarbeitung

**Status:** umgesetzt und getestet  
**Bereich:** Automatisierung / Einstellungen / Converter-Queue / Live-Queue / Worker  
**Ziel:** Beliebig viele Eingangsordner überwachen und fertig geschriebene Videodateien ohne zweite Verarbeitungspipeline sicher an die bestehende Dragon-Tools-Queue übergeben.

#### Geänderte bzw. neue Module

- `dragontools/core/watch_folder.py` *(neu, Qt-unabhängig)*
- `dragontools/core/settings_watch.py` *(neu)*
- `dragontools/core/settings.py`
- `dragontools/core/release_validation_smoke_modules.py`
- `dragontools/gui/settings_dialog.py`
- `dragontools/gui/settings_sections/runtime.py`
- `dragontools/gui/settings_sections/automation.py` *(neu)*
- `dragontools/gui/watch_folder_rule_dialog.py` *(neu)*
- `dragontools/gui/watch_folder_controller.py` *(neu)*
- `dragontools/gui/watch_folder_main_window_bridge.py` *(neu)*
- `dragontools/gui/main_window.py`
- `dragontools/gui/main_window_menus.py`
- `dragontools/gui/main_window_settings_actions.py`
- `dragontools/gui/convert_widget.py`
- `dragontools/gui/convert_widget_watch_intake.py` *(neu)*
- `dragontools/gui/convert_widget_file_queue.py`
- `dragontools/worker/converter_thread.py`
- `dragontools/worker/parallel_converter_queue.py`
- `dragontools/tests/test_patch_g_watch_folder.py` *(neu)*

#### Funktionale Änderungen

1. **Eigener Einstellungsbereich „Watch-Folder / Automatisierung“**
   - Globaler Hauptschalter; nach dem Update standardmäßig deaktiviert.
   - Scan-Intervall einstellbar.
   - Stabilitätszeit einstellbar: Eine Videodatei wird erst übernommen, wenn Größe und Änderungszeit über den kompletten Zeitraum unverändert geblieben sind.
   - Direkter Menüeintrag unter `Einstellungen`.

2. **Mehrere unabhängige Watch-Folder**
   - Pro Regel konfigurierbar:
     - Name,
     - Quellordner,
     - aktiv/inaktiv,
     - Unterordner ja/nein,
     - Converter `H.265`, `H.264` oder `AV1`,
     - optional festes Encoder-Profil,
     - Auto-Start ja/nein.
   - Regeln lassen sich hinzufügen, bearbeiten und entfernen.

3. **Keine zweite Converter-Pipeline**
   - Fertige Dateien werden ausschließlich an die bereits vorhandene sichtbare Converter-Queue übergeben.
   - Der in Patch C eingeführte normalisierte Queue-Pfadindex bleibt die verbindliche Duplikatprüfung.
   - H.265/H.264/AV1 werden über dieselben normalen Converter-Tabs und Worker verarbeitet wie manuell hinzugefügte Dateien.

4. **Sichere Erkennung fertig geschriebener Dateien**
   - Nur bekannte Videoerweiterungen werden berücksichtigt.
   - Typische unfertige Downloads wie `*.mkv.part`, `*.tmp` oder andere Nicht-Video-Endungen fallen automatisch durch den Videofilter.
   - Ändert sich Größe oder `mtime`, beginnt die Stabilitätszeit erneut.
   - Scanner läuft außerhalb des GUI-Threads; große Ordner blockieren dadurch nicht den Qt-Eventloop.
   - Der Scan kann beim Programm-Shutdown unterbrochen werden.

5. **Persistenter Verarbeitungszustand**
   - Nach erfolgreicher Übergabe wird die Dateisignatur aus Pfad, Größe und Änderungszeit gespeichert.
   - Dieselbe unveränderte Quelldatei wird nach einem Dragon-Tools-Neustart nicht erneut automatisch eingereiht.
   - Ändert sich die Datei am selben Pfad, wird sie als neuer Kandidat erkannt.
   - Der gespeicherte Zustand wird begrenzt, damit QSettings nicht unbegrenzt wächst.

6. **Festes Profil pro Watch-Folder**
   - Optional kann eine Watch-Regel ein konkretes Encoder-Profil des gewählten Codecs verwenden.
   - Ohne Auswahl verwendet die Datei das normale globale Converter-Profil.
   - Das Profil wird als vorhandener per-Datei-Override gesetzt; es entsteht keine parallele Profilmechanik.
   - Single- und Parallel-Worker besitzen dafür einen atomaren `add_file_with_override()`-Pfad, sodass ein freier Parallel-Slot nicht starten kann, bevor der Override vorhanden ist.

7. **Live-Add in bereits laufende Verarbeitung**
   - Läuft der passende Converter bereits, können Watch-Dateien über die bestehende Live-Queue nachgereicht werden.
   - Queue-Sperren während nicht inkrementeller Move-Phasen werden respektiert.
   - Abgelehnte Live-Adds werden nicht als verarbeitet bestätigt und können bei einem späteren Scan erneut versucht werden.

8. **Sicherer Auto-Start**
   - Ist eine Watch-Regel auf Auto-Start gestellt und der Converter frei, kann die normale Konvertierung automatisch gestartet werden.
   - Auto-Start startet **keine bereits manuell bestückte Queue** mit.
   - Enthält die Queue Dateien einer Watch-Regel mit „nur Queue“, wird ebenfalls nicht automatisch gestartet.
   - Bei bereits laufendem Worker genügt das Live-Add; ein zweiter Start wird nicht ausgelöst.

9. **Preflight und Verschieben werden nicht umgangen**
   - Ist im Converter `Verschieben` aktiv, wird die Watch-Datei sicher eingereiht, der automatische Start aber angehalten.
   - Der bestehende Preflight bleibt die verbindliche Zielentscheidung für Film/TV/Anime und vorhandene SxxExx-Ersetzungsregeln aus Patch E.
   - Damit führt Patch G keine unbeaufsichtigten/destruktiven Zielpfadentscheidungen anhand bloßer Watch-Folder-Namen ein.
   - Jellyfin-Aktualisierung folgt weiterhin Patch F nach einem tatsächlich erfolgreichen Move/Rename.

10. **Lazy-Loading bleibt kompatibel**
    - Ein sichtbarer H.264-/AV1-Converter kann bei Bedarf über den bereits vorhandenen Lazy-Load-Signalweg geladen werden, ohne den aktuell sichtbaren Tab umzuschalten.
    - Ist der erforderliche Converter-Tab ausgeblendet oder kann er nicht geladen werden, wird der Kandidat nicht bestätigt und später erneut versucht.

#### Stabilitäts- und Sicherheitsverbesserungen

- Unfertige Dateien werden nicht während des Schreibens verarbeitet.
- Bereits verarbeitete unveränderte Quellen werden nicht nach jedem Programmstart erneut encodiert.
- Temporär gesperrte/ausgeblendete Converter führen nicht zum Verlust eines Watch-Kandidaten.
- Watch-Folder respektiert Queue-Sperren, Live-Queue, per-Datei-Overrides, Preflight, Replacement-Regeln und Jellyfin-Lifecycle statt diese zu duplizieren.
- Auto-Start kann keine fremde/manuell zusammengestellte Queue unbeabsichtigt starten.
- Keine zusätzliche Python-Abhängigkeit wie `watchdog`; die Überwachung verwendet vorhandene Standardbibliothek plus Qt-Timer/Thread.

#### Regressionstests

Die neuen Patch-G-Tests prüfen insbesondere:

- Normalisierung von Watch-Regeln und Codec-Fallback.
- Stabilitätszeit für unveränderte Dateien.
- Neustart der Stabilitätszeit nach einer Dateiänderung.
- persistente Signatur nach erfolgreicher Übergabe und Wiederverwendung nach Neustart.
- erneute Erkennung, wenn sich eine bereits bekannte Datei tatsächlich ändert.
- rekursive und nicht rekursive Ordnerüberwachung.
- Ignorieren von Nicht-Video- und Partial-Dateien.
- Settings-Roundtrip für mehrere Watch-Regeln.
- Begrenzung/Persistenz des verarbeiteten Watch-Zustands.
- Integration in Settings, MainWindow, Converter und atomaren Live-Override-Pfad.
- bestehende Architekturverträge für MainWindow, Settings, Queue und private Objektgrenzen.

**Fokussierte Patch-G-/Architekturtests:** 55/55 Tests bestanden.  
**Gesamter Regressionstest:** 1467 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Teilarchivfehler.  
Die vier verbleibenden Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; ein CI-Vertrag erwartet die im Teilarchiv fehlende `.github`-Struktur; zwei Versions-/Build-Verträge erwarten `release_manifest.json` bzw. `build_v9.bat` außerhalb des gelieferten Teilarchivs. Es wurde keine neue Regression durch Patch G festgestellt.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für 9.8.5 sollte festgehalten werden:

- Dragon Tools kann jetzt mehrere Watch-Folder automatisch überwachen.
- Dateien werden erst nach einer einstellbaren Stabilitätszeit übernommen.
- Watch-Folder können H.265, H.264 oder AV1 und optional ein festes Encoder-Profil verwenden.
- Die Funktion nutzt vollständig die bestehende Queue einschließlich Live-Add und Duplikatschutz.
- Verarbeitete Quellen werden persistent erkannt und nach einem Neustart nicht erneut eingereiht.
- Auto-Start ist sicher gegen manuelle Queue-Inhalte abgesichert.
- Automatisches Verschieben umgeht bewusst nicht den vorhandenen Preflight.

#### Migration / neue Abhängigkeiten

- Keine neue externe Python-Abhängigkeit.
- Keine Datenbankmigration.
- Watch-Folder ist nach dem Update standardmäßig deaktiviert und muss ausdrücklich eingerichtet/aktiviert werden.



### Patch H – Mediathek Fix Queue

**Status:** umgesetzt und getestet  
**Bereich:** Mediathek / Reparaturwarteschlange / NFO / Trickplay / Medienanalyse  
**Ziel:** Gefundene, sicher reparierbare Mediathek-Probleme gesammelt prüfen, auswählen und seriell beheben, ohne vorhandene Mediendateien blind oder destruktiv zu verändern.

#### Geänderte Module

- `dragontools/core/media_library_fix_queue.py` *(neu)*
- `dragontools/gui/media_library_fix_tab.py` *(neu)*
- `dragontools/gui/media_library_fix_actions.py` *(neu)*
- `dragontools/gui/media_library_fix_controller.py` *(neu)*
- `dragontools/gui/media_library_fix_worker.py` *(neu)*
- `dragontools/worker/media_library_fix_service.py` *(neu)*
- `dragontools/gui/media_library_dialog.py`
- `dragontools/gui/media_library_dialog_contracts.py`
- `dragontools/gui/media_library_dialog_service.py`
- `dragontools/gui/media_library_dialog_view.py`
- `dragontools/worker/postprocess_runner.py`
- `dragontools/core/release_validation_package.py`
- `dragontools/tests/test_patch_h_media_library_fix_queue.py` *(neu)*

#### Funktionale Änderungen

1. **Eigener Mediathek-Tab „Fix Queue“**
   - Die bestehende Mediathek erhält einen zusätzlichen Fix-Queue-Tab.
   - Gefundene Probleme und die eigentliche Reparaturwarteschlange sind getrennt.
   - Einzelne oder alle Treffer können in die Fix Queue übernommen werden.
   - Mehrfachauswahl, Entfernen und vollständiges Leeren der Queue sind möglich.

2. **Gezielte Problemprüfung**
   - Prüfkategorien sind separat an-/abwählbar.
   - Aktuell unterstützt Patch H:
     - fehlende NFO-Dateien,
     - fehlendes oder leeres Trickplay,
     - unvollständige Mediathek-Analyse, z. B. fehlende Dauer, Video-Codec, Auflösung oder Stream-Inventar.
   - Die Prüfung liest ausschließlich den Dragon-Tools-Mediathek-Snapshot und verändert bei der Suche keine Mediendateien.
   - Die Ergebniszahl ist begrenzt; ein abgeschnittener Trefferbestand wird sichtbar gemeldet.

3. **Sichere NFO-Reparatur**
   - Fehlende NFOs können über die bestehende Postprocess-/NFO-Logik erzeugt werden.
   - Fix-Queue-NFOs arbeiten bewusst im **Create-only-/Skip-Modus**.
   - Taucht zwischen Problemprüfung und Ausführung bereits eine NFO auf, wird sie nicht überschrieben.
   - Nach erfolgreicher Erzeugung wird der NFO-Status in der Mediathek aktualisiert.

4. **Sichere Trickplay-Reparatur**
   - Fehlendes oder leeres Trickplay kann über den bestehenden Trickplay-Generator ergänzt werden.
   - Die Fix Queue erzwingt `only_missing` und `skip` statt vorhandene Trickplay-Daten zu überschreiben.
   - Der vorhandene FFmpeg-/Abbruchpfad des Trickplay-Generators wird weiterverwendet.
   - Nach der Reparatur wird der Trickplay-Status in der Mediathek aktualisiert.

5. **Mediendaten neu analysieren**
   - Bei unvollständigem Datenbankstand wird die konkrete Datei erneut über die vorhandene Medienanalyse eingelesen.
   - Dragon Tools aktualisiert damit Dauer, Video-/Audio-/Untertitel-Streams, Codec-, Auflösungs- und weitere Analysefelder aus der realen Datei.
   - Dies ist bewusst zunächst eine **Analysekorrektur**, keine blinde Container-/Timestamp-Manipulation.

6. **Serielle Batch-Verarbeitung mit Ergebnis pro Aktion**
   - Die Fix Queue läuft seriell in einem eigenen Worker.
   - Pro Eintrag werden Status und Ergebnistext angezeigt.
   - Fortschritt wird über die komplette Queue berechnet.
   - Ein Fehler einer einzelnen Datei wird als Fehlerergebnis gespeichert und stoppt die restliche Queue nicht.

7. **Abbruch und Task-Koordination**
   - Fix Queue, normaler Mediathek-Scan und NFO-Scan blockieren sich gegenseitig.
   - Das Mediathek-Fenster kann nicht geschlossen werden, solange eine Fix-Aufgabe läuft.
   - Abbruch wird an den laufenden Fix-Worker weitergereicht; laufende Postprocess-/Tool-Aufrufe erhalten denselben Worker-Kontext.

8. **Fail-closed bei verschwundenen Dateien**
   - Vor jeder Reparatur wird geprüft, ob die Mediendatei noch existiert.
   - Eine seit der Problemprüfung gelöschte/verschobene Datei wird als Fehler markiert; die Queue läuft danach weiter.

#### Bewusste Abgrenzung zu Patch I

- **Unbekannte/falsche Audio- oder Untertitelsprache wird in Patch H noch nicht automatisch korrigiert.**
- **Fehlende/falsche Tracktitel werden ebenfalls nicht auf Verdacht neu geschrieben.**
- Diese Fälle werden mit Patch I um Whisper/faster-whisper, Text-Spracherkennung und Confidence-basierte Metadatenkorrektur erweitert.
- Dadurch rät Patch H bei `und` nicht einfach „Deutsch“ und überschreibt keine Stream-Metadaten ohne belastbare Erkennung.

#### Dauer-/Timestamp-Sicherheit

- Ein fehlender/ungültiger Dauerwert in der Mediathek löst zunächst eine erneute reale Medienanalyse aus.
- Patch H führt **keine** verlustfreie Timestamp-Reparatur nur aufgrund eines fehlerhaften Datenbankwerts aus.
- Die vorhandene Duration-/Timestamp-Reparatur besitzt eigene CFR/VFR-, Framecount-, Stream- und Output-Verifikation und bleibt der verbindliche Reparaturpfad für echte Timing-Schäden.
- Damit wird ein Analyseproblem nicht mit einem Containerdefekt verwechselt.

#### Stabilitätsverbesserungen

- Reparaturen sind von der Problemerkennung getrennt; ein Scan verändert keine Dateien.
- NFO und Trickplay werden create-only ergänzt und nicht blind ersetzt.
- Ein fehlerhafter Eintrag stoppt keine Batch-Reparatur.
- Verschwundene Dateien werden unmittelbar vor dem Fix erneut geprüft.
- NFO-/Trickplay-Status wird nach erfolgreicher Reparatur gezielt aktualisiert, ohne unnötig das komplette Video neu zu analysieren.
- Ein bei der Implementierung gefundener GUI-Fehler wurde behoben: Die ausgewählten Problemkategorien werden jetzt tatsächlich an den Discovery-Worker übergeben. Ohne diese Korrektur hätte „Probleme prüfen“ wegen eines fehlenden Arguments abbrechen können.

#### Regressionstests

Neue Patch-H-Tests prüfen insbesondere:

- Erkennung fehlender NFOs, Trickplay-Daten und unvollständiger Medienanalyse.
- Keine falsche Metadaten-Reparatur bei gesunden Streamdaten.
- Deduplizierung nach Medien-ID + Fix-Aktion.
- Leichtgewichtige Aktualisierung der NFO-/Trickplay-Statusfelder.
- Sicheres Fehlerergebnis bei inzwischen fehlender Mediendatei.
- Wiederverwendung der bestehenden Medienanalyse.
- create-only NFO-/Trickplay-Konfiguration.
- unbekannte Aktionen bleiben auf den einzelnen Queue-Eintrag begrenzt.
- Einbindung des neuen Tabs, Controllers und Dialogvertrags.
- korrekte Übergabe der in der GUI ausgewählten Prüfkategorien.

**Fokussierte Patch-H-/Mediathek-Tests:** 39/39 Tests bestanden.  
**Gesamter Regressionstest:** 1478 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Teilarchivfehler.  
Die vier verbleibenden Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; ein CI-Vertrag erwartet die im Teilarchiv fehlende `.github`-Struktur; zwei Versions-/Build-Verträge erwarten `release_manifest.json` bzw. `build_v9.bat` außerhalb des gelieferten Teilarchivs. Es wurde keine neue Regression durch Patch H festgestellt.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für 9.8.5 sollte festgehalten werden:

- Die Mediathek besitzt jetzt eine eigene Fix Queue.
- Fehlende NFOs und fehlendes/leeres Trickplay können gesammelt ergänzt werden.
- Unvollständig analysierte Mediendateien können gezielt neu eingelesen werden.
- Reparaturen laufen seriell mit Status/Ergebnis pro Eintrag und isolieren Fehler auf die betroffene Datei.
- Sprache und Tracktitel werden mit dem jetzt umgesetzten Patch I Confidence-basiert korrigiert.

#### Migration / neue Abhängigkeiten

- Keine Datenbankmigration.
- Keine neue externe Python-Abhängigkeit.
- Bestehende Mediathek-Datenbanken können direkt verwendet werden.



### Patch I – Audio-/Untertitel-Spracherkennung und sichere Track-Metadatenkorrektur

**Status:** umgesetzt und getestet  
**Bereich:** Mediathek / Fix Queue / Audio / Untertitel / MKV-Metadaten / Whisper  
**Ziel:** Unbekannte Streamsprachen nicht mehr erraten, sondern über mehrere belastbare Samples bzw. Untertiteltext erkennen und erst bei ausreichender Konfidenz in MKV-Metadaten übernehmen.

#### Geänderte Module

- `dragontools/core/language_detection.py` *(neu)*
- `dragontools/core/mkv_track_metadata.py` *(neu)*
- `dragontools/core/track_titles.py` *(neu)*
- `dragontools/worker/media_stream_language_service.py` *(neu)*
- `dragontools/core/media_library_fix_queue.py`
- `dragontools/core/settings_media_library.py`
- `dragontools/core/lang_codes.py`
- `dragontools/worker/media_library_fix_service.py`
- `dragontools/gui/media_library_fix_tab.py`
- `dragontools/gui/media_library_fix_controller.py`
- `dragontools/gui/media_library_dialog.py`
- `dragontools/core/release_validation_package.py`
- `dragontools/tests/test_patch_i_language_detection.py` *(neu)*

#### Funktionale Änderungen

1. **Neue Fix-Queue-Kategorie „Sprache / Tracktitel“**
   - Die Mediathek kann jetzt interne MKV-Audio- und Untertitelstreams mit fehlender/`und`-Sprache erkennen.
   - Zusätzlich werden fehlende bzw. bewusst als generisch erkannte Tracktitel als eigene Fix-Aktion angeboten.
   - Nur tatsächlich in Patch I sicher schreibbare MKV-Streams werden als reparierbare Streamprobleme angeboten; MP4 wird nicht als vermeintlich reparierbarer Header-Fix in die Queue gestellt.

2. **Audio-Spracherkennung über optionales `faster-whisper`**
   - `faster-whisper` wird ausschließlich bei einer Audio-Spracherkennung lazy importiert und geladen.
   - Dragon Tools bleibt vollständig startfähig, wenn die optionale Abhängigkeit nicht installiert ist.
   - Standardmodell: `small`.
   - Standardmäßig werden 3 kurze Audio-Samples à 15 Sekunden analysiert.
   - Die Samples werden über frühe, mittlere und späte Bereiche der Laufzeit verteilt statt den kompletten Film zu transkribieren.
   - FFmpeg extrahiert die Samples gezielt aus dem betroffenen Audiostream als 16-kHz-Mono-WAV.
   - Ein Whisper-Modell wird innerhalb einer Fix-Queue-Ausführung nur einmal geladen und anschließend für weitere Streams wiederverwendet.

3. **GPU-/CPU-Fallback**
   - Wenn CTranslate2 eine CUDA-GPU erkennt, wird zunächst CUDA/FP16 verwendet.
   - Kann der CUDA-Pfad nicht initialisiert werden, fällt die Erkennung auf CPU/INT8 zurück.
   - Dadurch ist die Funktion nicht fest an eine NVIDIA-GPU gebunden.

4. **Konservative Mehrsample-Confidence**
   - Ergebnisse werden nicht per einfachem „2 von 3 gewinnt“ übernommen.
   - Die Konfidenz berücksichtigt die Probability-Masse des Gewinnergebnisses über alle verwertbaren Samples.
   - Widersprüchliche Samples senken die Gesamtkonfidenz deutlich.
   - Zusätzlich ist eine echte Mehrheitsunterstützung erforderlich.
   - Standard-Mindestkonfidenz: 85 %.
   - Wird der Schwellwert nicht erreicht, lautet der Fix-Status `übersprungen`; es werden keine Stream-Metadaten verändert.

5. **Direkte Text-Spracherkennung für Textuntertitel**
   - SRT/SubRip, ASS/SSA, WebVTT und weitere textbasierte Untertitel werden per FFmpeg als Text extrahiert.
   - Die Spracherkennung benötigt dafür kein Whisper-Audiomodell.
   - Unicode-Schriftsysteme werden für Japanisch, Koreanisch, Chinesisch, Russisch, Arabisch und Griechisch berücksichtigt.
   - Für lateinische Sprachen wird eine konservative Funktionswort-/Stopword-Auswertung genutzt.
   - Zu wenig oder zu uneindeutiger Text führt ebenfalls zu `übersprungen` statt zu einer geratenen Änderung.

6. **PGS/VobSub bewusst noch nicht geraten**
   - Bitmap-Untertitel (`PGS`, `VobSub/DVD`) werden in Patch I nicht per Audio oder Dateiname geraten.
   - Die Fix Queue meldet dafür ausdrücklich, dass OCR aus Patch J erforderlich ist.

7. **Sichere MKV-Trackadressierung**
   - FFprobe-Streamindizes werden nicht fälschlich direkt als `mkvpropedit track:n` interpretiert.
   - Patch I berechnet pro Datei und Streamtyp die Audio-/Subtitle-Ordinalposition.
   - MKV-Metadaten werden typbezogen als `track:a1`, `track:a2`, `track:s1`, ... adressiert.
   - Dadurch wird bei ungewöhnlicher Streamreihenfolge nicht versehentlich eine andere Spur verändert.

8. **Legacy- und IETF-Sprachtag gemeinsam setzen**
   - Erkannte Sprache wird in MKV sowohl als bevorzugter ISO-639-2-Legacy-Code als auch als IETF-Code geschrieben.
   - Beispiel Deutsch: `language=deu` plus `language-ietf=de`.
   - Das hält MKVToolNix-, FFprobe-/Jellyfin- und Dragon-Tools-Normalisierung konsistent.

9. **Tracktitel nur bei sicher ersetzbaren Titeln**
   - Benutzerdefinierte Titel wie `Director Commentary` werden nicht überschrieben.
   - Ersetzt werden nur leere/generische Titel wie `Audio`, `Subtitle`, `Track 2`, `unknown` oder `und`.
   - Audiotitel verwenden die bestehende Dragon-Tools-Titellogik, z. B. `Deutsch EAC3 5.1 640kbps`.
   - Untertitel erhalten einen kompakten Titel wie `Deutsch` bzw. `Deutsch Forced`.

10. **Nach erfolgreichem Header-Fix erneute Mediathek-Analyse**
    - Nach einer erfolgreichen `mkvpropedit`-Änderung wird die Datei erneut über die bestehende Medienanalyse eingelesen.
    - Der SQLite-Snapshot wird dadurch aus der realen Datei aktualisiert und nicht nur künstlich in der Datenbank umgeschrieben.

11. **Konfigurierbare Sprachparameter in der Fix Queue**
    - Whisper-Modell: `tiny`, `base`, `small`, `medium`, `large-v3`.
    - Mindestkonfidenz: 50–99 %.
    - Audio-Samples: 1–7.
    - Sampledauer: 5–60 Sekunden.
    - Einstellungen werden über die vorhandenen Mediathek-QSettings persistiert.

#### Sicherheitsentscheidungen

- **Kein automatisches Überschreiben bei Unsicherheit.** Unterhalb der Mindestkonfidenz wird nur ein Ergebnis protokolliert.
- **Keine MP4-In-place-Manipulation in Patch I.** Der Service besitzt eine zusätzliche Fail-closed-Prüfung; selbst bei direktem Aufruf wird MP4 nicht still remuxt/ersetzt.
- **Keine Bitmap-Untertitel-Sprache ohne OCR.** PGS/VobSub bleiben bis Patch J unangetastet.
- **Keine benutzerdefinierten Tracktitel überschreiben.** Nur klar generische Titel werden automatisch ersetzt.
- **Keine Audio-Reencodes.** FFmpeg erzeugt nur kurze temporäre Analyse-Samples; die Mediendatei selbst wird nicht encodiert.
- **MKV-Änderungen betreffen ausschließlich Header-/Track-Metadaten über `mkvpropedit`.**

#### Regressionstests

Neue Patch-I-Tests prüfen insbesondere:

- sichere Mehrsample-Konsensbildung bei 3 übereinstimmenden Whisper-Ergebnissen,
- Ablehnung widersprüchlicher Samples trotz numerischer Mehrheit,
- Text-Spracherkennung für Deutsch und Japanisch,
- Schutz benutzerdefinierter Tracktitel,
- kanonische Audio-/Forced-Untertiteltitel,
- Verteilung der Audio-Samples über die Laufzeit,
- typbezogene `mkvpropedit`-Adressierung (`track:a2` statt unsicherem globalem Index),
- Schreiben von ISO-639-2- und IETF-Sprachtag,
- Discovery von unbekannter Sprache und fehlendem Tracktitel,
- kein Angebot nicht sicher schreibbarer MP4-Header-Fixes,
- PGS/VobSub-Sperre bis Patch J,
- MP4-Fail-closed auch bei direktem Service-Aufruf,
- mehrere gemockte Whisper-Samples ohne reale Modellabhängigkeit,
- erfolgreicher Fix mit anschließender realer Mediathek-Neuanalyse,
- Low-Confidence-Ergebnis bleibt `übersprungen`,
- GUI-Einbindung der Streamkategorie und Whisper-Parameter.

**Fokussierte Patch-H/I-Tests:** 25/25 Tests bestanden.  
**Gesamter Regressionstest:** 1492 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Teilarchivfehler.  
Die vier verbleibenden Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; ein CI-Vertrag erwartet die im Teilarchiv fehlende `.github`-Struktur; zwei Versions-/Build-Verträge erwarten `release_manifest.json` bzw. `build_v9.bat` außerhalb des gelieferten Teilarchivs. Es wurde keine neue Regression durch Patch I festgestellt.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für 9.8.5 sollte festgehalten werden:

- Die Mediathek-Fix-Queue kann jetzt unbekannte MKV-Audio- und Textuntertitelsprachen erkennen und bei ausreichender Sicherheit korrigieren.
- Audio verwendet mehrere kurze `faster-whisper`-Samples statt einer vollständigen Transkription.
- Unsichere oder widersprüchliche Ergebnisse werden nicht automatisch übernommen.
- Fehlende/generische Tracktitel können sicher aus den verifizierten Streamdaten ergänzt werden.
- PGS/VobSub bleiben bis zur OCR-Erweiterung unangetastet.

#### Migration / neue Abhängigkeiten

- Keine Datenbankmigration.
- `faster-whisper` ist **optional** und wird lazy geladen; ohne Paket bleibt Dragon Tools vollständig nutzbar, nur Audio-Spracherkennung wird übersprungen.
- Für die 9.8.5-PyInstaller-/EXE-Auslieferung sind `faster-whisper` und CTranslate2 jetzt in der optionalen/buildrelevanten Dependency-Konfiguration enthalten. `build_v9.bat` prüft beide Imports, installiert fehlende Pakete aus `requirements-optional.txt` und lässt PyInstaller beide Pakete samt Metadaten explizit einsammeln.
- Whisper-Modelldaten sollten nicht fest in die EXE eingebrannt werden; sie können beim ersten Einsatz geladen und anschließend im üblichen Modellcache wiederverwendet werden.
- Der vorliegende Review-/Patch-Container enthält kein reales `faster-whisper`-Modell; die Inferenzlogik wurde daher deterministisch mit gemockten Sample-Ergebnissen getestet. Ein abschließender Windows-/CUDA-Runtime-Test gehört vor dem 9.8.5-Release in den vollständigen Build-Test.

### Patch J – PGS/VobSub OCR mit manuellem Review

**Status:** umgesetzt und getestet  
**Bereich:** Mediathek Fix Queue / Bilduntertitel / OCR / Tesseract / SRT-Sidecars  
**Ziel:** PGS- und VobSub/DVD-Bilduntertitel sicher in editierbare SRT-Entwürfe überführen, ohne OCR-Fehler blind zu übernehmen oder die originale Bilduntertitelspur zu verändern.

#### Geänderte bzw. neue Module

- `dragontools/core/bitmap_subtitle_ocr.py` *(neu)*
- `dragontools/worker/bitmap_subtitle_ocr_service.py` *(neu)*
- `dragontools/gui/bitmap_subtitle_ocr_review.py` *(neu)*
- `dragontools/core/media_library_fix_queue.py`
- `dragontools/worker/media_library_fix_service.py`
- `dragontools/gui/media_library_fix_tab.py`
- `dragontools/gui/media_library_fix_controller.py`
- `dragontools/gui/media_library_fix_actions.py`
- `dragontools/gui/media_library_dialog_contracts.py`
- `dragontools/core/settings_media_library.py`
- `dragontools/core/settings_storage.py`
- `dragontools/core/tool_paths.py`
- `dragontools/gui/settings_sections/runtime.py`
- `dragontools/tests/test_patch_j_bitmap_subtitle_ocr.py` *(neu)*

#### Funktionale Änderungen

1. **Eigene optionale OCR-Kategorie in der Fix Queue**
   - `PGS/VobSub OCR` ist separat an-/abwählbar und standardmäßig deaktiviert.
   - PGS (`hdmv_pgs_subtitle`) sowie DVD/VobSub (`dvd_subtitle`, `vobsub`) werden als OCR-Kandidaten erkannt.
   - Bilduntertitel werden nicht mehr als normale Text-Spracherkennung behandelt.
   - Patch J bietet den OCR-Kandidaten auch dann an, wenn die vorhandene Track-Sprache bereits korrekt gesetzt ist.

2. **Tesseract als optionale OCR-Engine**
   - Tesseract wird als eigenes externes Tool in den Dragon-Tools-Toolpfaden unterstützt.
   - Auto-Suche und benutzerdefinierter Tool-Pfad sind in den Einstellungen vorhanden.
   - Die benötigten Tesseract-Sprachdaten werden vor der OCR geprüft.
   - Standard-Sprachpakete der Fix Queue: `deu+eng`; die Angabe ist frei konfigurierbar, z. B. `deu+eng+jpn`.

3. **FFmpeg rendert PGS/VobSub für OCR**
   - FFprobe liest die Zeitpunkte der betroffenen Bilduntertitel-Pakete aus.
   - Für jeden Cue wird am zeitlichen Mittelpunkt ein OCR-Bild erzeugt.
   - Der bevorzugte Renderpfad vergleicht ein Video-Frame mit derselben Szene inklusive Bitmap-Untertitel und bildet daraus ein Differenzbild; dadurch wird der Videohintergrund weitgehend entfernt.
   - Falls dieser Filterpfad mit einem konkreten FFmpeg-Build nicht funktioniert, existiert ein konservativer Fallback mit direktem Bitmap-Subtitle-Overlay.
   - PGS und VobSub verwenden damit dieselbe kontrollierte OCR-Pipeline.

4. **OCR-Confidence wird aus Tesseract-TSV übernommen**
   - Tesseract liefert Wort-Konfidenzen; Dragon Tools bildet daraus eine nach Wortlänge gewichtete Cue-Konfidenz.
   - Standard-Grenze für „unsicher“: 75 %.
   - Der Grenzwert ist in der Fix Queue zwischen 30 und 99 % einstellbar.
   - Unsichere Cues werden nicht verworfen, sondern im Review explizit markiert.

5. **Doppelte/mehrfach gerenderte Cues werden konsolidiert**
   - Direkt aufeinanderfolgende identische OCR-Texte werden zusammengeführt.
   - Die Zeitspanne wird erweitert, die niedrigere Confidence bleibt als konservativer Wert erhalten.
   - Leere OCR-Ergebnisse werden nicht als SRT-Cues geschrieben.

6. **Zweistufiger Sicherheitsworkflow statt automatischer Konvertierung**
   - Die Fix Queue erzeugt zunächst ausschließlich:
     - `*.srt.pending` als OCR-Entwurf,
     - `*.json.pending` als Confidence-/Review-Bericht.
   - Der Queue-Status lautet anschließend `review`; das ist weder Erfolg noch Fehler.
   - Ein normales `.srt` wird zu diesem Zeitpunkt ausdrücklich noch nicht erzeugt.

7. **Neuer OCR-Review-Dialog**
   - `OCR-Entwurf prüfen` öffnet den ausgewählten Entwurf.
   - Angezeigt werden pro Cue:
     - Startzeit,
     - Endzeit,
     - OCR-Confidence,
     - bearbeitbarer OCR-Text.
   - Unsichere Cues sind mit einem Warnhinweis versehen.
   - Der Benutzer kann Texte korrigieren oder einen Cue durch Leeren des Textes entfernen.
   - Nur `Bestätigen & SRT speichern` erzeugt das endgültige SRT.

8. **Originalspur bleibt vollständig erhalten**
   - Die PGS-/VobSub-Spur im MKV wird weder gelöscht noch ersetzt noch verändert.
   - Patch J schreibt nur einen zusätzlichen SRT-Sidecar.
   - Eine OCR-Konvertierung kann deshalb jederzeit mit der originalen Bilduntertitelspur verglichen werden.

9. **Kollisionssicheres finales Sidecar**
   - Bestehende SRT-Dateien werden niemals überschrieben.
   - Beispiel: Existiert bereits `Film.de.forced.srt`, verwendet Patch J automatisch `Film.de.forced.1.srt`, danach `.2.srt` usw.
   - Forced-Status wird im Sidecar-Dateinamen erhalten.

10. **Spracherkennung aus Patch I wird weiterverwendet**
    - Ist die Bitmap-Track-Sprache bekannt, wird sie für das finale Sidecar übernommen.
    - Ist sie `und`/unbekannt, wird der erzeugte OCR-Text mit der vorhandenen Text-Spracherkennung aus Patch I ausgewertet.
    - Kann die Sprache nicht sicher bestimmt werden, bleibt der Sidecar-Sprachtag bewusst `und` statt geraten zu werden.

11. **Fail-closed auf MKV begrenzt**
    - Die automatische Bitmap-OCR-Fix-Queue wird in Patch J ausschließlich für interne MKV-Bilduntertitel angeboten.
    - Direkte Service-Aufrufe mit MP4 werden ebenfalls abgelehnt.
    - Dadurch entsteht kein zusätzlicher MP4-Remux-/Replace-Pfad nur für OCR.

12. **Abbruch und temporäre Dateien**
    - Während der OCR wird zwischen Cues auf das bestehende Abbruchsignal geprüft.
    - Temporäre Renderbilder liegen in einem temporären Arbeitsverzeichnis und werden automatisch entfernt.
    - Ein abgebrochener Lauf erzeugt keinen halb bestätigten finalen SRT-Sidecar.

#### Stabilitäts- und Sicherheitsverbesserungen

- OCR-Ergebnisse werden niemals automatisch als fehlerfreie Untertitel behandelt.
- Niedrige Confidence bleibt sichtbar und erzwingt keinen automatischen Metadaten-Fix.
- Die originale PGS-/VobSub-Spur bleibt immer als verlustfreie Referenz erhalten.
- Vorhandene SRT-Sidecars werden nicht überschrieben.
- Ein bereits vorhandener `.pending`-Entwurf wird nicht still ersetzt; der Benutzer muss ihn zuerst prüfen oder entfernen.
- Fehlende Tesseract-Sprachdaten führen zu einer klaren Fehlermeldung statt zu einem OCR-Lauf mit falschem Sprachmodell.
- Die neue OCR-Funktion ist vollständig optional; ohne Tesseract funktionieren alle anderen Dragon-Tools-Bereiche weiter.

#### Tests und reale Tool-Prüfung

Neue Patch-J-Tests prüfen insbesondere:

- Tesseract-TSV-Parsing und gewichtete Confidence,
- Erhalt von Zeilenumbrüchen,
- Zusammenführen identischer aufeinanderfolgender OCR-Cues,
- konservative Confidence beim Merge,
- `.pending`-Entwurf und JSON-Review-Bericht,
- Finalisierung erst nach explizitem Review,
- kollisionssichere Sidecar-Namen ohne Überschreiben vorhandener SRTs,
- PGS-, DVD-Subtitle- und VobSub-Discovery,
- keine normale Sprach-Fix-Aktion für Bitmap-Untertitel ohne aktivierte OCR-Kategorie,
- vollständige OCR-Orchestrierung mit gemocktem FFmpeg/Tesseract,
- MKV-only-Fail-closed,
- GUI-Einbindung von OCR-Kategorie, Tesseract-Sprachdaten, Confidence und Review-Button,
- Tesseract als regulär konfigurierbarer Dragon-Tools-Toolpfad.

**Fokussierte Patch-H/I/J-Tests:** 35/35 Tests bestanden.  
**Realer Tesseract-Smoke-Test:** Tesseract 5.5 erkannte ein synthetisches deutsches Subtitle-Bild korrekt mit 95,3 % berechneter Confidence.  
**Gesamter Regressionstest (vier Blöcke):** 1502 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Teilarchivfehler.  
Die vier bekannten Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; ein CI-Vertrag erwartet die im Teilarchiv fehlende `.github`-Struktur; zwei Versions-/Build-Verträge erwarten `release_manifest.json` bzw. `build_v9.bat`. Es wurde keine neue Regression durch Patch J festgestellt.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für 9.8.5 sollte festgehalten werden:

- Die Mediathek-Fix-Queue kann PGS- und VobSub-Bilduntertitel jetzt optional per Tesseract in einen SRT-Entwurf umwandeln.
- OCR-Ergebnisse müssen vor der finalen SRT-Erstellung manuell geprüft werden.
- Confidence wird pro Cue ausgewiesen; unsichere Zeilen sind editierbar.
- Original-Bilduntertitel bleiben immer erhalten.
- Tesseract und die verwendeten OCR-Sprachdaten sind konfigurierbar.

#### Migration / neue Abhängigkeiten

- Keine Datenbankmigration.
- **Tesseract OCR ist eine neue optionale externe Abhängigkeit** für Patch J.
- Für die spätere 9.8.5-Auslieferung sollte entschieden werden, ob Tesseract samt ausgewählten Sprachdaten gebündelt oder wie die übrigen externen Tools separat erkannt/konfiguriert wird.
- Die Standardkonfiguration erwartet `deu+eng`; zusätzliche Sprachen wie Japanisch benötigen das entsprechende Tesseract-Sprachpaket (`jpn`).
- Der eigentliche OCR-Workflow besitzt keine neue Python-OCR-Laufzeitabhängigkeit wie EasyOCR/PaddleOCR; Dragon Tools ruft die Tesseract-CLI direkt auf.
- Vor dem finalen Windows-Release sollte zusätzlich ein realer MKV-Test mit mindestens einer PGS- und einer VobSub-Spur durchgeführt werden. Der Review-Container besitzt keine solche reale Medienfixture.


---


### Patch K – Automatische VMAF-Qualitätsziel-Suche

**Status:** umgesetzt und getestet  
**Bereich:** Encoder / Qualitätstester / Workflow-Planung / VMAF  
**Ziel:** Optional pro SDR-Datei automatisch den höchsten noch zulässigen CQ-/CRF-/Q-/QP-Wert finden, der ein vorgegebenes VMAF-Ziel gegenüber der Quelle erreicht, ohne die absolute Quellqualität zu behaupten oder bestehende feste Encoderwerte zu ersetzen.

#### Geänderte bzw. neue Module

- `dragontools/core/quality_target.py` *(neu)*
- `dragontools/worker/quality_target_service.py` *(neu)*
- `dragontools/worker/quality_target_integration.py` *(neu)*
- `dragontools/core/settings_conversion.py`
- `dragontools/gui/settings_sections/video.py`
- `dragontools/gui/settings_dialog.py`
- `dragontools/gui/encoder_settings_options.py`
- `dragontools/worker/quality_process_runner.py`
- `dragontools/worker/converter_thread_state.py`
- `dragontools/worker/converter_runtime_builder.py`
- `dragontools/worker/workflow_factory.py`
- `dragontools/worker/workflow_planning_service.py`
- `dragontools/worker/workflow_engine.py`
- `dragontools/core/release_validation_smoke_modules.py`
- `dragontools/tests/test_patch_k_quality_target.py` *(neu)*

#### Funktionale Änderungen

1. **Fester Qualitätswert bleibt der Standard**
   - Die VMAF-Zielsuche ist standardmäßig deaktiviert.
   - Ohne Aktivierung verhalten sich H.264-, H.265- und AV1-Konvertierung unverändert.
   - Der bisherige CQ/CRF/Q/QP-Wert bleibt immer der sichere Fallback.

2. **Neuer Einstellungsbereich `Automatisches VMAF-Qualitätsziel`**
   - Aktivierung global an-/abwählbar.
   - Konfigurierbar sind:
     - Ziel-VMAF, Standard `95.0`,
     - Anzahl repräsentativer Samples, Standard `3`,
     - Samplelänge, Standard `10 s`,
     - Suchbereich für CQ/CRF/Q/QP, Standard `18–30`.
   - Die Grenzen werden beim Speichern normalisiert, falls der Benutzer sie vertauscht.

3. **Per-Datei-Suche nach der normalen Medienanalyse**
   - Dragon Tools entscheidet den Qualitätswert für jede Datei separat.
   - Die ermittelte Zahl wird nur in den aktuellen `WorkflowContext` übernommen.
   - Globale Encoderwerte, Profile und nachfolgende Dateien werden nicht verändert.

4. **Repräsentative Testsegmente**
   - Die vorhandene automatische Segmentauswahl des Qualitätstesters wird wiederverwendet.
   - Die Samples werden über die Laufzeit verteilt statt nur am Dateianfang gewählt.
   - Bei Downscale wird derselbe Ziel-Scale-Modus wie beim Hauptencode verwendet.

5. **Adaptive/binäre Suche statt vollständigem Durchprobieren**
   - Niedrigere Qualitätswerte bedeuten höhere Qualität/größere Dateien.
   - Gesucht wird der **höchste** Wert, der das Ziel-VMAF noch erreicht.
   - Zuerst wird der kompressionsstärkste obere Grenzwert geprüft.
   - Besteht er bereits, endet die Suche sofort.
   - Andernfalls wird der qualitätsstärkste untere Grenzwert geprüft und der verbleibende Bereich anschließend binär eingegrenzt.
   - Dadurch müssen bei einem typischen Bereich 18–30 nur wenige Kandidaten statt aller 13 Werte getestet werden.

6. **Mehrere Samples werden gemeinsam bewertet**
   - Jeder Kandidat wird über alle konfigurierten Samples getestet.
   - Der Entscheidungswert ist das arithmetische Mittel der gemessenen Segment-VMAF-Werte.
   - Einzelwerte und Mittelwert werden im normalen Dragon-Tools-Log ausgegeben.

7. **Encoder-spezifische Qualitätsparameter**
   - CPU: `CRF`
   - NVIDIA NVENC: `CQ`
   - Intel QSV: `Q`
   - AMD AMF: `QP`
   - Der gefundene Wert wird sowohl in den effektiven Workflow-Wert als auch in die jeweils korrekte Encoderoption geschrieben.

8. **Keine falsche Aussage über die Quellqualität**
   - VMAF vergleicht Testencode und Originalsegment.
   - Die Funktion bewertet damit ausschließlich den zusätzlichen Verlust durch den neuen Encode.
   - Eine schlechte Quelle erhält nicht automatisch die Aussage „gute Qualität“, nur weil der Re-Encode nahe an ihr liegt.

9. **HDR/Dolby Vision/HLG bleiben vorerst beim festen Wert**
   - Die automatische Entscheidung ist in Patch K bewusst auf SDR begrenzt.
   - Normales `libvmaf` ist für PQ/HLG/Dolby-Vision nicht als verlässliche automatische HDR-Entscheidungsmetrik ausreichend.
   - HDR-, HDR10+-, Dolby-Vision- und HLG-Quellen werden deshalb protokolliert übersprungen und mit dem bisherigen festen Qualitätswert encodiert.

10. **Fail-closed bei unzureichender Messbasis**
    - Unbekannte Quelllaufzeit → feste Qualität bleibt aktiv.
    - FFprobe des Testoutputs schlägt fehl → keine automatische Entscheidung.
    - VMAF kann nicht ermittelt werden → feste Qualität bleibt aktiv.
    - Selbst der qualitätsstärkste konfigurierte Wert erreicht das Ziel nicht → feste Qualität bleibt aktiv.
    - Es wird ausdrücklich nicht still auf den minimalen CRF/CQ umgeschaltet und dadurch eine unerwartet große Datei erzeugt.

11. **Temporäre Testoutputs werden laufend bereinigt**
    - Testencodes liegen nur in einem temporären Verzeichnis.
    - Ein Segmentoutput wird unmittelbar nach der VMAF-Messung entfernt.
    - Der Suchlauf hinterlässt keine Testvideos neben der Quelldatei.

12. **Abort-Verhalten an den Converter angepasst**
    - `Sofort abbrechen` beendet auch einen laufenden VMAF-Testprozess.
    - `Nach aktueller Datei abbrechen` lässt die aktuell bearbeitete Datei einschließlich ihrer Qualitätsziel-Suche sauber fertiglaufen.
    - Der allgemeine Qualitätstester behält sein bisheriges direktes Abort-Verhalten.

#### Stabilitäts- und Sicherheitsverbesserungen

- Die Funktion ist vollständig opt-in und kann einen vorhandenen festen Encoderwert nicht unbemerkt ersetzen, wenn die Messung unsicher oder technisch nicht möglich ist.
- Qualitätsziel-Ergebnisse sind auf den aktuellen Datei-Kontext beschränkt; Profile und globale UI-Werte werden nicht mutiert.
- HDR/DV/HLG wird nicht mit einer ungeeigneten SDR-VMAF-Automatik entschieden.
- Fehlgeschlagene Testprobes verwenden keine geratenen 1920×1080-Werte.
- Temporäre Testdateien werden nach jeder Messung entfernt.
- Die bestehenden Architekturgrenzen für Converter, Settings und Encoder-Controller mussten nicht aufgeweicht werden.
- Die neuen Module sind Bestandteil des Release-Smoke-Vertrags.

#### Tests und reale Tool-Prüfung

Neue Patch-K-Tests prüfen insbesondere:

- Normalisierung und Begrenzung der Konfiguration,
- direkten Treffer am oberen Suchbereich,
- binäre Suche nach dem höchsten noch bestandenen Ganzzahlwert,
- Fail-closed wenn selbst der untere Grenzwert das Ziel verfehlt,
- korrekte Zuordnung auf NVENC-CQ, QSV-Q, AMF-QP und CPU-CRF,
- HDR-Sperre,
- unbekannte Quelllaufzeit,
- vollständige adaptive Service-Suche mit mehreren gemockten VMAF-Samples,
- Übernahme des gefundenen Werts in den aktuellen Workflow,
- unveränderten festen Wert bei nicht angewendetem Ergebnis.

**Patch-K-Regressionstests:** 10/10 bestanden.  
**Fokussierter Architektur-/Workflow-Abschlussblock:** 35/35 bestanden.  
**Realer FFmpeg-Testencode:** synthetisches H.264-Testmaterial wurde über den neuen Segment-Encodepfad erfolgreich erzeugt und mit `ffprobe` als 320×180 validiert.  
**Gesamter Regressionstest (vier Blöcke):** 1512 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Teilarchivfehler.  
Die vier bekannten Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; ein CI-Vertrag erwartet die im Teilarchiv fehlende `.github`-Struktur; zwei Versions-/Build-Verträge erwarten `release_manifest.json` bzw. `build_v9.bat`. Es wurde keine neue Regression durch Patch K festgestellt.

Der Linux-FFmpeg-Build der Review-Umgebung enthält **kein `libvmaf`-Filtermodul**. Die reale VMAF-Messung selbst konnte deshalb hier nicht gegen einen echten FFmpeg-`libvmaf`-Lauf geprüft werden. Suchlogik, Segment-Encoding, Probe, Workflow-Integration und Fallbackverhalten sind deterministisch getestet. Vor dem 9.8.5-Windows-Release sollte mit dem gebündelten FFmpeg einmal ein echter VMAF-Zieltest durchgeführt werden.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für 9.8.5 sollte festgehalten werden:

- Dragon Tools kann für SDR-Encoding optional automatisch einen CQ-/CRF-/Q-/QP-Wert anhand eines Ziel-VMAF bestimmen.
- Standard bleibt weiterhin der manuell konfigurierte feste Qualitätswert.
- Die Funktion bewertet Re-Encode-Verlust gegenüber der Quelle, nicht die absolute Güte der Quelle.
- Ziel-VMAF, Sampleanzahl, Sampledauer und Suchbereich sind konfigurierbar.
- HDR/DV/HLG nutzt in 9.8.5 weiterhin den festen Qualitätswert.
- Im Log werden getestete Qualitätswerte, Segment-VMAFs und der gewählte Endwert ausgewiesen.

#### Migration / neue Abhängigkeiten

- Keine Datenbankmigration.
- Neue QSettings-Werte unter `quality_target/*`; bestehende Installationen bleiben durch `enabled=false` unverändert.
- Keine neue Python-Abhängigkeit.
- Voraussetzung für die tatsächliche automatische Bewertung ist ein FFmpeg-Build mit verfügbarem `libvmaf`-Filter. Fehlt er, bleibt Dragon Tools beim festen Qualitätswert.
- Vor dem finalen Release muss der mit der EXE ausgelieferte FFmpeg-Build auf `libvmaf` geprüft werden.



### Patch L – Native Windows-Benachrichtigungen

**Status:** umgesetzt und getestet  
**Bereich:** Desktop-Benachrichtigungen / Converter-Queue / Fehlertransparenz / Einstellungen  
**Ziel:** Lange oder unbeaufsichtigte Konvertierungsläufe können optional über native Windows-Desktopmeldungen über Abschluss und Fehler informieren, ohne externe Dienste oder zusätzliche Python-Abhängigkeiten einzuführen.

#### Geänderte bzw. neue Module

- `dragontools/core/settings_notifications.py` *(neu)*
- `dragontools/core/conversion_notifications.py` *(neu)*
- `dragontools/core/settings.py`
- `dragontools/core/release_validation_package.py`
- `dragontools/gui/windows_notification_backend.py` *(neu)*
- `dragontools/gui/settings_sections/notifications.py` *(neu)*
- `dragontools/gui/settings_sections/runtime.py`
- `dragontools/gui/settings_dialog.py`
- `dragontools/gui/convert_widget_composition.py`
- `dragontools/gui/conversion_result_service.py`
- `dragontools/gui/conversion_result_file_events.py`
- `dragontools/gui/conversion_result_finish.py`
- `dragontools/gui/conversion_run_finalizer.py`
- `dragontools/tests/test_patch_l_windows_notifications.py` *(neu)*

#### Funktionale Änderungen

1. **Neuer Einstellungsbereich „Windows-Benachrichtigungen“**
   - Globaler Hauptschalter; standardmäßig deaktiviert.
   - Separat aktivierbar:
     - Queue vollständig abgeschlossen,
     - Fehler,
     - jede erfolgreich abgeschlossene Datei.
   - Queue-Abschluss und Fehler sind nach Aktivierung des Hauptschalters standardmäßig eingeschaltet.
   - Einzeldatei-Meldungen sind standardmäßig ausgeschaltet, damit große Queues nicht unnötig viele Meldungen erzeugen.
   - Einstellungen werden unter `notifications/*` in QSettings gespeichert und bei jedem Ereignis neu gelesen. Änderungen gelten daher auch für bereits geöffnete Converter-Tabs ohne App-Neustart.

2. **Native Windows-Ausgabe ohne neue Fremdbibliothek**
   - Die Zustellung erfolgt über `QSystemTrayIcon.showMessage()` und damit über die Windows-Systemtray-/Benachrichtigungsintegration von Qt.
   - Das temporär benötigte Tray-Objekt wird nur bei einer Meldung eingeblendet und nach kurzer Zeit wieder ausgeblendet.
   - Informations-, Warn- und Fehlermeldungen verwenden passende native Meldungssymbole.
   - Auf Nicht-Windows-Systemen bleibt das Backend wirkungslos; die Verarbeitung läuft unverändert weiter.

3. **Sofortige Fehlermeldungen für einzelne Dateien**
   - Terminale Dateiresultate `❌` und `⚠️` erzeugen bei aktivierter Fehleroption unmittelbar eine Benachrichtigung.
   - Der Dateiname und eine kompakte vorhandene Fehlerbeschreibung werden angezeigt.
   - Bewusst übersprungene Dateien (`⏭️`) gelten nicht als Fehlerbenachrichtigung.

4. **Optionale Meldung nach erfolgreicher Einzeldatei**
   - Terminale `✅`-Ergebnisse können auf Wunsch einzeln gemeldet werden.
   - Die Option ist bewusst separat und standardmäßig aus.
   - Post-Processing-Pending-Zustände lösen keine vorzeitige Erfolgsmeldung aus; gemeldet wird erst das terminale Dateiergebnis.

5. **Queue-Abschluss wird erst am echten Run-Ende gemeldet**
   - Die Abschlussmeldung läuft über den bestehenden Run-Finalizer.
   - Optionales Verschieben ist zu diesem Zeitpunkt bereits beendet.
   - Die Meldung enthält Erfolgs-, Fehler- und Übersprungen-Zähler sowie bei Move-Läufen die Move-Zähler.
   - Läufe mit Fehlern verwenden ein Warnsymbol, erfolgreiche Läufe ein Informationssymbol.
   - Ein abgebrochener Lauf wird ausdrücklich **nicht** als „Queue abgeschlossen“ gemeldet.
   - Werden Fehlerdateien im Abschlussdialog erneut in die Queue gelegt, wird für den gerade weitergeführten Lauf keine irreführende Abschlussmeldung ausgegeben.

6. **Verschiebefehler werden separat sichtbar**
   - `move_errors > 0` erzeugt bei aktivierter Fehleroption eine eigene Fehlermeldung.
   - Dadurch werden auch Fehler nach erfolgreich abgeschlossenem Encode sichtbar, die erst beim finalen Verschieben entstehen.

7. **Interne Abschlussfehler können gemeldet werden**
   - Unerwartete Ausnahmen in `on_finished()` bzw. im finalen Run-Finalizer werden best effort an den Benachrichtigungsdienst gemeldet.
   - Lange Tracebacks werden für die Desktopmeldung kompakt gekürzt; das vollständige Logging bleibt unverändert erhalten.

#### Stabilitäts- und Sicherheitsverbesserungen

- Die gesamte Benachrichtigungsfunktion ist opt-in und verändert bei bestehenden Installationen kein Verhalten.
- Notification-Zustellung ist konsequent **best effort**: Fehler im Windows-/Tray-Backend können niemals einen Encode, Move, Jobstatus oder Run-Finalizer fehlschlagen lassen.
- Die fachliche Ereignislogik liegt in einem Qt-freien Core-Service; Windows-/Qt-Ausgabe ist in einem separaten Backend gekapselt.
- Es wurde keine Discord-, Telegram-, Slack- oder sonstige dienstspezifische Abhängigkeit eingeführt.
- Keine neue Python-Abhängigkeit und keine Netzwerkkommunikation.
- Windows-Pfade werden für Meldungen plattformunabhängig korrekt auf den reinen Dateinamen reduziert.
- Neue Module wurden in den Release-Smoke-Vertrag aufgenommen, ohne die bestehende Größenbegrenzung von `release_validation_package.py` aufzuweichen.

#### Tests

Neue Patch-L-Tests prüfen insbesondere:

- Opt-in-Default,
- separate Einzeldatei-Erfolgsoption,
- unmittelbare Datei-Fehlermeldungen,
- keine Fehlermeldung für bewusst übersprungene Dateien,
- korrekte Queue-Zusammenfassung einschließlich Move-Zählern,
- separate Meldung bei Verschiebefehlern,
- keine Abschlussmeldung bei Abbruch,
- best-effort-Verhalten bei Backend-Ausnahmen,
- Verdrahtung von Result-Service, Finalizer, Windows-Backend und Einstellungsoberfläche.

**Patch-L-Regressionstests:** 9/9 bestanden.  
**Fokussierter Integrations-/Architekturblock:** 71 Tests bestanden, 1 übersprungen.  
**Gesamter Regressionstest in vier Blöcken:** 1521 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Teilarchivfehler.  
Die vier bekannten Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; ein CI-Vertrag erwartet die im Teilarchiv fehlende `.github`-Struktur; zwei Versions-/Build-Verträge erwarten `release_manifest.json` bzw. `build_v9.bat`. Es wurde keine neue Regression durch Patch L festgestellt.

Die Review-Umgebung ist Linux und enthält kein PyQt6-Systemtray. Die tatsächliche visuelle Darstellung einer Windows-Benachrichtigung konnte deshalb hier nicht als Hardware-/Desktop-Smoke-Test ausgeführt werden. Vor dem finalen 9.8.5-Release sollte die erzeugte Windows-EXE einmal mit einer Testqueue auf Queue-Abschluss, Dateifehler und optionalen Einzeldatei-Abschluss geprüft werden.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für 9.8.5 sollte festgehalten werden:

- Dragon Tools kann optional native Windows-Benachrichtigungen anzeigen.
- Meldungen sind getrennt für Queue-Abschluss, Fehler und einzelne erfolgreiche Dateien steuerbar.
- Einzeldatei-Meldungen sind standardmäßig deaktiviert.
- Ein Abbruch wird nicht als erfolgreicher Queue-Abschluss gemeldet.
- Benachrichtigungsfehler beeinflussen niemals die Medienverarbeitung.
- Es wurden keine externen Benachrichtigungsdienste integriert.

#### Migration / neue Abhängigkeiten

- Keine Datenbankmigration.
- Neue QSettings-Werte unter `notifications/*`.
- Bestehende Installationen bleiben durch `notifications/enabled=false` unverändert.
- Keine neue Python-Abhängigkeit; verwendet wird die bereits vorhandene PyQt6-/Windows-Systemtray-Integration.

### Patch M – Experimentelles SDR → HDR Enhancement – umgesetzt

#### Geänderte / neue Module

- `core/sdr_hdr_enhancement.py` **neu**
  - zentrale, Qt-freie Eignungsprüfung für SDR→HDR, Konfigurationsnormalisierung und libplacebo-Filterplanung.
- `worker/sdr_hdr_runtime.py` **neu**
  - echte FFmpeg/libplacebo/Vulkan-Runtimeprobe mit Cache; ein bloß in `ffmpeg -filters` gelisteter, aber nicht initialisierbarer Filter gilt bewusst als nicht verfügbar.
- `core/settings_conversion.py`
  - neue QSettings-Schlüssel und Defaults für das experimentelle Enhancement.
- `gui/settings_dialog.py`
  - neuer sichtbarer Einstellungsbereich `SDR → HDR Enhancement (experimentell)`.
- `gui/settings_sections/video.py`
  - Opt-in-Schalter und konfigurierbare `contrast_recovery`-Stärke.
- `gui/encoder_settings_options.py`
  - übernimmt die globalen Enhancement-Einstellungen in die Encoderoptionen.
- `worker/converter_runtime_builder.py`
  - führt beim Worker-Start die echte libplacebo-Initialisierungsprobe aus und stellt das Ergebnis für alle per-Datei-Encoderprofile bereit.
- `worker/encode_plan_service.py`
  - aktiviert Range Expansion nur für sicher geeignete SDR-BT.709-Quellen, H.265/AV1 und funktionsfähiges libplacebo.
- `worker/hdr10_color.py`
  - HDR10-Ausgabetags können jetzt auch für bewusst erzeugte SDR→HDR-Ausgaben erzwungen werden.
- `worker/standard_pipeline_runner.py`
  - setzt bei angewendetem Enhancement BT.2020/PQ/Limited/10-Bit-Ausgabeparameter und bei x265 die passenden HDR10-VUI-Parameter.
- `worker/media_contract.py` / `worker/media_contract_builder.py`
  - finaler Medienvertrag erwartet bei Enhancement tatsächlich HDR und mindestens 10 Bit.
- `worker/workflow_planning_service.py`
  - reicht den real wirksamen Enhancement-Status in die Output-Verifikation weiter.
- `worker/quality_target_service.py`
  - Patch K wird bei aktivem SDR→HDR bewusst übersprungen; SDR-Referenz gegen HDR-Ausgabe wird nicht als automatische VMAF-Entscheidung missbraucht.
- `core/release_validation_smoke_modules.py`
  - neue Core-/Worker-Module in den Release-Smoke-Vertrag aufgenommen.
- `tests/test_patch_m_sdr_hdr_enhancement.py` **neu**
  - 9 deterministische Regressionstests für Eligibility, Filter, Runtimeprobe, HDR-Vertrag und Patch-K-Interaktion.

#### Funktionale Änderungen

1. **Explizites Opt-in, standardmäßig aus**
   - Neue Einstellung `SDR BT.709 per libplacebo nach HDR10 erweitern`.
   - Bestehende Installationen verhalten sich ohne Aktivierung exakt wie bisher.
   - Die Funktion wird in GUI und Dokumentation ausdrücklich als **experimentell** bezeichnet.

2. **Kein bloßes HDR-Um-Taggen**
   - Dragon Tools verwendet libplacebo `inverse_tonemapping=1` zur Range Expansion.
   - Ausgabe wird als 10-Bit BT.2020/PQ/Limited erzeugt.
   - Gamut-Mapping ist `perceptual`; Tone-Mapping-Kurve ist `spline`.
   - `contrast_recovery` ist in den Einstellungen von 0,00 bis 3,00 konfigurierbar; Default 0,30.

3. **Strenge Quell-Eignungsprüfung**
   - Enhancement nur bei Quellen, die eindeutig als SDR erkannt werden.
   - Primärfarben müssen explizit BT.709 sein.
   - Transferfunktion muss explizit BT.709 sein.
   - Eine vorhandene Matrix muss BT.709 sein.
   - HDR, HDR10+, Dolby Vision und HLG werden niemals durch diesen Pfad geschickt.
   - Unklare/fehlende Farbtags führen zum normalen SDR-Encode statt zu geratenen Annahmen.

4. **Nur H.265/HEVC und AV1**
   - H.264 wird für künstlich erzeugtes HDR bewusst nicht unterstützt.
   - H.265 und AV1 werden auf 10-Bit-Ausgabe festgelegt.
   - x265 erhält zusätzlich die HDR10-VUI-Parameter `colorprim=bt2020`, `transfer=smpte2084`, `colormatrix=bt2020nc`, `range=limited`, `hdr10=1`.

5. **Echter libplacebo-/Vulkan-Selbsttest vor dem Encode**
   - Ein Eintrag in `ffmpeg -filters` reicht nicht als Verfügbarkeitsnachweis.
   - Beim Worker-Start wird ein 64×64-Testframe tatsächlich durch libplacebo geschickt.
   - Damit werden auch Fälle erkannt, in denen FFmpeg libplacebo einkompiliert hat, aber kein kompatibler Vulkan-Treiber initialisiert werden kann.
   - Der Test ist pro FFmpeg-Pfad gecacht und läuft nicht pro Datei neu.

6. **Fail-closed / normaler SDR-Fallback**
   - libplacebo fehlt → normaler SDR-Encode.
   - Vulkan/libplacebo lässt sich nicht initialisieren → normaler SDR-Encode.
   - Quelle ist bereits HDR/DV/HLG → vorhandener HDR-Pfad bleibt zuständig.
   - Farbtags sind unklar → normaler SDR-Encode.
   - Zielcodec ist H.264 → normaler SDR-Encode.
   - Die experimentelle Funktion darf damit keinen ansonsten gültigen Encode allein wegen fehlender HDR-Erweiterung unbrauchbar machen.

7. **Output-Verifikation wurde erweitert**
   - Wird Enhancement tatsächlich angewendet, verlangt der finale Medienvertrag:
     - nachweisbares HDR,
     - mindestens 10-Bit-Video,
     - den normalen erwarteten Zielcodec.
   - Dolby Vision und HDR10+ werden nicht künstlich behauptet oder erzeugt.

8. **Keine erfundenen Mastering-Metadaten**
   - Dragon Tools setzt BT.2020/PQ-/HDR10-Farbsignalisierung, erfindet aber keine ST-2086-Mastering-Display- oder MaxCLL/MaxFALL-Werte für eine SDR-Quelle.
   - Die Funktion ist Range Expansion und wird ausdrücklich **nicht** als Wiederherstellung eines verlorenen HDR-Masters dargestellt.

9. **Patch-K-VMAF bleibt fachlich sauber**
   - Wenn SDR→HDR tatsächlich angewendet werden kann, wird die automatische VMAF-CQ/CRF-Suche übersprungen.
   - Ein direktes VMAF zwischen unveränderter SDR-Referenz und bewusst in einen anderen Helligkeits-/Farbraum transformierter HDR-Ausgabe wäre keine saubere Qualitätsziel-Metrik.
   - Der normale feste CQ/CRF/QP-Wert bleibt in diesem Fall aktiv.

#### Stabilitäts- und Sicherheitsverbesserungen

- Feature vollständig opt-in.
- Strenge SDR-BT.709-Whitelist statt heuristischem „wahrscheinlich SDR“.
- Keine Verarbeitung bereits vorhandener HDR-/DV-/HLG-Quellen durch den neuen Pfad.
- Keine H.264-HDR-Ausgabe.
- Funktionsfähigkeitsprobe von libplacebo **inklusive echter Initialisierung** statt bloßer Feature-Liste.
- Keine erfundenen dynamischen oder statischen Mastering-Metadaten.
- Output-Vertrag verhindert, dass ein angeblicher Enhancement-Job still als 8-Bit/SDR akzeptiert wird.
- Neue Module erfüllen die bestehenden Architektur-/Release-Verträge; keine Grenzwerte wurden aufgeweicht.

#### Tests

Neue Patch-M-Regressionstests prüfen insbesondere:

- nur explizites BT.709-SDR ist zulässig,
- fehlende/abweichende Primaries/Transfer-Tags blockieren Enhancement,
- bestehendes HDR wird nicht angefasst,
- H.264 wird abgelehnt,
- fehlendes libplacebo führt zum Fallback,
- Filterkette enthält P010, BT.2020, PQ, perceptual gamut mapping und Inverse Tone Mapping,
- `contrast_recovery` wird auf den erlaubten Bereich begrenzt,
- EncodePlan markiert Enhancement nur bei real erfüllten Voraussetzungen,
- StandardPipeline setzt HDR10-Ausgabeparameter und x265-HDR10-VUI,
- finaler Medienvertrag verlangt HDR/10 Bit,
- Patch K startet keine SDR-vs-HDR-VMAF-Suche,
- die Runtimeprobe akzeptiert libplacebo nur bei erfolgreicher echter Initialisierung.

**Patch-M-Regressionstests:** 9/9 bestanden.  
**Fokussierter Integrations-/Architekturblock:** 70/70 bestanden.  
**Gesamter Regressionstest in vier Blöcken:** 1530 Tests bestanden, 17 übersprungen, 4 bekannte Baseline-/Teilarchivfehler.  
Die vier bekannten Fehler sind unverändert: ein Headless-Test importiert ein PyQt6-abhängiges Queue-Modul; ein CI-Vertrag erwartet die im Teilarchiv fehlende `.github`-Struktur; zwei Versions-/Build-Verträge erwarten `release_manifest.json` bzw. `build_v9.bat`. Es wurde keine neue Regression durch Patch M festgestellt.

Die Review-Umgebung enthält einen FFmpeg-Build, der `libplacebo` zwar listet, dessen Vulkan-Initialisierung jedoch mit `VK_ERROR_INCOMPATIBLE_DRIVER` fehlschlägt. Dieser reale Smoke-Test war der Anlass für die zusätzliche echte Runtimeprobe und bestätigt das gewünschte Fallback-Verhalten. Vor dem finalen 9.8.5-Release sollte die Windows-EXE auf dem Zielsystem mit der RTX-GPU einmal mit realem BT.709-Material visuell geprüft werden.

#### Relevanz für Help / Dokumentation / Änderungshistorie

Für 9.8.5 sollte festgehalten werden:

- Neuer experimenteller, standardmäßig deaktivierter Modus `SDR → HDR Enhancement`.
- Nur eindeutig erkanntes SDR BT.709 wird verarbeitet.
- Range Expansion erfolgt mit FFmpeg/libplacebo Inverse Tone Mapping.
- Ausgabe: 10 Bit, BT.2020, PQ, Limited Range; nur H.265/AV1.
- Keine Rekonstruktion echten HDR-Masterings und keine erfundenen Mastering-Metadaten.
- Bei fehlendem/defektem libplacebo/Vulkan oder unklaren Farbtags bleibt automatisch der normale SDR-Encode aktiv.
- Automatische VMAF-Qualitätsziel-Suche ist während SDR→HDR deaktiviert.
- Vor produktiver Massennutzung wird ein visueller Vorher-/Nachher-Test empfohlen.

#### Migration / neue Abhängigkeiten

- Keine Datenbankmigration.
- Neue QSettings-Werte unter `sdr_hdr/*`:
  - `sdr_hdr/enabled`
  - `sdr_hdr/contrast_recovery`
- Bestehende Installationen bleiben durch `sdr_hdr/enabled=false` unverändert.
- Keine neue Python-Abhängigkeit.
- Erforderlich für die Funktion ist ein FFmpeg-Build mit **funktionsfähigem libplacebo/Vulkan**; Dragon Tools prüft dies automatisch zur Laufzeit.

## Geplante Folgepatches – abgeschlossen

Die mit diesem Review definierte Funktions-Roadmap A–M ist mit Patch M vollständig umgesetzt. Weitere neue Funktionen sollten erst nach dem gemeinsamen 9.8.5-Release-Abschluss und realen Windows-/Medien-Smoke-Tests geplant werden.

---

## Bewusst nicht Teil der aktuellen 9.8.5-Roadmap

- Hash-/Video-Fingerprint-Duplikaterkennung.
- Eigener Kapitelmanager.
- HDR → SDR als reguläre Dragon-Tools-Funktion.
- Dienstspezifische Discord-/Telegram-/Slack-Benachrichtigungen.

---

## Pflegekonvention für weitere Patches

Jeder weitere Patch ergänzt dieses Dokument um:

1. Patch-Name und Status.
2. Geänderte bzw. neu angelegte Module.
3. Konkrete funktionale Änderung.
4. Stabilitäts-/Sicherheitsauswirkung.
5. Neue oder geänderte Tests und deren Ergebnis.
6. Hinweise für Help, Benutzerhandbuch und Änderungshistorie.
7. Eventuelle Migrationen, Einstellungsänderungen oder neue Abhängigkeiten.

Die Anwendungsversion bleibt während der einzelnen Entwicklungspatches auf der jeweiligen Entwicklungsbasis; der endgültige Versionssprung auf **9.8.5** erfolgt erst beim gemeinsamen Release-Abschluss.

---

## Dokumentations- und About-Abschluss für 9.8.5

Nach Abschluss der Patches A-M wurden Help, technisches Handbuch, V9-Änderungshistorie und der Über-Dialog auf den finalen 9.8.5-Stand synchronisiert.

### Geänderte Module / Dokumente

- `dragontools/core/version.py`
  - Anwendungsversion auf `9.8.5` angehoben.
- `dragontools/core/project_info.py`
  - verifizierte Release-Fallbackwerte aktualisiert.
  - Über-Dialog auf den Funktionsstand A-M erweitert.
  - Projektzahlen werden im Entwicklungs-/Onedir-Betrieb weiterhin live aus den vorhandenen Python-Quellen ermittelt; Frozen-Builds verwenden die Release-Fallbackwerte.
- `help.html`
  - V9.8.5, Patchstand A-M, neue Funktionen, Abhängigkeiten, Test- und Projektumfang aktualisiert.
- `DragonToolsV9_Dokumentation.docx` / `Handbuch/Handbuch.pdf`
  - Titel, Projektstatistik und neues Abschlusskapitel 36 für Patchstand A-M ergänzt.
- `Aenderungshistorie/CHANGELOG.json` und `CHANGELOG.txt`
  - V9.8.5 als aktueller Patchstand A-M ergänzt.

### Verifizierter Projektumfang 9.8.5

- **917 Python-Dateien / Programme** einschließlich `DragonToolsV9.py`.
- **137.842 Gesamtzeilen**.
- **116.563 Codezeilen** (nichtleer, keine reinen Kommentarzeilen).
- **711 Produktivdateien** einschließlich Einstiegspunkt.
- **206 Testpaket-Dateien**, davon **203 `test_*.py`**.
- **1.527 statisch erkannte Testfunktionen**.
- Patch-A-M-Review: **1.544 Tests bestanden**, **18 übersprungen**, **0 fehlgeschlagen**.

### Dokumentations-/Release-Hinweise

- Die Projektzahlen im Über-Dialog sind nicht mehr nur statischer Text: im Quell-/Onedir-Betrieb werden sie live berechnet.
- Für die EXE bleiben die oben genannten verifizierten Releasewerte hinterlegt, falls keine Python-Quellen mitgeliefert werden.
- Die Benutzer- und Entwicklerdokumentation benennt die optionalen Komponenten `faster-whisper/CTranslate2`, Tesseract, `libvmaf` und `libplacebo` sowie deren Fail-safe-/Fallback-Verhalten.
- Das finale Handbuch wurde als DOCX und daraus erzeugtes PDF auf **376 Seiten** geprüft; Textblöcke liegen innerhalb der Seitenränder, und die aktualisierten Abschlussseiten sind ohne Überlagerung oder Abschneiden gerendert.



---

## Release-Hardening nach Patch M – technisches Review 17.09.2026

**Status:** umgesetzt und fokussiert getestet.

### Korrigierte Release-/Versionsfehler

- `release_manifest.json` ist vollständig auf **9.8.5** migriert; Manifest und zentrale `APP_VERSION` stimmen wieder überein.
- Aktive Build-/Projekttexte in `README.md`, `Info.txt` und `.github/copilot-instructions.md` wurden auf 9.8.5 synchronisiert. Historische, datierte 9.8.3-/9.8.4-Artefakte bleiben bewusst historisch.
- Der fertige PyInstaller-Build liefert keinen separaten `Daten\Python`-Quellbaum mehr aus. Build- und App-Validator prüfen diesen Source-free-Vertrag ausdrücklich.

### Whisper / CTranslate2 im offiziellen Build

- `requirements-optional.txt` enthält `faster-whisper` und `ctranslate2` als Build-/Feature-Abhängigkeiten.
- `build_v9.bat` prüft vor PyInstaller, ob `faster_whisper` und `ctranslate2` importierbar sind.
- Fehlen die Pakete, führt der Builder `python -m pip install -r requirements-optional.txt` in der aktiven Build-Umgebung aus und prüft die Imports erneut; bei Fehler wird der Build abgebrochen.
- PyInstaller sammelt `faster_whisper` und `ctranslate2` inklusive Paketdaten/Metadaten explizit ein.
- Auf dem Benutzer-PC wird **kein pip-Install** ausgeführt. Nur das ausgewählte Whisper-Modell wird beim ersten tatsächlichen Einsatz heruntergeladen und anschließend lokal gecacht.
- CUDA/FP16 bleibt bevorzugt, wenn CTranslate2 eine nutzbare NVIDIA-CUDA-Runtime erkennt; andernfalls bleibt der CPU-/INT8-Fallback erhalten.

### Migrations- und Netzwerk-Hardening

- Regel-/Profilmigrationen lehnen Konfigurationsdateien mit einer **neueren unbekannten Schema-Version** jetzt fail-closed ab. Solche Dateien werden weder auf eine ältere Schema-Version umgelabelt noch automatisch überschrieben.
- `Retry-After` von TMDB/TheTVDB/Jellyfin ist hart begrenzt, damit ein Serverwert keinen Worker minuten- oder stundenlang blockieren kann.
- Manuelle Online-Metadatensuche und Provider-Verbindungstests laufen außerhalb des GUI-Threads; beim Beenden wird auf einen laufenden Metadata-Thread kontrolliert gewartet und ein unsicherer Shutdown verhindert.

### Watch-Folder-Hardening

- Watch-Dateien werden nicht mehr bereits bei Queue-Aufnahme als verarbeitet persistiert.
- Eine Signatur wird erst nach einem terminalen erfolgreichen Ergebnis (`✅`) bestätigt; Fehler/Skip bleiben erneut versuchbar.
- Änderungen der Quelldatei während eines laufenden Jobs können nicht durch das Ergebnis der alten Signatur fälschlich bestätigt werden.
- Der Watch-Thread besitzt einen kontrollierten Shutdown-Vertrag; ein noch laufender Scan führt nicht mehr zu einem blinden QThread-Abbau.

### Release-Smoke / Tests

- Der Release-Smoke umfasst jetzt alle in Patch A–M dokumentierten Produktivmodule sowie den neuen asynchronen Metadata-Action-Worker.
- Neue Regressionstests decken Manifest 9.8.5, Whisper-Buildvertrag, Source-free-Distribution, Forward-Schema-Schutz und Retry-Caps ab.
- Verifizierter Quellumfang nach dem Hardening: **917 Python-Dateien**, **137.842 Gesamtzeilen**, **116.563 Codezeilen**, **206 Testpaket-Dateien**, davon **203 `test_*.py`**, **1.527 statisch erkannte Tests**.
- Fokussierte Release-/Architekturprüfung nach Source-free-Umstellung: **29/29 bestanden**. Weitere fokussierte Hardening-/Retry-/Migration-/Watch-Tests wurden separat erfolgreich ausgeführt.
- Reale Windows-Smoke-Tests mit CUDA/CTranslate2, Whisper-Modell-Download, Tesseract/PGS/VobSub, libvmaf, libplacebo/Vulkan und den gebündelten externen Tools bleiben Bestandteil der finalen EXE-Abnahme.

## Finale Release-Abnahme 9.8.5 - 17.09.2026

- `build_v9.bat`: Source-free-Abschlusscheck korrigiert. Der Build verlangt keine entfernten `Daten\Python`-Quellen mehr und bricht stattdessen ab, falls dieser Quellordner unerwartet im Release auftaucht.
- `gui/main_window_shutdown.py`: Shutdown-Gate aus `MainWindow` ausgelagert; Online-Metadaten- und Watch-Folder-Threads werden kooperativ beendet, ohne die Architekturgrenze der Composition-Root zu verletzen.
- `worker/converter_process_executor.py`: Race Condition nach langer Pause beseitigt. Ein bereits beendeter Capture-Prozess gewinnt jetzt vor der Timeout-Prüfung und wird nicht mehr fälschlich als Exit-Code 124 markiert.
- `core/release_validation_environment.py`: Validierungsreihenfolge kompatibel zu bestehenden Build-Verträgen gehalten; Whisper/CTranslate2 bleiben verpflichtender Bestandteil des offiziellen Build-Vertrags.
- Regressionstests für Source-free-Build, Schema-Schutz, Retry-Caps und Whisper-Buildvertrag ergänzt/aktualisiert.
- Finaler verifizierter Quellumfang: **917 Python-Dateien**, **137.842 Gesamtzeilen**, **116.563 Codezeilen**, **206 Testpaket-Dateien**, davon **203 `test_*.py`**, **1.527 statisch erkannte Tests**.
- Host-kompatibler Abnahmelauf: **1.544 Tests bestanden**, **18 übersprungen**, **0 fehlgeschlagen**. Reale DV/HDR-/Windows-/CUDA-Smokes bleiben wie vorgesehen Release-Abnahmen auf dem Zielsystem.

---

## Patch N – Original-Timeline-Fallback für VFR-Timestamp-Reparaturen – 19.09.2026

**Status:** umgesetzt und fokussiert getestet  
**Bereich:** Output-Validierung / MKV / VFR / Timestamp-Reparatur  
**Ziel:** Bei einer durch fehlerhafte Video-PTS extrem aufgeblähten MKV-Laufzeit soll Dragon Tools bei echter VFR nicht mehr ausschließlich abbrechen, solange die unveränderte Originaldatei noch als sichere Zeitbasis vorhanden ist.

### Geänderte bzw. neue Module

- `dragontools/worker/duration_original_timeline_service.py` *(neu)*
- `dragontools/worker/duration_timestamp_service.py`
- `dragontools/worker/duration_repair_orchestrator.py`
- `dragontools/worker/duration_repair_service.py`
- `dragontools/worker/workflow_duration_repair.py`
- `dragontools/tests/test_duration_repair_service.py`

### Funktionale Änderungen

1. **Originaldatei wird als zusätzliche sichere VFR-Zeitbasis verwendet**
   - Der Workflow reicht `ctx.input_path` bis zur Timestamp-Reparatur durch.
   - Erkennt Dragon Tools eine echte VFR-Datei, bei der die bisherige CFR-Rekonstruktion bewusst verweigert wird, kann jetzt ein zusätzlicher Original-Timeline-Fallback starten.
   - Die per-Frame-PTS der Originaldatei werden mit `ffprobe -show_frames` ausgelesen und als MKVToolNix-Timestamp-Datei im Format v2 erzeugt.
   - MKVToolNix übernimmt anschließend diese Originalzeitpunkte verlustfrei auf den bereits erzeugten Videostream. Es findet **kein Re-Encode** statt.

2. **Keine blinde Interpolation und keine erfundene CFR-Timeline**
   - Der Fallback wird nur angewendet, wenn Original und Reparaturausgabe exakt dieselbe Videoframe-Anzahl besitzen.
   - Fehlt die Frameanzahl, unterscheidet sie sich oder sind die Original-PTS nicht vollständig/streng monoton, wird der Fallback verworfen.
   - Die vorhandene Schutzregel `VFR -> keine blinde CFR-Reparatur` bleibt vollständig bestehen.

3. **Sichere Validierung vor dem Commit**
   - Der reparierte Kandidat wird erneut durch den normalen Output-Verifier geprüft.
   - Stream-Anzahlen werden wie bei den bisherigen Timestamp-Kandidaten zusätzlich über den bestehenden `RepairStreamGuard` gegengeprüft.
   - Die reparierte Videodauer muss zur extrahierten Original-Timeline passen.
   - Bereits die Originaldatei wird auf plausiblen Audio-/Video-Start und passende Audio-/Videodauer geprüft, bevor ihre Timeline als Referenz akzeptiert wird.
   - Bei vorhandenem Audio werden außerdem Audio-/Videodauer und Startzeit des reparierten Kandidaten erneut auf plausible Synchronität geprüft.
   - Erst nach vollständiger Validierung ersetzt der Kandidat die defekte Ausgabe.

4. **Fail-closed bei unsicheren Fällen**
   - Mehrere Videotracks, fehlendes `ffprobe`/MKVToolNix, fehlende Originaldatei, nicht passende Frameanzahl oder unplausible Original-Timeline führen weiterhin zum sicheren Abbruch.
   - Ein verworfener erzeugter Reparaturkandidat wird wie bisher unter `Archiv/Timestamp_Reparatur` abgelegt.
   - Temporäre Timestamp-Dateien werden immer entfernt.

5. **Rückwärtskompatibilität**
   - Ältere interne/Test-Kontexte ohne `input_path` bleiben lauffähig; in diesem Fall wird der neue Original-Timeline-Fallback schlicht nicht angeboten.
   - CFR-Reparaturen über `setts`, `+genpts/+igndts` sowie der normale Container-Remux bleiben unverändert.

### Typischer Ablauf nach Patch N

```text
Ausgabedauer unplausibel
  -> normaler MKVToolNix-Remux
  -> weiterhin unplausibel
  -> Timestamp-Prüfung
  -> echte VFR erkannt
  -> Originaldatei noch vorhanden
  -> Original-PTS pro Videoframe auslesen
  -> exakte Frameanzahl Original == Output prüfen
  -> MKVToolNix --timestamps <Videotrack>:<timecodes-v2>
  -> Output-/Stream-/Synchronitätsprüfung
  -> bei Erfolg Kandidat übernehmen
  -> sonst unverändert fail-closed archivieren
```

### Regressionstests / Abnahme

Neu bzw. erweitert geprüft wurden:

- erfolgreiche Übernahme einer echten VFR-Original-Timeline bei identischer Frameanzahl,
- korrekter Aufbau der MKVToolNix-Timestamp-v2-Datei,
- vollständige Entfernung temporärer Timestamp-Dateien,
- sicherer Abbruch ohne `--timestamps`, wenn Original und Output unterschiedliche Frameanzahlen besitzen,
- Übergabe des echten Originalpfads aus dem Workflow an den Reparaturservice,
- bestehende CFR-, Remux-, Stream-Guard- und Workflow-Verträge.

**Fokussierte Duration-/Workflow-/Architekturtests:** 45/45 bestanden.  
**Zusätzliche angrenzende Verifikation:** 40 bestanden, 1 übersprungen.  
**Statische Prüfung:** 919 Python-Dateien ohne Syntax-/Compile-Fehler.

Ein kompletter `pytest dragontools/tests`-Lauf wurde in der bereitgestellten Container-Umgebung begonnen. Der erste breite Fehler tritt unabhängig von Patch N im vorhandenen CI-/Build-Vertragstest auf, weil das hochgeladene Paket die vom Test erwarteten Repository-/Build-Dateien am `PROJECT_ROOT` nicht vollständig bereitstellt. Bis zu diesem bekannten Paket-/Umgebungsfehler liefen **871 Tests erfolgreich, 10 wurden übersprungen**.

### Relevanz für Help / Dokumentation / Änderungshistorie

Für die spätere 9.8.5-Dokumentation sollte ergänzt werden:

- VFR-Timestamp-Reparaturen können jetzt die noch vorhandene Originaldatei als verlustfreie per-Frame-Zeitbasis verwenden.
- Der Fallback ist ausdrücklich **kein CFR-Zwang**; unterschiedliche Frameanzahlen oder unsichere Original-PTS werden nicht repariert.
- Die Reparatur bleibt fail-closed und wird erst nach erneuter Output-, Stream- und Synchronitätsvalidierung übernommen.


---

## Patch O – Jellyfin gezielte Erkennung / Metadatenanalyse und Pfad-Hardening – 19.09.2026

**Status:** umgesetzt und fokussiert getestet  
**Bereich:** Jellyfin API / Mediathek-Mappings / Move & Renamer / Metadatenanalyse  
**Ziel:** Neu nach Jellyfin verschobene oder umbenannte Dateien sollen ohne globalen Bibliotheksscan zuverlässig über Jellyfins normalen Datei-/Ordner-Refresh erkannt und anschließend durch die übliche Medien-/Metadatenanalyse verarbeitet werden. Falsche Windows-/UNC-Pfade dürfen nicht mehr als scheinbar erfolgreiche `204`-Pfadmeldung durchgehen.

### Geänderte Module

- `dragontools/core/jellyfin_api.py`
- `dragontools/core/jellyfin_refresh_service.py`
- `dragontools/gui/jellyfin_refresh_dispatch.py`
- `dragontools/gui/jellyfin_connection_test.py`
- `dragontools/gui/settings_sections/jellyfin.py`
- `dragontools/tests/test_patch_f_jellyfin_api.py`

### Funktionale Änderungen

1. **Jellyfin-Serverpfade werden vor der gezielten Meldung verifiziert**
   - Der API-Client liest jetzt `GET /Library/PhysicalPaths` aus.
   - Dragon Tools vergleicht jeden erzeugten Zielpfad mit den tatsächlich von Jellyfin gemeldeten Mediathekswurzeln.
   - Ein lokaler Windows-/UNC-Pfad, der versehentlich nicht auf Jellyfins Container-/Serverpfad gemappt wurde, wird nicht mehr an `/Library/Media/Updated` gesendet.
   - Bei aktiviertem Full-Scan-Fallback wird in diesem Fall kontrolliert auf `/Library/Refresh` ausgewichen; ohne Fallback erscheint ein konkreter Fehler inklusive ungültigem Pfad und den von Jellyfin bekannten Roots.

2. **Mediathek-Datenbank ist für Jellyfin-Pfade jetzt Teil der Refresh-Quelle**
   - Die Refresh-Dispatch-Logik verwendet nicht mehr ausschließlich `media_library/path_mappings_json` aus `QSettings`.
   - Vorhandene `path_mappings` aus der Dragon-Tools-Mediathek-Datenbank werden zusätzlich geladen.
   - Bei übereinstimmendem Mapping ist der in der Mediathek gespeicherte externe Jellyfin-Pfad maßgeblich; der aktuelle lokale Move-Zielpfad aus den Einstellungen bleibt für die lokale Seite des Mappings maßgeblich.
   - Damit werden bereits importierte Jellyfin-Roots wie `/TVSerien`, `/Anime` und `/Filme` direkt wiederverwendet.

3. **Neue Dateien melden zusätzlich ihren Zielordner**
   - Neben der eigentlichen neuen/geänderten/gelöschten Datei wird bei der gezielten Aktualisierung der enthaltene Ordner einmalig als `Modified` gemeldet.
   - Beispiel: Für `/TVSerien/Supernatural (2005)/Staffel 07/Folge.mkv` wird zusätzlich `/TVSerien/Supernatural (2005)/Staffel 07` gemeldet.
   - Jellyfin kann dadurch den bereits bekannten Parent (z. B. Staffel-/Filmordner) aktualisieren und die neue Datei über seinen normalen Discovery-/Analysepfad aufnehmen.
   - Mehrere Dateien im selben Ordner erzeugen nur einen Parent-Hinweis.

4. **Keine künstliche zweite Metadatenaktualisierung per Item-ID nötig**
   - Neue Dateien besitzen vor der Erkennung noch keine Jellyfin-Item-ID.
   - Dragon Tools stößt deshalb zuerst korrekt die Datei-/Ordnererkennung an. Die anschließende Medien-/Metadatenanalyse bleibt Teil von Jellyfins normalem Refresh-Verhalten und überschreibt nicht unnötig vorhandene Metadaten mit `ReplaceAllMetadata`.

5. **Verbindungstest prüft jetzt auch den Pfad-Namespace**
   - `Verbindung testen` prüft neben `/System/Info` auch `/Library/PhysicalPaths`.
   - Bei Erfolg werden die von Jellyfin gesehenen Mediathekspfade im Status angezeigt. Dadurch ist sofort sichtbar, ob Dragon Tools mit `/TVSerien`, `/Anime`, `/Filme` usw. arbeiten muss.

6. **Einstellungen verständlicher beschriftet**
   - Der Modus heißt jetzt `Gezielte Erkennung + Metadatenanalyse (empfohlen)`.
   - Der Hilfetext erklärt die Serverpfad-Prüfung und dass lokale Windows-/UNC-Pfade nicht mehr stillschweigend akzeptiert werden.

### Zusätzlich im bereitgestellten Jellyfin-12-Log erkannt

Die Jellyfin-Roots selbst sind korrekt und werden vom Server real verwendet (`/TVSerien`, `/Anime`, `/Filme`). Das Log zeigt außerdem unabhängig von Dragon Tools wiederholt:

```text
System.IO.IOException: The configured user limit (8192) on the number of inotify watches has been reached
```

Dadurch fällt Jellyfins Linux-Dateisystemüberwachung zeitweise aus bzw. wird neu gestartet. Patch O verlässt sich für Dragon-Tools-Moves deshalb nicht auf ein zufällig ankommendes Dateisystemevent, sondern meldet die Änderung explizit über die Jellyfin-API. Das Linux-/NAS-`inotify`-Limit selbst ist eine Jellyfin-/Host-Konfiguration und wird von Dragon Tools bewusst nicht verändert.

### Regressionstests / Abnahme

Neu bzw. erweitert geprüft wurden:

- Abruf und Deduplizierung von `/Library/PhysicalPaths`,
- Zusammenführung von QSettings- und Mediathek-DB-Mappings,
- Vorrang des DB-Jellyfin-Roots bei aktuellem lokalem Zielpfad,
- Parent-Ordner-Hinweis für neue Episoden/Dateien,
- Ablehnung eines ungemappten Windows-Pfads gegen `/TVSerien`, `/Anime`, `/Filme`,
- Full-Scan-Fallback **vor** einer fehlerhaften gezielten Pfadmeldung,
- bestehende API-Retry-, Move-/Rename- und Vollscan-Verträge.

**Fokussierter Jellyfin-Test:** 19/19 bestanden.  
**Jellyfin + Release-/Architekturtests:** 35/35 bestanden.  
**Zusätzliche Mediathek-/Mapping-Regressions:** 81/81 bestanden.  
**Gesamt der für Patch O sinnvoll ausführbaren fokussierten Tests:** 116/116 bestanden.  
Die zusätzlich aufgerufenen GUI-Safety-Tests sind in der bereitgestellten Container-Umgebung wegen fehlendem `PyQt6`/`qapp` nicht vollständig ausführbar; die bis dahin gelaufenen Tests waren erfolgreich bzw. die Fehler entstanden bereits beim fehlenden GUI-Import/Fixture.  
**Syntaxprüfung:** alle 919 Python-Dateien erfolgreich mit `compileall` geprüft.

### Relevanz für Help / Dokumentation / Änderungshistorie

Für 9.8.5 ergänzen:

- gezielte Jellyfin-Aktualisierung validiert ihre Pfade gegen den Server,
- Mediathek-DB-Mappings werden für `/TVSerien`, `/Anime`, `/Filme` direkt genutzt,
- bei neuen Dateien wird der Parent-Ordner zusätzlich gemeldet, damit Jellyfin die Datei erkennt und normal analysiert,
- Verbindungstest zeigt die vom Server gemeldeten Mediathekspfade,
- ein zu niedriges Linux-`inotify`-Limit bleibt eine separate Jellyfin-/NAS-Konfiguration und ist kein Dragon-Tools-Pfadfehler.


---

## Patch P – Werkzeugpfade live prüfen · lokales Whisper-Modell · NFO/Track-Sprachsync – 19.09.2026

**Status:** umgesetzt und fokussiert getestet  
**Bereich:** Einstellungen / Werkzeugdiagnose / Mediathek-Fix-Queue / faster-whisper / NFO-Konsistenz  
**Ziel:** Neu eingetragene Werkzeugpfade müssen direkt im noch geöffneten Einstellungsfenster prüfbar sein. Die Audio-Spracherkennung soll optional ein vollständig lokales Whisper-Modell verwenden können. Eine erkannte Sprache darf außerdem nicht nur in der Dragon-Tools-Datenbank landen, sondern muss den tatsächlichen MKV-Sprachtag und – falls vorhanden – den zugehörigen NFO-Streamdetail-Sprachtag konsistent korrigieren.

### Geänderte Module

- `dragontools/core/settings_storage.py`
- `dragontools/core/tool_diagnostics.py`
- `dragontools/core/language_detection.py`
- `dragontools/core/whisper_runtime.py`
- `dragontools/core/nfo_stream_metadata.py`
- `dragontools/core/media_library_fix_queue.py`
- `dragontools/core/release_validation_package.py`
- `dragontools/gui/settings_sections/runtime.py`
- `dragontools/gui/tool_path_live_check.py`
- `dragontools/gui/main_window_system_actions.py`
- `dragontools/worker/media_stream_language_service.py`
- `dragontools/worker/media_stream_metadata_guard.py`
- `dragontools/tests/test_patch_p_live_tools_whisper_nfo_sync.py`

### Funktionale Änderungen

1. **Werkzeugpfade können vor dem Speichern sofort geprüft werden**
   - Im Bereich `Einstellungen -> Werkzeugpfade` gibt es jetzt `✅ Eingaben prüfen`.
   - Die Prüfung verwendet direkt den aktuellen Inhalt der sichtbaren Eingabefelder.
   - Das Einstellungsfenster muss dafür weder mit `OK` geschlossen noch zwischengespeichert werden.
   - Die Live-Prüfung schreibt die noch nicht gespeicherten Werte bewusst **nicht** in `QSettings` und verändert den globalen Tool-Path-Singleton nicht.
   - Wenn ein aktuelles Eingabefeld leer ist oder das Tool dort nicht gefunden wird, bleibt die normale automatische Suche als Fallback erhalten.

2. **Werkzeugprüfung wurde vervollständigt**
   - Der normale F9-Test zeigt jetzt zusätzlich `mkvpropedit` und `Tesseract`.
   - `faster-whisper`/`CTranslate2` wird als eigener Runtime-Eintrag geprüft.
   - Die Diagnose zeigt Paketversionen, Audio-Spracherkennungsfähigkeit und den verwendeten lokalen Modellordner bzw. `intern / Modellcache`.
   - Fehler eines konfigurierten lokalen Whisper-Modells werden auch dann sichtbar angezeigt, wenn die Python-Pakete selbst vorhanden sind.

3. **Lokaler faster-whisper/CTranslate2-Modellordner**
   - In den Werkzeugpfaden kann optional ein lokaler Whisper-Modellordner gewählt werden.
   - Erwartet wird ein bereits für CTranslate2/faster-whisper nutzbarer Modellordner mit mindestens `model.bin` und `config.json`.
   - Ist ein lokaler Modellordner konfiguriert, ist er maßgeblich und überschreibt den Modellnamen/Downloadcache.
   - Ein ungültiger konfigurierter Ordner fällt **nicht** still auf einen Online-Download zurück, sondern wird sicher als Fehler gemeldet.
   - Ohne lokalen Ordner bleibt das bisherige Verhalten erhalten: `tiny/base/small/medium/large-v3` wird über faster-whisper bzw. dessen lokalen Cache geladen.

4. **Whisper ist weiterhin kein externes `whisper.exe`**
   - faster-whisper ist in Dragon Tools eine Python-/CTranslate2-Laufzeitkomponente und kein klassisches Einzel-Executable wie FFmpeg.
   - Deshalb wird kein künstlicher `whisper.exe`-Pfad eingeführt.
   - Für Offline-/lokale Nutzung ist stattdessen der tatsächliche Modellordner konfigurierbar; die Paketverfügbarkeit selbst wird über die Werkzeugprüfung kontrolliert.

5. **Erkannte Sprache wird weiterhin direkt in der MKV-Datei repariert**
   - Die Fix Queue schreibt bei sicher erkannter Sprache über `mkvpropedit` den Matroska-Tracktag.
   - Es werden sowohl der klassische Matroska-Sprachtag (`language=deu`, `eng`, …) als auch der IETF-Tag (`language-ietf=de`, `en`, …) gesetzt.
   - Die Mediendatei wird weiterhin nicht neu encodiert; die Änderung betrifft nur Header-/Trackmetadaten.

6. **Bestehende NFO wird jetzt synchron mitrepariert**
   - Besitzt das Medium eine NFO mit `<fileinfo><streamdetails>`, wird beim Sprach-Fix der **entsprechende Audio- oder Untertitel-Track derselben Typ-Ordinalzahl** aktualisiert.
   - Beispiel: Audio-Track 2 in der MKV -> zweites `<audio>`-Element der NFO.
   - Der NFO-Sprachwert verwendet den Jellyfin/Kodi-kompatiblen ISO-639-2-Tag, z. B. `deu`.
   - Fehlt in einer vorhandenen NFO der komplette `streamdetails`-Block, gibt es dort keinen alten Sprachtag zu synchronisieren; die MKV-Korrektur bleibt möglich.
   - Ist eine vorhandene NFO dagegen beschädigt oder die Track-Zuordnung nicht eindeutig, wird der gesamte Sprach-Fix **fail-closed** abgelehnt, damit MKV und NFO nicht auseinanderlaufen.

7. **MKV + NFO werden vor dem Commit gemeinsam vorbereitet**
   - Die MKV wird wie bisher auf einer isolierten Kopie mit `mkvpropedit` bearbeitet.
   - Eine vorhandene NFO wird ebenfalls zunächst separat und sicher geparst/gestaged.
   - Erst wenn beide Kandidaten gültig sind und sich weder Quelldatei noch NFO zwischenzeitlich geändert haben, erfolgt der Commit.
   - Schlägt der Video-Commit nach einem bereits erfolgten NFO-Replace fehl, wird die ursprüngliche NFO aus dem temporären Backup wiederhergestellt.

8. **Fix-Queue kennt den bereits ermittelten NFO-Pfad**
   - Stream-Fix-Einträge übernehmen `media_items.nfo_path` aus der Mediathek-Datenbank.
   - Falls dort kein Pfad gespeichert ist, wird weiterhin sicher auf `<Videoname>.nfo` bzw. `movie.nfo` zurückgefallen.

### Verhalten nach Patch P

```text
Sprache/Tracktitel prüfen
  -> Audio unbekannt
  -> mehrere kurze Whisper-Samples
  -> Sprache mit ausreichender Konfidenz erkannt
  -> MKV-Kopie: language + language-ietf per mkvpropedit setzen
  -> vorhandene NFO: passenden <audio>/<subtitle>-Sprachtag setzen
  -> beide Quellen unverändert seit Queue-Erstellung?
       Ja  -> Commit
       Nein -> verwerfen
  -> Mediathekdatei neu analysieren
  -> DB übernimmt den tatsächlich geschriebenen Tracktag
```

### Regressionstests / Abnahme

Neu geprüft wurden unter anderem:

- zielgenaue Aktualisierung des zweiten Audio-Sprachtags in einer NFO,
- gemeinsamer MKV-/NFO-Sprach-Fix,
- beschädigte NFO blockiert den Video-Commit fail-closed,
- `nfo_path` wird in Stream-Fix-Einträge übernommen,
- lokaler CTranslate2-Modellordner überschreibt den Modellnamen,
- unvollständiger lokaler Modellordner wird abgelehnt,
- Whisper-Werkzeugdiagnose meldet einen defekten lokalen Modellordner,
- Werkzeugpfad-UI enthält Live-Prüfung und lokalen Whisper-Modellpfad.

**Fokussierte Patch-P-/Whisper-/Tool-/Settings-Tests:** 41/41 bestanden.  
**Zusätzliche Mediathek-/Fix-/Release-nahe Tests:** 109 bestanden; die übrigen Fehler der breiteren Auswahl entstanden ausschließlich durch die bereits bekannte Container-Umgebung ohne `PyQt6/qapp` bzw. durch im bereitgestellten Paket fehlende Repository-Root-Dateien (`release_manifest.json`, `build_v9.bat`, Requirements-Dateien).  
**Syntaxprüfung:** `core`, `gui`, `worker` und `tests` vollständig mit `compileall` erfolgreich geprüft.

### Relevanz für Help / Dokumentation / Änderungshistorie

Für 9.8.5 ergänzen:

- Werkzeugpfade können direkt im geöffneten Einstellungsfenster geprüft werden,
- F9 prüft auch `mkvpropedit`, Tesseract und faster-whisper/CTranslate2,
- optionaler lokaler Whisper-CTranslate2-Modellordner für Offline-Betrieb,
- erkannte Audio-/Untertitelsprache wird nicht nur in der Datenbank, sondern in der MKV und vorhandenen NFO-Streamdetails konsistent korrigiert,
- beschädigte/uneindeutige NFOs verhindern einen inkonsistenten Teil-Commit.


---

## Patch Q – Companion-first Move für Jellyfin · kompakter Über-Dialog – 19.09.2026

**Status:** umgesetzt und fokussiert getestet  
**Bereich:** Verschieben / NFO / Untertitel / Trickplay / Jellyfin-Erkennung / Über-Dialog  
**Ziel:** Companion-Dateien sollen beim finalen Erscheinen einer Videodatei bereits im Ziel vorhanden sein, damit Jellyfin insbesondere vorhandene Trickplay-Daten übernehmen kann, statt direkt eine Neuerzeugung zu starten. Gleichzeitig wird der Über-Dialog wieder auf eine kurze allgemeine Projektbeschreibung reduziert.

### Geänderte Module

- `dragontools/core/move_file_service.py`
- `dragontools/core/move_preparation.py` *(neu)*
- `dragontools/core/move_sidecars.py`
- `dragontools/core/project_info.py`
- `dragontools/core/release_validation_smoke_modules.py`
- `dragontools/worker/move_batch_executor.py`
- `dragontools/worker/move_batch_lifecycle.py`
- `dragontools/worker/move_companion_adapter.py` *(neu)*
- `dragontools/worker/move_completion_service.py`
- `dragontools/worker/move_result_commit.py`
- `dragontools/worker/move_thread.py`
- `dragontools/tests/test_patch_q_companion_first_move.py` *(neu)*
- `dragontools/tests/test_project_info.py`

### Funktionale Änderungen

1. **Companions werden vor dem Video sichtbar gemacht**
   - Die Zielreihenfolge ist jetzt fachlich: **NFO → Untertitel → Trickplay → Video → Mediathek/Jellyfin-Abschluss**.
   - Dragon Tools löst zuerst den endgültigen Videonamen auf, inklusive Konflikt-Umbenennung wie `Film_01.mkv`.
   - Erst danach werden die zu diesem endgültigen Stem gehörenden Companion-Ziele vorbereitet.

2. **Sicheres Vorbereiten statt destruktivem Früh-Move**
   - Fehlt ein Companion im Ziel, wird er vor dem Video **in den endgültigen Zielnamen kopiert**, während die Quelle bis zum erfolgreichen Video-Commit erhalten bleibt.
   - Existiert im Ziel bereits eine NFO, ein Untertitel oder ein Trickplay-Ordner, bleibt dieser zunächst unangetastet, ist aber für den folgenden Video-Commit geschützt.
   - Dadurch ist beim Auftauchen der finalen Videodatei bereits ein gültiger Companion-Pfad vorhanden, ohne dass ein fehlgeschlagener Video-Move die Companion-Quelle verloren gehen lässt.

3. **Rollback bei fehlgeschlagenem Video-Move**
   - Nur die von Dragon Tools neu vorbereiteten Companion-Kopien werden bei einem fehlgeschlagenen Video-Move wieder entfernt.
   - Vorher vorhandene Ziel-Companions werden nicht verändert.
   - Die Original-NFOs, Untertitel und Trickplay-Ordner bleiben bis zum erfolgreichen Video-Commit erhalten und können bei einem Retry erneut verwendet werden.

4. **SxxExx-Ersetzung schützt neue Companion-Ziele**
   - Die bestehende Episode-Replacement-Logik entfernt weiterhin alte Videos sowie alte NFO-/Trickplay-Artefakte mit dem alten Episodentitel.
   - Bereits vorbereitete neue NFO-/Trickplay-Ziele werden von dieser Bereinigung ausdrücklich ausgenommen.
   - Damit kann z. B. `S07E07 - Neuer Titel.trickplay` bereits vorhanden sein, während `S07E07 - Alter Titel.trickplay` zusammen mit dem alten Video entfernt wird.

5. **Bestehender Trickplay-Ordner bleibt während des Video-Wechsels verfügbar**
   - Wenn der Ziel-Trickplay-Ordner bereits existiert, wird er vor dem Video nicht entfernt.
   - Nach dem Video-Commit greift weiterhin die konfigurierte Trickplay-Konfliktregel (`skip`, `overwrite`, `backup`).
   - Dadurch sieht Jellyfin beim finalen Video-Event bereits den `.trickplay`-Ordner und kann ihn seiner neuen Item-ID zuordnen, bevor eine unnötige Neuerzeugung gestartet wird.

6. **NFO bei Episoden-Ersetzung bleibt konsistent**
   - Bei einer bestätigten SxxExx-Ersetzung wird eine neue NFO nach dem Video-Commit auch dann sauber übernommen, wenn der allgemeine Video-Konfliktmodus auf `skip` steht.
   - Das erhält die bisherige Semantik, bei der die alte Episoden-NFO zusammen mit dem alten Episodenvideo ersetzt wurde.

7. **Recovery bleibt idempotent**
   - Ein Crash nach Companion-Vorbereitung, aber vor dem Video-Commit, lässt die Original-Companions stehen.
   - Beim Retry werden bereits vorbereitete identische Companion-Ziele erkannt und nicht als fremder Konflikt behandelt.
   - Quelle und Ziel desselben Sidecars werden nicht versehentlich gelöscht, falls ein Recovery-Kontext bereits direkt im Ziel arbeitet.

8. **Move-Architektur bleibt modular**
   - Zielauflösung und spätere Konfliktauflösung wurden in `core/move_preparation.py` ausgelagert.
   - Die Companion-/Video-Adapter liegen in `worker/move_companion_adapter.py`.
   - Dadurch bleiben die bestehenden Architekturgrenzen für `move_file_service.py` und `move_result_commit.py` eingehalten.

9. **Über-Dialog deutlich verkürzt**
   - Entfernt wurden die Abschnitte `Neuerungen`, `Workflow & Sicherheit`, `Metadaten & Mediathek`, Entwicklungs-/Testzeit, Vorversionen und Shortcut-Liste.
   - Der Dialog enthält nur noch:
     - `Dragon Tools V9.8.5` plus kurze allgemeine Beschreibung,
     - `Video & HDR`,
     - `Projektumfang`,
     - `Externe Werkzeuge & optionale Komponenten`.
   - Die Projektstatistik bleibt weiterhin dynamisch, sofern Python-Quellen vorhanden sind, und verwendet sonst die verifizierten Release-Fallbackwerte.

### Neuer Move-Ablauf

```text
Ziel und finalen Videonamen auflösen
  -> NFO im finalen Ziel bereitstellen
  -> Untertitel im finalen Ziel bereitstellen
  -> Trickplay im finalen Ziel bereitstellen
  -> Video final verschieben / ersetzen
  -> vorbereitete Companion-Quellen finalisieren
  -> Mediathek aktualisieren
  -> Jellyfin gezielt informieren
```

Wichtig: Das Vorbereiten erfolgt bei noch nicht vorhandenen Ziel-Companions als sichere Kopie. Die Quell-Companions werden erst nach erfolgreichem Video-Commit entfernt. Damit erhält Dragon Tools die gewünschte Jellyfin-Reihenfolge, ohne den bisherigen Recovery-/Rollback-Schutz aufzugeben.

### Regressionstests / Abnahme

Neu bzw. erweitert geprüft wurden:

- NFO → Untertitel → Trickplay werden unabhängig von der Eingabeliste in dieser Reihenfolge vorbereitet,
- Companion-Ziele existieren vor dem Video-Commit,
- die Companion-Quellen bleiben bis zum erfolgreichen Video-Commit erhalten,
- ein fehlgeschlagener Video-Move entfernt nur neu vorbereitete Kopien,
- SxxExx-Ersetzung entfernt alte NFO-/Trickplay-Artefakte, aber nicht die bereits vorbereiteten neuen Ziele,
- Rename-Zielstems bleiben für Sidecars konsistent,
- Recovery löscht keinen Sidecar, wenn Quelle und Ziel identisch sind,
- Batch-Reihenfolge ist Companion-Vorbereitung → Video → Abschluss/DB,
- der Über-Dialog enthält nur noch die gewünschten allgemeinen Abschnitte.

**Fokussierte Move-/Jellyfin-/Mediathek-/Patch-P-/Architekturtests:** 189 bestanden, 2 übersprungen, 0 fehlgeschlagen.  
**Syntaxprüfung:** 926 Python-Dateien im bereitgestellten Paket erfolgreich mit `compileall` geprüft.

### Relevanz für Help / Dokumentation / Änderungshistorie

Für die nächste Dokumentationspflege fachlich einsortieren:

- Verschiebeablauf: Companion-first für NFO/Untertitel/Trickplay vor finalem Video,
- Jellyfin: vorhandene Trickplay-Struktur ist beim Video-Event bereits sichtbar,
- Recovery: Companion-Vorbereitung kopiert zunächst und konsumiert die Quelle erst nach Video-Erfolg,
- Über-Dialog: nur allgemeine Kurzbeschreibung, Video/HDR, Projektumfang und externe/optionale Werkzeuge.

## Patch R – Werkzeugpfad-Layout, lokale Whisper-Umschaltung und scrollbare Diagnose – 19.09.2026

### Werkzeugpfade / Oberfläche
- Die Aktionen **„Alle Tools automatisch suchen“** und **„Eingaben prüfen“** liegen jetzt in einer eigenen, über alle Grid-Spalten gespannten Kopfzeile. Dadurch verbreitern die beiden großen Buttons nicht mehr die schmalen Browse-/Auto-Spalten und das eigentliche Pfadfeld erhält den verfügbaren Platz.
- **faster-whisper / lokales Modell** besitzt jetzt eine eigene Checkbox. Sie schaltet explizit zwischen dem normalen Modellnamen/Cache und einem lokalen CTranslate2-Modellordner um.
- Der lokale Modellpfad bleibt beim Deaktivieren erhalten, wird aber nicht verwendet. Beim Browsen auf einen lokalen Modellordner wird die Checkbox automatisch aktiviert.
- Für bestehende Patch-P/Q-Konfigurationen gilt eine Migration ohne Datenverlust: Ist bereits ein lokaler Modellpfad gespeichert und die neue Schalter-Einstellung fehlt, wird der lokale Modus automatisch als aktiv interpretiert.

### Whisper-Runtime / Sicherheit
- Neue Einstellung `tools/whisper/use_local_model`.
- Ist der lokale Modus aktiv, aber kein gültiger Modellordner ausgewählt, bricht die Spracherkennung fail-closed ab; es gibt keinen stillen Download-/Cache-Fallback.
- Ist der lokale Modus deaktiviert, wird ein eventuell gespeicherter lokaler Pfad bewusst ignoriert und der konfigurierte Whisper-Modellname bzw. Modellcache verwendet.
- F9 und die Live-Werkzeugprüfung zeigen den tatsächlich aktiven Modus an.

### Werkzeugdiagnose
- Die bisherige `QMessageBox`-Ausgabe wurde für Werkzeugprüfungen durch einen resizablen Dialog mit `QPlainTextEdit` ersetzt.
- Die Ausgabe ist vertikal scrollbar und wird auf Fensterbreite umgebrochen; lange Toolpfade machen den Dialog daher nicht mehr höher als den Bildschirm.
- Der gleiche scrollbare Dialog wird sowohl von **„Eingaben prüfen“** als auch von **F9 / Werkzeuge prüfen** verwendet.

### Verifikation Patch R
- 70 relevante Regressionstests bestanden, 1 umgebungsabhängiger Test übersprungen.
- Alle 927 Python-Dateien lassen sich per `compileall` fehlerfrei kompilieren.
- Projekt-Fallbackstatistik auf 927 Python-Dateien, 140.850 Gesamtzeilen, 119.227 Codezeilen und 1.572 statisch erkannte Tests aktualisiert.

## Patch S – HandBrake-Desktopprüfung und Whisper-Runtime/Cache-Diagnose – 19.09.2026

**Bereich:** Werkzeugpfade / F9-Diagnose / HandBrake / faster-whisper / CTranslate2  
**Ziel:** Dragon Tools verwendet HandBrake ausschließlich als extern geöffnete Desktop-Anwendung. Die Werkzeugprüfung darf daher nicht fälschlich `HandBrakeCLI.exe` verlangen. Zusätzlich muss die Whisper-Diagnose klar zwischen Python/CTranslate2-Laufzeit und dem separat heruntergeladenen Modellcache unterscheiden.

### HandBrake

- Automatische Suche, Live-Prüfung, F9-Diagnose, Diagnosepaket und externe Programmstarter verwenden jetzt ausschließlich `HandBrake.exe`.
- `HandBrakeCLI.exe` ist für den Dragon-Tools-Workflow nicht erforderlich.
- `ToolPaths.handbrake` ist die primäre Property. `handbrake_cli` bleibt nur als interner Kompatibilitätsalias bestehen, damit ältere Aufrufer nicht brechen.
- Die Werkzeugdiagnose bezeichnet HandBrake jetzt als externe GUI und startet die GUI bei der Versionsprüfung weiterhin nicht versehentlich.

### faster-whisper / CTranslate2 / Modellcache

- Die Runtime-Prüfung testet jetzt die **tatsächliche Importierbarkeit** von `faster_whisper` und `ctranslate2`; das ist auch für Frozen-/PyInstaller-Laufzeiten aussagekräftiger als eine reine `find_spec`-Prüfung.
- Die Modellcache-Erkennung ist getrennt von der Runtime-Prüfung. Unterstützte Standardmodelle (`tiny`, `base`, `small`, `medium`, `large-v3`) werden im üblichen Hugging-Face-Hub-Cache gesucht.
- Ein vorhandener Modellcache ersetzt **nicht** `faster-whisper` oder CTranslate2. Fehlen diese Komponenten, nennt die Diagnose das jetzt ausdrücklich.
- Ist die Runtime vorhanden, aber das ausgewählte Modell noch nicht gecacht, bleibt die Prüfung erfolgreich und erklärt, dass das Modell beim **ersten tatsächlichen Einsatz** automatisch geladen und danach wiederverwendet wird.
- Ist das ausgewählte Modell bereits gecacht, zeigt die Diagnose den gefundenen Snapshot-Pfad an.
- F9 und die Live-Prüfung berücksichtigen den aktuell eingestellten Whisper-Modellnamen statt pauschal nur `small` anzuzeigen.
- Ein explizit aktivierter lokaler CTranslate2-Modellordner bleibt weiterhin autoritativ und fail-closed.

### Tests

- Neue Regressionstests prüfen die reine `HandBrake.exe`-Auflösung, Live-/Auto-Suche, Cache-Erkennung, Runtime-vs.-Cache-Trennung und den First-Use-Download-Hinweis.

## Patch T – Renamer bleibt während der Metadatensuche bedienbar – 19.09.2026

**Bereich:** Renamer / Metadatensuche / GUI-Reaktivität / manuelle Suchkorrektur

### Problem

Während einer laufenden Metadatensuche wurden fast alle Renamer-Aktionen deaktiviert. Dadurch musste eine komplette Batch-Suche beendet sein, bevor ein falscher Listeneintrag entfernt oder der Suchbegriff einer einzelnen Datei korrigiert werden konnte. Ein einfaches Freischalten der Buttons wäre nicht sicher gewesen, weil der bisherige Worker Ergebnisse anhand veränderlicher Tabellenzeilen zurückmeldete: Wird während der Suche eine Zeile entfernt, verschieben sich die Row-Indizes und ein spätes Ergebnis könnte auf der falschen Datei landen.

### Änderungen

1. **Entfernen und Suchkorrektur bleiben während der Suche verfügbar**
   - `Als Serie suchen`, `Als Film suchen`, `Alle Treffer`, `Suchbegriff`, `Entfernen` und `Alle` bleiben bei laufender Hintergrundsuche aktiv.
   - Dateien und Ordner können weiterhin hinzugefügt werden.
   - Aktionen, die einen vollständig stabilen Ergebnisstand benötigen (`Vorschläge suchen`, Akzeptieren/Ablehnen und endgültiges Umbenennen), bleiben bis zum Ende der laufenden Suche gesperrt.

2. **Manuelle Suche wird priorisiert statt blockiert**
   - Eine manuell geänderte Suche wird sofort in die laufende Suchwarteschlange eingeschoben.
   - Noch nicht gestartete automatische Suchjobs für dieselbe Datei werden aus der Warteschlange entfernt.
   - Nach dem aktuell bereits laufenden Provider-Aufruf wird die manuelle Korrektur bevorzugt verarbeitet; danach läuft der übrige Batch normal weiter.

3. **Keine Row-Index-Race-Condition mehr**
   - Worker-Ergebnisse werden nicht mehr blind an den ursprünglichen Tabellenindex gebunden.
   - Jede Suche erhält pro Dateipfad eine monotone Request-ID.
   - Beim Eintreffen eines Ergebnisses wird die aktuelle Tabellenzeile über den stabilen Dateipfad neu ermittelt.
   - Veraltete Ergebnisse werden ignoriert, sobald für dieselbe Datei eine neuere manuelle Suche gestartet wurde.

4. **Entfernte Dateien können keine späten Treffer mehr erhalten**
   - `Entfernen` und `Alle` invalidieren zuerst die offenen Request-IDs und löschen noch nicht gestartete Jobs für die betroffenen Pfade aus der Worker-Warteschlange.
   - Ein Provider-Aufruf, der für eine gerade entfernte Datei bereits läuft, darf zu Ende kommen; sein Ergebnis wird danach sicher verworfen.

5. **Thread-sichere Prioritätswarteschlange**
   - Neue Komponente `gui/movie_renamer_job_queue.py` kapselt Priorisierung und Pfad-Cancel der Renamer-Suchjobs.
   - Der bestehende einzelne Suchworker bleibt erhalten; es werden nicht unkontrolliert parallele Provider-Threads erzeugt.
   - Damit bleiben Retry/Rate-Limit-Verhalten und Provider-Clients überschaubar, während die GUI trotzdem direkt bedienbar ist.

### Verifikation

- Neue Patch-T-Tests prüfen Priorisierung, Pending-Cancel, veraltete Ergebnisunterdrückung, Entfernen während laufender Suche und die freigeschalteten GUI-Aktionen.
- Fokussierte Renamer-/Architektur-/Jellyfin-/Patch-P/Q/S-Regressionstests: **107 bestanden, 0 fehlgeschlagen**.
- Projekt-Fallbackstatistik: **930 Python-Dateien**, **141.292 Gesamtzeilen**, **119.578 Codezeilen**, **211 Testpaket-Dateien**, **208 `test_*.py`**, **1.584 statisch erkannte Tests**.

## Patch U – Move completion wiring repariert

### Behoben
- `dragontools/worker/move_result_commit.py`: fehlende Factory `_completion_service()` wiederhergestellt.
- `MoveBatchLifecycleMixin._execute_move_batch()` kann `MoveCompletionService` damit wieder korrekt erzeugen; der Absturz `AttributeError: 'MoveThread' object has no attribute '_completion_service'` ist behoben.
- Die Factory verdrahtet Journal, Companion-/Sidecar-Abschluss, Mediathek-Commit, Move-Report und Worker-Logging wieder an einer Stelle.

### Regressionstest
- `dragontools/tests/test_refactor_block7_move_architecture.py`: statischer Contract-Test stellt sicher, dass Lifecycle-Aufruf und Completion-Factory nicht erneut auseinanderlaufen.


## Patch V – Qt-Signal-Callback-Härtung und MainWindow-Geometrie – 19.09.2026

**Bereich:** PyQt6 / Callback-Dispatch / ToolRunner / Watch-Folder / GUI-Geometrie

### Fehlerbild

Beim Programmstart konnten mehrfach Meldungen der Form
`TypeError: native Qt signal is not callable` auftreten. Zusätzlich meldete Qt
bei einzelnen Installationen eine erzwungene MainWindow-Mindestbreite von mehreren
tausend Pixeln, z. B. `minimum size: 4766x341`.

### Korrekturen

- `core/callback_dispatch.py`
  - `is_callback_like()` ergänzt.
  - Native Qt-Signale werden weiterhin ausschließlich über `.emit(...)` aufgerufen.
- `worker/tool_runner.py`
  - stdout-/stderr-Line-Callbacks laufen jetzt über `invoke_callback()` statt über direkten Funktionsaufruf.
  - Signalartige Callback-Objekte werden auch dann korrekt erkannt, wenn ihr direkter `__call__` in PyQt6 nicht zulässig ist.
- `gui/watch_folder_controller.py`
  - Status-Callbacks signal-sicher gemacht.
- `gui/convert_widget_watch_intake.py`
  - Watch-Folder-Completion-Callbacks signal-sicher gemacht.
- `gui/video_file_input.py`
  - Drag&Drop-Callback signal-sicher gemacht.
- `gui/preflight_series_view.py`
  - Metadaten-Refresh-Callback signal-sicher gemacht.
- `gui/convert_widget_custom_widgets.py`
  - `BannerLabel.minimumSizeHint()` erzwingt horizontal keine Mindestbreite mehr.
  - Große Banner-Pixmaps können damit nicht mehr die Mindestbreite des QMainWindow auf ihre Quell-/Pixmap-Breite hochziehen.
- Move-Fix aus Patch U bleibt unverändert enthalten (`MoveCompletionService`-Factory).

### Regressionstests

- Neuer Test `test_patch_v_startup_signal_geometry.py` reproduziert absichtlich ein Qt-Signalobjekt, dessen direkter Aufruf `TypeError: native Qt signal is not callable` auslöst.
- ToolRunner muss dasselbe Objekt über `.emit()` korrekt bedienen.
- Statischer Guard stellt sicher, dass `BannerLabel` die horizontale Mindestbreite auf 0 freigibt.
- Kombinierter betroffener Testlauf: **22 bestanden, 1 übersprungen**.
- `compileall`: erfolgreich.

## Patch W – QObject-`event()`-Namenskollision im Converter behoben – 19.09.2026

**Bereich:** PyQt6 / ConverterThread / DV-Remux / Parallel-Converter / Strip-Only

### Fehlerbild

Beim Start bzw. Abschluss einer Strip-Only-/Remux-Datei – und grundsätzlich auch im normalen Encoderpfad – konnte auf der Konsole wiederholt
`TypeError: native Qt signal is not callable`
erscheinen. Die bisherigen Callback-Härtungen aus Patch V konnten diesen Fehler nicht vollständig beseitigen, weil die verbleibende Ursache kein normaler Callback-Aufruf war.

### Ursache

`ConverterThread`, `DVRemuxThread` und `ParallelConverterThread` deklarierten ein eigenes PyQt-Signal mit dem Namen `event`.
Diese Klassen erben direkt oder indirekt von `QObject`; `QObject`/`QThread` besitzen bereits die native virtuelle Methode `event(QEvent*)` für die Qt-Eventzustellung.
Das eigene `event = pyqtSignal(object)` überschrieb damit auf Python-Ebene den nativen Qt-Methodennamen. Sobald Qt intern ein Event an den Worker zustellte, konnte PyQt statt der erwarteten Methode auf ein Signalobjekt treffen und `TypeError: native Qt signal is not callable` ausgeben.

### Korrektur

- Das Dragon-Tools-interne strukturierte Worker-Signal heißt jetzt durchgehend `worker_event` statt `event`.
- Umgestellt wurden:
  - `worker/converter_thread.py`
  - `worker/converter_static_composition.py`
  - `worker/dv_remux_thread.py`
  - `worker/dv_remux_file_dispatcher.py`
  - `worker/dv5_encode_fallback.py`
  - `worker/parallel_worker_launcher.py`
  - `worker/dv_result_contract.py`
  - `worker/parallel_converter_thread.py`
  - `worker/dv_remux_job.py`
- Logging-, Progress- und Result-Events bleiben fachlich unverändert; nur der kollidierende Qt-Attributname wurde ersetzt.
- Es wird bewusst **kein** Legacy-Alias `event` angelegt, weil genau dieser Alias die native `QObject.event()`-Methode erneut verdecken würde.

### Regressionstests

- Neuer Test `test_patch_w_qobject_event_signal_collision.py` prüft statisch, dass die drei QObject/QThread-Worker kein Signal namens `event` mehr deklarieren und stattdessen `worker_event` besitzen.
- Zusätzlich wird der Worker-Bereich auf verbliebene `.event.emit(...)`-/`.event.connect(...)`-Verwendungen geprüft.
- Parallel-Converter-, DV-Transaktions-, DV-Fallback- und Converter-Refactor-Tests: **52 bestanden**.
- Strip-Only-/Workflow-/Conversion-/Move-Sicherheitsset: **48 bestanden, 5 übersprungen**; ein separater CI/Build-Contract-Test wurde im Source-Patch mangels vollständiger Repository-/Build-Metadaten abgewählt.
- `compileall`: erfolgreich.

## Patch X – Review-Hardening: Source-ZIP, Secrets, Jellyfin-HTTP und Qualitätsverträge – 20.09.2026

- Source-ZIP-BAT behandelt `INTEGRATION_TESTS.md`, Manifest, Help, PATCH, pytest.ini und die zentralen Requirements als Pflichtdateien und verifiziert diese nach dem Packen.
- Automatisch erzeugte PyInstaller-`.spec`-Dateien werden weder vom BAT- noch vom Python-Source-Packager ausgeliefert; der aktive Build bleibt `pyinstaller-cli` über `build_v9.bat`.
- `INTEGRATION_TESTS.md` ist wieder Bestandteil des Source-Vertrags und beschreibt Standardtests sowie die bewusst manuell gestarteten realen DV/HDR-Roundtrips.
- Patch-S-Tests verwenden paketrelative Pfade und hängen nicht mehr vom aktuellen Arbeitsverzeichnis ab.
- Für `release_validation_package.py` wurde das starre 380-Zeilen-Limit durch AST-basierte Kohäsions-/Komplexitätsgrenzen ersetzt: Anzahl Top-Level-Funktionen, Entscheidungs-Komplexität, Funktionsgröße und interner Import-Fanout.
- TMDB-/TheTVDB-/Jellyfin-Secrets werden bei realen PyQt6-QSettings unter Windows transparent mit DPAPI geschützt. Bestehende Klartextwerte bleiben lesbar und werden beim nächsten Speichern migriert. Passwortgeschützte DragonTools-Backups sichern weiterhin die entschlüsselten Secretwerte und schützen sie beim Restore erneut lokal.
- Beim erstmaligen Speichern/Aktivieren einer HTTP-Jellyfin-Adresse warnt die Einstellungen-Seite, dass der API-Key auf diesem Transport nicht verschlüsselt ist; eine bewusst interne HTTP-Konfiguration bleibt zulässig.
- Literal stumm geschluckte `except Exception: pass`-Blöcke im Produktcode protokollieren Best-Effort-Fehler jetzt auf Debug-Ebene; ein Regressionstest verhindert neue vollständig stumme Broad-Exception-Pass-Blöcke.
- README/Help/Änderungshistorie referenzieren keine bewusst nicht ausgelieferten internen Review-/Patch-Abschlussdateien mehr. Historische Reviewbefunde werden als damaliger Zustand bezeichnet und nicht mehr als weiterhin offen dargestellt, wenn spätere Patches sie abgesichert haben.
- Patches V/W (Qt-Signal-Dispatch und `QObject.event()`-Kollision) sind in der öffentlichen Hilfe als aktueller V9.8.5-Stand dokumentiert.


## Patch Y – Review-Nachhärtung: Logging, Release-Scan, CrashGuard, DPAPI und Source-ZIP – 20.09.2026

**Bereich:** Fehlerdiagnose / QSettings / Audit / CrashGuard / Release-Validierung / Windows DPAPI / Source-Packaging

### Korrekturen

- `core/audit_log.py`
  - Schreibfehler des Einstellungs-Audits werden nicht mehr still in `None` umgewandelt, sondern als Warnung mit Traceback protokolliert.
  - Fehler beim Erstellen von QSettings-Snapshots bleiben fail-soft, werden aber auf Debug-Ebene nachvollziehbar protokolliert.
- `core/settings_access.py`
  - Fehler beim Erzeugen bzw. Lesen von QSettings bleiben bewusst fallback-fähig, werden nun jedoch auf Debug-Ebene mit dem betroffenen Schlüssel protokolliert.
- `core/crash_guard.py`
  - Ein Fehler bereits bei der Initialisierung des CrashGuards bleibt startverträglich, wird aber zusätzlich über einen minimalen `stderr`-Fallback sichtbar gemacht.
  - Nicht lesbarer Crash-State wird protokolliert und über denselben Fallback sichtbar gemacht; Kommando-Normalisierungsfehler werden auf Debug-Ebene erfasst.
- `core/release_validation_package.py`
  - Eine nicht lesbare Release-Textdatei wird beim Datenschutzscan nicht mehr still übersprungen. Der Release-Validator erzeugt dafür jetzt eine explizite Warnung und behauptet damit nicht mehr fälschlich einen vollständig erfolgreichen Scan.
- `core/secret_settings.py` / Tests
  - Zusätzlich zum gemockten Secret-Contract existiert ein echter Windows-DPAPI-Roundtrip-Test für `CryptProtectData`/`CryptUnprotectData`; außerhalb von Windows wird nur dieser Test erwartungsgemäß übersprungen.
- `DragonTools_Source_ZIP.bat`
  - ZIP-Einträge werden nun explizit mit `/` als Entry-Separator geschrieben, statt sich auf `CreateFromDirectory()` und dessen plattformspezifische Namen zu verlassen.
  - Die Verify-Phase prüft zusätzlich die rohen ZIP-Namen und bricht ab, sobald ein Backslash in einem Entry-Namen auftaucht.

### Verhalten

- Parser-/Konvertierungs-Fallbacks werden weiterhin nicht pauschal mit Warnungen zugespammt.
- Operative Fehler, bei denen Audit-, Settings-, Crash- oder Release-Information verloren gehen würde, bleiben fail-soft, sind aber diagnostizierbar.
- Jellyfin-HTTP-Warnlogik bleibt unverändert: Sie greift nur bei aktivierter Jellyfin-Integration, wie vorgesehen.


## Patch Z – Renamer-Popup-Geometrie und Release-Smoke-Abdeckung – 20.09.2026

**Bereich:** Renamer / PyQt6-Geometrie / Release-Validierung / Regressionstests

### Fehlerbild

Nach dem Laden von Renamer-Treffern konnte Windows/Qt versuchen, das Hauptfenster auf mehrere tausend Pixel Mindestbreite zu setzen, z. B. `minimum size: 5158x341`. Ursache war die Kandidaten-ComboBox: `WideCandidateComboBox.showPopup()` setzte die Mindestbreite der internen Item-View auf die Breite des längsten Provider-Treffers. Diese Mindestbreite konnte über Tabelle/Layout bis zum `QMainWindow` propagieren.

### Korrekturen

- `gui/movie_renamer_view.py`
  - Die interne ComboBox-View erhält **keine** dynamische `setMinimumWidth()`-/`setFixedWidth()`-Vorgabe mehr.
  - Die gewünschte Breite wird weiterhin aus dem längsten Treffer berechnet, aber auf die verfügbare Bildschirmbreite begrenzt.
  - Erst nachdem Qt das Popup erzeugt hat, wird ausschließlich das transiente Popup-Fenster per `resize()` verbreitert.
  - Lange Provider-Titel können damit das Hauptfenster nicht mehr auf mehrere tausend Pixel Mindestbreite zwingen.
- `core/release_validation_package.py`
  - Die in Patch X/Y neu dokumentierten Produktivmodule `core/audit_log.py`, `core/crash_guard.py`, `core/secret_settings.py` und `core/settings_access.py` wurden in die Release-Smoke-Pflichtliste aufgenommen.
  - Dadurch ist der bestehende Vertrag wieder erfüllt, dass jedes im Patchprotokoll genannte Produktivmodul vom Release-Smoke abgedeckt wird.
- `tests/test_patch_z_renamer_popup_geometry.py` *(neu)*
  - Regressionstest verbietet künftig `setMinimumWidth()` und `setFixedWidth()` in `WideCandidateComboBox.showPopup()`.
  - Zusätzlich wird geprüft, dass die Popup-Größenänderung erst nach `super().showPopup()` erfolgt und eine Bildschirmbegrenzung vorhanden ist.
- `DragonTools_Source_ZIP.bat`
  - Root-BAT-Dateien werden nicht mehr pauschal über `*.bat` eingesammelt, sondern nur noch die autoritativen Build-/Packaging-Skripte. Dadurch gelangen temporäre Review-/Backup-BATs nicht versehentlich in künftige Source-Releases.
  - Der obsolete Zwischenstand `DragonTools_Source_ZIP_patchY.bat` wurde aus dem gepatchten Paket entfernt.

### Verifikation

- Vollständige Testsuite in vier Teilblöcken: **1.622 bestanden, 24 übersprungen, 0 fehlgeschlagen**.
- Die Skips betreffen ausschließlich fehlendes PyQt6/pytest-qt auf dem Review-Host, den echten Windows-DPAPI-Roundtrip sowie nicht konfigurierte reale DV/HDR-Werkzeuge.
- `compileall`: erfolgreich.
- Release-Validator auf bereinigtem Source-Baum: **27 OK, 4 erwartete Warnungen, 0 Fehler**.
- Die vier Warnungen sind der bewusst fehlende `dist`-Ordner im Source-Paket sowie die bekannten historischen/persönlichen Namensnennungen in Help/V7/V8-Changelog.

## Patch AA – Renamer-Mindestbreite nach Kandidatenauflösung vollständig behoben – 20.09.2026

**Bereich:** Renamer / PyQt6-Geometrie / QComboBox-SizeHint / persistierter Header-State

### Fehlerbild

Patch Z verhinderte zwar, dass das geöffnete Kandidaten-Popup selbst eine mehrere tausend Pixel breite Mindestgröße setzt. Nach der ersten Metadatensuche konnte das Hauptfenster trotzdem erneut extrem breit und praktisch nicht mehr verkleinerbar werden.

### Ursache

- Eine normale `QComboBox` berechnet `sizeHint()` und `minimumSizeHint()` aus dem längsten Eintrag. Die Renamer-Kandidatencombo wird als Index-Widget in die `QTableWidget` eingesetzt; ein sehr langer Provider-Treffer konnte dadurch auch **ohne geöffnetes Popup** einen extrem breiten Größenwunsch in die Widget-Hierarchie tragen.
- Zusätzlich wurde weiterhin `renamer/table_header_state_v1` wiederhergestellt. Bereits in älteren Ständen gespeicherte übergroße Spaltenbreiten konnten damit nach dem Laden des Renamers erneut aktiv werden.

### Korrektur

- `gui/movie_renamer_candidate_combo.py` kapselt den Kandidatenselektor als eigene View-Komponente.
- `WideCandidateComboBox` verwendet horizontal `QSizePolicy.Ignored`; der Tabellenzellenrahmen bestimmt die sichtbare Breite.
- `minimumSizeHint()` liefert horizontal 0, `sizeHint()` wird für Layoutzwecke auf 240 px begrenzt. Die breite Trefferanzeige bleibt ausschließlich Aufgabe des transienten Popups.
- Der Header-State wurde auf `renamer/table_header_state_v2` migriert. Alte v1-Zustände werden dadurch bewusst nicht mehr restauriert.
- Einzelne Renamer-Spalten sind zusätzlich auf maximal 1200 px begrenzt, sodass auch ein künftig beschädigter/unerwarteter Header-State keine 5000+-px-Spalte wiederherstellen kann.

### Regressionstests

- Der bestehende Geometrietest prüft nun zusätzlich die horizontale `Ignored`-SizePolicy, den neutralen Minimum-SizeHint, den begrenzten Layout-SizeHint, den v2-Header-State und die maximale Section-Breite.


## Patch AB – Renamer-Geometrie nach erfolgreicher Umbenennung – 20.09.2026

**Bereich:** Renamer / QTableWidget / Zeilenentfernung / Layout-Invalidierung

### Fehlerbild

Nach dem ersten erfolgreichen Umbenennen und Entfernen einer Renamer-Zeile konnte das Hauptfenster erneut auf eine extrem große Mindestbreite springen und ließ sich nicht mehr normal verkleinern. Sobald neue Dateien hinzugefügt wurden, wurde die Geometrie neu berechnet und das Fenster ließ sich wieder verkleinern.

### Ursache

- Der problematische Zustand entstand nicht mehr beim Kandidaten-Popup, sondern beim Übergang `removeRow()`/`setRowCount(0)` nach erfolgreicher Umbenennung.
- Qt kann dabei Größeninformationen von gerade entfernten Cell-Widgets/Editoren bis zum nächsten Eventloop-/Layout-Zyklus cachen. Dadurch blieb kurzfristig ein veralteter horizontaler Minimum-Size-Hint in der Widget-Hierarchie aktiv.
- Das erneute Einfügen einer Zeile invalidierte die Geometrie zufällig wieder, weshalb das Fenster danach erneut verkleinerbar war.

### Korrektur

- `RenameTable` besitzt nun horizontal `QSizePolicy.Ignored` und liefert in `minimumSizeHint()` grundsätzlich 0 px als horizontale Mindestbreite. Die Tabelle ist scrollbar und darf daher die Mindestbreite des Hauptfensters niemals bestimmen.
- `rowsRemoved` und `modelReset` planen nach der Tabellenänderung eine Geometrie-Aktualisierung im nächsten Qt-Eventloop ein.
- Dabei werden `updateGeometry()` und die Layout-Invalidierung entlang der Eltern-Widget-Kette ausgeführt. Alte Größen-Caches nach `removeRow()` können dadurch nicht bis zum `QMainWindow` bestehen bleiben.
- Die bereits in Patch Z/AA eingeführten Popup-, ComboBox- und Header-Grenzen bleiben unverändert bestehen.

### Regressionstest

- Der Renamer-Geometrietest prüft zusätzlich, dass `RenameTable` horizontal keine Mindestbreite anfordert und nach Zeilenentfernung eine verzögerte Geometrie-Neuberechnung über `QTimer.singleShot()` besitzt.
## Patch AC – Renamer-Fensterbreite nach Umbenennen (2026-09-20)

- `movie_renamer_view.py`: Statuszeile des Renamers kann die Fenster-Mindestbreite nicht mehr bestimmen.
- Ursache: Nach Rename schreibt der asynchrone Jellyfin-Refresh auch lange Fallback-/Fehlermeldungen mit vollständigen Pfaden in ein ungebrochenes `QLabel`. Dessen Textbreite wurde als Layout-Minimum bis zum `QMainWindow` propagiert.
- Statuslabel jetzt mit Word-Wrap, `minimumWidth=0` und horizontaler `QSizePolicy.Ignored`.
- `movie_renamer_widget.py`: zusätzliche Tab-Seiten-Sicherung: horizontale Mindestbreite immer 0 und horizontale SizePolicy `Ignored`, damit kein Renamer-Kindwidget jemals die Hauptfenster-Mindestbreite anheben kann.
- Neuer statischer Regressionstest `test_patch_ac_renamer_status_geometry.py`.


## Patch AD – Move-Quelle gegen transiente Dateisystemfehler absichern + Jellyfin-Fallback entkoppeln – 20.09.2026

**Bereich:** Zwischenverschieben / finaler Move / Dateisystemdiagnose / Jellyfin API / Fallback-Vollscan

### Fehlerbild Move

In einem seltenen Zwischenverschiebe-Fall wurden zwei bereits fertig konvertierte Episoden mit
`Fertige Datei nicht mehr gefunden, aus Zwischenverschieben entfernt` aus dem Move-State gestrichen, obwohl die Dateien tatsächlich vorhanden waren und anschließend manuell verschoben werden konnten.

### Ursache

- `gui/move_incremental_lifecycle.py` verwendete einen einzelnen `Path.exists()`-Check.
- Ein einziges negatives Ergebnis führte sofort zu einem **destruktiven State-Update**: Output und Companion-Zuordnung wurden aus `fertig` bzw. `sidecar_outputs_by_video` entfernt.
- `Path.exists()` verschluckt außerdem den zugrunde liegenden `OSError`; damit war der damalige Zustand nicht mehr diagnostizierbar.

### Korrekturen Move

- `core/move_source_probe.py` *(neu)*
  - Gemeinsamer, Qt-freier Source-Probe mit drei kurzen Wiederholungsprüfungen.
  - Verwendet `stat()` statt `exists()` und bewahrt Exception-Typ und Fehlermeldung auf.
  - Erfasst zusätzlich Elternordner-Erreichbarkeit und reale Dateigröße, wenn verfügbar.
  - Companion-Dateien können einzeln mit Verfügbarkeits-/Fehlerstatus protokolliert werden.
- `gui/move_incremental_lifecycle.py`
  - Ein temporär nicht erreichbarer fertiger Output wird **nicht mehr** aus `state.fertig` entfernt.
  - NFO-/Untertitel-/Trickplay-Zuordnungen bleiben ebenfalls erhalten.
  - Die Datei wird nur für den aktuellen Zwischenmove übersprungen und bleibt für einen späteren/finalen Move vorgemerkt.
  - Warnlog enthält vollständigen Quellpfad, Wiederholungsanzahl, echten `OSError`, Elternordnerstatus, Dateigröße, geplantes Ziel und bekannte Companion-Dateien.
- `worker/move_batch_executor.py`
  - Auch der eigentliche/finale Move prüft die Quelle nicht mehr nur einmal, sondern verwendet denselben Wiederholungs-Probe.
  - Bleibt die Quelle wirklich unerreichbar, wird ein Diagnoseblock geloggt und der Move sauber als Fehler gejournalt; es findet keine stille State-Vernichtung statt.

### Jellyfin-Fallback-Härtung

- `core/jellyfin_api.py`
  - Unterstützt jetzt `GET /ScheduledTasks` und erkennt den laufenden globalen Jellyfin-Mediatheksscan über Task-Key/Task-State.
- `core/jellyfin_full_scan_guard.py` *(neu)*
  - Full-Scan-Fallback ist nun Single-Flight: Ein bereits auf dem Server laufender Mediatheksscan wird wiederverwendet.
  - Zusätzlich schützt ein kurzer prozesslokaler 30-Sekunden-Lease gegen das Race zweier nahezu gleichzeitig fertig werdender Episoden/Worker.
  - Dadurch kann der zweite Fallback nicht mehr direkt einen gerade gestarteten `/Library/Refresh` erneut anstoßen und den ersten Scan abbrechen/neustarten.
- `core/jellyfin_refresh_service.py`
  - Meldet explizit, ob ein vollständiger Scan neu gestartet oder ein bereits laufender Scan wiederverwendet wurde.
  - `JellyfinRefreshResult` enthält dafür `full_scan_reused`.
- `gui/jellyfin_refresh_dispatch.py`
  - Ein **Fallback** wird in der GUI nun bewusst mit `⚠️`/Warn-Level geloggt statt mit einem irreführenden grünen Erfolgshaken.
  - Erfolgreiche gezielte Aktualisierungen und explizit konfigurierte Vollscans bleiben normale Erfolgslogs.

### Tests / Release

- `tests/test_patch_ad_move_jellyfin_hardening.py` *(neu)* prüft Source-Retry, OSError-Diagnose, Companion-Diagnose, State-Erhalt, Worker-Recheck, Fallback-Warnlog und Release-Smoke-Abdeckung.
- `tests/test_patch_f_jellyfin_api.py` deckt zusätzlich Scheduled-Task-Erkennung, Reuse eines laufenden Scans und die Deduplizierung zweier unmittelbarer Fallback-Vollscans ab.
- `tests/test_incremental_move_queue_edit.py` prüft, dass ein temporär fehlender fertiger Output samt Companion-State und geplantem Ziel erhalten bleibt.
- `core/release_validation_package.py` enthält die neuen Produktivmodule in der Release-Smoke-Pflichtliste.

## Patch AE – Renamer-Batchcache, Rename/Jellyfin-Trennung und Strip-Only-Watch-Feedback – 21.09.2026

**Bereich:** Serien-Renamer / TheTVDB / TMDB / Jellyfin / Watch-Folder / Strip-Only / Overwrite-in-place

### Renamer: Metadaten für Serien stapelweise wiederverwenden

Bei großen Serienpaketen lief der Resolver zwar bereits mit wiederverwendeten Provider-Clients, führte aber pro Datei weiterhin den kompletten Auflösungspfad aus. TheTVDB hatte bereits einen Episodenlisten-Cache, wiederholte aber identische Seriensuchen/Kandidatenbildung. TMDB verwendete im Renamer sogar den einzelnen Episode-Endpunkt pro Folge.

- **TheTVDB**
  - identische Seriensuchen werden jetzt auf Renamer-Ebene pro Client/Session gecacht;
  - Seriendetails und die bereits vorhandene vollständige Episodenliste werden für weitere Folgen derselben Serie direkt wiederverwendet;
  - Staffel-/Folgenzuordnung erfolgt danach lokal aus dem geladenen Episodenbestand.
- **TMDB**
  - identische Seriensuchen werden ebenfalls auf Renamer-Ebene wiederverwendet;
  - für den Renamer wird eine Staffel über `/tv/<id>/season/<season>` einmal geladen und im RAM gecacht;
  - alle Folgen derselben Staffel werden anschließend lokal aus diesem Staffel-Payload aufgelöst;
  - der teurere Einzel-Episode-Endpunkt bleibt nur als Kompatibilitäts-/Fallback-Pfad für unvollständige oder generische Staffelantworten erhalten.
- `CompositeMetadataClient` und der Renamer-Kandidatenresolver bevorzugen den neuen Batch-Pfad automatisch, fallen bei Providern ohne Batch-Unterstützung aber weiterhin auf den bisherigen Resolver zurück.

Damit skaliert z. B. eine Serie mit 78 Folgen über acht Staffeln nicht mehr wie 78 vollständige TMDB-Episodenabfragen; im Normalfall werden ungefähr die tatsächlich benötigten Staffeln geladen, während TheTVDB seinen einmal geladenen Serien-Episodenbestand wiederverwendet.

### Renamer darf keinen Jellyfin-Vollscan mehr auslösen

- Die Jellyfin-Benachrichtigung nach erfolgreichem Renamen ist standardmäßig jetzt **deaktiviert** und damit opt-in.
- Wird sie bewusst aktiviert, erzwingt der Trigger `rename` immer `targeted` und setzt `fallback_full_scan=False` – unabhängig von den globalen Jellyfin-Einstellungen.
- Ein Rename kann dadurch weder einen expliziten `/Library/Refresh` noch einen Fallback-Vollscan auslösen.
- Vollscan/Fallback bleibt ausschließlich dem Move-Workflow vorbehalten, nachdem eine Datei tatsächlich in ihrem finalen Mediathekspfad angekommen ist.
- Die Jellyfin-Einstellungsseite erklärt diese Trennung ausdrücklich.

### Strip-Only: Watch-Folder-Feedbackschleife behoben

Bei Overwrite-in-place/Strip-Only konnte der Watch-Folder dieselbe bereits erfolgreich verarbeitete Datei nach kurzer Zeit erneut als neue Eingabe erkennen:

1. Der Watch-Scanner merkte sich vor der Konvertierung `size + mtime` der Quelle.
2. Strip-Only ersetzte dieselbe Quelldatei korrekt durch den bereinigten Output.
3. Der Erfolg wurde aber mit der **alten** Signatur bestätigt.
4. Durch neue Dateigröße/mtime erschien der eigene Output nach Ablauf des Stability-Fensters wieder als neue Eingabe.
5. Die bereits gestripte Datei wurde erneut verarbeitet; mehrere nachlaufende Worker konnten danach auf dieselbe Original-/Backup-Datei treffen und `WinError 32`, Backup-Kollisionen, `WinError 5` oder später `WinError 2` erzeugen.

Korrektur:

- `WatchFolderScanner.acknowledge_current()` bestätigt nach erfolgreicher Verarbeitung die **aktuelle Signatur der tatsächlich auf Platte liegenden Datei**.
- Existiert die Quelle nach dem Erfolg noch (typisch Strip-Only/Overwrite), wird ihre neue Größe/mtime als bereits verarbeitet gespeichert.
- Wurde die Quelle dagegen wegverschoben, fällt die Bestätigung kontrolliert auf die ursprüngliche Kandidatensignatur zurück.
- `watch_folder_controller.py` verwendet nach einem erfolgreichen Job ausschließlich diese Post-Commit-Bestätigung.

Damit kann DragonTools seinen eigenen korrekt erzeugten Strip-Only-Output nicht mehr nach dem Stability-Timeout erneut in die Queue aufnehmen.

### Tests / Release

- Neuer Regressionstest `test_patch_ae_renamer_watch_jellyfin.py` prüft:
  - Post-Commit-Watch-Folder-Signatur bei Overwrite-in-place,
  - TMDB-Staffelcache ohne Einzel-Episode-Requests,
  - TheTVDB-Reuse von Seriensuche/Seriendetails/Episodenbatch,
  - Verwendung des Batch-Resolvers im Renamer,
  - Rename-Jellyfin standardmäßig aus und technisch targeted-only ohne Fullscan-Fallback.
- Die neuen/angepassten Produktivmodule sind in der Release-Smoke-Pflichtliste enthalten.

## Patch AF – Hardware-Encoder-Argumente für aktuelles FFmpeg korrigiert – 21.09.2026

**Bereich:** NVENC / Intel QSV / AMD AMF / Standard / Dolby Vision / HDR10+ / Encoder-Override

### Ursache des DV/NVENC-Fehlers

Der Fehler war **nicht auf den manuellen Datei-Override beschränkt**. Der Override hat in dem gemeldeten Fall lediglich NVENC aktiviert. Sobald NVENC aktiv war und Spatial/Temporal AQ eingeschaltet war, liefen Standard-, DV-, HDR10+- und Qualitäts-Testpfade über denselben zentralen `_vid_args()`/`_nvenc_args()`-Builder.

Der Builder verwendete die älteren Aliasnamen `-spatial_aq` und `-temporal_aq`. Ältere FFmpeg-Stände akzeptierten diese zusätzlich, aktuelle FFmpeg/NVENC-Stände verwenden die kanonischen Optionen `-spatial-aq` und `-temporal-aq`. Dadurch konnte **jede** NVENC-Konvertierung mit aktivem AQ an der FFmpeg-Argumentprüfung scheitern – unabhängig davon, ob NVENC global, per Profil oder per manuellem Datei-Override gewählt wurde.

### NVENC

- `-spatial_aq` → `-spatial-aq`
- `-temporal_aq` → `-temporal-aq`
- `aq-strength` wird vor FFmpeg sicher auf 1–15 normalisiert.
- CQ wird codecgerecht begrenzt: H.264/H.265 auf 0–51, AV1 auf 0–63.
- `b_ref_mode` wird nur noch mit gültigen Werten `disabled`, `each` oder `middle` ausgegeben; ungültige/stale Konfigurationswerte gelangen nicht mehr ungeprüft in FFmpeg.
- Die Korrektur sitzt bewusst im zentralen Encoder-Builder und gilt damit automatisch für Standard, Dolby Vision, HDR10+, Quality-Test und Datei-Overrides.

### Intel QSV – zusätzlicher Kompatibilitätsfehler gefunden und behoben

Bei der Kontrolle des Intel-Pfads fiel ein unabhängiger Fehler auf:

- DragonTools setzte bisher gleichzeitig `-q` und `-look_ahead 1`.
- `-q` aktiviert in FFmpeg den generischen QSCALE/CQP-Pfad; zusammen mit QSV-Lookahead kann FFmpeg damit zwei konkurrierende Rate-Control-Modi erkennen und den Encode ablehnen.
- QSV verwendet jetzt den dokumentierten Qualitätsparameter `-global_quality`.
- `h264_qsv` behält den dort gültigen klassischen `-look_ahead 1` + `-look_ahead_depth`-Pfad (LA_ICQ).
- `hevc_qsv` und `av1_qsv` erhalten **kein** H.264-spezifisches `-look_ahead`; dort werden die dokumentierten Optionen `-extbrc 1` + `-look_ahead_depth` verwendet.
- QSV-Qualität wird auf den gültigen Bereich 1–51 begrenzt.

### AMD AMF – HEVC-Optionsfehler gefunden und behoben

Auch beim AMD-Pfad gab es einen codecabhängigen Optionsfehler:

- `hevc_amf` bietet aktuell `qp_i` und `qp_p`, aber kein `qp_b`.
- DragonTools setzte bisher bei H.264 **und HEVC** `-qp_b`; ein aktuelles FFmpeg konnte HEVC-AMF daher bereits bei der Optionsauswertung ablehnen.
- `-qp_b` wird jetzt nur für `h264_amf` und `av1_amf` gesetzt, wo die Option vorhanden ist.
- AMF-QP wird für H.264/H.265 auf 0–51 und für AV1 auf den dort gültigen größeren Bereich begrenzt.

### Tests / Verifikation

- Regressionstests prüfen die kanonischen NVENC-AQ-Namen für H.264, H.265 und AV1 und verbieten die alten Unterstrich-Aliase.
- Tests prüfen die codecabhängige QSV-Lookahead-Ausgabe und verhindern die frühere `-q`/`-look_ahead`-Kombination.
- Tests prüfen, dass HEVC-AMF kein `-qp_b` mehr erhält, H.264/AV1-AMF dagegen weiterhin schon.
- Argumentgrenzen für NVENC/QSV/AMF werden am zentralen Builder abgesichert.
- Die aktuellen FFmpeg-Optionsdefinitionen wurden zusätzlich gegen die offiziellen FFmpeg-Encoderdefinitionen für NVENC, QSV und AMF geprüft.
- Zusätzlich prüft ein Override-Regressionstest explizit, dass **globales NVENC, NVENC-Profil und manueller Datei-Override** alle denselben korrigierten zentralen Builder verwenden.
- Ein DV-spezifischer Regressionstest prüft den tatsächlichen `dv_video_encode_args()`-Pfad mit aktivem Spatial/Temporal AQ.
- Vollständige lokale Testsuite: **1.661 bestanden, 24 übersprungen, 0 fehlgeschlagen**. Die übersprungenen Tests benötigen PyQt6/pytest-qt, Windows-DPAPI oder die reale DV/HDR-Toolchain.
- Statische Prüfung: **948 Python-Dateien**, 0 AST-Fehler, 0 JSON-Fehler; Bytecode-Kompilierung erfolgreich.
- Release-Validator auf bereinigtem Source-Baum: **27 OK, 4 bekannte Warnungen, 0 Fehler**.
- Intel/AMD wurden auf Argument-/FFmpeg-Optionskompatibilität geprüft. Ein echter Hardware-Encode mit Intel-QSV bzw. AMD-AMF ist auf dem lokalen Review-Host nicht verfügbar und wird daher nicht als Hardware-Laufzeitnachweis behauptet.

## Patch AG – Externer Dragon-HDR10+-Generator und DaVinci-Resolve-Free-Backend-Vorbereitung – 21.09.2026

**Bereich:** HDR10+ / Dolby Vision 8.1 / HDR10-PQ / externe Tools / Settings / Workflow-Pipeline / DaVinci Resolve / Release-Validierung / Tests

### Ziel und Architektur

Dieser Patch bereitet zwei bewusst getrennte Erweiterungen vor, ohne die bestehende HDR10+-Injection, DV-RPU-Verarbeitung oder den FFmpeg-SDR→HDR-Pfad neu zu erfinden:

1. **Dragon HDR10+ Generator** als eigenständiges externes Werkzeug/Unterprojekt.
2. **DaVinci Resolve Free** als optional erkannter und auswählbarer, aber noch nicht automatisiert ausführbarer SDR→HDR10/PQ-Backend-Platzhalter.

Die vorhandenen DragonTools-Dienste für `hdr10plus_tool`, Dolby Vision, Muxing und Endvalidierung bleiben die maßgeblichen Implementierungen. Der externe Generator ist ausschließlich für die Analyse des finalen PQ-Videostreams und die spätere Erzeugung einer `hdr10plus.json` zuständig.

Zielreihenfolge:

```text
Decode / Skalierung / Burn-in / Encode
→ finaler Videostream
→ Dragon HDR10+ Generator
→ hdr10plus.json
→ bestehender hdr10plus_tool-Injection-Pfad
→ bei DV 8.x anschließend bestehende DV-RPU-Injection
→ Mux
→ bestehende HDR10+/DV-Endvalidierung
```

Nach der HDR10+-Analyse gibt es im neuen Pfad keine bildverändernde Verarbeitung mehr. Damit bleiben Framefolge und dynamische Metadaten synchron.

### Neue DragonTools-Schnittstelle für den externen HDR10+-Generator

Neu: `dragontools/worker/hdr10plus_generator_client.py`

Stabiler CLI-Vertrag:

```text
HDRPlusGenerator.exe --version
HDRPlusGenerator.exe analyze --input <Videodatei> --output <hdr10plus.json>
```

- Aufruf erfolgt als Argumentliste ohne Shell-String; Windows-Pfade mit Leerzeichen und Umlauten bleiben dadurch unverändert erhalten.
- stdout wird ausschließlich als maschinenlesbares JSON interpretiert; frei formulierte Logtexte werden nicht geparst.
- Unterstützt strukturierte Erfolgs-/Fehlerantworten, Exitcodes, Timeout und kooperativen Abbruch.
- Fehlerfälle wie fehlendes Tool, ungültige JSON-Antwort, fehlender/ungültiger Output oder Abbruch laufen fail-closed.
- Stale/teilweise erzeugte Outputdateien werden bei fehlgeschlagenen Generatorläufen entfernt.
- Der Client führt **keine** HDR10+-Injection, keinen Remux und keinen Videoersatz durch.

Beispiel Erfolg:

```json
{
  "success": true,
  "version": "1.0.0",
  "input": "...",
  "output": "...",
  "frames": 143812,
  "scenes": 1247,
  "transfer": "smpte2084"
}
```

Beispiel Fehler:

```json
{
  "success": false,
  "error": "SOURCE_NOT_PQ",
  "message": "Quelle verwendet keine PQ/ST2084-Transferfunktion."
}
```

### HDR10+-Eligibility: PQ/ST2084 statt generischem `is_hdr`

Neu: `dragontools/core/hdr10plus_generation.py`

Die automatische Generierung wird nicht über einen allgemeinen HDR-Boolean entschieden, sondern explizit über Transferfunktion/Quellmerkmale:

- **SDR:** keine automatische HDR10+-Erzeugung.
- **HLG:** zunächst keine automatische HDR10+-Erzeugung.
- **PQ/ST2084 + HEVC/H.265 + kein HDR10+:** für die Generatorpipeline geeignet.
- **HDR10+ bereits vorhanden:** standardmäßig unverändert übernehmen, keine Regeneration.
- **DV Profil 8.x + PQ-Base + kein HDR10+:** Generatoranalyse ist erlaubt; der DV-Pfad bleibt erhalten.
- **DV Profil 8.x + vorhandenes HDR10+:** vorhandene Metadaten werden übernommen.
- **Nicht unterstützte DV-Profile / Fälle, bei denen DV nicht erhalten werden könnte:** automatische Generierung wird blockiert.

Zusätzlicher Preservation-Guard verhindert, dass ein explizit erzwungener reiner HDR10+-Pfad bei einer DV-Quelle die RPU entfernt. Ein explizites `STANDARD`-Override trägt außerdem keinen versehentlichen Generatorauftrag in den Medienvertrag weiter.

### Integration in bestehende HDR10+- und DV-Pipelines

Angepasst wurden insbesondere:

- `dragontools/worker/hdrplus_pipeline_coordinator.py`
- `dragontools/worker/hdrplus_conversion.py`
- `dragontools/worker/hdrplus_helper_services.py`
- `dragontools/worker/hdrplus_runtime_models.py`
- `dragontools/worker/dv_dynamic_metadata_service.py`
- `dragontools/worker/dv_processing_pipeline.py`
- `dragontools/worker/dv_pipeline_*`
- `dragontools/worker/dv_workflow_pipeline_adapter.py`
- `dragontools/worker/dv_final_metadata_verifier.py`

Der neue Generate-Modus liefert die JSON-Datei an den **bestehenden** HDR10+-Bitstream-/Injection-Service. Bei DV 8.x wird anschließend die bestehende DV-RPU-Verarbeitung ausgeführt. Bestehende Extraktions-/Preserve-Pfade für bereits vorhandenes HDR10+ bleiben unverändert.

### Workflow-/Medienvertrag und Pipeline-Auswahl

Angepasst wurden:

- `dragontools/rules/pipeline_selector.py`
- `dragontools/rules/pipeline_capabilities.py`
- `dragontools/worker/media_contract.py`
- `dragontools/worker/media_contract_builder.py`
- `dragontools/worker/pipeline_decision_service.py`
- `dragontools/worker/workflow_models.py`
- `dragontools/worker/workflow_planning_service.py`
- `dragontools/worker/workflow_engine.py`

Der Generatorauftrag wird explizit im Workflowvertrag geführt. Normale PQ/HDR10-Quellen ohne HDR10+ können bei aktivierter Funktion in die HDR10+-Pipeline wechseln. DV 8.x bleibt dagegen in der DV-Pipeline, damit das RPU erhalten bleibt.

Während der Regressionstests wurden Architekturgrenzen nachgezogen: Der Pipeline-Selector bleibt innerhalb der bestehenden Modul-/Funktionsgrößenbudgets; optionale Runtime-Erkennung wurde aus dem Converter-Runtime-Builder in ein separates Modul ausgelagert.

### Zentrale Tool-Erkennung und Einstellungen

Neue optionale Tool-IDs:

- `hdr10plus_generator`
- `davinci_resolve`

Angepasst:

- `dragontools/core/tool_paths.py`
- `dragontools/core/tool_diagnostics.py`
- `dragontools/core/diagnostic_package.py`
- `dragontools/gui/tool_path_live_check.py`
- `dragontools/gui/main_window_system_actions.py`
- `dragontools/gui/settings_dialog.py`
- `dragontools/gui/settings_sections/runtime.py`
- `dragontools/gui/settings_sections/video.py`
- `dragontools/gui/encoder_settings_options.py`
- `dragontools/core/settings_conversion.py`
- `dragontools/core/settings_storage.py`

Der Generator besitzt einen eigenen Pfad und Aktivierungsschalter. Fehlt das optionale Werkzeug oder ist es deaktiviert, bleiben die bestehenden Konvertierungswege unverändert verfügbar.

Resolve wird über einen konfigurierten Pfad, PATH und unter Windows zusätzlich über den üblichen Blackmagic-Installationspfad gesucht. Die Diagnose startet Resolve **nicht** nur zur Versionsabfrage.

### Optionale Runtime-Erkennung

Neu: `dragontools/worker/converter_optional_runtime.py`

Das Modul kapselt die Erkennung von:

- FFmpeg/libplacebo,
- DaVinci Resolve,
- Dragon HDR10+ Generator inklusive `--version`-Probe.

Dadurch bleibt `converter_runtime_builder.py` klein und bestehende Runtime-/Encoder-Erkennung wird nicht mit optionalen Backends vermischt.

### DaVinci Resolve Free – bewusst nur vorbereitet

`dragontools/core/sdr_hdr_enhancement.py` kennt weiterhin den vollständig funktionsfähigen Backendwert `ffmpeg`. Zusätzlich ist `davinci_free` als vorbereiteter Backendwert verfügbar.

Aktueller Status:

- **Implementiert:** Settings, Pfad-/Verfügbarkeitserkennung, Diagnose, Backend-Auswahl und saubere Isolation zum FFmpeg-Pfad.
- **Vorbereitet:** späterer SDR→HDR10/PQ-Workflow über Resolve Free.
- **Nicht implementiert:** automatischer Resolve-Free-Renderauftrag.
- **Bewusst nicht verwendet:** Dolby-Vision-/HDR10+-Studiofunktionen sowie Remote-/Developer-Scripting, das nicht als Free-Funktion vorausgesetzt werden darf.

Wird `davinci_free` gewählt, meldet DragonTools deshalb kontrolliert, dass die automatische Free-Integration vorbereitet, aber nicht ausführbar ist. Es wird **kein** scheinbar erfolgreicher Fake-Render gestartet und kein bestehender FFmpeg-Pfad verändert.

### Eigenständiges Unterprojekt `dragon_hdr10plus_generator`

Neu angelegt:

```text
dragon_hdr10plus_generator/
├── pyproject.toml
├── README.md
├── src/dragon_hdr10plus_generator/
│   ├── analyzer/
│   │   ├── decoder.py
│   │   ├── luminance.py
│   │   ├── scene_detection.py
│   │   └── statistics.py
│   ├── metadata/
│   │   ├── st2094_40.py
│   │   ├── tone_mapping.py
│   │   └── json_writer.py
│   ├── cli.py
│   └── config.py
└── tests/
```

Bereits vorhanden:

- FFprobe-basierte Quellprüfung,
- korrekte ST2084/PQ-EOTF-/OETF-Grundfunktionen,
- robuste Statistik-/Perzentilgrundlagen,
- Histogramm-/Szenengrenzen-Grundlagen,
- atomarer JSON-Writer,
- strukturierte CLI-Ausgabe,
- CPU-fähige modulare Architektur.

**Bewusst noch nicht implementiert:** vollständiges Frame-Decoding/Batching der PQ-Bildebene, finale MaxSCL-/AverageRGB-/AverageMaxRGB-Szenenaggregation, robuste Highlight-/Untertitel-Ausreißerbehandlung, Knee-Point-/Bezier-Tone-Mapping und ein validierter ST-2094-40-Metadatenwriter.

`metadata/st2094_40.py` und `metadata/tone_mapping.py` sind absichtlich fail-closed. Bei einer ansonsten gültigen PQ-Quelle gibt das Generator-Unterprojekt derzeit `METADATA_GENERATION_NOT_IMPLEMENTED` zurück, statt erfundene oder formal unvalidierte HDR10+-Werte zu erzeugen.

### Source-Packaging / PyInstaller-Trennung

- `DragonTools_Source_ZIP.bat` nimmt `dragon_hdr10plus_generator` in das Source-Paket auf.
- Der explizite Required-File-Vertrag des vorhandenen Source-Packagers bleibt erhalten.
- Das Generator-Unterprojekt wird **nicht** automatisch in den DragonTools-PyInstaller-Build eingebettet; es bleibt ein eigenständiges externes Werkzeug.
- `dragontools/core/release_validation_source.py` und `release_validation_smoke_modules.py` prüfen die neuen verpflichtenden Source-/Runtime-Bestandteile.

### Geänderte/neue Module

**Neue DragonTools-Dateien:**

- `dragontools/core/hdr10plus_generation.py`
- `dragontools/worker/hdr10plus_generator_client.py`
- `dragontools/worker/converter_optional_runtime.py`
- `dragontools/tests/test_patch_ag_external_hdr10plus_generator.py`

**Neues eigenständiges Unterprojekt:** 16 Dateien unter `dragon_hdr10plus_generator/`.

**Geänderte bestehende Dateien:** 36 Produktiv-/Build-Dateien vor dieser `PATCH.md`-Ergänzung, darunter die oben genannten Settings-, Tool-, Pipeline-, HDR10+- und DV-Module. Es wurden keine bestehenden Dateien entfernt.

### Tests und Verifikation

Neu/erweitert geprüft werden insbesondere:

- Generator aktiviert/deaktiviert,
- Generatorpfad vorhanden/nicht vorhanden,
- `--version`-Erkennung,
- korrekter CLI-Aufruf als Argumentliste,
- Pfade mit Leerzeichen und Umlauten,
- strukturierte Erfolgs-/Fehler-JSON-Antworten,
- Exitcodes, Timeout und Abbruch,
- temporärer/staler Output-Cleanup,
- SDR wird nicht automatisch analysiert,
- HLG wird nicht automatisch analysiert,
- PQ/HDR10 ohne HDR10+ wird akzeptiert,
- vorhandenes HDR10+ wird standardmäßig nicht neu erzeugt,
- DV 8.x + PQ kann analysiert werden, ohne DV zu entfernen,
- HDR10+-Analyse erfolgt erst nach dem finalen Encode,
- keine Bildverarbeitung nach Metadatenerzeugung,
- vorhandene HDR10+-/DV-Kombinationspipeline bleibt kompatibel,
- DaVinci-Einstellungen verändern den FFmpeg-Pfad nicht,
- fehlendes Resolve oder fehlender Generator beeinträchtigen DragonTools nicht,
- Tool-/Settings-/Source-Packaging-/Architekturverträge bleiben erhalten.

**Tatsächlich ausgeführt auf dem Review-Host:**

- Vollständiger DragonTools-Testbestand in drei deterministischen Chunks: **1.680 bestanden, 24 übersprungen, 0 fehlgeschlagen**.
- Die 24 Skips sind erwartete Umgebungsfälle für PyQt6/pytest-qt, Windows-DPAPI bzw. reale DV/HDR-Integrationstools/Hardware.
- Ein zusätzlicher gezielter Abschlusslauf der direkt betroffenen Release-/HDR10+/DV-/Settings-/Tool-Tests: **81 bestanden, 0 fehlgeschlagen**.
- Eigenständiges Generator-Unterprojekt: **5 bestanden, 0 fehlgeschlagen**; eine harmlose Pytest-Konfigurationswarnung entsteht durch den im Parent-Projekt gesetzten `qt_api`-Eintrag bei fehlendem pytest-qt auf dem Linux-Review-Host.
- AST: **966 Python-Dateien**, 0 Fehler.
- JSON: **7 Dateien**, 0 Fehler.
- `compileall`: erfolgreich.
- Direkte Import-Smokes der neuen HDR10+-/Runtime-/DV-Module und des Generatorpakets: erfolgreich.
- `ruff` ist auf dem Review-Host nicht installiert; deshalb wurde lokal kein separater Ruff-F821-Lauf behauptet. Die umfangreiche pytest-/Import-/AST-/compileall-Prüfung lief dagegen tatsächlich.
- Release-Validator auf bereinigtem Source-Baum: **29 OK, 4 bekannte Warnungen, 0 Fehler**. Warnungen: kein lokaler `dist`-Build vorhanden sowie drei bereits vorhandene Datenschutz-Hinweise auf den Namen „Dragon Developer“ in Dokumentations-/Legacy-Dateien.

Ein einzelner monolithischer `pytest -q`-Aufruf wird in dieser Ausführungsumgebung bei ca. 80 % durch das externe Tool-Zeitlimit beendet. Deshalb wurde die vollständige Testsuite deterministisch in drei Chunks ausgeführt; zusammen decken sie sämtliche Testdateien ab.

### Nicht als real getestet behauptet

Mangels entsprechender lokaler Hardware/Programme wurden **nicht** als reale End-to-End-Läufe behauptet:

- DaVinci Resolve Free,
- NVIDIA NVENC / Intel QSV / AMD AMF Hardware-Encode für diesen Patch,
- echte DV-/HDR10+-Toolchain mit `dovi_tool`, `hdr10plus_tool` und MP4Box,
- Windows-PyInstaller-EXE-Build,
- produktive HDR10+-Generierung, da der ST-2094-40-Writer absichtlich noch nicht implementiert ist.

### Versionsstand

DragonTools bleibt **9.8.5**. Dieser Patch ändert die Anwendungsversionsnummer nicht.

---

## Patch AH – ComfyUI-SDR→HDR-Backend-Grundlage und Generator-Abnahme – 21.09.2026

**Bereich:** SDR→HDR / ComfyUI / externe Werkzeuge / lokale API / Workflow-Vertrag / HDR10+-Generator / Release-Validierung / Regressionstests

### Ziel

Patch AH bereitet ComfyUI als drittes, vollständig optionales SDR→HDR-Backend vor, ohne ein bestimmtes Modell, Custom-Node-Paket oder einen nicht validierten HDR-Workflow fest in DragonTools einzubauen. Der bestehende FFmpeg/libplacebo-Pfad bleibt vollständig funktionsfähig; DaVinci Resolve Free bleibt unverändert als vorbereiteter, nicht automatisch gesteuerter Backend-Platzhalter erhalten.

Die vorgesehene spätere Kette ist klar getrennt:

```text
SDR BT.709
→ ComfyUI + ausgewähltes/validiertes SDR→HDR-Modell
→ finaler HDR10/PQ-Bildstrom
→ Dragon HDR10+ Generator
→ objektive Analyse des finalen PQ-Bildstroms
→ ST-2094-40 / hdr10plus.json
→ hdr10plus_tool
→ Injection / Remux / Validierung
```

ComfyUI darf später Bildinformation rekonstruieren. Der HDR10+-Generator bleibt davon unabhängig und darf dynamische Metadaten nicht aus AI-Schätzungen übernehmen, sondern muss den tatsächlich erzeugten finalen PQ-Stream messen.

### Neue ComfyUI-Tool-/Settings-Schnittstelle

ComfyUI ist als eigener optionaler Werkzeugschlüssel `comfyui` in der zentralen Tool-Verwaltung vorhanden. Der Benutzer kann den Installationsordner unter **Einstellungen → Werkzeuge** eintragen. Als Installationsmarker werden derzeit `ComfyUI.exe`, `comfyui.exe` oder `main.py` akzeptiert. Diese Pfadangabe startet ComfyUI nicht automatisch; sie dient Installationserkennung und Diagnose.

Neue SDR→HDR-Einstellungen:

- Backendwert `comfyui` zusätzlich zu `ffmpeg` und `davinci_free`,
- lokale API-Adresse, Standard `http://127.0.0.1:8188`,
- optionaler Pfad zu einem später exportierten ComfyUI-Workflow im **API-JSON-Format**.

Solange kein konkretes SDR→HDR-Modell validiert und dessen I/O-Vertrag festgelegt wurde, liefert die Pipelineentscheidung für `comfyui` bewusst `applied=False`. Der normale SDR-Encode wird dadurch nicht ersetzt und bestehende FFmpeg-/DV-/HDR10+-Pfade werden nicht beeinflusst.

### Modellneutraler ComfyUI-API-Client

Neu: `dragontools/worker/comfyui_client.py`

Der Qt-freie Client kapselt ausschließlich den lokalen HTTP-Vertrag und besitzt keine Modellkenntnis:

- `GET /system_stats` – Health-/Versions-/GPU-/VRAM-Erkennung,
- `POST /prompt` – API-Workflow einreihen,
- `GET /history/{prompt_id}` – Ergebnis-/Historienabfrage,
- `POST /api/jobs/{prompt_id}/cancel` – **gezielter** Abbruch genau des eigenen Jobs.

Der neue Job-spezifische Cancel-Pfad wird bewusst gegenüber einem globalen `/interrupt` bevorzugt. Damit kann ein DragonTools-Auftrag nicht versehentlich einen anderen parallel laufenden ComfyUI-Auftrag abbrechen. Ältere ComfyUI-Versionen ohne diesen Job-spezifischen Vertrag werden nicht durch einen unsicheren globalen Fallback kaschiert.

API-Fehler, nicht erreichbare Dienste und ungültige Antworten bleiben fail-closed. ComfyUI ist keine Pflichtabhängigkeit.

### Workflow-Vertrag ohne Modell-Festverdrahtung

Neu: `dragontools/core/comfyui_workflow.py`

Das Modul:

- lädt Workflow-Dateien als UTF-8-JSON,
- akzeptiert ausschließlich nichtleere ComfyUI-API-Workflows mit String-Node-IDs, `class_type` und Objekt-`inputs`,
- validiert den Workflow vor einer späteren Ausführung,
- unterstützt modellneutrale Platzhalter für die spätere Integration:
  - `{{INPUT_VIDEO}}`
  - `{{OUTPUT_DIR}}`
  - `{{OUTPUT_PREFIX}}`
  - `{{PEAK_NITS}}`
- ersetzt numerische Platzhalter typstabil, wenn der komplette JSON-Wert nur aus dem Token besteht.

Noch nicht festgelegt sind konkrete Video-Load-/Save-Nodes, Custom-Node-Namen, Modellnamen, Checkpoints oder Tiling-/Temporal-Parameter. Diese Details werden erst nach Auswahl und Validierung des tatsächlichen SDR→HDR-Modells ergänzt.

### Runtime-Erkennung und Isolation

Angepasst: `dragontools/worker/converter_optional_runtime.py` und `dragontools/core/sdr_hdr_enhancement.py`.

Nur wenn SDR→HDR aktiviert **und** Backend `comfyui` gewählt ist, versucht DragonTools die lokale API mit kurzem Timeout zu prüfen. Gespeichert werden interne Runtime-Capabilities für:

- Installationsmarker vorhanden/nicht vorhanden,
- API erreichbar/nicht erreichbar,
- ComfyUI-Version,
- primäres Torch-/GPU-Gerät,
- gemeldeter VRAM,
- Workflow vorhanden/valide bzw. Fehlertext.

Eine laufende API kann auch dann erkannt werden, wenn ComfyUI außerhalb des eingetragenen Installationspfads gestartet wurde. Ein vorhandener Installationsordner allein gilt umgekehrt nicht als Beweis für einen laufenden Dienst.

### Zentral verwaltete Werkzeuge / GUI / Diagnose

Geändert wurden:

- `dragontools/core/settings_storage.py`
- `dragontools/core/settings_conversion.py`
- `dragontools/core/tool_paths.py`
- `dragontools/core/tool_diagnostics.py`
- `dragontools/core/diagnostic_package.py`
- `dragontools/core/project_info.py`
- `dragontools/gui/settings_sections/runtime.py`
- `dragontools/gui/settings_sections/video.py`
- `dragontools/gui/encoder_settings_options.py`
- `dragontools/gui/tool_path_live_check.py`
- `dragontools/gui/main_window_system_actions.py`

ComfyUI erscheint dadurch als eigener optionaler Werkzeugeintrag. Die Videoeinstellungen enthalten Backend, API-Adresse und Workflow-Pfad. Die bestehenden Architekturgrenzen der Settings-Module bleiben eingehalten; während der Abschlussprüfung wurden `runtime.py` und `encoder_settings_options.py` wieder unter ihre bestehenden Größenbudgets gebracht.

### HDR10+-Generator – aktueller Funktionsstatus geprüft

Das separate Projekt bleibt auf Version `0.1.0`; DragonTools selbst bleibt Version **9.8.5**.

Zusätzlich zu den Unit-Tests wurde auf dem Review-Host ein realer CLI-Smoke mit installiertem FFmpeg/FFprobe ausgeführt:

1. `HDRPlusGenerator --version` liefert weiterhin exakt eine strukturierte JSON-Antwort mit `success=true` und Version `0.1.0`.
2. Eine synthetische HEVC-10-Bit-Testdatei wurde mit BT.2020 + SMPTE2084/PQ-Tags erzeugt.
3. FFprobe erkennt `yuv420p10le`, `bt2020`, `bt2020nc` und `smpte2084`.
4. `analyze` erkennt die PQ-Quelle korrekt und erreicht den vorgesehenen Metadaten-Generierungsschritt.
5. Der Generator beendet den Lauf weiterhin bewusst mit `METADATA_GENERATION_NOT_IMPLEMENTED` und erzeugt **keine** `hdr10plus.json`.

Das bedeutet: CLI, Pfadbehandlung, FFprobe-Vertrag und PQ-Gate funktionieren real. Ein produktiver ST-2094-40-Writer ist **noch nicht implementiert**. Dieser Zustand ist beabsichtigt und verhindert ungültige/fingierte HDR10+-Metadaten.

Erweiterter Test: `dragon_hdr10plus_generator/tests/test_foundation.py` prüft jetzt zusätzlich, dass eine valide PQ-Probe mit Umlautpfad den Metadatenzustand erreicht und fail-closed ohne Output endet.

### Release-/Source-Vertrag

Geändert:

- `dragontools/core/release_validation_source.py`
- `dragontools/core/release_validation_smoke_modules.py`
- `DragonTools_Source_ZIP.bat`
- `README.md`
- `help.html`

Der Release-Validator verlangt jetzt auch den ComfyUI-API-Client und den Workflow-Vertrag. Die Release-Smoke-Liste enthält die neuen Module. Zusätzlich wurde ein bereits im Patch-AG-Text sichtbarer Altbefund korrigiert: mehrere dort dokumentierte HDR10+/DV-Produktivmodule fehlten trotz Dokumentation noch im Smoke-Vertrag; sie sind jetzt ebenfalls abgedeckt.

### Neue Tests

Neu: `dragontools/tests/test_patch_ah_comfyui_backend.py`

Automatisiert geprüft werden:

- Normalisierung lokaler ComfyUI-URLs,
- `/system_stats` inklusive Version, RTX-Gerätename und 16-GB-VRAM-Wert,
- korrekter `/prompt`-Aufruf,
- Pfade mit Leerzeichen/Umlauten innerhalb des Workflow-JSON,
- gezielter Job-Abbruch über `/api/jobs/{id}/cancel`,
- keine Verwendung eines globalen Interrupts,
- nicht erreichbarer Dienst bleibt fail-closed,
- API-Workflow-Laden und -Validierung,
- modellneutrale Platzhalter einschließlich numerischem `PEAK_NITS`,
- ungültige Workflows werden vor Ausführung abgewiesen,
- ComfyUI beeinflusst den FFmpeg-SDR→HDR-Pfad nicht,
- ComfyUI bleibt ohne ausgewähltes Modell/Workflow nur vorbereitet,
- externer Werkzeugpfad akzeptiert eine portable `main.py`-Installation.

### Tatsächlich ausgeführte Prüfung nach Patch AH

DragonTools-Testbestand vollständig, deterministisch in Teilgruppen ausgeführt:

- **1.689 bestanden**
- **24 übersprungen**
- **0 fehlgeschlagen**

Die 24 Skips sind ausschließlich erwartete Umgebungsfälle: fehlendes PyQt6/pytest-qt auf dem Linux-Review-Host, Windows-DPAPI sowie nicht konfigurierte reale DV/HDR-Integration mit `dovi_tool`, `hdr10plus_tool` und MP4Box.

Zusätzlich:

- neue/gezielte ComfyUI + Patch-AG Regressionstests: erfolgreich,
- eigenständiges Generator-Unterprojekt: **6 bestanden, 0 fehlgeschlagen**,
- AST: **969 Python-Dateien**, 0 Fehler,
- JSON: **7 Dateien**, 0 Fehler,
- `compileall`: erfolgreich.

### Neue/geänderte Dateien gegenüber dem abgeschlossenen Patch-AG-Paket

**Neu:**

- `dragontools/core/comfyui_workflow.py`
- `dragontools/worker/comfyui_client.py`
- `dragontools/tests/test_patch_ah_comfyui_backend.py`

**Geändert:**

- `dragontools/core/settings_storage.py`
- `dragontools/core/settings_conversion.py`
- `dragontools/core/tool_paths.py`
- `dragontools/core/tool_diagnostics.py`
- `dragontools/core/diagnostic_package.py`
- `dragontools/core/project_info.py`
- `dragontools/core/release_validation_source.py`
- `dragontools/core/release_validation_smoke_modules.py`
- `dragontools/core/sdr_hdr_enhancement.py`
- `dragontools/worker/converter_optional_runtime.py`
- `dragontools/gui/settings_sections/runtime.py`
- `dragontools/gui/settings_sections/video.py`
- `dragontools/gui/encoder_settings_options.py`
- `dragontools/gui/tool_path_live_check.py`
- `dragontools/gui/main_window_system_actions.py`
- `dragon_hdr10plus_generator/tests/test_foundation.py`
- `DragonTools_Source_ZIP.bat`
- `README.md`
- `help.html`
- `PATCH.md`

### Bewusst noch offen

- Auswahl und Qualitätsvalidierung eines konkreten SDR→HDR-Modells für ComfyUI,
- Festlegung der benötigten Custom Nodes und deren Versions-/Lizenzvertrag,
- endgültige Video-I/O-Bindings des Workflow-JSON,
- WebSocket-Fortschrittsanzeige im DragonTools-GUI,
- automatische ComfyUI-Serverinitialisierung; aktuell wird ein bereits laufender lokaler Dienst erwartet,
- temporale Stabilitäts-/Flicker-Prüfung eines später gewählten AI-Modells,
- produktiver Frame-/Szenen-Analyzer des Dragon-HDR10+-Generators,
- validierter ST-2094-40-Knee-/Bezier-Metadatenwriter,
- reale GPU-/Windows-/PyInstaller-Abnahme dieses neuen Backends.

Es wird weiterhin weder ein SDR→HDR-AI-Modell noch ein Fake-HDR10+-Metadatenmodell ausgeliefert.

---

## Patch AH – Nachtrag: DaVinci Resolve als externes Startwerkzeug

Der bereits vorbereitete optionale DaVinci-Resolve-Free-Pfad wurde um den fehlenden manuellen Launcher ergänzt. DragonTools automatisiert Resolve Free weiterhin **nicht**; der Nutzer kann Resolve jedoch wie HandBrake direkt aus DragonTools öffnen und eine dort manuell erzeugte HDR10/PQ-Datei anschließend wieder dem normalen DragonTools-Konverter bzw. dem späteren HDR10+-Generator zuführen.

### Geändert

- `dragontools/gui/main_window_menus.py`
  - `🎨 DaVinci Resolve öffnen` unter **Werkzeuge** ergänzt.
  - denselben externen Startpunkt unter **Ansicht → Externe Programme** ergänzt.
- `dragontools/gui/main_window_system_actions.py`
  - `Resolve.exe` dem zentralen externen Launcher als `davinci_resolve` zugeordnet.
  - nutzt zusätzlich die bereits vorhandene zentrale `ToolPaths.davinci_resolve`-Auflösung; dadurch wird eine Standardinstallation unter Blackmagics üblichem Windows-Installationspfad auch ohne manuell gesetzten Werkzeugpfad gefunden.
- `dragontools/gui/tab_manager.py`
  - DaVinci Resolve im Bereich **Externe Programme öffnen** ergänzt.
  - dieselbe zentrale `davinci_resolve`-Auflösung für den Start verwendet.
  - optionales Bundle-Unterverzeichnis `Daten/Programme/davinci_resolve` als Fallback ergänzt.
- `dragontools/core/release_validation_package.py`
  - `gui/tab_manager.py` in den zentralen Release-Smoke-Vertrag aufgenommen, weil der Launcher nun produktiv geändert wird.
- `dragontools/tests/test_patch_ai_davinci_launcher.py`
  - Regressionstests für Menüeinträge, Tool-Key-Mapping, zentrale Resolve-Auflösung und Tab-Manager-Integration ergänzt.

### Verhalten

- Resolve bleibt ein **externes/manuelles Werkzeug**.
- keine Studio-only Remote-Scripting-/Developer-API wird vorausgesetzt.
- fehlendes Resolve beeinflusst DragonTools, FFmpeg oder ComfyUI nicht.
- ComfyUI bleibt das vorbereitete automatisierbare SDR→HDR-Backend.
- der Dragon-HDR10+-Generator bleibt davon unabhängig und analysiert später den finalen PQ-Stream.

### Abschlussprüfung dieses Nachtrags

- vollständiger DragonTools-Testbestand: **1.692 bestanden, 24 übersprungen, 0 fehlgeschlagen**
- Dragon-HDR10+-Generator-Unterprojekt: **6 bestanden, 0 fehlgeschlagen**
- die Skips bleiben dieselben erwarteten Umgebungsfälle (PyQt6/pytest-qt, Windows-DPAPI, reale DV/HDR-Toolchain).

---

## Patch AI – konkretes ComfyUI-HDR-Modellprofil für RTX 4080 16 GB

Der zuvor absichtlich modellneutrale ComfyUI-Unterbau wurde auf einen ersten konkreten, weiterhin optionalen SDR→HDR-Modellvertrag vorbereitet. Die Versionsnummer bleibt **9.8.5**.

### Empfohlenes erstes Modell: HDRTVDM / LSN

Für die erste produktnahe Integration wird **AndreGuo/HDRTVDM** vorbereitet:

- Repository: `https://github.com/AndreGuo/HDRTVDM`
- Modellarchitektur: Luminance Segmented Network / `TriSegNet`
- empfohlener Checkpoint: `method/params_3DM.pth`
- Fallback: `method/params.pth`
- erwartete Ausgabe: PQ/ST2084 + BT.2020 Code Values
- Third-Party-Code/Weights werden **nicht** in DragonTools eingebettet.

`params_3DM.pth` wird als DragonTools-Defaultprofil gewählt, weil der Checkpoint laut offiziellem Projekt auf mehreren Degradationsmodellen trainiert wurde und damit für gemischte reale SDR-Medienquellen der robustere Startpunkt ist.

LumaFlux bleibt ein späterer Kandidat, wird auf der RTX 4080 16 GB aber nicht als Standardprofil gewählt: das LumaFlux-Projekt nennt für die Standardinferenz ungefähr 27 GB GPU-Speicher pro 1080p-Frame. DragonTools behauptet deshalb keine problemlose 16-GB-LumaFlux-Ausführung.

### Neue Modell-/Readiness-Architektur

Neu: `dragontools/core/comfyui_hdr_models.py`

- zentraler ComfyUI-HDR-Modellprofilvertrag,
- Profil `hdrtvdm_lsn_3dm`,
- Repository-/Checkpoint-Auflösung,
- `params_3DM.pth` vor `params.pth`,
- Pfade mit Leerzeichen/Umlauten,
- deklarierte erwartete Transferfunktion `smpte2084`,
- deklarierte Primärfarben `bt2020`,
- Liste der benötigten ComfyUI-Custom-Nodes,
- eingebautes chunk-basiertes HDRTVDM-API-Workflow-Template,
- benutzerdefiniertes Profil bleibt als Erweiterungspunkt erhalten.

Neu: `dragontools/worker/comfyui_runtime.py`

- ComfyUI-Service-Health,
- GPU-/VRAM-Erkennung,
- HDRTVDM-Repository-Check,
- Checkpoint-Check,
- `/object_info`-Prüfung auf benötigte Custom Nodes,
- Workflow-Validierung,
- `_comfyui_backend_ready` nur wenn alle Voraussetzungen erfüllt sind,
- fail-closed ohne Einfluss auf FFmpeg/Standard-Konverter.

`dragontools/worker/comfyui_client.py`:

- `/object_info` ergänzt, damit DragonTools installierte Node-Klassen maschinenlesbar prüfen kann.

### DragonTools-ComfyUI-Bridge

Neu unter:

`extras/comfyui/DragonTools_HDRTVDM/`

Enthalten sind ausschließlich DragonTools-Bridge-Nodes; das HDRTVDM-Projekt selbst und seine Gewichte werden nicht kopiert.

Nodes:

- `DragonHDRTVDMModelLoader`
  - importiert `method/network.py` aus dem vom Nutzer installierten offiziellen HDRTVDM-Repository,
  - lädt `TriSegNet`,
  - lädt den gewählten Checkpoint,
  - CUDA/CPU-Vertrag,
  - FP16 auf CUDA, FP32-Fallback.
- `DragonFrameSequenceLoader`
  - lädt nur einen konfigurierten Frame-Batch statt eines kompletten Films,
  - vorbereitet für eine spätere DragonTools-Chunk-Schleife.
- `DragonHDRTVDMConvert`
  - ComfyUI IMAGE (RGB Float) → HDRTVDM → PQ/BT.2020-Codewerte,
  - Padding auf die durch die Netzarchitektur benötigte Vierergrenze,
  - Crop zurück auf Originalabmessung,
  - Ausgabe bleibt Float bis zur HDR-Ausgabe.
- `DragonHDR16TiffWriter`
  - schreibt 16-Bit-RGB-TIFF,
  - verhindert, dass der spätere HDR-Pfad über ein normales 8-Bit-`SaveImage` reduziert wird.

Zusatzabhängigkeiten der externen ComfyUI-Bridge:

- `einops`
- `imageio`
- `tifffile`

Sie werden **nicht** DragonTools selbst aufgezwungen, sondern nur in der ComfyUI-Python-Umgebung installiert.

### Einstellungen erweitert

Unter SDR→HDR/ComfyUI gibt es jetzt zusätzlich:

- `AI-HDR-Modell`
  - `HDRTVDM LSN / params_3DM.pth (empfohlen)`
  - `Benutzerdefiniert / später`
- `HDRTVDM Repository`
- `HDRTVDM Checkpoint`
- weiterhin `ComfyUI API`
- weiterhin optionaler eigener `ComfyUI Workflow (API-JSON)`

Bei leerem HDRTVDM-Checkpoint sucht DragonTools:

1. `method/params_3DM.pth`
2. `method/params.pth`

Bei leerem Workflow-Pfad verwendet das HDRTVDM-Profil den eingebauten API-Workflow-Vertrag.

### Workflow-Vertrag erweitert

`dragontools/core/comfyui_workflow.py` unterstützt zusätzlich:

- `{{INPUT_DIR}}`
- `{{MODEL_ROOT}}`
- `{{CHECKPOINT}}`
- `{{START_INDEX}}`
- `{{BATCH_SIZE}}`

Damit kann der spätere Worker ein Video kontrolliert in Frame-Chunks zerlegen und jeden Chunk reproduzierbar über ComfyUI schicken, ohne einen kompletten Film gleichzeitig in RAM/VRAM zu laden.

### Noch bewusst nicht aktiviert

Die Modellinstallation kann jetzt vollständig geprüft werden, aber der automatische Produktionspfad bleibt weiterhin deaktiviert, bis der finale Worker implementiert ist:

`Video → Frames → ComfyUI-Batchschleife → 16-Bit-HDR-Frames → HEVC/AV1 10-Bit PQ/BT.2020 → Dragon HDR10+ Generator`.

Noch offen:

- reale RTX-4080-Messung von VRAM, Durchsatz und optimaler Batchgröße,
- FFmpeg-Frame-Extraktion/temporäre Frame-Verzeichnisse im produktiven Worker,
- WebSocket-Fortschritt für die Batchschleife,
- robustes Resume/Abbruch/Cleanup des vollständigen AI-HDR-Jobs,
- finaler 10-Bit-HDR-Encode aus der 16-Bit-TIFF-Sequenz,
- temporale Flicker-/Szenenkonsistenztests,
- Qualitätskalibrierung `params_3DM.pth` gegen `params.pth` und FFmpeg/libplacebo,
- anschließend objektive HDR10+-Analyse des finalen PQ-Videostreams.

### Neue Installationsanleitung

Neu: `COMFYUI_HDR_SETUP.md`

Sie nennt genau, was installiert werden muss, welche Ordner erwartet werden und welche DragonTools-Einstellungen zu setzen sind.

### Source-/Release-Vertrag

Geändert:

- `DragonTools_Source_ZIP.bat`
  - `extras/` wird ins Source-Paket aufgenommen,
  - `COMFYUI_HDR_SETUP.md` ist verpflichtender Source-Paket-Bestandteil.
- `dragontools/core/release_validation_source.py`
  - Modellprofil, Runtime-Readiness, Bridge-Nodes und Setup-Datei werden validiert.
- `dragontools/core/release_validation_smoke_modules.py`
  - `comfyui_hdr_models` und `comfyui_runtime` in Import-Smoke-Vertrag aufgenommen.

### Tests

`dragontools/tests/test_patch_ah_comfyui_backend.py` wurde erweitert um:

- HDRTVDM ist das empfohlene Modellprofil,
- `params_3DM.pth` ist der bevorzugte Checkpoint,
- Pfade mit Umlauten,
- Fallback-/Fehlerverhalten bei fehlendem Checkpoint,
- eingebauter chunk-basierter Workflow,
- numerische `START_INDEX`-/`BATCH_SIZE`-Platzhalter,
- 16-Bit-TIFF-Writer im Workflow,
- `/object_info`-Clientvertrag,
- Prüfung aller benötigten Node-Klassen,
- Bridge enthält keine `.pth`-Gewichte,
- fehlende Modellassets können niemals als angewendetes SDR→HDR durchfallen.

### Abschlussprüfung Patch AI

Vollständiger DragonTools-Testbestand nach allen Modell-/Bridge-Änderungen, deterministisch in vier Dateigruppen ausgeführt:

- **1.702 bestanden**
- **24 übersprungen**
- **0 fehlgeschlagen**

Die 24 Skips sind dieselben erwarteten Umgebungsfälle: fehlendes PyQt6/pytest-qt auf dem Linux-Review-Host, Windows-DPAPI sowie nicht konfigurierte reale DV/HDR-Integration mit `dovi_tool`, `hdr10plus_tool` und MP4Box.

Zusätzlich:

- eigenständiges Dragon-HDR10+-Generator-Unterprojekt: **6 bestanden, 0 fehlgeschlagen**,
- optionaler HDRTVDM-ComfyUI-Bridge-Smoke mit lokalem CPU/PyTorch-Mockmodell: Modell laden → Batch konvertieren → 16-Bit-TIFF schreiben: **erfolgreich**,
- dabei gefundener PyTorch-Fehler (`clamp_()` auf Inference-Tensor außerhalb `inference_mode`) wurde auf nicht-in-place `clamp()` korrigiert und als optionaler Regressionstest `test_patch_ai_hdrtvdm_bridge_optional.py` aufgenommen.

Neue/zusätzlich geänderte Patch-AI-Dateien:

- `dragontools/core/comfyui_hdr_models.py`
- `dragontools/worker/comfyui_runtime.py`
- `dragontools/gui/settings_sections/comfyui_fields.py`
- `extras/comfyui/DragonTools_HDRTVDM/__init__.py`
- `extras/comfyui/DragonTools_HDRTVDM/nodes.py`
- `extras/comfyui/DragonTools_HDRTVDM/requirements.txt`
- `extras/comfyui/DragonTools_HDRTVDM/README.md`
- `dragontools/tests/test_patch_ai_hdrtvdm_bridge_optional.py`
- `COMFYUI_HDR_SETUP.md`
- `INTEGRATION_TESTS.md`

Die Versionsnummer bleibt **9.8.5**.


### Patch AJ – ComfyUI/HDRTVDM-Settings ohne Grid-Überlagerung

**Status:** umgesetzt und getestet  
**Bereich:** Einstellungen / SDR→HDR / ComfyUI / GUI-Layout  
**Ziel:** Die neu ergänzten HDRTVDM-Felder dürfen die bestehende FFmpeg-Kontrast-Recovery-Zeile nicht überlagern.

#### Ursache

`build_comfyui_fields()` belegte im gemeinsamen `QGridLayout` die Zeilen 2 bis 6. Die anschließend in `video.py` ergänzte Zeile `Kontrast-Recovery (FFmpeg)` wurde weiterhin fest in Zeile 4 eingetragen. Damit lagen `HDRTVDM Repository` und `Kontrast-Recovery (FFmpeg)` inklusive Eingabefeldern/Info-Buttons auf derselben Grid-Zeile.

#### Änderungen

- `dragontools/gui/settings_sections/comfyui_fields.py`
  - `build_comfyui_fields(...)` liefert jetzt die **nächste freie Grid-Zeile** zurück (`7`).
- `dragontools/gui/settings_sections/video.py`
  - übernimmt den Rückgabewert als `next_sdr_hdr_row`,
  - setzt `Kontrast-Recovery (FFmpeg)` dynamisch auf diese freie Zeile statt auf die fest codierte Zeile 4,
  - der Wrapper `_build_comfyui_fields(...)` gibt die freie Zeile ebenfalls zurück.
- `dragontools/tests/test_patch_aj_comfyui_layout.py` *(neu)*
  - prüft den Rückgabevertrag der ComfyUI-Feldgruppe,
  - prüft, dass die FFmpeg-Kontrastzeile die zurückgegebene freie Zeile verwendet,
  - verhindert eine erneute feste Doppelbelegung von Grid-Zeile 4.

#### Verhalten

Die Reihenfolge im Bereich `SDR → HDR Enhancement (experimentell)` ist jetzt eindeutig:

1. Aktivierung
2. Backend
3. ComfyUI API
4. AI-HDR-Modell
5. HDRTVDM Repository
6. HDRTVDM Checkpoint
7. ComfyUI Workflow
8. Kontrast-Recovery (FFmpeg)

Es wurden keine Settings-Keys, Backend-Entscheidungen, ComfyUI-API-Verträge oder HDRTVDM-Modellpfade geändert. Die Versionsnummer bleibt **9.8.5**.

### Patch AK – SDR→HDR BT.709-Matrix-Erkennung korrigiert

**Status:** umgesetzt und getestet  
**Bereich:** SDR→HDR Eligibility / MediaInfo-Farbmetadaten  
**Version:** unverändert **9.8.5**

#### Ursache

Bei MediaInfo-Quellen kann `VideoStream.color_space` lediglich den generischen Komponentenraum `YUV` enthalten, während die echte YUV→RGB-Matrix separat korrekt als `MediaInfo.matrix_coefficients = BT.709` vorliegt. Die SDR→HDR-Eignungsprüfung priorisierte bisher fälschlich `video.color_space` und interpretierte dadurch `YUV` als Matrixbezeichnung. Eine eindeutig als BT.709 analysierte SDR-Datei wurde deshalb mit `BT.709-Matrix nicht eindeutig (yuv)` vom Enhancement ausgeschlossen.

#### Änderung

- `dragontools/core/sdr_hdr_enhancement.py`
  - explizite `matrix_coefficients` haben jetzt Vorrang vor dem generischen `color_space`-Feld,
  - generische Komponentenraum-Bezeichnungen wie `YUV`, `RGB`, `GBR` oder `XYZ` werden nicht mehr als Matrix-Koeffizienten fehlinterpretiert,
  - echte widersprüchliche Matrixangaben (z. B. BT.601) werden weiterhin für die HDR-Konvertierung abgelehnt; ab Patch AM bleibt der Auftrag dabei als normaler SDR-Encode aktiv.
- `dragontools/tests/test_patch_m_sdr_hdr_enhancement.py`
  - Regressionstest für `ColorSpace=YUV` + `MatrixCoefficients=BT.709`,
  - Regressionstest für generisches `YUV` ohne explizite Matrix,
  - Regressionstest für eine explizit widersprüchliche Matrix.

#### Ergebnis

Quellen wie `H.264 / 1920×1080 / SDR / BT.709 Primaries / BT.709 Transfer / BT.709 Matrix / Limited`, bei denen MediaInfo zusätzlich `ColorSpace=YUV` meldet, werden jetzt korrekt als geeignete BT.709-SDR-Quelle erkannt.

### Patch AL – ComfyUI/HDRTVDM Voll-Datei-Worker aktiviert

**Status:** implementiert, automatisiert getestet; reale RTX-4080-Abnahme offen  
**Bereich:** SDR→HDR / ComfyUI / HDRTVDM / Standardpipeline / Abbruch / Release-Vertrag  
**Version:** unverändert **9.8.5**

#### Ziel

Die in Patch AI–AK vorbereitete ComfyUI/HDRTVDM-Integration wird als echter Voll-Datei-Pfad ausführbar. Es gibt bewusst keinen separaten Testmodus: kurze Testdateien und komplette Filme verwenden denselben Worker.

#### Ausführungsreihenfolge

```text
SDR BT.709 / CFR
→ bestehender DragonTools-Filterplan (Crop / Scale / Burn-in)
→ FFmpeg RGB-Decode per Pipe
→ ComfyUI DragonHDRTVDMVideoConvert
→ HDRTVDM Frame/Batch-Inferenz
→ RGB48 PQ/BT.2020 per Pipe
→ vorhandener DragonTools-Videoencoder als 10-Bit HDR10/PQ
→ video-only HDR-Zwischenergebnis
→ vorhandene Audio-/Untertitelregeln + Mux
→ bestehende Outputvalidierung
```

Es wird keine komplette TIFF-/PNG-Framefolge auf Platte materialisiert.

#### Neue/angepasste Module

- `dragontools/worker/comfyui_video_worker.py` *(neu)*
  - rendert den modellneutralen API-Workflow,
  - startet genau einen ComfyUI-Job,
  - überwacht `/history/<prompt_id>`,
  - liest Fortschritt/Ergebnis aus dem atomaren Manifest,
  - bricht bei DragonTools-Abbruch gezielt die eigene `prompt_id` ab,
  - validiert Output und Frameergebnis.
- `extras/comfyui/DragonTools_HDRTVDM/nodes.py`
  - neuer `DragonHDRTVDMVideoConvert`,
  - FFmpeg-Decode und HDR-Encode laufen als Pipes,
  - GPU-Inferenz frame-/batchweise,
  - ComfyUI-Interrupt beendet Unterprozesse,
  - JSON-Manifest enthält Frames, Laufzeit und CUDA-Peak-VRAM,
  - vorhandene Debug-/TIFF-Nodes bleiben erhalten, werden vom Produktionsworkflow aber nicht benötigt.
- `dragontools/core/comfyui_hdr_models.py`
  - eingebauter Workflow verwendet `DragonHDRTVDMModelLoader` + `DragonHDRTVDMVideoConvert`,
  - produktiv benötigte Node-Klassen entsprechend aktualisiert.
- `dragontools/core/comfyui_workflow.py`
  - Voll-Datei-/Encoder-/Timing-/Manifest-Platzhalter ergänzt.
- `dragontools/core/sdr_hdr_enhancement.py`
  - vollständig bereites HDRTVDM wird für CFR-Quellen tatsächlich angewendet,
  - VFR bzw. unbekannte Framerate wird für AI-HDR nicht freigegeben; ab Patch AM bleibt der normale SDR-Encode aktiv.
- `dragontools/worker/comfyui_runtime.py`
  - Readiness beschreibt jetzt den ausführbaren Streaming-Node/Workflow.
- `dragontools/worker/encode_plan_service.py`
  - ComfyUI/HDRTVDM wird nur bei eindeutiger BT.709-Colorimetry und vollständiger Readiness aktiviert; fehlt die Eignung oder Readiness, bleibt die Ausgabe SDR und der normale Encode läuft weiter.
- `dragontools/worker/standard_pipeline_runner.py`
  - führt den ComfyUI-HDR-Videojob aus,
  - verwendet danach den erzeugten Videostream per `-c:v copy`,
  - übernimmt weiterhin die vorhandenen Audio-/Subtitle-/Sidecar-Regeln,
  - temporäres video-only Ergebnis wird über `TemporaryDirectory` aufgeräumt.
- `dragontools/core/release_validation_smoke_modules.py`
- `dragontools/core/release_validation_source.py`
  - neuer Worker in Release-/Import-Vertrag aufgenommen.
- `dragontools/gui/settings_sections/comfyui_fields.py`, `README.md`, `help.html`, `COMFYUI_HDR_SETUP.md`, `INTEGRATION_TESTS.md`
  - UI-/Doku-Text vom vorbereiteten TIFF-Workflow auf den ausführbaren Voll-Datei-Pfad aktualisiert.

#### Fail-Closed und Kompatibilität

ComfyUI/HDRTVDM wird nur gestartet, wenn Quelle und Backend im Preflight eindeutig geeignet/bereit sind. Fehlen BT.709-Colorimetry, ComfyUI-API, Modell, Nodes, Workflow oder eine unterstützte CFR-Framerate, wird dies geloggt und die Ausgabe bleibt SDR. Erst wenn ein ComfyUI-HDR-Job tatsächlich gestartet wurde und während der Ausführung fehlschlägt, wird der Auftrag abgebrochen. Andere Backends – insbesondere FFmpeg/libplacebo – bleiben davon unabhängig.

Die AI-Verarbeitung findet **vor** dem finalen Videostream statt. Audio und Untertitel werden danach ohne Neuerfindung ihrer Regeln gemuxt. Strip-Only bleibt semantisch ein Video-Copy-Pfad und ist daher kein SDR→HDR-AI-Encode.

#### Tests

Neu/erweitert:

- `dragontools/tests/test_patch_al_comfyui_video_worker.py`
  - ComfyUI wird bei CFR/Readiness angewendet,
  - VFR wird für AI-HDR abgewiesen und ab Patch AM kontrolliert als SDR weiterverarbeitet,
  - Voll-Datei-Workflow/Unicode-Pfade/Argumentlisten,
  - exakter Prompt-Abbruch,
  - Integration in `StandardPipelineRunner` und anschließender Audio-Mux,
  - kontrollierter SDR-Fallback bei nicht verfügbarem ComfyUI bzw. fehlender eindeutiger BT.709-Colorimetry;
  - weiterhin harter Fehler, wenn ein bereits gestarteter ComfyUI-HDR-Job scheitert.
- `dragontools/tests/test_patch_ai_hdrtvdm_bridge_optional.py`
  - bestehender CPU-Modell-/TIFF-Smoke bleibt,
  - zusätzlicher echter FFmpeg-Streaming-Smoke mit CPU/PyTorch-Mocknetz:
    SDR-Testvideo → Streaming-Node → 10-Bit HEVC/PQ/BT.2020 → Manifest/Framezahl.
- bestehende ComfyUI-, SDR→HDR-, Standard-HDR-, Workflow-, Encoder-, Settings- und Release-Regressionen bleiben Bestandteil der Abschlussprüfung.

#### Bewusst noch offen

- reale Ausführung des offiziellen `params_3DM.pth` auf der RTX 4080 SUPER 16 GB,
- gemessene 1080p-/2160p-Leistung und Peak-VRAM,
- Entscheidung über größere Batchgrößen bzw. 2160p-Tiling,
- visuelle Prüfung auf Frame-zu-Frame-Flicker/Pumping,
- VFR-Timestamp-Unterstützung,
- produktive automatische HDR10+-Erzeugung für ursprünglich SDR stammende Quellen; der getrennte Dragon-HDR10+-Generator bleibt weiterhin fail-closed, solange sein validierter ST-2094-40-Writer nicht fertig ist.

#### Abschlussprüfung Patch AL

Nach dem finalen Frame-Mismatch-Guard und der Dokumentationsaktualisierung wurde der vollständige DragonTools-Testbestand deterministisch über alle 224 Testdateien ausgeführt:

- **1.716 bestanden**
- **24 übersprungen**
- **0 fehlgeschlagen**

Die 24 Skips sind erwartete Umgebungsfälle: PyQt6/pytest-qt auf dem Linux-Testhost, Windows-DPAPI sowie nicht konfigurierte reale DV/HDR-Integration mit `dovi_tool`, `hdr10plus_tool` und MP4Box.

Zusätzlich:

- fokussierte ComfyUI/HDRTVDM-/HDR-/Workflow-/Release-Regressiongruppe: **122 bestanden, 0 fehlgeschlagen**,
- eigenständiges Dragon-HDR10+-Generator-Unterprojekt: **6 bestanden, 0 fehlgeschlagen** (eine erwartete pytest-Warnung zum globalen `qt_api`-Eintrag),
- AST: **979 Python-Dateien, 0 Fehler**,
- JSON: **7 Dateien, 0 Fehler**,
- `compileall`: erfolgreich,
- direkte Import-Smokes für ComfyUI-Worker, HDRTVDM-Workflow, SDR→HDR-Decision und Standardpipeline: erfolgreich.

Nicht als real ausgeführt behauptet werden: offizieller HDRTVDM-Checkpoint auf RTX 4080, reale NVENC/QSV/AMF-Ausführung dieses AI-HDR-Pfads, 2160p-VRAM-Messung und visuelle Qualitäts-/Flicker-Abnahme. Diese Tests erfolgen auf der Benutzerhardware.

#### Release-Abschluss Patch AL

Vergleich zum unmittelbar vorherigen Patch-AK-Source-Stand:

- **2 neue Dateien**,
- **18 geänderte Dateien**,
- **0 entfernte Dateien**,
- damit **20 Patch-AL-Dateiänderungen**.

Der Release-Validator wurde nach vollständiger Entfernung von `__pycache__`, `.pytest_cache`, `.pyc` und `.pyo` auf dem finalen Source-Baum ausgeführt:

- **36 OK**
- **4 erwartete Warnungen**
- **0 Fehler**

Die vier Warnungen sind unverändert: kein `dist`-Build im Source-Paket sowie die bereits vorhandenen Namensstellen in `help.html`, `CHANGELOGV7.txt` und `CHANGELOGV8.txt`.


---

## Patch AM – kontrollierter SDR-Fallback vor ComfyUI-Jobstart

### Ziel

Die SDR→HDR-Option bleibt strikt an explizit erkannte BT.709-Colorimetry gebunden. Nicht eindeutig getaggte Quellen und ein nicht verfügbares/nicht vollständig eingerichtetes ComfyUI dürfen den normalen Konverter jedoch nicht blockieren.

### Verhalten

```text
SDR→HDR aktiviert + Backend ComfyUI
├─ BT.709 eindeutig + Backend bereit → HDRTVDM-Voll-Datei-Worker
├─ Colorimetry fehlt/ist ungeeignet   → Warnung, Ausgabe bleibt SDR
├─ ComfyUI/API/Modell/Nodes fehlen    → Warnung, Ausgabe bleibt SDR
└─ HDR-Job wurde gestartet und scheitert → Auftrag bricht ab
```

Damit wird niemals still eine nicht eindeutig geeignete Quelle nach HDR gewandelt. Gleichzeitig bleiben gewöhnliche SDR-Konvertierungen funktionsfähig, wenn HDRTVDM nicht genutzt werden kann.

### Geänderte Module

- `dragontools/worker/encode_plan_service.py`
  - entfernt den Preflight-`RuntimeError` für ein nicht verfügbares ComfyUI-Backend;
  - loggt stattdessen klar `Ausgabe bleibt SDR; normaler SDR-Encode wird fortgesetzt.`;
  - `_sdr_hdr_applied` bleibt `False`, sodass keine BT.2020/PQ-/10-Bit-HDR-Ausgabeparameter erzwungen werden.
- `dragontools/tests/test_patch_al_comfyui_video_worker.py`
  - Regressionstest: ComfyUI nicht erreichbar → normaler SDR-Plan statt Abbruch;
  - Regressionstest: fehlende BT.709-Primärfarben/Transfer/Matrix → normaler SDR-Plan statt Abbruch;
  - bestehende Tests für tatsächlich gestartete ComfyUI-Jobs und deren harte Laufzeitfehler bleiben erhalten.

### Bewusst unverändert

- Es wird **kein** BT.709 für ungetaggte Quellen geraten.
- Der HDRTVDM-Worker wird nur bei `enhancement.applied=True` gestartet.
- Fehler nach echtem Jobstart bleiben fail-closed; es gibt dann keinen automatischen SDR-Neustart desselben Auftrags.
- FFmpeg/libplacebo, DaVinci-Vorbereitung, DV/HDR10+/Audio/Untertitel/Queue/MoveThread bleiben unberührt.

### Abschlussprüfung Patch AM

Der vollständige DragonTools-Testbestand wurde nach der Policy-Änderung deterministisch über alle 224 Testdateien ausgeführt:

- **1.718 bestanden**
- **24 übersprungen**
- **0 fehlgeschlagen**

Die 24 Skips sind unverändert erwartete Umgebungsfälle (PyQt6/pytest-qt, Windows-DPAPI sowie nicht konfigurierte reale DV/HDR-Integration).

Zusätzlich:

- fokussierte ComfyUI/SDR→HDR/Release-Regressionen: **45 bestanden, 0 fehlgeschlagen**,
- eigenständiges Dragon-HDR10+-Generator-Unterprojekt: **6 bestanden, 0 fehlgeschlagen**,
- AST: **979 Python-Dateien, 0 Fehler**,
- JSON: **7 Dateien, 0 Fehler**,
- `compileall`: erfolgreich.

Vergleich zum Patch-AL-Source-Stand:

- **7 geänderte Dateien**,
- **0 neue Dateien**,
- **0 entfernte Dateien**.

---

## Patch AN – ComfyUI `Media input missing` durch statischen Load-Image-Workflow verhindert

### Ziel

DragonTools darf keinen gespeicherten ComfyUI-Test-/Frontend-Workflow mit statischer Mediendatei (z. B. `Load Image -> banner.png`) als produktiven SDR→HDR-Videoworkflow an die ComfyUI-API senden. Genau dieser Fall führte zu:

```text
Media input missing
Load Image is missing a required media file.
```

### Ursache

Die bisherige Workflow-Prüfung validierte nur die allgemeine ComfyUI-API-Struktur (`class_type`, `inputs`). Dadurch galt auch ein formal korrektes API-JSON mit `LoadImage` und fest eingetragenem `banner.png` als gültig, obwohl der DragonTools-Voll-Datei-Worker dynamische Video-/Output-/Manifestpfade benötigt.

### Geänderte Module

- `dragontools/core/comfyui_workflow.py`
  - neuer DragonTools-Voll-Datei-Workflowvertrag;
  - statische `LoadImage`-/`LoadImageMask`-Nodes werden vor dem Queueing erkannt und abgewiesen;
  - Pflicht-Platzhalter `{{INPUT_VIDEO}}`, `{{OUTPUT_VIDEO}}`, `{{MANIFEST_PATH}}` werden geprüft;
  - optional benötigte Node-Klassen werden ebenfalls validiert.
- `dragontools/core/comfyui_hdr_models.py`
  - zentrale Workflow-Auflösung ergänzt;
  - ein ungültiger benutzerdefinierter Workflow fällt beim HDRTVDM-Profil kontrolliert auf den eingebauten Voll-Datei-Streaming-Workflow zurück;
  - Ursache und Fallback werden als Warning bereitgestellt.
- `dragontools/worker/comfyui_runtime.py`
  - Readiness verwendet dieselbe produktive Workflow-Auflösung wie der eigentliche Worker;
  - effektive Workflow-Quelle und Fallback-Warnung werden in den Laufzeitoptionen hinterlegt und geloggt.
- `dragontools/worker/comfyui_video_worker.py`
  - queued nur noch einen validierten DragonTools-Videoworkflow;
  - ein statischer `banner.png`-Workflow wird nicht mehr an ComfyUI gesendet;
  - bei HDRTVDM wird stattdessen der eingebaute `DragonHDRTVDMVideoConvert`-Workflow genutzt.
- `dragontools/gui/settings_sections/comfyui_fields.py`
  - Hilfetext präzisiert den Unterschied zwischen normalem ComfyUI-Testworkflow und DragonTools-Voll-Datei-API-Workflow.
- `COMFYUI_HDR_SETUP.md`
  - Workflowvertrag und automatischer HDRTVDM-Fallback dokumentiert.
- `dragontools/tests/test_patch_an_comfyui_media_input_fallback.py` *(neu)*
  - Regressionstests für den konkreten `LoadImage/banner.png`-Fehler.

### Neues Verhalten

```text
Benutzerdefinierter ComfyUI-Workflow
├─ DragonTools-Voll-Datei-Vertrag erfüllt → eigener Workflow wird verwendet
├─ statisches Load Image / banner.png      → Workflow wird verworfen
│                                            und HDRTVDM-Builtin wird verwendet
├─ Pflicht-Platzhalter fehlen              → Workflow wird verworfen
│                                            und HDRTVDM-Builtin wird verwendet
└─ Custom-Profil ohne gültigen Workflow    → weiterhin fail-closed
```

Damit kann ein in ComfyUI gespeicherter Testworkflow nicht mehr versehentlich den produktiven DragonTools-Job mit einer fehlenden Bilddatei blockieren.

### Tests

- gezielte Patch-AN-/ComfyUI-/HDRTVDM-Regression: **48 bestanden, 0 fehlgeschlagen**;
- darin enthalten: vorhandene ComfyUI-API-, HDRTVDM-Bridge-, Layout-, Voll-Datei-Worker- und SDR→HDR-Tests;
- neuer Regressionstest bestätigt explizit, dass ein `LoadImage` mit `banner.png` **nicht** gequeued wird und stattdessen `DragonHDRTVDMVideoConvert` verwendet wird.

---

## Patch AO – ComfyUI/HDRTVDM Manifest WinError 5 behoben

### Fehlerbild

Während eines von DragonTools gestarteten HDRTVDM-Voll-Datei-Jobs konnte der ComfyUI-Node unter Windows mit folgendem Fehler abbrechen:

```text
[WinError 5] Zugriff verweigert:
...\\hdrtvdm_manifest.json.tmp -> ...\\hdrtvdm_manifest.json
```

### Ursache

`DragonHDRTVDMVideoConvert` schrieb den Fortschritt nach jedem verarbeiteten Batch zunächst in eine feste `.tmp`-Datei und ersetzte anschließend `hdrtvdm_manifest.json` per `Path.replace()`/`os.replace()`.

DragonTools liest dieselbe Manifestdatei parallel etwa alle 0,75 Sekunden zur Fortschrittsanzeige. Unter Windows kann ein Rename/Replace des Zielpfads scheitern, solange der andere Prozess die Zieldatei gerade zum Lesen geöffnet hat. Bei `batch_size=1` kam hinzu, dass bislang praktisch nach jedem Frame ein Dateireplace ausgeführt wurde.

### Änderung

- `extras/comfyui/DragonTools_HDRTVDM/nodes.py`
  - Manifest-Fortschritt wird nicht mehr über `.tmp -> replace` veröffentlicht;
  - stattdessen direkte, kurze Rewrite-Operation auf der ephemeren JSON-Datei;
  - WinError 5/32/33 werden beim Öffnen/Schreiben kurz und begrenzt erneut versucht;
  - Progress-Manifest wird auf maximal etwa zwei Updates pro Sekunde gedrosselt statt pro Frame/Batch;
  - finaler `complete`-/`failed`-Status wird weiterhin immer geschrieben, bevor der ComfyUI-Node endet.

Die DragonTools-Seite tolerierte bereits kurzzeitig leere/unvollständige Manifestdaten und liest beim nächsten Poll erneut. Für diese reine IPC-/Fortschrittsdatei ist daher kein atomarer Rename erforderlich.

### Wichtig bei bestehenden ComfyUI-Installationen

Der Fehler steckt im installierten Custom Node. Nach dem DragonTools-Update muss daher auch

```text
extras/comfyui/DragonTools_HDRTVDM/
```

nach

```text
ComfyUI/custom_nodes/DragonTools_HDRTVDM/
```

kopiert bzw. der vorhandene Ordner ersetzt und ComfyUI anschließend neu gestartet werden.

---

## Patch AP – SDR→HDR-Einstellungen, ComfyUI-Autostart und Per-Datei-Override

### Ziel

Der produktive SDR→HDR/HDRTVDM-Pfad soll im normalen DragonTools-Betrieb sichtbar und ohne manuelles Starten von ComfyUI nutzbar sein. Gleichzeitig muss SDR→HDR gezielt nur für einzelne Quellen aktiviert oder für einzelne Dateien trotz globaler Aktivierung abgeschaltet werden können.

### Einstellungen / GUI

- `Einstellungen` enthält jetzt den direkten Menüpunkt **`🌈 SDR → HDR / ComfyUI`**.
- Der vorhandene Bereich `sdr_hdr` wird damit direkt geöffnet; die Optionen bleiben zusätzlich im globalen Einstellungsfenster erreichbar.
- Neue ComfyUI-Optionen:
  - `ComfyUI bei Bedarf automatisch starten`,
  - `ComfyUI Startdatei` mit Dateiauswahl für `.bat`, `.cmd` und `.exe`,
  - `Start-Wartezeit` von 5 bis 180 Sekunden, Standard **30 s**.
- Für ComfyUI Portable ist `run_nvidia_gpu.bat` der empfohlene Launcher. `main.py` wird nicht als vollständige Startdatei behandelt, weil Interpreter und Startparameter fehlen.

### ComfyUI-Autostart

Beim Initialisieren eines angeforderten ComfyUI-SDR→HDR-Auftrags gilt jetzt:

```text
ComfyUI API erreichbar
└─ normal weiter; kein zweiter Prozess wird gestartet

ComfyUI API nicht erreichbar + Auto-Start aktiv
├─ expliziten Launcher verwenden
│  oder Portable-Launcher automatisch neben ComfyUI/main.py suchen
├─ Launcher starten
├─ API bis zur konfigurierten Frist wiederholt prüfen
└─ sobald erreichbar: normalen HDRTVDM-Readiness-Check fortsetzen

API nach Ablauf weiterhin nicht erreichbar
└─ bestehender sicherer SDR-Fallback bleibt aktiv
```

Parallel startende Converter teilen eine Start-Sperre. Zusätzlich verhindert ein kurzer Cooldown, dass dieselbe Portable-Installation während eines laufenden Startversuchs mehrfach geöffnet wird.

### Per-Datei-Override

Im bestehenden Datei-Override unter **`HDR Policy (per Datei)`** gibt es jetzt zusätzlich:

```text
🌈 SDR → HDR:
- Global-Standard
- Aktiv / anwenden
- Deaktivieren
```

Semantik:

- `Global-Standard`: globale Einstellung übernehmen,
- `Aktiv`: SDR→HDR nur für diese Datei anfordern, auch wenn global deaktiviert,
- `Deaktivieren`: Datei bleibt SDR, auch wenn SDR→HDR global aktiviert ist.

Das Override schaltet nur die Anwendung pro Quelle. Backend, ComfyUI-URL, Launcher, Modell-Repository, Checkpoint und Workflow bleiben globale technische Einstellungen. Queue-Badges kennzeichnen explizite `SDR→HDR`- bzw. `SDR→HDR:aus`-Overrides.

Die optionale Runtime berücksichtigt bereits vor dem Dateilauf auch per-Datei aktivierte SDR→HDR-Overrides. Damit wird ComfyUI/HDRTVDM vorbereitet, wenn SDR→HDR global aus ist, aber mindestens eine vorhandene Queue-Datei das Override `Aktiv` besitzt.

### HDRTVDM-Qualitätsparameter

Es wurden bewusst keine künstlichen Qualitätsregler erfunden. Der aktuelle Vertrag bleibt:

- **Checkpoint:** wichtigster modellseitiger Look-Faktor; Default `params_3DM.pth`, explizit möglich sind auch `params.pth`, `params_DaVinci.pth` oder ein eigener gültiger Pfad.
- **Encoderqualität:** bestehende DragonTools-CQ/CRF/QP-/Preset-/Codec-Einstellungen steuern die Kompressionsqualität auch beim ComfyUI-HDR-Zwischenstrom und werden nicht doppelt geführt.
- **FP16:** bleibt für den eingebauten CUDA-Workflow Standard; primär Performance/VRAM/numerische Präzision, kein kreativer HDR-Stärke-Regler.
- **Batchgröße 1:** bleibt zunächst Standard; primär Performance/VRAM, nicht HDR-Look.
- **PQ / BT.2020 / 10 Bit:** fester HDR10-Ausgabevertrag, keine freie Qualitätsoption.
- **Kontrast-Recovery:** gilt nur für FFmpeg/libplacebo und beeinflusst HDRTVDM nicht.

Ein allgemeiner `HDR Strength`-/Brightness-/Contrast-Regler wird nicht ergänzt, solange dafür keine validierte HDR-Nachbearbeitung mit kontrollierten Peak-/Gamut-/Clipping-Grenzen definiert ist.

### Geänderte Module

- `dragontools/core/settings_conversion.py`
- `dragontools/core/comfyui_hdr_models.py`
- `dragontools/core/comfyui_workflow.py`
  - Produktions-`assert` aus dem Patch-AN-Validator durch explizite defensive Validierung ersetzt.
- `dragontools/core/encoder_profile_override.py`
  - das SDR→HDR-Tri-State wird zusammen mit den übrigen wirksamen per-Datei-Encoderoptionen gemerged.
- `dragontools/core/file_override_normalization.py`
- `dragontools/gui/settings_sections/comfyui_fields.py`
- `dragontools/gui/settings_sections/video.py`
- `dragontools/gui/main_window_menus.py`
- `dragontools/gui/main_window_settings_actions.py`
- `dragontools/gui/convert_override_groups.py`
- `dragontools/gui/convert_widget_override_dialog.py`
- `dragontools/gui/convert_widget_queue_badges.py`
- `dragontools/worker/workflow_planning_service.py`
- `dragontools/worker/converter_optional_runtime.py`
- `dragontools/worker/comfyui_runtime.py`
- `dragontools/tests/test_main_window_actions_architecture.py`
- `dragontools/tests/test_patch_aj_comfyui_layout.py`
- `dragontools/tests/test_patch_ap_sdr_hdr_settings_autostart_override.py` *(neu)*
- `COMFYUI_HDR_SETUP.md`
- `INTEGRATION_TESTS.md`
- `PATCH.md`

### Tests

- neuer Patch-AP-Regressionssatz prüft Tri-State-Normalisierung, per-Datei Aktiv/Deaktiv, Launcher-Auflösung, Portable-Autodetektion, API-Polling nach Autostart, Runtime-Initialisierung bei global deaktiviertem SDR→HDR und den neuen Menüeintrag;
- bestehender ComfyUI-/HDRTVDM-/Settings-Regressionssatz wurde an das erweiterte Layout angepasst;
- `compileall` über `dragontools` und den HDRTVDM-Custom-Node: erfolgreich;
- kompletter DragonTools-Testbestand in zwei deterministischen Hälften: **1.730 bestanden, 24 erwartete Skips, 0 fehlgeschlagen**. Die Skips betreffen nicht vorhandenes PyQt6/pytest-qt in der Testumgebung, Windows-DPAPI und die nicht konfigurierte reale DV/HDR-Integration.

---

## Patch AQ – HDR10+ Generator 0.2.0, SDR→HDR-HDR10+ und Remux-Injection

### Ziel

Der bislang nur vorbereitete Dragon HDR10+ Generator wurde zu einem tatsächlich arbeitenden Analyse-/JSON-Generator vervollständigt. DragonTools kann die erzeugten ST-2094-40-Metadaten anschließend über den bestehenden `hdr10plus_tool`-Pfad injizieren und am finalen Container wieder semantisch verifizieren.

Zusätzlich wird die Generierung jetzt auch in zwei bisher fehlenden Fällen unterstützt:

- eine SDR-Quelle wird zuerst per SDR→HDR/HDRTVDM zu PQ/BT.2020/10-Bit HEVC verarbeitet und erhält danach optional HDR10+;
- eine vorhandene PQ/HDR10-HEVC-Datei ohne HDR10+ kann im Strip-Only-/Remux-Modus analysiert und ohne Video-Re-Encode mit HDR10+ versehen werden.

### Dragon HDR10+ Generator 0.2.0

Der Generator:

- prüft die Quelle mit ffprobe auf PQ/ST2084 und BT.2020;
- decodiert jeden Präsentationsframe mit ffmpeg in eine reduzierte 16-Bit-RGB-Analysefläche;
- linearisiert PQ nach SMPTE ST 2084 und ermittelt MaxSCL, AverageMaxRGB, Luminanzperzentile, den Anteil bis 100 Nits und ein Histogramm;
- erkennt Szenen über Histogrammdistanzen mit Mindest-Szenenlänge;
- erzeugt ein klassisches hdr10plus_tool-kompatibles ST-2094-40-JSON im Profil A mit einem SceneInfo-Eintrag je Frame;
- schreibt Fortschritt auf stderr und genau ein maschinenlesbares Ergebnisobjekt auf stdout;
- akzeptiert explizite ffmpeg-/ffprobe-Pfade, damit die DragonTools-Third-Party-Binaries genutzt werden können;
- Version wurde von 0.1.0 auf 0.2.0 angehoben;
- build.bat stellt NumPy vor dem PyInstaller-Build sicher.

Profil A wurde bewusst gewählt: Der Generator erzeugt gemessene Szenenstatistik und erfindet keine nicht validierten Profil-B-Bezier-/Knee-Kurven.

### DragonTools-Integration

- Der Generator-Client übergibt jetzt die von DragonTools konfigurierten ffmpeg- und ffprobe-Pfade an HDRPlusGenerator.exe.
- Die Generator-Verfügbarkeit wird unabhängig von der globalen Checkbox ermittelt, damit ein explizites Per-Datei-Override auch bei global deaktiviertem Generator funktionieren kann.
- Neue per-Datei HDR-Policy `HDR10+ erzeugen`:
  - Global-Standard,
  - Aktiv,
  - Deaktivieren.
- Queue-Badges kennzeichnen explizite Erzeugungs-Overrides.
- Bei SDR→HDR wird erst der finale PQ/BT.2020-HEVC-Output erzeugt. Anschließend wird genau dieser fertige Videostream analysiert, HDR10+ injiziert, neu gemuxt und verifiziert.
- Strip-Only/Remux bleibt videoverlustfrei: Der bereits remuxte HEVC-Stream wird nur extrahiert, analysiert und mit HDR10+-SEI versehen; es findet kein erneuter Video-Encode statt.
- MKV verwendet für den finalen Roh-HEVC-Remux weiterhin mkvmerge. MP4 verwendet den bestehenden MP4Box-Pfad und die bestehende Untertitel-Policy.
- Der bisherige Output wird erst nach erfolgreicher HDR10+-Endverifikation durch die neue Datei ersetzt (fail-closed).

### Architektur

Der neue HDR10+-Postprozess liegt bewusst in einem eigenen Service, damit die bestehenden Größen-/Architekturgrenzen der Workflow- und HDRPlus-Fassaden erhalten bleiben. Die Entscheidung, ob ein bereits erzeugter Output nachträglich HDR10+ erhalten muss, liegt ebenfalls in einem kleinen separaten Workflow-Policy-Modul.

### Tests

- Dragon-HDR10+-Generator: 7/7 Unit-/Foundation-Tests bestanden.
- zusätzlicher realer Smoke-Test mit ffmpeg/x265: 12 PQ/BT.2020-Frames gescannt, Profil-A-JSON mit 12 SceneInfo-Einträgen erfolgreich erzeugt.
- neuer Patch-AQ-Regressionssatz prüft:
  - Tri-State-Normalisierung von `generate_hdr10plus`,
  - Aktivierung per Datei trotz global deaktivierter Generator-Policy,
  - Deaktivierung per Datei trotz global aktivierter Policy,
  - HDR10+-Postprozess nach Standardausgabe,
  - HDR10+-Postprozess nach Strip-Only/Remux.
- DragonTools-Testbestand deterministisch in zwei Hälften ausgeführt: **1.735 bestanden, 24 erwartete Skips, 0 fehlgeschlagen**.
- `compileall` über DragonTools und den eingebetteten Generator: erfolgreich.

### Hinweis zur Validierung

Der erzeugte JSON-Vertrag folgt dem öffentlichen klassischen hdr10plus_tool-Format und der öffentlich dokumentierten Profil-A-Semantik. Er ist für den bestehenden DragonTools-Inject-/Verify-Pfad ausgelegt. Eine proprietäre HDR10+-Zertifizierungs-/Authoring-Suite wurde in dieser Entwicklungsumgebung nicht ausgeführt; deshalb wird keine formale Zertifizierung behauptet.

---

## Patch AR – Dokumentation, Handbuch, Help und Projektstatistik – 22.09.2026

### Ziel

Die Dokumentation wurde auf den Stand nach Patch AQ synchronisiert. Der **Dragon HDR10+ Generator 0.2.0** wird dabei als eigenes Bauteil, aber als Bestandteil des Gesamtprojekts **DragonTools** gezählt und dokumentiert. Veraltete Hinweise auf einen nur vorbereiteten ComfyUI-/HDRTVDM-Pfad wurden entfernt.

### Aktueller Projektumfang

Gezählt werden der DragonTools-Python-Quellbaum sowie der Source- und Testbereich des Dragon HDR10+ Generators. Build-/Dist-Artefakte, Caches und generierte Binaries werden nicht als Programmquellcode gezählt.

- **984 Python-Dateien/Programme**
- **149.473 Gesamtzeilen**
- **126.368 Codezeilen**
- **232 Python-Testdateien im Testbereich**, davon **228 `test_*.py`**
- **1.722 statisch erkannte Tests**
- Produktivcode ohne Tests: **752 Python-Dateien**, **105.329 Gesamtzeilen**, **90.676 Codezeilen**

Die Statistik im `Über`-Dialog wurde entsprechend erweitert und zählt den Generator dynamisch mit.

### Dokumentation

Synchronisiert bzw. erweitert wurden:

- `README.md`
- `COMFYUI_HDR_SETUP.md`
- `INTEGRATION_TESTS.md`
- `help.html`
- `DragonToolsV9_Dokumentation.docx`
- `Handbuch/Handbuch.pdf`
- `Aenderungshistorie/CHANGELOG.txt`
- `Aenderungshistorie/CHANGELOG.json`
- `PATCH.md`

Neu dokumentiert sind insbesondere:

- direkter PowerShell-Aufruf von `HDRPlusGenerator.exe analyze --input ... --output ...`;
- Generator-Optionen und Standardwerte;
- ST-2094-40 Profil-A-Erzeugung und die Abgrenzung zu nicht erzeugten Profil-B-Tone-Mapping-Kurven;
- automatischer Ablauf **SDR → HDRTVDM → HDR10 → HDR10+**;
- verlustfreier **HDR10-Remux → HDR10+-Analyse → Injection → Remux** ohne erneuten Video-Encode;
- per-Datei-Override für SDR→HDR und HDR10+-Erzeugung;
- ComfyUI-Autostart und der produktive HDRTVDM-Pfad;
- gemessener Praxiswert für **RTX 4080 SUPER / 1080p SDR→HDR: ca. 4:1 Konvertierungsdauer zu Filmdauer**, ausdrücklich als hardware-/quellenabhängiger Richtwert.

### UI / Projektinfo

- Der SDR→HDR-Einstellungsbereich bezeichnet ComfyUI/HDRTVDM nicht mehr als „vorbereitet“, sondern als produktiv nutzbaren lokalen API-Pfad.
- Der Infotext nennt Autostart, Per-Datei-Override und den gemessenen 4:1-Praxiswert.
- `project_info.py` zählt zusätzlich `dragon_hdr10plus_generator/src` und dessen Tests und weist den Generator im Über-Dialog als integrierten Bestandteil aus.

### Tests und Dokument-QA

- fokussierte Projektinfo-/HDR10+-Generator-Regressionstests: **15 bestanden, 0 fehlgeschlagen**;
- `compileall` über DragonTools und Generator: **erfolgreich**;
- das aktualisierte DOCX wurde zu einem **373-seitigen PDF-Handbuch** gerendert;
- alle 373 PDF-Seiten wurden als Kontaktbogen visuell auf offensichtliche Layoutfehler geprüft;
- die inhaltlich geänderten Seiten mit Projektstatistik und HDR10+-Generator-Dokumentation wurden zusätzlich hochauflösend geprüft.


---

## Patch AS – robuste HDR10+/Dolby-Vision-Medienerkennung – 22.09.2026

### Ziel

Die Medienanalyse wurde gegen reale Feldvarianten von MediaInfo und ffprobe gehärtet. Anlass war ein erfolgreich erzeugter/injizierter HDR10+-Profile-A-Stream, den MediaInfo 26.05 als `SMPTE ST 2094 App 4` und ffprobe frameweise als `HDR Dynamic Metadata SMPTE2094-40 (HDR10+)` meldete, während DragonTools wegen zu enger String-Prüfung `HDR10+: Nein` anzeigte.

### HDR10+

- MediaInfo-Erkennung akzeptiert jetzt neben `HDR10+`/`HDR10plus` auch die gebräuchlichen ST-2094-40-Schreibweisen, insbesondere `SMPTE ST 2094 App 4`, `SMPTE ST 2094 Application 4`, `SMPTE ST 2094-40`, `SMPTE2094-40` und entsprechende Kurzformen.
- MediaInfo- und ffprobe-Evidence werden vereinigt; ein vorhandener MediaInfo-Track überschreibt zusätzliche ffprobe-Side-Data nicht mehr.
- Für PQ/HEVC- bzw. AV1-Quellen ohne bereits erkannten HDR10+-Marker gibt es einen gezielten ffprobe-Frame-Fallback über die ersten zwei Sekunden. Dadurch werden echte framebasierte `HDR Dynamic Metadata SMPTE2094-40 (HDR10+)`-SEI/Side-Data erkannt, ohne bei jeder Datei einen Vollscan auszuführen.
- Der Fallback wird nur bei plausiblen HDR-Quellen gestartet und in `analysis_source`/`analysis_warnings` nachvollziehbar protokolliert.
- Mediathek-/Jellyfin-Marker wurden ebenfalls um `2094 App 4` erweitert.

### Dolby Vision

- MediaInfo-Parsing erkennt jetzt robuster `Profile N`/`Profile N.x` und Codec-Tags `dvhe`, `dvh1`, `dva1`, `dvav` sowie `dav1`.
- ffprobe-`DOVI configuration record` wird strukturiert ausgewertet (`dv_profile`, `dv_level`).
- MediaInfo und ffprobe werden für DV-Details zusammengeführt; bei abweichenden Profilnummern wird eine Analysewarnung geschrieben und der strukturierte ffprobe-DOVI-Profilwert verwendet.
- `dv_profile`, `dv_profile_major`, `dv_level` und vorhandene Codec-Tags bleiben auch bei ffprobe-only-Analyse erhalten.
- Explizit erkanntes Dolby Vision wird nicht mehr allein wegen H.264/AVC oder <10 Bit aus der Medienerkennung gelöscht. Ob eine erkannte Quelle von einer DragonTools-Pipeline verarbeitet werden kann, entscheidet weiterhin separat die Pipeline-Capability.
- Mediathek-/Jellyfin-DV-Marker kennen jetzt ebenfalls `dvh1`, `dva1`, `dvav` und `dav1`.

### Regression / Validierung

- 9 neue Patch-AS-Regressionsfälle für MediaInfo ST-2094 App 4, DV 8.1, DV-Codec-Tags, ffprobe-DOVI, Profilkonflikte, AVC-DV, Quell-Merge und Frame-Fallback.
- Die vom Anwender erzeugten realen Dumps wurden direkt gegen den Parser geprüft:
  - MediaInfo `HDR_Format = SMPTE ST 2094 App 4` -> HDR10+ erkannt;
  - ffprobe Frame-Side-Data `HDR Dynamic Metadata SMPTE2094-40 (HDR10+)` -> HDR10+ erkannt.
- Gesamter Testbestand in zwei deterministischen Gruppen ausgeführt: **1.745 bestanden, 24 erwartete/umgebungsbedingte Skips, 0 fehlgeschlagen**.
- `compileall` über `dragontools`: erfolgreich.

---

## Patch AT – Preflight-Serienjahr und Strip-Only-Mehrfachauswahl – 23.09.2026

### Preflight / Online-Metadaten

- Ein nicht erreichbarer oder veralteter Mediathek-Datenbanktreffer beendet die Serien-Metadatensuche nicht mehr vorzeitig.
- Lokale Ordnersuche und – falls aktiviert – TMDB/TheTVDB-Suche laufen weiter, sodass insbesondere das Serienjahr weiterhin ermittelt werden kann.
- Wird online ein Serienjahr gefunden, bleibt der Hinweis auf den unbrauchbaren DB-Pfad sichtbar, überschreibt aber weder den Online-Titel noch den gewählten TV-/Anime-Bereich.
- Ein nutzbarer Mediathek-Treffer bleibt weiterhin terminal und vermeidet unnötige Online-Abfragen.

### Queue / Strip-Only

- Der Kontextmenüpunkt für Strip-Only arbeitet jetzt auf der gesamten aktuellen Mehrfachauswahl der Dateiliste.
- Bei gemischter Auswahl aktiviert die Aktion Strip-Only für alle markierten Dateien; sind bereits alle markierten Dateien Strip-Only, wird es für alle deaktiviert.
- Bereits laufende/abgeschlossene Dateien werden einzeln abgelehnt und gesammelt gemeldet; noch nicht gestartete markierte Dateien werden trotzdem aktualisiert.
- Einzeldatei-Aufrufe bleiben vollständig kompatibel.

### Tests

- Regression für einen unbrauchbaren Mediathek-Treffer im falschen Bereich mit anschließender Online-Jahresauflösung (`Robin Hood (2025)`).
- Regression für kombinierte Online-Metadaten + DB-Pfadwarnung.
- Regression für Strip-Only auf Mehrfachauswahl sowie Kontextmenü-Verdrahtung.


---

## Patch AU – HDR-Direktzugriffe, Help-Ausbau und Dokumentationssync – 23.09.2026

### Einstellungen / GUI

- `Einstellungen` enthält jetzt neben `🌈 SDR → HDR / ComfyUI` einen eigenen Eintrag `✨ Dragon HDR10+ Generator`.
- Der Generator-Eintrag öffnet gezielt nur den Abschnitt `hdr10plus_generator`; das globale Einstellungsfenster ist dafür nicht mehr nötig.
- Der ausführbare Generatorpfad bleibt bewusst zentral unter `Einstellungen → Werkzeugpfade`, damit es keine doppelte Pfadpersistenz gibt.

### Help

Die Help-Datei wurde von 63 auf 66 eigenständige Hauptpunkte erweitert. Neu sind:

1. `🌈 SDR → HDR mit ComfyUI / HDRTVDM` – Voll-Datei-Workflow, Autostart, Override, Fail-safe und gemessener RTX-4080-SUPER-Praxiswert.
2. `✨ Dragon HDR10+ Generator` – Profile-A-JSON, PowerShell-Aufruf, SDR→HDR→HDR10+, verlustfreier HDR10-Remux und Verifikation.
3. `🎛️ HDR-Erkennung, Datei-Overrides & Strip-Only` – MediaInfo/ffprobe-ST-2094-40-Erkennung, DV-DOVI-Profilzusammenführung, per-Datei-Policies und Strip-Only auf Mehrfachauswahl.

Das Inhaltsverzeichnis sowie alle nachfolgenden Help-Kapitelnummern wurden fortlaufend neu nummeriert.

### Dokumentation / Projektstatistik

- README, COMFYUI-HDR-Setup, Integrationstest-Dokumentation, DOCX-Handbuch, PDF-Handbuch, Help und Änderungshistorie werden auf denselben Funktionsstand gebracht.
- Aktueller Quellumfang einschließlich Dragon HDR10+ Generator: **986 Python-Dateien/Programme**, **150.125 Gesamtzeilen**, **126.908 Codezeilen**.
- Produktivcode ohne Tests: **753 Dateien**, **105.564 Gesamtzeilen**, **90.866 Codezeilen**.
- Testpakete: **233 Python-Dateien**, davon **229 `test_*.py`** mit **1.736 statisch erkannten Tests**.

### Regression

- Architekturtest kennt den neuen Settings-Action-Handler.
- Direkter Generator-Menüeintrag wird statisch gegen Menüverdrahtung und Section-Filter geprüft.
- Help- und Dokumentationsstruktur werden im Patch-AU-Test auf die drei neuen Hauptkapitel und fortlaufende Nummerierung geprüft.

---

## Patch AV – MOV_Text-Sidecars und robuste Timestamp-Reparatur – 24.09.2026

### MOV_Text / tx3g → SRT-Sidecar bei MKV

- `mov_text`/`tx3g` wird bei einem MKV-Ziel nicht mehr per `-c:s copy` in Matroska gemappt. Damit kann ein MP4-Timed-Text-Track den gesamten FFmpeg-MKV-Header nicht mehr mit `Subtitle codec mov_text ... is not supported` abbrechen.
- Fachlich ausgewählte `mov_text`-/`tx3g`-Spuren werden stattdessen automatisch mit FFmpeg nach **SubRip/SRT** konvertiert und als Sidecar neben der Zieldatei gespeichert – auch wenn die allgemeinen zusätzlichen Sidecar-Optionen deaktiviert sind.
- Sprache, Forced-Kennzeichnung und vorhandene Sidecar-Namenslogik bleiben erhalten, z. B. `Film.en.forced.srt`.
- Der Sidecar-Export bleibt fail-closed: Schlägt die SRT-Konvertierung fehl, gilt die Untertitelverarbeitung nicht als vollständig; die Spur wird nicht still verworfen.
- Standard-Encoding und Strip-Only verwenden dieselbe Kompatibilitätsregel. Der erwartete MKV-Medienvertrag verlangt einen ausgelagerten `mov_text`-/`tx3g`-Track folgerichtig nicht mehr als internen Untertitel.

### Stream-Gegenprüfung bei Timestamp-Reparaturen

- ffprobe/FFmpeg, MediaInfo und MKVToolNix (`mkvmerge -J`) werden als drei unabhängige Stream-Inventare ausgewertet.
- **OR-Regel für vorhandene Streams:** Bestätigt mindestens eines der verfügbaren Werkzeuge die erwartete Video-, Audio- oder Untertitelspur, gilt dieser Streamtyp als vorhanden. Parser-Widersprüche werden protokolliert, verwerfen den Reparaturkandidaten aber nicht.
- Ein Streamtyp gilt erst dann als wirklich verloren, wenn **alle drei Werkzeuge verfügbar sind und alle drei** weniger als die erwartete Anzahl melden.
- Sind weniger als drei Prüfwerkzeuge verfügbar und keines liefert einen positiven Nachweis, wird kein künstlicher 3-von-3-Verlust behauptet; der Fall bleibt als Warnung sichtbar und wird durch die übrigen Integritätsprüfungen abgesichert.
- Damit verwirft insbesondere ein fehlerhafter MediaInfo-Rückgabewert `V=0/A=0/S=0` keinen Kandidaten mehr, wenn ffprobe oder MKVToolNix die Streams korrekt erkennt.

### MKV-Timestamp-Reparatur

- Für MKV ist der primäre Stage-2-Reparaturweg jetzt der verlustfreie MKVToolNix-Remux mit `--default-duration`.
- Die echte Matroska-Videotrack-ID wird vorab mit `mkvmerge -J` ermittelt; Track-ID `0` wird nicht pauschal angenommen.
- Beispielprinzip: `mkvmerge --ui-language en --output repaired.mkv --default-duration <TrackID>:24000/1001fps broken.mkv`.
- FFmpeg `setts` und anschließend `+genpts+igndts` bleiben als lossless Fallbacks erhalten.
- Der vorhandene Original-Timeline-Fallback für echte VFR-Quellen bleibt bevorzugt. Nur beim eng eingegrenzten Sonderfall **±1 Frame**, plausibler Frame/FPS-Dauer und gleichzeitig eindeutigem Millionen-Sekunden-/2^32-ms-Timestamp-Wrap darf anschließend der sichere CFR-`default-duration`-Neuaufbau versucht werden.

### Toleranz und Integritätsprüfung

- Für reparierte Video- und Containerlaufzeit gilt eine explizite Reparaturtoleranz von **±0,4 Sekunden** zur Referenzlaufzeit.
- Ein einzelner abweichender Audio-`duration`-Metadatenwert verwirft die Reparatur nicht mehr allein; solche Stream-Durationsfelder sind bei beschädigten Matroska-Timelines nicht zuverlässig genug.
- Die gelockerte Zeitprüfung wird durch eine strengere Nutzdatenprüfung abgesichert: ffprobe zählt vor/nach der Reparatur die Pakete **pro Stream** und erzeugt für jedes Paket einen **SHA-256-Hash**.
- Paketanzahl und Hashreihenfolge müssen innerhalb jedes Video-, Audio- und Untertitelstreams identisch bleiben. Die globale Interleaving-Reihenfolge zwischen den Streams darf sich durch den Remux ändern.
- Die Reparatur selbst darf somit weiterhin **keine Pakete/Frames hinzufügen, entfernen oder verändern**. Die ±1-Frame-Toleranz betrifft nur die Abweichung der bereits komprimierten Datei zur externen Original-/Quellreferenz im beschriebenen Wrap-Sonderfall.
- Nach der Reparatur werden zusätzlich maximaler Video-PTS und Videopaketdauer geprüft. Millionen-Sekunden-Timestamps, `maxPTS > Referenz + 0,4 s` oder unplausibel große Videopakete verwerfen den Kandidaten.
- Erst nach erfolgreicher Dauer-, 3-Tool-Stream- und Paket-/Hashprüfung wird der Reparaturkandidat übernommen. Der bestehende Archiv-/Fail-closed-Pfad bleibt unverändert erhalten.

### Regression

- Neuer Patch-AV-Test deckt MOV_Text-Ausschluss aus internem MKV-Mux, obligatorischen SRT-Sidecar, echte MKVToolNix-Track-ID/`--default-duration`, 0,3-s-Dauertoleranz, den engen ±1-Frame-Wrap-Fall und streamweise SHA-256-Paketprüfung ab.
- Relevanter Subtitle-/Sidecar-/Repair-/Contract-Testverbund: **110 bestanden, 4 umgebungsbedingte PyQt6-Skips, 0 Fehler**.
- Gesamter DragonTools-Testbestand deterministisch in zwei Gruppen ausgeführt: **1.757 bestanden, 25 umgebungsbedingte/optionale Skips, 0 Fehler**.
- `compileall` über DragonTools und den eingebetteten Dragon HDR10+ Generator: **erfolgreich**.

---

## Patch AW – MOV_Text intern als SRT, Originalspur nur als Fehlerfallback – 24.09.2026

### MKV-Untertitel

- Die in Patch AV zunächst immer ausgelagerten `mov_text`-/`tx3g`-Spuren werden im normalen MKV-Pfad jetzt direkt nach **SubRip/SRT** transcodiert und als **interne MKV-Untertitelspur** gemuxt.
- Andere MKV-kompatible Untertitel bleiben weiterhin Stream-Copy; Sprache, Titel und Forced-Disposition werden pro Ausgabespur gesetzt.
- Der erwartete Medienvertrag verlangt bei erfolgreicher Konvertierung folgerichtig `subrip` als internen Codec für eine ursprüngliche `mov_text`-/`tx3g`-Spur.

### Fail-safe / Originalspur erhalten

- Nur wenn der MKV-Lauf mit ausgewähltem `mov_text`/`tx3g` fehlschlägt, aktiviert DragonTools automatisch den Sicherheitsfallback.
- Die ursprüngliche Timed-Text-Spur wird dann **verlustfrei per Stream-Copy** in eine kleine Subtitle-only-MP4 gesichert, z. B. `Episode.en.forced.mov_text.mp4`.
- Danach wird der Encode/Remux ohne die nicht konvertierbare interne Timed-Text-Spur wiederholt. Die Video-/Audioverarbeitung muss also nicht wegen eines einzelnen problematischen `mov_text`-Tracks verloren gehen.
- Schlägt bereits die verlustfreie Sicherung der Originalspur fehl, bleibt das Verhalten fail-closed und der Auftrag wird als Fehler beendet.
- Schlägt auch der Wiederholungslauf ohne `mov_text` fehl, werden die nur für diesen fehlgeschlagenen Versuch erzeugten Backup-Sidecars wieder entfernt, damit ein späterer Retry nicht an vorhandenen Dateien scheitert.
- Der Fallback gilt sowohl für normales Standard-Encoding als auch für **Strip-Only** und für den finalen ComfyUI/HDRTVDM-Mux.

### Output-Vertrag / Sidecar-Commit

- Erfolgreich ausgelagerte Fallback-Spuren werden dem Pipeline-Ergebnis mit ihren ursprünglichen Stream-Indizes mitgegeben.
- Der erwartete Medienvertrag wird anschließend gezielt neu aufgebaut und verlangt genau diese ausgelagerten Spuren nicht mehr zusätzlich intern in der MKV.
- Die Backup-MP4 wird über den bestehenden Sidecar-Commit zusammen mit der Videodatei weitergeführt.
- Normale erfolgreiche `mov_text → SRT`-Konvertierung erzeugt **keinen Sidecar**.

### Regression / Smoke-Test

- Regressionen prüfen internen `mov_text → subrip`-Mux, Strip-Only, expliziten Ausschluss beim Retry, verlustfreien Subtitle-only-MP4-Backup und die Anpassung des Medienvertrags.
- Relevanter Subtitle-/Fallback-/Architektur-Testverbund: **101 bestanden, 8 umgebungsbedingte PyQt6-Skips, 0 Fehler**.
- Gesamter DragonTools-Testbestand in zwei deterministischen Gruppen ausgeführt: **1.762 bestanden, 25 umgebungsbedingte/optionale Skips, 0 Fehler**.
- `compileall` über DragonTools und den eingebetteten Dragon HDR10+ Generator: **erfolgreich**.
- Realer FFmpeg-Smoke-Test bestätigt: `mov_text` lässt sich nach SubRip in MKV wandeln und die unveränderte Originalspur lässt sich separat als subtitle-only MP4 mit `mov_text` stream-copieren.

---

## Patch AX – fehlende HDR10+-Workflow-Abhängigkeit im Inkrementalpatch ergänzt – 24.09.2026

### Import-/Paketierungsfix

- Der Inkrementalpatch AW enthielt `workflow_planning_service.py`, aber nicht dessen bereits vorhandene direkte Abhängigkeit `worker/hdr10plus_workflow_policy.py`.
- Wurde AW auf einen Arbeitsstand angewendet, in dem dieses Modul noch fehlte, brach `start_convert()` bereits beim Import des Converter-Workers mit `ModuleNotFoundError: No module named 'dragontools.worker.hdr10plus_workflow_policy'` ab.
- Patch AX liefert die fehlende Workflow-Policy deshalb ausdrücklich mit und enthält den dazugehörigen Planner erneut. Damit ist diese Importkante im Patch selbst geschlossen.
- Die HDR10+-Entscheidungslogik wird nicht verändert; es handelt sich ausschließlich um einen Vollständigkeits-/Paketierungsfix.

### Regression

- Neuer Regressionstest importiert `hdr10plus_workflow_policy` und `workflow_planning_service` direkt und prüft die zentrale `should_postprocess_generated_hdr10plus()`-Entscheidung.
- Der vorhandene Release-Smoke-Vertrag führt `hdr10plus_workflow_policy` weiterhin explizit als Pflichtmodul.

---

## Patch AY – vollständige Workflow-Importkette für Converter-Start – 24.09.2026

### Import-/Paketierungsfix

- Nach AX zeigte ein älterer lokaler Arbeitsstand die nächste fehlende Refactor-Abhängigkeit: `worker/workflow_override_summary.py`.
- Der Fehler entstand nicht in der Konvertierungslogik selbst, sondern weil frühere Inkrementalpatches neue Workflow-Dateien voraussetzten, die in einem älteren Arbeitsstand noch nicht vollständig vorhanden waren.
- Patch AY liefert deshalb nicht nur das unmittelbar fehlende Modul, sondern den **kompletten aktuellen `workflow_*`-Modulsatz** sowie die direkten Workflow-Helfer `hdr10plus_workflow_policy.py` und `dv_workflow_pipeline_adapter.py` mit.
- Damit ist die Importkette `converter_thread -> converter_runtime_builder -> workflow_factory -> workflow_planning_service/...` im Inkrementalpatch geschlossen und es entsteht kein weiteres Domino aus fehlenden Workflow-Hilfsmodulen.
- `workflow_override_summary.format_override_summary()` bleibt unverändert die zentrale Log-Zusammenfassung für Per-Datei-Overrides.

### Regression

- Neuer Import-Closure-Test lädt den vollständigen Workflow-Modulsatz, `hdr10plus_workflow_policy`, den DV-Workflow-Adapter und `converter_runtime_builder` explizit.
- Zusätzlich wird geprüft, dass `format_override_summary()` als aufrufbares Symbol vorhanden ist.

## Patch AZ – Renamer: E19-Erkennung und manuelle Staffelwahl

- Serien-Releases mit reinem Episodenmarker wie `E19` werden jetzt als Serie erkannt, auch wenn kein `Sxx`/`EPxx` vorhanden ist.
- Bei `E19` wird Staffel 1 als praktischer Standard angenommen und direkt für die Metadatensuche verwendet; die Annahme wird im Hinweistext sichtbar gemacht.
- Der Episodenmarker `E19` und nachfolgende Technik-Tags werden aus dem Provider-Suchbegriff entfernt.
- Der Renamer erhält den neuen Button **„🗓 Staffel ändern“**. Die Staffel kann damit auch bei bereits erkannten `SxxExx`-Dateien oder bei automatisch als Staffel 1 interpretierten `E19`-Releases manuell überschrieben werden.
- Nach einer manuellen Staffeländerung wird die Metadatensuche für die betroffenen Zeilen automatisch mit der neuen Staffel neu gestartet.
- Explizite Staffel-Overrides sind nicht mehr auf `EPxx`-Dateien mit fehlender Staffel beschränkt.

## Patch BA – getrennte Original-Timingreferenzen und tolerantere lossless Timestamp-Validierung – 25.09.2026

### Original-Timing statt globalem Maximalwert

- Die Timestamp-Reparatur vermisst die **Originaldatei jetzt getrennt** und führt Containerdauer, Videodauer, Frame/FPS-Dauer und Frameanzahl als eigene Referenzen.
- Die reparierte Videotimeline wird nicht mehr gegen die bisherige globale `max(Container, Video, Audio, Untertitel)`-Dauer geprüft. Dadurch kann ein später endender Subtitle-/Containerwert eine technisch korrekte Videoreparatur nicht mehr fälschlich verwerfen.
- Im Reparaturlog erscheint zusätzlich eine kompakte `Original-Referenz` mit Container-, Video-, Frame/FPS-Dauer und Frameanzahl.

### Reparaturtoleranz

- Für **lossless** Timestamp-Reparaturen gilt bei vorhandener Originalreferenz jetzt eine praxisnahe Toleranz von **±1,0 s** für Video- und Containerdauer.
- Die Frame/FPS-Prüfung verwendet ebenfalls die Original-Videoreferenz und toleriert mindestens eine Frame-Dauer; eine bereits beim Encode entstandene Abweichung von genau einem Frame verhindert die Timestamp-Reparatur nicht mehr.
- Die enge ±1-Frame-Sonderfreigabe für eindeutige `2^32 ms`-/Millionen-Sekunden-Wraps akzeptiert jetzt bis zu 1,0 s Differenz zwischen Quell-/Containerdauer und framebasierter Videodauer.
- Diese Toleranz ist **keine** Freigabe für Datenverlust: Paketanzahl und SHA-256-Nutzdaten werden weiterhin pro Stream zwischen defektem Encode und Reparaturkandidat verglichen und müssen unverändert bleiben; Millionen-Sekunden-PTS und unplausible Paketdauern bleiben Ablehnungsgründe.

### ffprobe-Robustheit

- `ffprobe -count_frames` erhält für die vollständige Reparaturprüfung bis zu **180 Sekunden** statt 90 Sekunden, damit längere Dateien nicht unnötig am Analyse-Timeout scheitern.

### Regression

- Neuer Patch-BA-Test reproduziert den Fall, dass die globale Quelldauer 0,75 s länger ist als die echte Videotimeline und bestätigt, dass die Reparatur mit separater Original-Videoreferenz akzeptiert wird.
- Zusätzliche Tests sichern die ±1,0-s-Grenze, den ±1-Frame-/Timestamp-Wrap-Fall und den verlängerten `-count_frames`-Timeout ab.


---

## Patch BB – Renamer: Episode manuell ändern und 3×5-Werkzeugleiste – 25.09.2026

### Manuelle Episodenwahl

- Neben **„🗓 Staffel ändern“** gibt es jetzt **„🔢 Episode ändern“** für markierte Serienzeilen.
- Staffel und Episode werden als getrennte Overrides geführt und können beliebig kombiniert werden, z. B. aus einem falsch erkannten `S01E19` gezielt `S03E07`.
- Nach einer Episodenänderung wird die Metadatensuche für die betroffenen Zeilen automatisch neu gestartet; Provider-Suche, Vorschlag und Zielname verwenden die manuell gewählte Episodennummer.
- Der Episoden-Override bleibt auch bei „Alle Treffer“, eigener Seriensuche und erneuter Vorschlagssuche erhalten.
- Die Override-Zustände wurden aus dem Tabellencontroller in einen eigenen kleinen State-Mixin ausgelagert, damit der Renamer-Controller trotz zusätzlicher Funktion innerhalb der Architekturgrenzen bleibt.

### Gleichmäßige Renamer-Werkzeugleiste

- Die jetzt **15 Renamer-Aktionen** sind exakt auf **3 Zeilen mit je 5 Buttons** verteilt.
- Alle fünf Spalten erhalten denselben Layout-Stretch; die Buttons dürfen horizontal gleichmäßig mitwachsen.
- Die Reihen sind logisch gruppiert: Datei/Suche, Treffer/Struktur/Auswahl sowie Annahme/Umbenennen/Entfernen.
- Dadurch bleibt die Leiste sowohl auf breiten als auch schmaleren Fenstern ausgeglichen und erzeugt keine unnötige Mindestbreite.

### Regression

- Neue Tests prüfen Episoden-Override, kombinierte Staffel-/Episoden-Overrides, ungültige Episodennummern, Button-Verdrahtung sowie die 3×5-Verteilung.
- Relevanter Duration-/Renamer-/Architektur-Testverbund: **74 bestanden, 1 umgebungsbedingter PyQt6-Skip, 0 Fehler**.
- `compileall` über `dragontools`: **erfolgreich**.

---

## Patch BC – Datei-Einstellungen auf Mehrfachauswahl anwenden – 25.09.2026

### Mehrfachauswahl im Queue-Kontextmenü

- **„⚙️ Datei-Einstellungen …“** arbeitet jetzt wie Strip-Only, Zielordner und Encoder-/Skalierungs-Override auf allen markierten Queue-Dateien, sofern auf eine bereits markierte Datei rechtsgeklickt wird.
- Bei Mehrfachauswahl zeigt das Kontextmenü **„⚙️ Datei-Einstellungen für Auswahl (N) …“** und der Dialog nennt die Anzahl der betroffenen Dateien sowie die Referenzdatei.
- Die angeklickte Datei wird innerhalb der vorhandenen Auswahl bewusst als erste Referenz verwendet. Ihre Streamstruktur dient damit für benutzerdefinierte Audio-/Untertitel-Trackindizes als Vorlage.

### Sichere Übernahme

- Dialogeigene Werte wie Processing-Modus, Encoder-Override, Audio/Untertitel, DRC/Loudnorm, IMAX sowie DV/HDR/HDR10+-Overrides werden auf jede markierte Datei übernommen.
- Zustände, die der Dialog nicht besitzt – insbesondere ein separat zugewiesenes **Encoder-Profil** – bleiben pro Datei erhalten und werden nicht versehentlich von der Referenzdatei kopiert.
- Bereits laufende oder abgeschlossene Queue-Dateien können weiterhin nicht geändert werden. Bei gemischter Auswahl werden noch nicht gestartete Dateien übernommen und abgelehnte Dateien gesammelt gemeldet.
- Für jede erfolgreich geänderte Datei werden Preflight-Cache und Queue-Badges aktualisiert.
- Bei benutzerdefinierten Audio-/Untertitelspuren weist der Dialog darauf hin, dass die Track-Indizes der Referenzdatei übernommen werden; bei unterschiedlicher Spurstruktur sollen die Dateien getrennt eingestellt werden.
