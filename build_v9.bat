@echo off
setlocal EnableExtensions

REM Immer aus dem Ordner dieser BAT arbeiten. Wichtig bei Doppelklick/Verknuepfungen.
pushd "%~dp0"
if errorlevel 1 (
  echo [FEHLER] Projektordner der Build-Datei konnte nicht geoeffnet werden: %~dp0
  goto :BUILD_FAILED_NO_POPD
)
echo [INFO] Arbeitsverzeichnis: %CD%

REM Dragon Tools V9 - kanonischer PyInstaller-CLI-Build.
REM Die konkrete Version wird ausschliesslich aus dragontools\core\version.py gelesen.
REM Der alte Dateiname build_v9_angepasst.bat bleibt als Kompatibilitaets-Wrapper erhalten.

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

REM Python zuerst separat pruefen. So ist sofort sichtbar, ob die gewaehlte
REM Umgebung ueberhaupt gestartet werden kann.
"%PYTHON_EXE%" --version >nul 2>nul
if errorlevel 1 (
  echo [FEHLER] Python konnte nicht gestartet werden: %PYTHON_EXE%
  goto :BUILD_FAILED
)

if not exist "dragontools\core\version.py" (
  echo [FEHLER] Versionsdatei fehlt: dragontools\core\version.py
  goto :BUILD_FAILED
)

REM Eine einzige Versionsquelle fuer App, Build-Ordner und EXE.
REM Kein FOR /F mit eingebettetem Python-Kommando: dessen zusaetzliche
REM cmd.exe-Quote-Ebene zerlegt auf Windows Pfade/Argumente beim Doppelklick.
set "VERSION_TMP=%TEMP%\dragontools_app_version_%RANDOM%_%RANDOM%.tmp"
"%PYTHON_EXE%" -c "import runpy; print(runpy.run_path(r'dragontools\core\version.py')['APP_VERSION'])" > "%VERSION_TMP%"
if errorlevel 1 (
  if exist "%VERSION_TMP%" del /q "%VERSION_TMP%" >nul 2>nul
  echo [FEHLER] APP_VERSION konnte nicht aus dragontools\core\version.py gelesen werden.
  goto :BUILD_FAILED
)
set /p "APP_VERSION=" < "%VERSION_TMP%"
del /q "%VERSION_TMP%" >nul 2>nul
if not defined APP_VERSION (
  echo [FEHLER] APP_VERSION ist leer. Pruefe dragontools\core\version.py.
  goto :BUILD_FAILED
)
echo [INFO] Erkannte App-Version: %APP_VERSION%
set "BUILD_NAME=DragonToolsV%APP_VERSION%"
set "DIST_ROOT=dist\%BUILD_NAME%"
set "DATA_ROOT=%DIST_ROOT%\Daten"

echo [INFO] Baue %BUILD_NAME%

REM Release-Dokumente / Ressourcen.
if not exist "Handbuch" mkdir "Handbuch"
if not exist "Handbuch\Handbuch.pdf" if exist "Handbuch.pdf" copy /Y "Handbuch.pdf" "Handbuch\Handbuch.pdf" >nul
for %%F in (
  "help.html"
  "Handbuch\Handbuch.pdf"
  "Aenderungshistorie\CHANGELOG.json"
  "Aenderungshistorie\CHANGELOG.txt"
  "icon\Feuerdrache.ico"
  "Bilder\banner.png"
  "Bilder\splash_Intro.png"
  "Bilder\splash_pyinstaller.png"
) do (
  if not exist %%F (
    echo [FEHLER] Erforderliche Build-Datei fehlt: %%~F
    goto :BUILD_FAILED
  )
)

REM Python-/Build-Abhaengigkeiten aus derselben Umgebung wie die App.
for %%M in (PyInstaller PyQt6 numpy cv2 cryptography) do (
  "%PYTHON_EXE%" -c "import %%M" >nul 2>nul
  if errorlevel 1 (
    echo [FEHLER] Python-Modul %%M fehlt in der verwendeten Umgebung.
    echo          Installiere reproduzierbar mit: "%PYTHON_EXE%" -m pip install -r requirements-build.txt
    goto :BUILD_FAILED
  )
)
"%PYTHON_EXE%" -m pip show pyinstaller-hooks-contrib >nul 2>nul
if errorlevel 1 (
  echo [FEHLER] pyinstaller-hooks-contrib fehlt.
  echo          Installiere reproduzierbar mit: "%PYTHON_EXE%" -m pip install -r requirements-build.txt
  goto :BUILD_FAILED
)

REM Paketdaten muessen am Runtime-Paketpfad vorhanden sein.
for %%F in (
  default_audio_rules.json
  default_move_rules.json
  default_profiles.json
  default_renamer_rules.json
  default_subtitle_rules.json
) do (
  if not exist "dragontools\config\%%F" (
    echo [FEHLER] dragontools\config\%%F wurde nicht gefunden.
    goto :BUILD_FAILED
  )
)

REM Das oeffentliche Programmpaket enthaelt bewusst keine Drittanbieterprogramme.
REM Anwender laden benoetigte Werkzeuge von den offiziellen Projektseiten herunter
REM und konfigurieren deren Pfade in DragonTools. Siehe TOOLS_INSTALLIEREN.txt.
if not exist "TOOLS_INSTALLIEREN.txt" (
  echo [FEHLER] Werkzeughinweise fehlen: TOOLS_INSTALLIEREN.txt
  goto :BUILD_FAILED
)

REM Vor dem Source-Release-Check alte App-Bundles entfernen.
REM validate_release(..., mode='source') prueft einen vorhandenen dist-Build ebenfalls.
REM Ein Build aus einem aelteren Quellstand darf deshalb den neuen Build nicht blockieren.
REM Wir loeschen erst hier: Alle erforderlichen Eingaben, Tools und Python-Abhaengigkeiten
REM wurden oben bereits fail-fast geprueft, sodass ein vorhandener funktionierender Build
REM nicht unnoetig verloren geht.
set "LEGACY_DIST_ROOT=dist\DragonToolsV9"

if exist "%DIST_ROOT%" (
  echo [INFO] Alter Build wird vor der Source-Pruefung entfernt: %DIST_ROOT%
  rmdir /S /Q "%DIST_ROOT%"
  if exist "%DIST_ROOT%" (
    echo [FEHLER] Alter Build-Ordner konnte nicht entfernt werden: %DIST_ROOT%
    echo [HINWEIS] Schliesse ggf. eine laufende DragonTools-EXE oder Prozesse, die Dateien im dist-Ordner verwenden.
    goto :BUILD_FAILED
  )
)

REM release_validation akzeptiert neben DragonToolsV<APP_VERSION> aus Kompatibilitaetsgruenden
REM auch dist\DragonToolsV9. Auch dieser Ordner kann sonst als veralteter Build erkannt werden.
if exist "%LEGACY_DIST_ROOT%" (
  echo [INFO] Alter Legacy-Build wird vor der Source-Pruefung entfernt: %LEGACY_DIST_ROOT%
  rmdir /S /Q "%LEGACY_DIST_ROOT%"
  if exist "%LEGACY_DIST_ROOT%" (
    echo [FEHLER] Alter Legacy-Build-Ordner konnte nicht entfernt werden: %LEGACY_DIST_ROOT%
    echo [HINWEIS] Schliesse ggf. eine laufende DragonTools-EXE oder Prozesse, die Dateien im dist-Ordner verwenden.
    goto :BUILD_FAILED
  )
)

REM Alte Test-/Bytecode-Artefakte beseitigen, danach ausschliesslich den aktuellen
REM Source-Stand pruefen. Der neue dist-Build wird erst nach PyInstaller separat validiert.
"%PYTHON_EXE%" -B -c "from dragontools.core.release_packaging import clean_forbidden_release_artifacts; removed=clean_forbidden_release_artifacts('.'); print('[INFO] Release-Caches entfernt:', len(removed))"
if errorlevel 1 goto :BUILD_FAILED
"%PYTHON_EXE%" -B -c "from dragontools.core.release_validation import validate_release, format_release_checks; c=validate_release('.', mode='source'); print(format_release_checks(c)); raise SystemExit(1 if any(x.status == 'error' for x in c) else 0)"
if errorlevel 1 (
  echo [FEHLER] Source-Release-Pruefung fehlgeschlagen.
  goto :BUILD_FAILED
)

REM Versionsinfo fuer reproduzierbare Build-Logs.
"%PYTHON_EXE%" -c "import sys, PyInstaller, PyQt6, cv2, numpy, cryptography; print('[INFO] App:', '%BUILD_NAME%'); print('[INFO] Python:', sys.version.split()[0]); print('[INFO] PyInstaller:', PyInstaller.__version__); print('[INFO] PyQt6:', getattr(PyQt6, '__version__', 'installiert')); print('[INFO] OpenCV:', cv2.__version__); print('[INFO] NumPy:', numpy.__version__); print('[INFO] cryptography:', cryptography.__version__)"

"%PYTHON_EXE%" -m PyInstaller ^
  --onedir ^
  --noconsole ^
  --noconfirm ^
  --clean ^
  --name "%BUILD_NAME%" ^
  --icon "icon\Feuerdrache.ico" ^
  --splash "Bilder\splash_pyinstaller.png" ^
  --contents-directory "Daten" ^
  --exclude-module PyQt5 ^
  --exclude-module PySide6 ^
  --exclude-module PySide2 ^
  --exclude-module PyQt6.QtWebEngineWidgets ^
  --hidden-import cv2 ^
  --collect-submodules cv2 ^
  --collect-binaries cv2 ^
  --collect-data cv2 ^
  --collect-submodules cryptography ^
  --collect-binaries cryptography ^
  --collect-data cryptography ^
  --add-data "icon\Feuerdrache.ico;icon" ^
  --add-data "help.html;." ^
  --add-data "Handbuch\Handbuch.pdf;Handbuch" ^
  --add-data "Aenderungshistorie\CHANGELOG.json;Aenderungshistorie" ^
  --add-data "Aenderungshistorie\CHANGELOG.txt;Aenderungshistorie" ^
  --add-data "Aenderungshistorie\CHANGELOGV8.txt;Aenderungshistorie" ^
  --add-data "Aenderungshistorie\CHANGELOGV7.txt;Aenderungshistorie" ^
  --add-data "Bilder\banner.png;Bilder" ^
  --add-data "Bilder\splash_Intro.png;Bilder" ^
  --add-data "TOOLS_INSTALLIEREN.txt;Programme" ^
  --add-data "dragontools\config;dragontools\config" ^
  --add-data "dragontools;Python\dragontools" ^
  --add-data "DragonToolsV9.py;Python" ^
  DragonToolsV9.py

if errorlevel 1 (
  echo [FEHLER] PyInstaller-Build fehlgeschlagen.
  goto :BUILD_FAILED
)

REM Die Werkzeuganleitung liegt zusaetzlich direkt neben der EXE, damit sie
REM vor dem ersten Programmstart ohne Suche auffindbar ist.
copy /Y "TOOLS_INSTALLIEREN.txt" "%DIST_ROOT%\TOOLS_INSTALLIEREN.txt" >nul
if errorlevel 1 (
  echo [FEHLER] Werkzeuganleitung konnte nicht in den Build kopiert werden.
  goto :BUILD_FAILED
)

REM Der Abschlusscheck verwendet exakt denselben dynamischen Buildnamen.
if not exist "%DIST_ROOT%\%BUILD_NAME%.exe" (
  echo [FEHLER] Build-EXE fehlt: %DIST_ROOT%\%BUILD_NAME%.exe
  goto :BUILD_FAILED
)
for %%F in (
  "%DATA_ROOT%\help.html"
  "%DATA_ROOT%\Handbuch\Handbuch.pdf"
  "%DATA_ROOT%\Aenderungshistorie\CHANGELOG.json"
  "%DIST_ROOT%\TOOLS_INSTALLIEREN.txt"
  "%DATA_ROOT%\Programme\TOOLS_INSTALLIEREN.txt"
  "%DATA_ROOT%\dragontools\config\default_profiles.json"
  "%DATA_ROOT%\dragontools\config\default_renamer_rules.json"
  "%DATA_ROOT%\Python\dragontools\__init__.py"
  "%DATA_ROOT%\Python\DragonToolsV9.py"
) do (
  if not exist %%F (
    echo [FEHLER] Build-Artefakt fehlt: %%~F
    goto :BUILD_FAILED
  )
)

REM App-Bundle mit derselben Release-Pruefung validieren.
"%PYTHON_EXE%" -B -c "from dragontools.core.release_validation import validate_release, format_release_checks; c=validate_release(r'%DIST_ROOT%', mode='app'); print(format_release_checks(c)); raise SystemExit(1 if any(x.status == 'error' for x in c) else 0)"
if errorlevel 1 (
  echo [FEHLER] Finale App-Bundle-Pruefung fehlgeschlagen.
  goto :BUILD_FAILED
)

echo.
echo [OK] %BUILD_NAME% wurde erfolgreich gebaut und validiert.
echo [OK] Ausgabe: %DIST_ROOT%
goto :BUILD_SUCCESS


:BUILD_SUCCESS
set "BUILD_RC=0"
echo.
echo ============================================================
echo [OK] Build-Skript beendet. Das Fenster bleibt zur Kontrolle offen.
echo ============================================================
goto :BUILD_FINISH

:BUILD_FAILED
set "BUILD_RC=1"
echo.
echo ============================================================
echo [FEHLER] Build wurde abgebrochen.
echo [HINWEIS] Die eigentliche Fehlermeldung steht direkt oberhalb dieses Blocks.
echo ============================================================
goto :BUILD_FINISH

:BUILD_FAILED_NO_POPD
set "BUILD_RC=1"
echo.
echo ============================================================
echo [FEHLER] Build konnte nicht gestartet werden.
echo ============================================================
goto :BUILD_FINISH_NO_POPD

:BUILD_FINISH
popd

:BUILD_FINISH_NO_POPD
REM Fuer automatisierte Aufrufe kann das Pause-Fenster mit
REM   set DRAGONTOOLS_BUILD_NO_PAUSE=1
REM unterdrueckt werden.
if not defined DRAGONTOOLS_BUILD_NO_PAUSE pause
exit /b %BUILD_RC%
