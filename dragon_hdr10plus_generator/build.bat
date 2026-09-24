@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=..\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo FEHLER: Python-Umgebung nicht gefunden:
    echo %PYTHON%
    echo.
    pause
    exit /b 1
)

"%PYTHON%" -c "import numpy" >nul 2>&1
if errorlevel 1 (
    echo NumPy wird installiert...
    "%PYTHON%" -m pip install "numpy>=2.0"
    if errorlevel 1 goto :failed
)

"%PYTHON%" -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo PyInstaller wird installiert...
    "%PYTHON%" -m pip install PyInstaller
    if errorlevel 1 goto :failed
)

echo Baue HDRPlusGenerator.exe...
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --console ^
    --name HDRPlusGenerator ^
    --paths "%CD%\src" ^
    --distpath "%CD%\dist" ^
    --workpath "%CD%\build" ^
    --specpath "%CD%" ^
    "%CD%\hdrplusgenerator_entry.py"

if errorlevel 1 goto :failed

echo.
echo Fertig:
echo %CD%\dist\HDRPlusGenerator.exe
echo.
"%CD%\dist\HDRPlusGenerator.exe" --version
echo.
pause
exit /b 0

:failed
echo.
echo FEHLER: Der Build ist fehlgeschlagen.
echo.
pause
exit /b 1
