@echo off
rem Double-click to run a SECOND local Xtream server that streams with the second login saved in your project
rem (File > Second login in the editor). Run start_server.bat too, for the first account.
rem It uses the next port up, the user name plus a 2, and its own password (shown in this window).
cd /d "%~dp0"
py main.py --serve --account 2
echo.
pause
