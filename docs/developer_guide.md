# Developer Guide

## Environment

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python run.py
```

## Tests

```powershell
.\.venv\Scripts\python -m pytest tests
```

## Build EXE

```powershell
.\build_scripts\build_exe.ps1 -Python .\.venv\Scripts\python.exe
```

## Build Installer

Install Inno Setup 6, then run:

```powershell
.\build_scripts\build_installer.ps1 -Python .\.venv\Scripts\python.exe
```

The installer is written to `dist\installer`.

## Runtime Data

Program files and user data are intentionally separated:

- Program files: installation directory
- User data: `%APPDATA%\PaperRadar`

Do not commit runtime databases, logs, reports, or local user settings.
