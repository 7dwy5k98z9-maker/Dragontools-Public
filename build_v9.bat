@echo off
setlocal EnableExtensions
set "BACKUP_CREATED="
set "LEGACY_BACKUP_CREATED="
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM Immer aus dem Ordner dieser BAT arbeiten. Wichtig bei Doppelklick/Verknuepfungen.
pushd "%~dp0"
if errorlevel 1 (
  echo [FEHLER] Projektordner der Build-Datei konnte nicht geoeffnet werden: %~dp0
  goto :BUILD_FAILED_NO_POPD
)
echo [INFO] Arbeitsverzeichnis: %CD%

REM Oeffentliche Arbeitskopie: PDF-Pruefung ist standardmaessig aktiv.
set "CHECK_PDF_PRIVACY=True"
:BUILD_ARGUMENTS
if "%~1"=="" goto :BUILD_ARGUMENTS_DONE
if /I "%~1"=="--private" (
  set "CHECK_PDF_PRIVACY=False"
  shift
  goto :BUILD_ARGUMENTS
)
if /I "%~1"=="--public" (
  set "CHECK_PDF_PRIVACY=True"
  shift
  goto :BUILD_ARGUMENTS
)
echo [FEHLER] Unbekanntes Build-Argument: %~1. Erlaubt: --private oder --public.
goto :BUILD_FAILED
:BUILD_ARGUMENTS_DONE

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
set "BACKUP_DIST_ROOT=%DIST_ROOT%.__previous__"

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

REM PDF-Pruefung nur fuer oeffentliche Builds; Reparatur vor jeder Dist-Aenderung.
if "%CHECK_PDF_PRIVACY%"=="True" (
  echo [INFO] Oeffentlicher Build: Pruefe PDF-Pruefung inklusive Versionsgrenzen ...
  "%PYTHON_EXE%" -B -c "from pypdf import PdfReader; from importlib.metadata import version; major=int(version('pypdf').split('.')[0]); print('[INFO] pypdf:', version('pypdf')); raise SystemExit(0 if 5 <= major < 7 else 2)"
  if errorlevel 1 (
    echo [INFO] Installiere/repariere pypdf fuer die PDF-Datenschutzpruefung ...
    "%PYTHON_EXE%" -m pip --version >nul 2>nul
    if errorlevel 1 (
      echo [FEHLER] pip ist in der verwendeten Build-Umgebung nicht verfuegbar.
      goto :BUILD_FAILED
    )
    "%PYTHON_EXE%" -m pip install "pypdf>=5,<7"
    if errorlevel 1 (
      echo [FEHLER] pypdf konnte nicht installiert werden. Pruefe pip und die Internetverbindung.
      goto :BUILD_FAILED
    )
  )
  "%PYTHON_EXE%" -B -c "from pypdf import PdfReader; from importlib.metadata import version; major=int(version('pypdf').split('.')[0]); raise SystemExit(0 if 5 <= major < 7 else 2)"
  if errorlevel 1 (
    echo [FEHLER] PDF-Pruefung ist nach der Installation weiterhin nicht verfuegbar.
    goto :BUILD_FAILED
  )
) else (
  echo [INFO] Privater Build: PDF-Datenschutzpruefung wird ausgelassen.
)

REM faster-whisper/CTranslate2 werden fuer die offizielle EXE mitgebuendelt.
REM Nicht nur die Importierbarkeit, sondern auch die freigegebenen Versionen
REM werden geprueft. Fehlt ein Paket oder liegt es ausserhalb der Constraints,
REM repariert die BAT ausschliesslich requirements-whisper.txt.
if not exist "requirements-whisper.txt" (
  echo [FEHLER] Whisper-Requirements fehlen: requirements-whisper.txt
  goto :BUILD_FAILED
)
echo [INFO] Pruefe faster-whisper / CTranslate2 inklusive Versionsgrenzen ...
"%PYTHON_EXE%" -c "from importlib.metadata import version; import re; vt=lambda n: tuple(int(x) for x in re.findall(r'\d+', version(n))[:3]); fw=vt('faster-whisper'); ct=vt('ctranslate2'); import faster_whisper, ctranslate2; print('[INFO] faster-whisper:', version('faster-whisper')); print('[INFO] CTranslate2:', version('ctranslate2')); raise SystemExit(0 if (fw >= (1,1) and fw < (2,) and ct >= (4,4) and ct < (5,)) else 2)"
if errorlevel 1 (
  echo [INFO] Whisper-Pakete fehlen oder liegen ausserhalb der freigegebenen Versionen.
  echo [INFO] Installiere/repariere nur requirements-whisper.txt ...
  "%PYTHON_EXE%" -m pip --version >nul 2>nul
  if errorlevel 1 (
    echo [FEHLER] pip ist in der verwendeten Build-Umgebung nicht verfuegbar.
    goto :BUILD_FAILED
  )
  "%PYTHON_EXE%" -m pip install -r requirements-whisper.txt
  if errorlevel 1 (
    echo [FEHLER] faster-whisper/CTranslate2 konnten nicht installiert werden.
    goto :BUILD_FAILED
  )
)
"%PYTHON_EXE%" -c "from importlib.metadata import version; import re; vt=lambda n: tuple(int(x) for x in re.findall(r'\d+', version(n))[:3]); fw=vt('faster-whisper'); ct=vt('ctranslate2'); import faster_whisper, ctranslate2; print('[INFO] faster-whisper:', version('faster-whisper')); print('[INFO] CTranslate2:', version('ctranslate2')); raise SystemExit(0 if (fw >= (1,1) and fw < (2,) and ct >= (4,4) and ct < (5,)) else 2)"
if errorlevel 1 (
  echo [FEHLER] faster-whisper/CTranslate2 sind nach der Installation nicht in den freigegebenen Versionen verfuegbar.
  goto :BUILD_FAILED
)

REM Python-/Build-Abhaengigkeiten aus derselben Umgebung wie die App.
for %%M in (PyInstaller PyQt6 numpy cv2 cryptography defusedxml faster_whisper ctranslate2) do (
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

REM Public-Build: externe Medienwerkzeuge werden separat installiert.
REM Vor dem Source-Release-Check alte App-Bundles entfernen.
REM validate_release(..., mode='source') prueft einen vorhandenen dist-Build ebenfalls.
REM Ein Build aus einem aelteren Quellstand darf deshalb den neuen Build nicht blockieren.
REM Wir loeschen erst hier: Alle erforderlichen Eingaben, Tools und Python-Abhaengigkeiten
REM wurden oben bereits fail-fast geprueft, sodass ein vorhandener funktionierender Build
REM nicht unnoetig verloren geht.
set "LEGACY_DIST_ROOT=dist\DragonToolsV9"
set "LEGACY_BACKUP_DIST_ROOT=%LEGACY_DIST_ROOT%.__previous__"
set "LEGACY_BACKUP_CREATED="

if exist "%LEGACY_BACKUP_DIST_ROOT%" (
  echo [FEHLER] Legacy-Sicherung aus vorherigem Build vorhanden: %LEGACY_BACKUP_DIST_ROOT%
  goto :BUILD_FAILED
)

if exist "%BACKUP_DIST_ROOT%" (
  echo [FEHLER] Build-Sicherung aus vorherigem Lauf vorhanden: %BACKUP_DIST_ROOT%
  goto :BUILD_FAILED
)
if exist "%DIST_ROOT%" (
  echo [INFO] Vorhandener funktionierender Build wird bis zum erfolgreichen Abschluss gesichert: %BACKUP_DIST_ROOT%
  move /Y "%DIST_ROOT%" "%BACKUP_DIST_ROOT%" >nul
  if errorlevel 1 (
    echo [FEHLER] Vorhandener Build konnte nicht gesichert werden: %DIST_ROOT%
    echo [HINWEIS] Schliesse ggf. eine laufende DragonTools-EXE oder Prozesse, die Dateien im dist-Ordner verwenden.
    goto :BUILD_FAILED
  )
  set "BACKUP_CREATED=1"
)

REM release_validation akzeptiert neben DragonToolsV<APP_VERSION> aus Kompatibilitaetsgruenden
REM auch dist\DragonToolsV9. Auch dieser Ordner kann sonst als veralteter Build erkannt werden.
if exist "%LEGACY_DIST_ROOT%" (
  echo [INFO] Legacy-Build wird bis zum erfolgreichen Abschluss gesichert: %LEGACY_DIST_ROOT%
  move /Y "%LEGACY_DIST_ROOT%" "%LEGACY_BACKUP_DIST_ROOT%" >nul
  if errorlevel 1 (
    echo [FEHLER] Legacy-Build-Ordner konnte nicht gesichert werden: %LEGACY_DIST_ROOT%
    echo [HINWEIS] Schliesse ggf. eine laufende DragonTools-EXE oder Prozesse, die Dateien im dist-Ordner verwenden.
    goto :BUILD_FAILED
  )
  set "LEGACY_BACKUP_CREATED=1"
)

REM Alte Test-/Bytecode-Artefakte beseitigen, danach ausschliesslich den aktuellen
REM Source-Stand pruefen. Der neue dist-Build wird erst nach PyInstaller separat validiert.
"%PYTHON_EXE%" -B -c "from dragontools.core.release_packaging import clean_forbidden_release_artifacts; removed=clean_forbidden_release_artifacts('.'); print('[INFO] Release-Caches entfernt:', len(removed))"
if errorlevel 1 goto :BUILD_FAILED
"%PYTHON_EXE%" -B -c "from dragontools.core.release_validation import validate_release, format_release_checks; c=validate_release('.', mode='source', check_pdf_privacy=%CHECK_PDF_PRIVACY%); print(format_release_checks(c)); raise SystemExit(1 if any(x.status == 'error' for x in c) else 0)"
if errorlevel 1 (
  echo [FEHLER] Source-Release-Pruefung fehlgeschlagen.
  goto :BUILD_FAILED
)

REM Versionsinfo fuer reproduzierbare Build-Logs.
"%PYTHON_EXE%" -c "import sys, PyInstaller, PyQt6, cv2, numpy, cryptography, defusedxml, ctranslate2; print('[INFO] App:', '%BUILD_NAME%'); print('[INFO] Python:', sys.version.split()[0]); print('[INFO] PyInstaller:', PyInstaller.__version__); print('[INFO] PyQt6:', getattr(PyQt6, '__version__', 'installiert')); print('[INFO] OpenCV:', cv2.__version__); print('[INFO] NumPy:', numpy.__version__); print('[INFO] CTranslate2:', getattr(ctranslate2, '__version__', 'installiert')); print('[INFO] cryptography:', cryptography.__version__); print('[INFO] defusedxml:', getattr(defusedxml, '__version__', 'installiert'))"

"%PYTHON_EXE%" -m extras.release_pyinstaller ^
  --onedir ^
  --noconsole ^
  --noconfirm ^
  --clean ^
  --name "%BUILD_NAME%" ^
  --icon "icon\Feuerdrache.ico" ^
  --splash "Bilder\splash_pyinstaller.png" ^
  --contents-directory "Daten" ^
  --collect-submodules dragontools ^
  --exclude-module dragontools.tests ^
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
  --hidden-import faster_whisper ^
  --hidden-import ctranslate2 ^
  --collect-submodules faster_whisper ^
  --collect-binaries faster_whisper ^
  --collect-data faster_whisper ^
  --collect-submodules ctranslate2 ^
  --collect-binaries ctranslate2 ^
  --collect-data ctranslate2 ^
  --copy-metadata faster-whisper ^
  --copy-metadata ctranslate2 ^
  --add-data "icon\Feuerdrache.ico;icon" ^
  --add-data "help.html;." ^
  --add-data "Handbuch\Handbuch.pdf;Handbuch" ^
  --add-data "Aenderungshistorie\CHANGELOG.json;Aenderungshistorie" ^
  --add-data "Aenderungshistorie\CHANGELOG.txt;Aenderungshistorie" ^
  --add-data "Aenderungshistorie\CHANGELOGV8.txt;Aenderungshistorie" ^
  --add-data "Aenderungshistorie\CHANGELOGV7.txt;Aenderungshistorie" ^
  --add-data "Bilder\banner.png;Bilder" ^
  --add-data "Bilder\splash_Intro.png;Bilder" ^
  --add-data "dragontools\config;dragontools\config" ^
  DragonToolsV9.py

if errorlevel 1 (
  echo [FEHLER] PyInstaller-Build fehlgeschlagen.
  goto :BUILD_FAILED
)

REM Gleiche Qt-/ICU-Policy wie im nativen CI-Smoke. Nur nachgewiesen
REM inkompatible ICU-Kopien entfernen; kompatible DLLs und andere Artefakte bleiben.
"%PYTHON_EXE%" -m dragontools.core.release_qt_icu "%DATA_ROOT%"
if errorlevel 1 (
  echo [FEHLER] Qt-/ICU-Vertrag des Builds ist nicht erfuellt.
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
  "%DATA_ROOT%\dragontools\config\default_profiles.json"
  "%DATA_ROOT%\dragontools\config\default_renamer_rules.json"
) do (
  if not exist %%F (
    echo [FEHLER] Build-Artefakt fehlt: %%~F
    goto :BUILD_FAILED
  )
)

REM Source-free Release-Vertrag: lesbare Projektquellen duerfen nicht separat
REM unter Daten\Python ausgeliefert werden. PyInstaller enthaelt den Code intern.
if exist "%DATA_ROOT%\Python" (
  echo [FEHLER] Unerwarteter Python-Quellordner im Build: %DATA_ROOT%\Python
  goto :BUILD_FAILED
)

REM Public-Vertrag: Installationshinweise und Inhaltspruefung.
if not exist "%DATA_ROOT%\Programme" mkdir "%DATA_ROOT%\Programme"
copy /Y "TOOLS_INSTALLIEREN.txt" "%DIST_ROOT%\TOOLS_INSTALLIEREN.txt" >nul
if errorlevel 1 goto :BUILD_FAILED
copy /Y "AUTHORS.md" "%DIST_ROOT%\AUTHORS.md" >nul
if errorlevel 1 goto :BUILD_FAILED
"%PYTHON_EXE%" -B "scripts\check_public_bundle.py" "%DIST_ROOT%"
if errorlevel 1 goto :BUILD_FAILED

REM App-Bundle mit derselben Release-Pruefung validieren.
"%PYTHON_EXE%" -B -c "from dragontools.core.release_validation import validate_release, format_release_checks; c=validate_release(r'%DIST_ROOT%', mode='app'); print(format_release_checks(c)); raise SystemExit(1 if any(x.status == 'error' for x in c) else 0)"
if errorlevel 1 (
  echo [FEHLER] Finale App-Bundle-Pruefung fehlgeschlagen.
  goto :BUILD_FAILED
)

REM Der entscheidende Smoke laeuft gegen EXAKT die finale Release-EXE und
REM initialisiert eine echte QApplication. Damit werden insbesondere fehlende
REM Qt-Platform-Plugins und Frozen-Importprobleme erkannt.
echo [INFO] Starte finalen Frozen-Runtime-Smoke mit 90s Timeout: %DIST_ROOT%\%BUILD_NAME%.exe --smoke-test
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath '%DIST_ROOT%\%BUILD_NAME%.exe' -ArgumentList '--smoke-test' -WindowStyle Hidden -PassThru; if (-not $p.WaitForExit(90000)) { try { $p.Kill($true) } catch {}; Write-Error 'DragonTools Frozen-Smoke Timeout nach 90s.'; exit 124 }; exit $p.ExitCode"
if errorlevel 1 (
  echo [FEHLER] Die finale DragonTools-EXE besteht den Frozen-Runtime-Smoke nicht oder hat das 90s-Zeitlimit ueberschritten.
  goto :BUILD_FAILED
)

if exist "%BACKUP_DIST_ROOT%" rmdir /S /Q "%BACKUP_DIST_ROOT%"
if defined LEGACY_BACKUP_CREATED if exist "%LEGACY_BACKUP_DIST_ROOT%" rmdir /S /Q "%LEGACY_BACKUP_DIST_ROOT%"
echo.
echo [OK] %BUILD_NAME% wurde erfolgreich gebaut, validiert und gestartet.
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
if defined LEGACY_BACKUP_CREATED (
  move /Y "%LEGACY_BACKUP_DIST_ROOT%" "%LEGACY_DIST_ROOT%" >nul
  if errorlevel 1 echo [WARNUNG] Legacy-Build bleibt gesichert unter: %LEGACY_BACKUP_DIST_ROOT%
)
REM Ein fehlgeschlagener Releasebuild darf den letzten funktionierenden Build nicht zerstoeren.
if defined BACKUP_CREATED if exist "%BACKUP_DIST_ROOT%" (
  if exist "%DIST_ROOT%" rmdir /S /Q "%DIST_ROOT%"
  move /Y "%BACKUP_DIST_ROOT%" "%DIST_ROOT%" >nul
  if errorlevel 1 echo [WARNUNG] Vorheriger Build konnte nicht automatisch wiederhergestellt werden: %BACKUP_DIST_ROOT%
)
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
