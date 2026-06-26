# PaperRadar

PaperRadar is a lightweight Windows desktop literature radar for researchers. It helps you monitor new papers every day, run historical literature surveys before starting a project, manage research-direction Profiles, score relevance locally, store papers in SQLite, and generate Markdown reports.

The current desktop application uses a modern desktop shell with a React/TypeScript interface and a local Python service that reuses the existing `paper_radar` core logic. The product and repository name are **PaperRadar**.

## What PaperRadar Does

- **Daily Radar**: quickly check recent papers with a low-distraction result list.
- **Historical Survey**: run longer searches over selected time ranges for project planning and literature review.
- **Research Profiles**: switch the software to a specific research direction through configurable YAML Profiles.
- **AI-assisted Profile drafting**: generate a prompt, paste it into an external AI tool, and import the returned YAML with a tolerant parser.
- **Preprint search**: query arXiv for recent and historical preprints.
- **Top-journal search**: combine latest journal monitoring and Crossref-based top-journal retrieval behind a user-friendly top-journal option.
- **Local relevance scoring**: score papers from title, abstract, categories, keyword groups, exclusion terms, and source quality.
- **Local database**: keep papers in a local SQLite database.
- **Reports**: export Daily Radar and Historical Survey results as Markdown.
- **System tray support**: keep PaperRadar running quietly in the background.

## Screenshots

Screenshots will be added later.

Suggested location:

```text
docs/images/
```

## Installation

### For Regular Users

Download and run the Windows installer:

```text
PaperRadar_Setup_v0.3.0.exe
```

The installer supports:

- installation to the standard Windows program folder;
- Start Menu shortcut;
- optional desktop shortcut;
- launch after installation;
- upgrade installation using a fixed application ID.

Uninstalling PaperRadar removes the program files only. It does not delete your Profiles, database, reports, or logs.

### For Developers

```powershell
git clone <repo-url> PaperRadar
cd PaperRadar
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python run.py
```

## User Data

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
  cache\
```

Updating or reinstalling PaperRadar does not overwrite these files by default. To completely remove all local user data, delete `%APPDATA%\PaperRadar\` manually.

## Research Profiles

A Profile tells PaperRadar what your research direction is. It contains:

- `search_queries`: compact phrases used for remote retrieval;
- `keyword_groups`: terms used for local matching and scoring;
- `exclude_terms`: terms that reduce false positives;
- `recommended_journals`: top journals worth watching for the field.

The default bundled Profile is **Optical Computing**. You can create a custom Profile from the Research Profile page:

1. Enter a research direction, for example `ultrafast photonics`.
2. Generate the AI prompt.
3. Paste it into an external AI assistant.
4. Use the external AI app's copy button or shortcut if available.
5. Paste the YAML back into PaperRadar.
6. Use smart parsing to preview and normalize the Profile.
7. Set it as the active research direction.

PaperRadar does not include an LLM and does not call any AI API. External AI is only used to help draft Profile YAML.

## Data Sources

### Preprints (arXiv)

PaperRadar can search arXiv for preprints. This works well for both daily checks and broader historical surveys, although arXiv can occasionally be slow or time out.

### Top Journals

The user interface presents a single **Top Journals** option. Internally, PaperRadar can use:

- RSS feeds for latest journal items;
- Crossref for historical top-journal retrieval.

RSS feeds are useful for daily monitoring, but they are not historical literature databases and often do not provide complete abstracts. Crossref is better for historical discovery, but metadata quality varies by publisher.

## Relevance Scoring

PaperRadar uses local rule-based scoring. A paper scores well when its title or abstract matches the active Profile's research keywords. Journal names such as Nature, Science, Optica, and Light are not treated as research keywords.

The score uses:

- keyword matches in title and abstract;
- combination bonuses for multiple meaningful matches;
- source quality as an auxiliary signal;
- exclusion-term penalties;
- caps for broad or weak matches.

The paper detail panel shows a score breakdown so users can understand why a result was ranked.

## Reports

Reports are saved under:

```text
%APPDATA%\PaperRadar\reports\
```

PaperRadar currently supports:

- Daily Radar reports;
- Historical Survey reports.

## Building the Windows App

### Build the EXE

```powershell
.\build_scripts\build_exe.ps1 -Python .\.venv\Scripts\python.exe
```

Output:

```text
dist\PaperRadar\PaperRadar.exe
```

The build script closes any running PaperRadar process before packaging, preventing file-lock issues during rebuilds.

### Build the Installer

Install Inno Setup 6, then run:

```powershell
.\build_scripts\build_installer.ps1 -Python .\.venv\Scripts\python.exe
```

Output:

```text
dist\installer\PaperRadar_Setup_v0.3.0.exe
```

The installer is generated from:

```text
installer\PaperRadar.iss
```

## Project Structure

```text
PaperRadar/
  README.md
  LICENSE
  requirements.txt
  run.py
  paper_radar/
  resources/
    default_profiles/
  config_templates/
  build_scripts/
  installer/
  scripts/
  tests/
  docs/
```

## GitHub Notes

Do not commit local runtime data or build artifacts. The repository `.gitignore` excludes:

- `build/`
- `dist/`
- local `config/`, `profiles/`, `data/`, `reports/`, `logs/`
- SQLite databases
- virtual environments
- cache and test artifacts

To create a GitHub repository after deciding whether it should be public or private:

```powershell
gh repo create PaperRadar --private --source=. --remote=origin --push
```

or:

```powershell
gh repo create PaperRadar --public --source=. --remote=origin --push
```

If GitHub CLI is not installed, create a repository named `PaperRadar` on GitHub, then run:

```powershell
git remote add origin https://github.com/<your-user-or-org>/PaperRadar.git
git push -u origin main
```

## Limitations

- RSS feeds are not historical literature databases.
- Crossref does not guarantee complete abstracts.
- arXiv requests can occasionally time out.
- Relevance scoring is rule-based and depends on Profile quality.
- PaperRadar does not include an LLM and does not call external AI APIs.
- Some publishers expose limited metadata through public APIs.

## Roadmap

- OpenAlex support.
- Semantic Scholar support.
- PDF metadata and abstract enrichment.
- Citation and reference analysis.
- BibTeX/Zotero export.
- More complete per-user/all-user installer modes.
- Automatic update support.

## License

License will be decided later.

