# Checkliste für eine öffentliche Veröffentlichung

Diese Arbeitskopie ist vom privaten Entwicklungsrepository getrennt. Nur diese Kopie darf mit dem späteren öffentlichen GitHub-Repository verbunden werden.

## Vor jedem Push

1. Datenschutzprüfung ausführen:

   ```powershell
   python scripts/check_public_privacy.py
   ```

2. Tests ausführen:

   ```powershell
   python -m pytest -m "not dv_hdr_integration"
   ```

3. Prüfen, was veröffentlicht würde:

   ```powershell
   git status
   git diff --cached
   git ls-files
   ```

4. Sicherstellen, dass keine Programme, Medien, Zugangsdaten, lokalen Einstellungen, Build-Ausgaben oder privaten Archive hinzugefügt wurden.

## GitHub-Repositories

- `Dragontools-Public`: anonymisierter Quellcode und Dokumentation
- `Dragontools-Releases`: fertige ZIP-Pakete ausschließlich über GitHub Releases

Das private Repository `Dragontools` bleibt privat und wird nicht mit der öffentlichen Historie vermischt.

## Erster öffentlicher Push

Das GitHub-Repository zunächst leer anlegen: ohne README, `.gitignore` oder Lizenz. Danach die angezeigte HTTPS-Adresse als `origin` dieser Arbeitskopie eintragen und `main` hochladen. Die Sichtbarkeit erst nach erfolgreicher Datenschutzprüfung auf öffentlich stellen.

## Programm-Release für den Updater

1. Einen geprüften Windows-Build erstellen.
2. Den kompletten Anwendungsordner als ZIP verpacken.
3. Eine SHA-256-Prüfsumme erzeugen und mit veröffentlichen.
4. Im Repository `Dragontools-Releases` ein GitHub Release anlegen.
5. Einen numerischen Tag verwenden, zum Beispiel `v9.9`.
6. ZIP, Prüfsumme und verständliche Release-Hinweise anhängen.
7. Das Release darf weder Entwurf noch Vorabversion sein, wenn es von der normalen Updateprüfung gefunden werden soll.

Die aktuelle Anwendungsversion ist `9.8.6`. Ein veröffentlichtes Release mit dieser Version löst bei älteren Versionen einschließlich V9.8.5 den Updatehinweis aus. Ein Git-Push allein veröffentlicht noch kein GitHub Release.

## Public-Paketierung ohne externe Werkzeuge (25.09.2026)

Der Public-Build bindet keine Dateien aus `third_party` ein. Externe Medienwerkzeuge werden separat installiert; `TOOLS_INSTALLIEREN.txt` liegt im Paket. `scripts/check_public_bundle.py` prüft Build-Ordner und ZIP auf ausgeschlossene Werkzeugdateien und nichtleere `Programme`-/`third_party`-Verzeichnisse. Diese Prüfung muss auch nach jedem erneuten Abgleich mit dem privaten Projekt bestehen. Die benötigten Python-/Qt-Laufzeitbibliotheken bleiben enthalten; dies ist keine pauschale Lizenzfreigabe für diese Bibliotheken.
