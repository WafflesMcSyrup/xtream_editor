@echo off
rem Double-click to run just the local Xtream server (no editor window).
rem It serves your last saved project. Leave this window open while you watch.
cd /d "%~dp0"
py main.py --serve
echo.
pause
