# Architektur: Verantwortlichkeiten statt Zeilenlimits

## Ergänzung 26.09.2026: prüfbare Abhängigkeiten und Zustandsbesitz

`test_review_dependency_ownership.py` ergänzt die Komplexitätsprüfung durch
transitive Importprüfungen für Renamer-Domänenlogik, Paketparser und Session-State.
Auch Imports innerhalb von Funktionen werden erfasst. Die betroffenen reinen
Komponenten dürfen nicht indirekt von GUI-Widgets abhängen.

Die Suchversionen gehören ausschließlich dem Renamer-Koordinator und seinem
Such-Mixin; die Prüfung erkennt Zuweisungen, Indexschreibzugriffe und mutierende
Dictionary-Aufrufe. Dateiumbenennungen bleiben im Aktionscontroller. Die
Invalidierung von Vorschlag, Freigabe und Zielname hat eine gemeinsame Implementierung.

Diese Verträge ersetzen keine fachliche Review. Dynamisch erzeugte Imports und
Mutation über beliebige Aliase werden nicht vollständig statisch erkannt.
Regressionstests sichern ergänzend Zustandsfolgen und echte Dialogbedienung ab.

Eine Datei darf länger als 300 Zeilen sein, wenn sie eine zusammenhängende
Verantwortlichkeit hat. Kommentare, Datentabellen, Typdefinitionen und ausführliche
Fehlerbehandlung sind kein Grund, zusätzliche Weiterleitungsmodule einzuführen.

## Verbindliche Prüfung

- Bestehende Architekturtests prüfen weiterhin fachliche Owner, öffentliche
  Schnittstellen, verbotene Abhängigkeiten und die Trennung von Oberfläche,
  Planung, Tool-Ausführung und Dateitransaktionen.
- Neue Funktionalität gehört zum zuständigen Owner. Unterschiedliche Gründe für
  Änderungen, eigene Seiteneffekte oder unabhängige Lebenszyklen sprechen für eine
  Trennung. Gemeinsame Daten oder ein gemeinsamer Dateiname allein reichen nicht.
- `test_responsibility_contracts.py` untersucht alle Python-Module des Pakets
  `dragontools`, einschließlich `subtitle` und neuer Unterpakete; nur Tests und
  Bytecode-Caches sind ausgenommen. Neue Funktionen mit mehr als 25 Entscheidungspunkten,
  Klassen mit mehr als 100 Verzweigungen oder mehr als acht Methoden mit jeweils
  mehr als fünf Entscheidungspunkten benötigen eine Überarbeitung.
  Einfache Weiterleitungen und Datenfelder werden nicht als eigenständiges
  Verhalten gewertet. Innere Funktionen werden separat beurteilt. Methoden in
  bedingten Klassenblöcken zählen zur Klasse; Methoden innerer Klassen nicht.
- Diese Strukturwerte sind Warnsignale, kein automatischer Beweis für fachliche
  Kohäsion. Im Review muss weiterhin klar benannt werden können, wofür ein Modul
  zuständig ist und welche Aufgaben ausdrücklich anderswo liegen.

## Bestehende Altlasten

`dragontools/tests/architecture_debt.json` hält die vor dieser Änderung bereits
vorhandenen Strukturüberschreitungen fest. Sie werden nicht nachträglich als gute
Architektur eingestuft. Bestehende Werte dürfen nicht wachsen; neue Überschreitungen
schlagen fehl. So erzwingt eine gezielte Fehlerkorrektur keinen unüberschaubaren
Umbau aller historischen Problemstellen.

Die Datei nicht automatisch neu erzeugen, um Tests grün zu bekommen. Bei einem
gezielten Refactoring Einträge entfernen oder absenken. Neue Ausnahmen verlangen
eine begründete Review-Entscheidung mit benanntem Owner und Folgeaufgabe.

## Sicherheitsverträge dieser Änderung

- Verlustfreie Zeitstempelreparaturen werden nur übernommen, wenn die Paketprüfung
  verfügbar **und** erfolgreich ist. Fehlende Tools, ungültige Analyseausgaben,
  fehlende Nutzdatenhashes und veränderte Pakete sperren die Übernahme.
- Scheitert die Spuranalyse im Einstellungsdialog, bleiben die bisherigen Audio-
  und Untertiteloptionen jeder betroffenen Datei erhalten. Andere Optionen dürfen
  weiterhin geändert werden. Abbrechen speichert nichts.
- Tests decken Einzel- und Mehrfachauswahl, verschiedene Override-Modi, leere
  erfolgreiche Analysen, Analysefehler und MKV-/MP4-Übernahme ab. Externe Tools
  werden dabei kontrolliert simuliert; das ersetzt keinen echten Medien-Probelauf.
