# PaperRadar Desktop

Current desktop flow:

- Tauri v2 shell
- React + TypeScript + Vite frontend
- Tailwind CSS UI
- Python FastAPI sidecar
- shared `paper_radar` backend logic for retrieval, scoring, reports, profiles, logs, and SQLite storage

The old PySide/Tk desktop frontend has been removed. Development and packaging should use this Tauri flow only.

## Development

```powershell
cd D:\PaperRadar\desktop
npm install
npm run desktop:dev
```

## Packaging

From the repository root:

```powershell
.\build_scripts\build_installer.ps1
```

The script rebuilds the Python sidecar, runs the Tauri production build, and stages:

```text
D:\PaperRadar\dist\PaperRadar-v0.4.0\PaperRadar.exe
D:\PaperRadar\dist\PaperRadar-v0.4.0\paperradar-backend.exe
D:\PaperRadar\dist\installer\PaperRadar_Setup_v0.4.0.exe
```
