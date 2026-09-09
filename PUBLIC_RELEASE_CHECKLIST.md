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

Die aktuelle Anwendungsversion ist `9.8.1`. Dieses Release löst bei V9.8 den Updatehinweis aus. Nach der Installation meldet sich erst eine höhere Version, beispielsweise `v9.8.2`, wieder als Update.
