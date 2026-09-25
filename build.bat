@echo off
rem Builds Clicker.exe (one file, no console) next to this script. Needs Python; installs PyInstaller if missing.
cd /d "%~dp0"
python -m PyInstaller --version >nul 2>&1 || python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Clicker --icon clicker.ico --add-data "clicker.ico;." clicker.py || exit /b 1
copy /y dist\Clicker.exe Clicker.exe >nul
echo Built %~dp0Clicker.exe
