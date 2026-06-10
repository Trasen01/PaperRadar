# PaperRadar

PaperRadar is a lightweight desktop literature radar for researchers. It helps monitor new papers, run historical literature surveys, configure research-direction Profiles, score relevance, store results locally, and generate Markdown reports.

The current desktop app is built with Python and PySide6. The internal Python package is still named `optical_radar` for compatibility, while the product and repository name are PaperRadar.

## Core Features

- Daily Radar for quick new-paper checks.
- Historical Survey for longer Crossref/arXiv searches.
- Research Profile system for changing research directions.
- External-AI assisted Profile generation with robust YAML import.
- arXiv search for preprints.
- RSS daily monitoring for journal latest items.
- Crossref top-journal historical search.
- Local SQLite database.
- Relevance scoring based on Profile keyword groups.
- Markdown report generation.
- Windows desktop GUI with system tray support.

## Screenshots

Screenshots will be added later.

Image assets can be placed under:

```text
docs/images/
```

## Installation

### For Regular Users

Download and run:

```text
PaperRadar_Setup_vX.Y.Z.exe
```

The installer creates Start Menu shortcuts, can optionally create a desktop shortcut, and can launch PaperRadar after installation.

### For Developers

```powershell
git clone <your-repo-url> PaperRadar
cd PaperRadar
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python run.py
```

## User Data Location

PaperRadar stores user data in:

```text
%APPDATA%\PaperRadar\
```

Typical contents:

```text
%APPDATA%\PaperRadar\
  config\
    settings.yaml
    sources.yaml
    keywords.yaml
  profiles\
    optical_computing.yaml
  data\
    papers.sqlite
  reports\
  logs\
    paper_radar.log
```

Updating or reinstalling PaperRadar does not delete these files by default. Uninstalling removes program files only. To fully remove all user data, manually delete `%APPDATA%\PaperRadar\`.

## Research Profiles

Profiles define a research direction:

- search queries;
- keyword groups;
- exclusion terms;
- recommended top journals.

The default Profile is Optical Computing. You can create your own direction from the Profile page:

1. Enter a research direction, such as `ultrafast photonics`.
2. Generate and copy the AI prompt.
3. Paste the prompt into an external AI tool.
4. Use the AI tool's copy button or copy shortcut, if available.
5. Paste the returned YAML into PaperRadar.
6. Use smart parsing and save it as the current direction.

PaperRadar does not include or call an LLM API. External AI is only used to help users draft Profile YAML.

See [docs/profile_guide.md](docs/profile_guide.md) for details.

## Data Sources

### arXiv

Used for preprint search. It supports date ranges and works well for daily checks and historical surveys.

### RSS Daily Monitoring

RSS is for monitoring latest/current journal entries. RSS feeds are not historical literature databases and often do not provide complete abstracts.

### Crossref Top-Journal Historical Search

Crossref is used for top-journal historical search across a selected time range. Crossref metadata quality varies by publisher; some records have no abstract.

## Reports

PaperRadar generates Markdown reports for:

- daily radar results;
- historical literature surveys.

Reports are saved under `%APPDATA%\PaperRadar\reports`.

## Build

### Build EXE

```powershell
.\build_scripts\build_exe.ps1 -Python .\.venv\Scripts\python.exe
```

Output:

```text
dist\PaperRadar\PaperRadar.exe
```

### Build Windows Installer

Install Inno Setup 6, then run:

```powershell
.\build_scripts\build_installer.ps1 -Python .\.venv\Scripts\python.exe
```

Output:

```text
dist\installer\PaperRadar_Setup_v0.2.0.exe
```

The first installer version supports standard Inno Setup installation, optional desktop shortcut, Start Menu shortcut, and launch-after-install. It uses a fixed AppId so later versions can be installed as updates. The installer does not delete `%APPDATA%\PaperRadar`.

## Updating

Install the new setup package over the old version. User settings, Profiles, database, logs, and reports are stored in `%APPDATA%\PaperRadar` and are preserved by default.

## Project Structure

```text
PaperRadar/
  README.md
  requirements.txt
  run.py
  optical_radar/
  resources/
    app_icon.ico
    default_profiles/
  config_templates/
  build_scripts/
  installer/
  tests/
  docs/
```

## GitHub Upload

After reviewing files:

```powershell
git init
git add .
git commit -m "Initial PaperRadar project"
```

Create the GitHub repository after deciding whether it should be public or private:

```powershell
gh repo create PaperRadar --private --source=. --remote=origin --push
```

or:

```powershell
gh repo create PaperRadar --public --source=. --remote=origin --push
```

Do not commit `dist`, `build`, databases, logs, reports, or local user data.

## Limitations

- RSS feeds are not historical literature databases.
- Crossref does not guarantee complete abstracts.
- Relevance scoring is rule-based and depends on the active Profile.
- PaperRadar does not include an LLM and does not call external AI APIs.
- Some publishers expose limited metadata through public APIs.

## Roadmap

- OpenAlex support.
- Semantic Scholar support.
- PDF metadata and abstract enrichment.
- Citation and reference analysis.
- BibTeX/Zotero export.
- More complete per-user/all-user installer modes.
- Automatic update mechanism.

## License

License will be decided later.
