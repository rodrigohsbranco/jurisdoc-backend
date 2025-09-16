@echo off
set FRONT_PORT=3000
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-demo.ps1" -FrontPort %FRONT_PORT%
pause
