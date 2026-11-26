@echo off
chcp 65001 >nul
if exist "%~dp0ShijieAgent.exe" (
  "%~dp0ShijieAgent.exe" stop --data-dir "%LOCALAPPDATA%\CareerPilotCompetition\judge-live-20261114-v2"
) else (
  python "%~dp0源码\scripts\delivery_launcher.py" stop --data-dir "%LOCALAPPDATA%\CareerPilotCompetition\judge-live-20261114-v2"
)
if errorlevel 1 pause
