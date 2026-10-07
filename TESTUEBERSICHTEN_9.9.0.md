# Testübersichten DragonTools 9.9.0

Die aktuellen Übersichten in Hilfe, README, „Über“, Word und Handbuch nennen den Testbestand und das Ergebnis der Patch-29-Abnahme vom 07.10.2026. 369 Testdateien enthalten 3.287 statisch erkannte Testfunktionen. Die Abnahme bestand mit 5.152 allgemeinen und 23 nativen DV/HDR-Testfällen, zusammen **5.175**. 14 Tests im allgemeinen und 2 im nativen Lauf wurden übersprungen; Gründe und Grenzen stehen im Patch-29-Bericht. Zusätzliche Fokus- und Exportläufe werden nicht nochmals addiert. Parametrisierte Testfälle sind von statischen Testfunktionen getrennt.

Die Programmversion bleibt 9.9.0. Die ergänzte Anzeige erhöht den Quellenumfang um eine Zeile: 1.297 Python-Dateien, 208.072 Gesamtzeilen und 175.787 Codezeilen; ohne Tests 922 Dateien, 129.255 Gesamtzeilen und 111.314 Codezeilen. Die historischen Patch-Berichte dokumentieren weiterhin ihren damaligen Stand.

Verifikation dieser Ergänzung: 14 bestehende Projekt-/Versions-/Artefakttests bestanden im ersten Lauf. Die private Snapshot-Prüfung benötigte das nach den Dokumentänderungen erneuerte Manifest und bestand danach separat (1 Test). Alle 1.297 Python-Dateien kompilieren; Source-Release-Prüfung 0 Fehler, 1 Warnung wegen fehlendem vollständigem EXE-Build. Die Testzahlen wurden gegen die tatsächlichen Patch-29-Logs abgeglichen.

Handbuch: 408 Seiten, 186 Inhaltsverzeichnisverweise geprüft. Abweichende Seiteninhalte erneut als unverkleinerte PNGs visuell geprüft; unveränderte Seiteninhalte mittels identischer Pixel bzw. identischer Text-, Bild- und Zeichnungspositionen mit dem zuvor geprüften PDF abgeglichen. Kopfzeilen und Seitenzahlen separat überprüft. Automatische Prüfung sämtlicher Seiten ohne fehlende Inventareinträge, Leer- oder Randfehler. Word-Autor DragonTools Team; PDF ohne persönlichen Autor.

Aktueller Quellenstand einschließlich Dokumentation: `DragonTools_9.9.0_Reviews_01-29_Testuebersichten.zip`. CRC, sämtliche Datei-SHA-256 und ein frisch entpacktes Snapshot-Manifest werden vor Übernahme geprüft. Die früheren Archive bleiben erhalten; ersetzte Originaldateien werden gesichert. Es wurde keine neue vollständige Hauptprogramm-EXE gebaut.
