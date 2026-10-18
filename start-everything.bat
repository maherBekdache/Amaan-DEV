@echo off
REM Double-click to start EVERYTHING: Amaan + WhatsApp bridge + Lookyloo (needs Docker Desktop running).
REM For the AI opinion also install Ollama once: see README.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\amaan.ps1" up -WhatsApp -Lookyloo
pause
