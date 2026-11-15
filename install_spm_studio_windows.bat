@echo off
rem Double-click this file (or run it from a Command Prompt) to install SPM Studio for your user.
rem It runs install_spm_studio_windows.ps1 without changing your PowerShell execution policy.
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_spm_studio_windows.ps1" %*
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (echo Finished.) else (echo The installer stopped with code %RC%. Read the messages above.)
pause
exit /b %RC%
