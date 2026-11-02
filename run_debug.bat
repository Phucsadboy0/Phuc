@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m aotr_farm
pause
