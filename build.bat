@echo off
rem Build DriverUpdater.exe locally (Windows, Python 3.10+).
cd /d "%~dp0"
python -m pip install -r requirements-build.txt || exit /b 1
python -m unittest discover -s tests -t . || exit /b 1
python -m PyInstaller --noconfirm --clean packaging\DriverUpdater.spec || exit /b 1
echo.
echo Done: dist\DriverUpdater.exe and dist\DriverUpdater-cli.exe
