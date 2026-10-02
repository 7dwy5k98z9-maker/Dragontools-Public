@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem ============================================================
rem DragonTools - öffentlicher Source-ZIP
rem
rem WICHTIG: Diese BAT besitzt KEINE eigene Datei-Inventarlogik mehr.
rem Der kanonische Vertrag liegt ausschließlich in
rem dragontools.core.release_packaging.create_source_release_zip().
rem Dadurch erzeugen BAT und Python-Packager exakt denselben Inhalt.
rem ============================================================

echo.
echo ============================================================
echo DragonTools - Public Source ZIP
echo ============================================================
echo Project root: %CD%
echo.

set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
    )
)
if not defined PYTHON_EXE (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    echo [ERROR] Keine Python-Installation gefunden.
    goto :fail
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
set "OUTZIP=%CD%\DragonTools_Source_%STAMP%.zip"

echo [1/2] Kanonisches Source-ZIP erstellen...
"%PYTHON_EXE%" %PYTHON_ARGS% -B -c "from dragontools.core.release_packaging import create_source_release_zip; print(create_source_release_zip('.', r'%OUTZIP%'))"
if errorlevel 1 goto :fail
if not exist "%OUTZIP%" goto :fail

echo [2/2] Gepacktes ZIP erneut validieren...
"%PYTHON_EXE%" %PYTHON_ARGS% -B -c "import tempfile, zipfile; from pathlib import Path; from dragontools.core.release_validation import validate_release, format_release_checks; z=Path(r'%OUTZIP%'); t=tempfile.TemporaryDirectory(); root=Path(t.name); a=zipfile.ZipFile(z); assert a.testzip() is None, 'CRC-Fehler'; a.extractall(root); a.close(); c=validate_release(root, mode='source'); print(format_release_checks(c)); t.cleanup(); raise SystemExit(1 if any(x.status == 'error' for x in c) else 0)"
if errorlevel 1 goto :fail

echo.
echo [OK] Public Source ZIP:
echo %OUTZIP%
echo.
if not defined DRAGONTOOLS_SOURCE_ZIP_NO_PAUSE pause
exit /b 0

:fail
echo.
echo [ERROR] Source ZIP wurde nicht erstellt bzw. nicht validiert.
echo.
if not defined DRAGONTOOLS_SOURCE_ZIP_NO_PAUSE pause
exit /b 1
