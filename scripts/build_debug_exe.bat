@echo off
setlocal
cd /d "%~dp0\.."
if not "%BUILD_PYTHON%"=="" (
  set "PYTHON_EXE=%BUILD_PYTHON%"
) else if exist "D:\Anaconda\envs\deep_physics\python.exe" (
  set "PYTHON_EXE=D:\Anaconda\envs\deep_physics\python.exe"
) else if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)
%PYTHON_EXE% -c "from PySide6.QtWidgets import QApplication; print('PySide6 QtWidgets OK')" || (
  echo.
  echo PySide6 QtWidgets failed in this Python environment.
  echo Please use Python 3.12 or set BUILD_PYTHON to a working interpreter.
  pause
  exit /b 1
)
%PYTHON_EXE% -m PyInstaller --clean --noconfirm PaperRadar.debug.spec
echo.
echo Debug EXE:
echo dist\PaperRadarDebug\PaperRadarDebug.exe
pause
