@echo off
rem TONK-RE one-click setup for Windows: double-click me.
rem Installs uv (per-user, no admin) if needed, runs install.ps1, then opens TONK-RE, whose
rem SETUP panel installs the toolchain (JDK, jadx, apktool, Android tools, frida) with one button.
setlocal
cd /d "%~dp0"
echo == TONK-RE setup
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
  echo [*] installing uv ^(Python runner, per-user^) ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  if errorlevel 1 goto fail
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 goto fail
echo.
echo [*] opening TONK-RE: click SETUP / INSTALL ALL to install the toolchain
rem uvw + --gui-script: no console window; the server stops when the TONK-RE window is closed
start "" uvw run --quiet --gui-script "%~dp0gui.py"
exit /b 0

:fail
echo.
echo [-] setup failed, see the messages above
pause
exit /b 1
