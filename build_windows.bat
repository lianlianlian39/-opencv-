@echo off
setlocal
cd /d "%~dp0"
py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --windowed --onedir --name LifeAfterImageClicker --collect-all cv2 main.py
if errorlevel 1 (
  echo Build failed. See the messages above.
  exit /b 1
)
echo Build complete: dist\LifeAfterImageClicker\LifeAfterImageClicker.exe

