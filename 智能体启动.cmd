@echo off
chcp 65001 >nul
setlocal
set "SHIJIE_AGENT_DATA=%LOCALAPPDATA%\CareerPilotCompetition\judge-live-20261114-v2"
if exist "%~dp0Shijie.exe" "%~dp0Shijie.exe" stop --data-dir "%SHIJIE_AGENT_DATA%"
if exist "%~dp0ShijieAgent.exe" (
  "%~dp0ShijieAgent.exe" start --data-dir "%SHIJIE_AGENT_DATA%" --allow-real-calls %*
) else (
  python "%~dp0源码\scripts\delivery_launcher.py" start --data-dir "%SHIJIE_AGENT_DATA%" --allow-real-calls %*
)
if errorlevel 1 pause
