@echo off
rem Double-click to run just the local Xtream server (no editor window).
rem It serves the last project saved from the editor. Leave this window open while you watch.
rem Extra options go on the end, e.g.  start_server.bat --port 8091 --refresh-at 04:00
cd /d "%~dp0"
XtreamServer.exe %*
echo.
pause
