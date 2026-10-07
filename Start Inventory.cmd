@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First run Setup.ps1 to install the project dependencies.
    echo See README.md for the setup command.
    pause
    popd
    exit /b 1
)
".venv\Scripts\python.exe" run.py
if errorlevel 1 pause
popd
