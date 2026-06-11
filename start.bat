@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe run.py
) else (
    echo No .venv found. Run setup_venv.bat first!
    pause
)
