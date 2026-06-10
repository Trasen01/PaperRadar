@echo off
setlocal
cd /d "%~dp0\.."
python -m venv .venv
if exist "%CONDA_PREFIX%\python3.dll" copy /Y "%CONDA_PREFIX%\python3.dll" ".venv\Scripts\python3.dll" >nul
if not exist ".venv\Scripts\python3.dll" if exist "D:\Anaconda\python3.dll" copy /Y "D:\Anaconda\python3.dll" ".venv\Scripts\python3.dll" >nul
call .venv\Scripts\python.exe -m pip install --upgrade pip
call .venv\Scripts\python.exe -m pip install -r requirements.txt
call .venv\Scripts\python.exe -m pip install pyinstaller
call .venv\Scripts\python.exe -c "from PySide6.QtWidgets import QApplication; print('PySide6 QtWidgets OK')" || (
  echo.
  echo PySide6 QtWidgets failed in this Python environment.
  echo Python 3.12 is recommended for packaging this project.
  pause
  exit /b 1
)
echo.
echo Virtual environment is ready.
pause
