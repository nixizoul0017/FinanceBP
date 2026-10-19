@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0scripts\launch_windows.ps1" %*
endlocal
