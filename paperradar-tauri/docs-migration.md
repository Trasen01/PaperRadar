# PaperRadar Tauri migration design

## Goal

Move the desktop GUI from PySide6 to a maintainable Tauri + React + TypeScript frontend while keeping the existing Python literature retrieval, scoring, caching, reporting, database and Profile logic.

## Boundaries

- Keep the existing PySide6 code as a rollback path.
- Do not move retrieval or scoring logic into React.
- React owns presentation, local UI state, filtering controls and interaction feedback.
- Python owns retrieval, scoring, cache, reports, storage, logs and Profile persistence.

## Frontend modules

- `src/app`: page routing and app-level state.
- `src/components/layout`: shell, sidebar and page headers.
- `src/components/ui`: shared Button, Card, Badge, Select, Switch, EmptyState and Toast primitives.
- `src/components/papers`: shared PaperTable and PaperDetailSheet.
- `src/components/profile`: Profile summary, Profile table and keyword workspace.
- `src/pages`: TodayDiscovery, HistoryResearch and ResearchProfiles.
- `src/services`: API adapter. It requests the local Python backend first and falls back to mock data when the backend is unavailable.
- `src/types`: TypeScript contracts for papers, summaries, source status, profiles and keywords.

## API contract

The first integration path is a local FastAPI sidecar bound to `127.0.0.1:8765`.

Implemented and verified:

- `GET /api/status`
- `GET /api/papers/today`
- `GET /api/papers/history`
- `GET /api/profiles`
- `POST /api/profiles`
- `PUT /api/profiles/{profile_id}`
- `DELETE /api/profiles/{profile_id}`

Reserved for the next step:

- `POST /api/papers/check`
- `POST /api/papers/stop`
- `POST /api/history/start`
- `POST /api/history/stop`
- `POST /api/reports/today`
- `POST /api/reports/history`
- `GET /api/logs/recent`

## Current integration status

- The backend imports the existing `paper_radar.database.PaperDatabase` and converts cached papers to the React `Paper` contract.
- The backend imports the existing `paper_radar.profile_manager` and converts local YAML profiles to the React `ResearchProfile` contract.
- The frontend keeps mock data as a development fallback, so UI work can continue even when the Python backend is not running.
- Existing PySide6 files remain untouched as a rollback path.

## Integration order

1. Wrap existing Profile loading/saving logic behind `/api/profiles`. Done.
2. Expose cached today/history papers with normalized `PaperSummary` and `SourceStatus`. Done.
3. Connect today discovery start/stop endpoints to `DailySearchService` as a background task.
4. Connect history research start/stop endpoints to `HistoricalSurveyService`, including same-day cache reuse.
5. Connect report generation and report folder opening via Tauri shell commands.
6. Add recent logs and user-facing error details.
7. Package Python backend as a Tauri sidecar.
8. Build Windows installer after Rust/Cargo is installed.

## Current known blocker

This machine currently has Node/npm, but `cargo` and `rustc` are not installed, so the React frontend builds and the Python backend runs, but the Tauri shell cannot compile yet.
