@echo off
rem Dry run by default. To really remove:  uninstall_spm_studio_windows.bat -Apply
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall_spm_studio_windows.ps1" %*
pause
