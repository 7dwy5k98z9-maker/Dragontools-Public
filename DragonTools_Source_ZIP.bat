@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem ============================================================
rem DragonTools - Source ZIP
rem
rem Place this BAT beside build_v9.bat and run it.
rem It creates a source/documentation ZIP WITHOUT:
rem   build, dist, third_party/thirdparty, .venv/venv,
rem   caches, logs, pyc/pyo, temp/backup files.
rem ============================================================

echo.
echo ============================================================
echo DragonTools - Source ZIP [Patch AI HDRTVDM ComfyUI profile]
echo ============================================================
echo Project root: %CD%
echo Script: %~f0
echo.

rem --- Minimal project checks ---
if not exist "build_v9.bat" (
    echo [ERROR] build_v9.bat was not found beside this file.
    goto :fail
)

if not exist "dragontools\" (
    echo [ERROR] Folder "dragontools" was not found.
    goto :fail
)

rem --- Timestamp ---
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"

set "ZIPNAME=DragonTools_Source_%STAMP%.zip"
set "OUTZIP=%CD%\%ZIPNAME%"
set "STAGE=%TEMP%\DragonTools_Source_%STAMP%_%RANDOM%"

if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Could not create temporary staging folder:
    echo         %STAGE%
    goto :fail
)

echo [1/4] Copy source folders...

rem Required source folders. These must exist and must be copied.
call :CopyRequiredDir "dragontools"
if errorlevel 1 goto :cleanup_fail

rem Standalone project: intentionally separate from the DragonTools PyInstaller app.
call :CopyRequiredDir "dragon_hdr10plus_generator"
if errorlevel 1 goto :cleanup_fail

call :CopyRequiredDir ".github"
if errorlevel 1 goto :cleanup_fail

rem Optional legacy/top-level source folders - copied only when present.
call :CopyOptionalDir "tests"
if errorlevel 1 goto :cleanup_fail

call :CopyOptionalDir "config"
if errorlevel 1 goto :cleanup_fail

call :CopyOptionalDir "core"
if errorlevel 1 goto :cleanup_fail

call :CopyOptionalDir "gui"
if errorlevel 1 goto :cleanup_fail

call :CopyOptionalDir "rules"
if errorlevel 1 goto :cleanup_fail

call :CopyOptionalDir "subtitle"
if errorlevel 1 goto :cleanup_fail

call :CopyOptionalDir "worker"
if errorlevel 1 goto :cleanup_fail

rem Documentation/resources that belong to the source project.
call :CopyOptionalDir "Handbuch"
if errorlevel 1 goto :cleanup_fail

call :CopyOptionalDir "Aenderungshistorie"
if errorlevel 1 goto :cleanup_fail

call :CopyOptionalDir "icon"
if errorlevel 1 goto :cleanup_fail

call :CopyOptionalDir "Bilder"
if errorlevel 1 goto :cleanup_fail

rem Optional ComfyUI bridge nodes and integration assets.
call :CopyOptionalDir "extras"
if errorlevel 1 goto :cleanup_fail


echo [2/4] Copy root project files...

rem All root Python sources
for %%F in (*.py) do (
    if exist "%%F" copy /y "%%F" "%STAGE%\" >nul
)

rem Required root files are staged explicitly so release-contract tests and
rem failures identify the exact missing file.
call :CopyRequiredFile "build_v9.bat"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "DragonTools_Source_ZIP.bat"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "README.md"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "PATCH.md"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "help.html"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "release_manifest.json"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "pytest.ini"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "INTEGRATION_TESTS.md"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "COMFYUI_HDR_SETUP.md"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "requirements-runtime.txt"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "requirements-optional.txt"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "requirements-test.txt"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "requirements-build.txt"
if errorlevel 1 goto :cleanup_fail
call :CopyRequiredFile "requirements-whisper.txt"
if errorlevel 1 goto :cleanup_fail

call :CopyFile "build_v9_angepasst.bat"

rem PyInstaller .spec files are generated build artifacts for the active CLI build
rem and are intentionally not part of the source archive.

rem Copy any additional requirements files not covered by the required contract.
for %%F in (requirements*.txt) do (
    if exist "%%F" copy /y "%%F" "%STAGE%\" >nul
)

rem Optional root documentation/configuration files.
call :CopyFile "Info.txt"
call :CopyFile "pyproject.toml"
call :CopyFile "setup.cfg"
call :CopyFile "tox.ini"
call :CopyFile ".gitignore"
call :CopyFile "LICENSE"
call :CopyFile "LICENSE.txt"
call :CopyFile "CHANGELOGV8.txt"
call :CopyFile "CHANGELOGV7.txt"


rem Documentation requested explicitly
call :CopyFile "Dokumentation.docx"
call :CopyFile "DragonToolsV9_Dokumentation.docx"

if not exist "Dokumentation.docx" if not exist "DragonToolsV9_Dokumentation.docx" (
    echo [WARN] No root documentation DOCX was found.
)

rem --- Verify files that must have been copied into staging ---
call :RequireStagedFile ".github\workflows\tests.yml"
if errorlevel 1 goto :cleanup_fail
call :RequireStagedFile "dragontools\tests\test_real_dv_hdr_integration.py"
if errorlevel 1 goto :cleanup_fail


echo [3/4] Create ZIP...

if exist "%OUTZIP%" del /f /q "%OUTZIP%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "Add-Type -AssemblyName System.IO.Compression;" ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "if (-not (Test-Path -LiteralPath $env:STAGE)) { throw 'Staging folder does not exist.' };" ^
  "$files = @(Get-ChildItem -LiteralPath $env:STAGE -File -Recurse -Force);" ^
  "if (-not $files) { throw 'Staging folder is empty.' };" ^
  "$stageRoot=[System.IO.Path]::GetFullPath($env:STAGE).TrimEnd('\','/') + [System.IO.Path]::DirectorySeparatorChar;" ^
  "$fs=[System.IO.File]::Open($env:OUTZIP,[System.IO.FileMode]::Create,[System.IO.FileAccess]::ReadWrite,[System.IO.FileShare]::None);" ^
  "$zip=[System.IO.Compression.ZipArchive]::new($fs,[System.IO.Compression.ZipArchiveMode]::Create,$false);" ^
  "try { foreach($file in $files) { $entryName=$file.FullName.Substring($stageRoot.Length).Replace('\','/'); if($entryName.Contains('\')){throw ('Invalid ZIP entry separator before write: ' + $entryName)}; $entry=$zip.CreateEntry($entryName,[System.IO.Compression.CompressionLevel]::Optimal); $input=$file.OpenRead(); $output=$entry.Open(); try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() } } } finally { $zip.Dispose(); $fs.Dispose() }"

if errorlevel 1 (
    echo [ERROR] ZIP creation failed.
    goto :cleanup_fail
)

if not exist "%OUTZIP%" (
    echo [ERROR] ZIP was not created:
    echo         %OUTZIP%
    goto :cleanup_fail
)

echo [4/4] Verify ZIP...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "$stageRoot=[System.IO.Path]::GetFullPath($env:STAGE).TrimEnd('\') + '\';" ^
  "$stageNames=@(Get-ChildItem -LiteralPath $env:STAGE -File -Recurse -Force | ForEach-Object { $_.FullName.Substring($stageRoot.Length).Replace('\','/') });" ^
  "$z=[System.IO.Compression.ZipFile]::OpenRead('%OUTZIP%');" ^
  "$rawNames=@($z.Entries | Where-Object { -not [string]::IsNullOrEmpty($_.Name) } | ForEach-Object { $_.FullName });" ^
  "$badSeparators=@($rawNames | Where-Object { $_.Contains('\') });" ^
  "$names=@($rawNames);" ^
  "$count=$names.Count;" ^
  "$required=@('README.md','PATCH.md','help.html','release_manifest.json','pytest.ini','INTEGRATION_TESTS.md','COMFYUI_HDR_SETUP.md','DragonToolsV9.py','build_v9.bat','requirements-runtime.txt','requirements-optional.txt','requirements-test.txt','requirements-build.txt','requirements-whisper.txt','.github/workflows/tests.yml','dragontools/tests/test_real_dv_hdr_integration.py');" ^
  "$missing=@($required | Where-Object { $_ -notin $names });" ^
  "$missingFromZip=@($stageNames | Where-Object { $_ -notin $names });" ^
  "$specs=@($names | Where-Object { $_ -like '*.spec' });" ^
  "$z.Dispose();" ^
  "if($count -lt 1){throw 'ZIP is empty'};" ^
  "if($badSeparators.Count -gt 0){throw ('ZIP entries use invalid backslash separators: ' + (($badSeparators | Select-Object -First 10) -join ', '))};" ^
  "if($missing.Count -gt 0){throw ('Required ZIP entries missing: ' + ($missing -join ', '))};" ^
  "if($missingFromZip.Count -gt 0){throw ('Files present in staging but missing from ZIP: ' + ($missingFromZip -join ', '))};" ^
  "if($specs.Count -gt 0){throw ('Generated .spec files must not be in source ZIP: ' + ($specs -join ', '))};" ^
  "Write-Host ('ZIP files: ' + $count + ' / staged files: ' + $stageNames.Count)"

if errorlevel 1 (
    echo [ERROR] ZIP verification failed.
    goto :cleanup_fail
)

rmdir /s /q "%STAGE%" >nul 2>&1

echo.
echo ============================================================
echo DONE
echo ============================================================
echo ZIP:
echo %OUTZIP%
echo.
echo Intentionally NOT included:
echo   build\
echo   dist\
echo   third_party\ / thirdparty\
echo   .venv\ / venv\
echo   .git\
echo   __pycache__ / .pytest_cache / other caches
echo   *.pyc / *.pyo / *.log / *.tmp / *.bak
echo.
pause
exit /b 0


:CopyRequiredDir
if not exist "%~1\." (
    echo [ERROR] Required source folder is missing: %~1
    exit /b 1
)

echo   + %~1\  [required]
robocopy "%~1" "%STAGE%\%~1" /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /XJ /NP /NFL /NDL /NJH /NJS ^
    /XD "__pycache__" ".pytest_cache" ".mypy_cache" ".ruff_cache" ".coverage" ".git" ^
        "build" "dist" ".venv" "venv" "third_party" "thirdparty" ^
    /XF "*.pyc" "*.pyo" "*.log" "*.tmp" "*.temp" "*.bak" "*.old" "*~" >nul
set "RC=!ERRORLEVEL!"
if !RC! GEQ 8 (
    echo [ERROR] Could not copy required folder: %~1 ^(robocopy exit !RC!^)
    exit /b 1
)
if not exist "%STAGE%\%~1\." (
    echo [ERROR] Required folder was not created in staging: %~1
    exit /b 1
)
exit /b 0


:CopyOptionalDir
if not exist "%~1\." exit /b 0

echo   + %~1\
robocopy "%~1" "%STAGE%\%~1" /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /XJ /NP /NFL /NDL /NJH /NJS ^
    /XD "__pycache__" ".pytest_cache" ".mypy_cache" ".ruff_cache" ".coverage" ".git" ^
        "build" "dist" ".venv" "venv" "third_party" "thirdparty" ^
    /XF "*.pyc" "*.pyo" "*.log" "*.tmp" "*.temp" "*.bak" "*.old" "*~" >nul
set "RC=!ERRORLEVEL!"
if !RC! GEQ 8 (
    echo [ERROR] Could not copy folder: %~1 ^(robocopy exit !RC!^)
    exit /b 1
)
exit /b 0


:RequireStagedFile
if not exist "%STAGE%\%~1" (
    echo [ERROR] Required file was not copied to staging: %~1
    exit /b 1
)
echo   = staged: %~1
exit /b 0


:CopyRequiredFile
if not exist "%~1" (
    echo [ERROR] Required source file is missing: %~1
    exit /b 1
)
echo   + %~1
copy /y "%~1" "%STAGE%\" >nul
if errorlevel 1 exit /b 1
exit /b 0


:CopyFile
if exist "%~1" (
    echo   + %~1
    copy /y "%~1" "%STAGE%\" >nul
)
exit /b 0


:cleanup_fail
if exist "%STAGE%" rmdir /s /q "%STAGE%" >nul 2>&1
if exist "%OUTZIP%" del /f /q "%OUTZIP%" >nul 2>&1

:fail
echo.
echo Source ZIP was NOT created.
echo.
pause
exit /b 1
