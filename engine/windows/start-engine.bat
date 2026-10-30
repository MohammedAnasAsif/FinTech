@echo off
REM Real market data from Angel One. Paper trading unless config.yaml says mode: live.
cd /d "%~dp0"
if not exist .env (echo Copy .env.example to .env and fill it in first. See docs\SETUP.md & pause & exit /b 1)
if not exist config.yaml copy config.example.yaml config.yaml
tradebot-engine.exe serve
pause
