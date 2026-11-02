@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
    echo Chua cai dat. Hay chay install.bat truoc.
    pause
    exit /b 1
)
rem pythonw: chay khong hien cua so console
start "" .venv\Scripts\pythonw.exe -m aotr_farm
