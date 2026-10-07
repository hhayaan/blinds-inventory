@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo First run Setup.ps1 to install the project dependencies.
    echo See README.md for the setup command.
    pause
    exit /b 1
)
rem Give Python its own visible console so Ctrl+C does not interrupt this batch.
start "Windowstock" /D "%~dp0" "%~dp0.venv\Scripts\python.exe" "%~dp0run.py"
exit /b
