@echo off
rem Builds two Windows programs with PyInstaller (run this on Windows, from this folder):
rem   dist\XtreamEditor\XtreamEditor.exe   the editor window (also has the server window inside it)
rem   dist\XtreamServer\XtreamServer.exe   the no-window server, runs in a console, no Qt, much smaller
rem Give people those folders. Their logins/projects live in their own user folder, not in these.
rem pushd (not cd) so it also works when this folder is on a network share (\\server\share)
pushd "%~dp0"
py -m pip install --upgrade pyinstaller
if errorlevel 1 goto :fail

py -m PyInstaller --noconfirm --clean --windowed --name XtreamEditor --add-data "help;help" main.py
if errorlevel 1 goto :fail

py -m PyInstaller --noconfirm --clean --console --name XtreamServer server_main.py
if errorlevel 1 goto :fail
copy /y start_server_exe.bat dist\XtreamServer\start_server.bat >nul
copy /y start_server_exe_2.bat dist\XtreamServer\start_server_2.bat >nul
copy /y LICENSE dist\XtreamServer\ >nul
copy /y DISCLAIMER.txt dist\XtreamServer\ >nul
copy /y LICENSE dist\XtreamEditor\ >nul
copy /y DISCLAIMER.txt dist\XtreamEditor\ >nul

echo.
echo Done. Look in the dist folder.
popd
pause
exit /b 0

:fail
echo.
echo Build failed - see the messages above.
popd
pause
exit /b 1
