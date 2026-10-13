@echo off
REM Double-click to start Amaan WITH the optional WhatsApp bridge (needs Docker Desktop running).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\amaan.ps1" up -WhatsApp
pause
