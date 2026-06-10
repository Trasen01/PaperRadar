from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

from dateutil import parser as date_parser


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = get_app_dir()
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
APPDATA_ROOT = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
USER_DATA_DIR = APPDATA_ROOT / "PaperRadar"
LEGACY_APP_DIR_DATA_DIR = APP_DIR
CONFIG_DIR = USER_DATA_DIR / "config"
PROFILES_DIR = USER_DATA_DIR / "profiles"
DATA_DIR = USER_DATA_DIR / "data"
REPORTS_DIR = USER_DATA_DIR / "reports"
LOGS_DIR = USER_DATA_DIR / "logs"
ASSETS_DIR = RESOURCE_DIR / "assets"
APP_ICON_PATH = ASSETS_DIR / "PaperRadar.png"
APP_ICON_ICO_PATH = ASSETS_DIR / "PaperRadar.ico"
LOG_FILE = LOGS_DIR / "paper_radar.log"


def ensure_directories() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def migrate_legacy_data_if_needed() -> None:
    ensure_directories()
    legacy_pairs = [
        (LEGACY_APP_DIR_DATA_DIR / "config" / "settings.yaml", CONFIG_DIR / "settings.yaml"),
        (LEGACY_APP_DIR_DATA_DIR / "config" / "sources.yaml", CONFIG_DIR / "sources.yaml"),
        (LEGACY_APP_DIR_DATA_DIR / "config" / "keywords.yaml", CONFIG_DIR / "keywords.yaml"),
        (LEGACY_APP_DIR_DATA_DIR / "data" / "papers.sqlite", DATA_DIR / "papers.sqlite"),
    ]
    for source, target in legacy_pairs:
        if source.resolve() == target.resolve():
            continue
        if source.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    for legacy_dir, target_dir in [
        (LEGACY_APP_DIR_DATA_DIR / "profiles", PROFILES_DIR),
        (LEGACY_APP_DIR_DATA_DIR / "reports", REPORTS_DIR),
        (LEGACY_APP_DIR_DATA_DIR / "logs", LOGS_DIR),
    ]:
        if legacy_dir.resolve() == target_dir.resolve():
            continue
        if not legacy_dir.exists():
            continue
        for source in legacy_dir.iterdir():
            target = target_dir / source.name
            if source.is_file() and not target.exists():
                shutil.copy2(source, target)


def setup_logging() -> None:
    ensure_directories()
    migrate_legacy_data_if_needed()
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        encoding="utf-8",
    )


def normalize_space(value: str | None) -> str:
    return " ".join((value or "").split())


def title_hash(title: str) -> str:
    return hashlib.sha256(normalize_space(title).lower().encode("utf-8")).hexdigest()


def format_date_only(value: object) -> str:
    if value is None:
        return "未知"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = normalize_space(str(value))
    if not text:
        return "未知"
    try:
        return date_parser.parse(text).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return "未知"


def open_url(url: str) -> None:
    if url:
        webbrowser.open(url)


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        webbrowser.open(f"file://{path}")
    else:
        webbrowser.open(f"file://{path}")
