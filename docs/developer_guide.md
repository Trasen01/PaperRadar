# Developer Guide

## Environment

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
cd desktop
npm install
npm run desktop:dev
```

## Tests

```powershell
.\.venv\Scripts\python -m pytest tests
```

## Build Desktop App

```powershell
cd desktop
npm run desktop:build
```

The Tauri build writes the app executable and NSIS installer under
`desktop\src-tauri\target\release`.

## Runtime Data

Program files and user data are intentionally separated:

- Program files: installation directory
- User data: `%APPDATA%\PaperRadar`

Do not commit runtime databases, logs, reports, or local user settings.
