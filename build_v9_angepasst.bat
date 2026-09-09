@echo off
REM Kompatibilitaets-Wrapper: der kanonische Build liegt in build_v9.bat.
call "%~dp0build_v9.bat" %*
exit /b %errorlevel%
