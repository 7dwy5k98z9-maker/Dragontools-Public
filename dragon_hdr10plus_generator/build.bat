@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Standalone build. Prefer an environment local to this subproject, then the
rem DragonTools environment, then a normal system Python installation.
set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist "%CD%\.venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%CD%\..\.venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\..\.venv\Scripts\python.exe"
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
    echo FEHLER: Keine nutzbare Python-Installation gefunden.
    goto :failed
)

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import sys; assert sys.version_info >= (3, 12); print(sys.executable, sys.version.split()[0])"
if errorlevel 1 goto :failed

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import numpy; from packaging.version import Version; assert Version(numpy.__version__) < Version('3')" >nul 2>&1
if errorlevel 1 (
    echo Installiere kompatibles NumPy...
    "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install "numpy>=2,<3" "packaging>=24,<26"
    if errorlevel 1 goto :failed
)

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import PyInstaller; from packaging.version import Version; v=Version(PyInstaller.__version__); assert Version('6.10') <= v < Version('7')" >nul 2>&1
if errorlevel 1 (
    echo Installiere kompatibles PyInstaller...
    "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install "PyInstaller>=6.10,<7" "packaging>=24,<26"
    if errorlevel 1 goto :failed
)

echo Baue HDRPlusGenerator.exe...
"%PYTHON_EXE%" %PYTHON_ARGS% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --console ^
    --name HDRPlusGenerator ^
    --paths "%CD%\src" ^
    --distpath "%CD%\dist" ^
    --workpath "%CD%\build" ^
    --specpath "%CD%\build" ^
    "%CD%\hdrplusgenerator_entry.py"

if errorlevel 1 goto :failed
if not exist "%CD%\dist\HDRPlusGenerator.exe" goto :failed

echo.
echo Pruefe gebaute EXE und strukturierten Versionsvertrag...
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import json, subprocess; exe=r'%CD%\dist\HDRPlusGenerator.exe'; p=subprocess.run([exe,'--version'],capture_output=True,text=True,timeout=30); print(p.stdout.strip()); data=json.loads(p.stdout); assert p.returncode == 0 and data.get('success') is True and data.get('version'), p.stderr or p.stdout"
if errorlevel 1 (
    echo FEHLER: HDRPlusGenerator.exe wurde gebaut, besteht den Runtime-/Versions-Smoke aber nicht.
    goto :failed
)

echo.
echo Fertig:
echo %CD%\dist\HDRPlusGenerator.exe
echo.
if not defined DRAGON_HDRPLUS_BUILD_NO_PAUSE pause
exit /b 0

:failed
echo.
echo FEHLER: Der Build ist fehlgeschlagen.
echo.
if not defined DRAGON_HDRPLUS_BUILD_NO_PAUSE pause
exit /b 1
