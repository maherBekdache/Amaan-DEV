@echo off
REM Double-click to stop Amaan.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\amaan.ps1" down
pause
