from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
import ctypes
import copy
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import tkinter as tk
import yaml
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .arxiv_client import ArxivClient
from .cache_manager import cache_size_bytes
from .crossref_client import CrossrefClient, build_search_queries_from_keywords
from .database import PaperDatabase
from .journal_fetcher import JournalRssFetcher
from .keyword_filter import KeywordFilter
from .models import Paper
from .profile_manager import (
    DEFAULT_PROFILE_ID,
    delete_profile,
    ensure_default_profile_available,
    generate_profile_prompt,
    load_active_profile,
    load_all_profiles,
    profile_to_keywords,
    save_profile,
    set_active_profile,
    validate_profile_yaml,
)
from .report import generate_daily_report, generate_survey_report
from .scorer import score_paper
from .settings import load_keywords, load_settings, load_sources
from .utils import REPORTS_DIR, format_date_only, open_folder, open_url, title_hash

logger = logging.getLogger(__name__)
RESULT_COLUMNS = ("score", "source", "type", "title", "authors", "date", "keywords", "action")


def enable_windows_high_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def has_relevant_keyword(matches: dict[str, list[str]]) -> bool:
    return any(group != "exclude" and bool(values) for group, values in matches.items())


def matched_fields_from_locations(locations: dict[str, dict[str, list[str]]]) -> list[str]:
    fields: list[str] = []
    for field, label in [("title", "标题"), ("abstract", "摘要"), ("metadata", "分类/元数据")]:
        if any(values for group, locs in locations.items() if group != "exclude" for loc, values in locs.items() if loc == field):
            fields.append(label)
    return fields


def dedupe_papers(papers: list[Paper]) -> list[Paper]:
    out: list[Paper] = []
    key_to_index: dict[str, int] = {}
    for paper in papers:
        keys = _paper_identity_keys(paper)
        indexes = [key_to_index[key] for key in keys if key in key_to_index]
        if not indexes:
            index = len(out)
            out.append(paper)
            for key in keys:
                key_to_index[key] = index
            continue
        index = indexes[0]
        out[index] = _merge_duplicate_papers(out[index], paper)
        for key in keys:
            key_to_index[key] = index
    return out


def _paper_identity_keys(paper: Paper) -> list[str]:
    keys: list[str] = []
    if paper.doi:
        keys.append(f"doi:{paper.doi.lower()}")
    if paper.arxiv_id:
        keys.append(f"arxiv:{paper.arxiv_id}")
    if paper.url:
        keys.append(f"url:{paper.url}")
    keys.append(f"title:{title_hash(paper.title)}")
    return keys


def _source_priority(source_type: str) -> int:
    return {"crossref": 3, "journal_rss": 2, "arxiv": 1}.get(source_type or "", 0)


def _merge_duplicate_papers(left: Paper, right: Paper) -> Paper:
    preferred, fallback = (left, right)
    if _source_priority(right.source_type) > _source_priority(left.source_type):
        preferred, fallback = right, left
    preferred.abstract = preferred.abstract or fallback.abstract
    preferred.authors = preferred.authors or fallback.authors
    preferred.published_date = preferred.published_date or fallback.published_date
    preferred.updated_date = preferred.updated_date or fallback.updated_date
    preferred.doi = preferred.doi or fallback.doi
    preferred.arxiv_id = preferred.arxiv_id or fallback.arxiv_id
    return preferred


def score_and_tag(papers: list[Paper], keyword_filter: KeywordFilter, keep_unmatched: bool) -> list[Paper]:
    scored: list[Paper] = []
    for paper in papers:
        locations = keyword_filter.match_with_locations(paper)
        matches = keyword_filter.flatten_location_matches(locations)
        if not has_relevant_keyword(matches):
            if not keep_unmatched:
                continue
            paper.matched_keywords = []
            paper.matched_fields = []
            paper.relevance_score = 0
            paper.reason_zh = "未命中当前研究关键词，仅作为来源存档。"
            paper.score_breakdown = {
                "keyword_score": 0,
                "source_quality_score": 0,
                "penalty_score": 0,
                "final_score": 0,
                "has_positive_keyword_hit": False,
            }
            scored.append(paper)
            continue
        paper.matched_keywords = keyword_filter.flatten_matches(matches)
        paper.matched_fields = matched_fields_from_locations(locations)
        paper.relevance_score, paper.reason_zh = score_paper(paper, matches, keyword_filter.title_matches(paper), locations)
        scored.append(paper)
    scored.sort(key=lambda item: (int(item.relevance_score), item.published_date or ""), reverse=True)
    return scored


class DailyRadarRunner:
    def __init__(self, days_back: int, sources: dict[str, bool], settings: dict[str, Any], emit, should_stop) -> None:
        self.days_back = days_back
        self.sources = sources
        self.settings = settings
        self.emit = emit
        self.should_stop = should_stop
        self.db = PaperDatabase()
        self.keyword_filter = KeywordFilter(load_keywords())

    def run(self) -> None:
        try:
            rows_per_query = int(self.settings.get("crossref", {}).get("rows_per_query", 20))
            max_queries = min(4, int(self.settings.get("crossref", {}).get("max_queries_per_run", 200)))
            network = self.settings.get("network", {})
            timeout = int(network.get("daily_timeout_seconds", 20))
            max_retries = int(network.get("max_retries", 3))
            retry_delay = int(network.get("retry_delay_seconds", 3))
            papers: list[Paper] = []
            stats = Counter()
            total_steps = sum(1 for key in ("arxiv", "rss", "crossref") if self.sources.get(key))
            completed = 0
            self.emit("daily_progress", {"completed": 0, "total": max(total_steps, 1), "source": "准备检索"})

            if self.sources.get("arxiv") and not self.should_stop():
                try:
                    batch = ArxivClient(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent(self.days_back, 300)
                    stats["arxiv"] = len(batch)
                    stats["success"] += 1
                except Exception as exc:
                    batch = []
                    stats["failed"] += 1
                    logger.warning("Daily arXiv failed: %s", exc)
                completed += 1
                self._handle_batch(batch, papers, stats, completed, total_steps, "预印本（arXiv）")

            if self.sources.get("rss") and not self.should_stop():
                try:
                    rss = JournalRssFetcher(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent(self.days_back)
                    batch = rss.papers
                    stats["rss"] = len(batch)
                    stats["success"] += 1
                    stats["failed"] += int(rss.stats.failed_sources)
                except Exception as exc:
                    batch = []
                    stats["failed"] += 1
                    logger.warning("Daily RSS failed: %s", exc)
                completed += 1
                self._handle_batch(batch, papers, stats, completed, total_steps, "顶级期刊最新文章")

            if self.sources.get("crossref") and not self.should_stop():
                try:
                    crossref = CrossrefClient(timeout=timeout, rows=rows_per_query, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent(
                        self.days_back, max_queries=max_queries
                    )
                    batch = crossref.papers
                    stats["crossref"] = len(batch)
                    stats["success"] += 1
                    stats["failed"] += len(crossref.failed_requests)
                except Exception as exc:
                    batch = []
                    stats["failed"] += 1
                    logger.warning("Daily Crossref failed: %s", exc)
                completed += 1
                self._handle_batch(batch, papers, stats, completed, total_steps, "顶级期刊近期检索")

            scored = score_and_tag(dedupe_papers(papers), self.keyword_filter, keep_unmatched=True)
            storage = self.db.upsert_papers_with_stats(scored)
            stats["deduped"] = len(scored)
            stats["displayed"] = len(scored)
            stats["inserted"] = storage.inserted_count
            stats["updated"] = storage.updated_count
            stats["high"] = sum(1 for paper in scored if paper.relevance_score >= 60)
            stats["skim"] = sum(1 for paper in scored if 40 <= paper.relevance_score < 60)
            self.emit("daily_finished", scored, dict(stats))
        except Exception as exc:
            logger.error("Daily radar failed: %s\n%s", exc, traceback.format_exc())
            self.emit("daily_failed", str(exc))

    def _handle_batch(self, batch: list[Paper], all_seen: list[Paper], stats: Counter, completed: int, total: int, source_label: str) -> None:
        all_seen.extend(batch)
        scored = score_and_tag(dedupe_papers(all_seen), self.keyword_filter, keep_unmatched=True)
        storage = self.db.upsert_papers_with_stats(scored)
        stats["deduped"] = len(scored)
        stats["matched"] = sum(1 for paper in scored if paper.matched_keywords)
        stats["displayed"] = len(scored)
        stats["inserted"] += storage.inserted_count
        stats["updated"] += storage.updated_count
        progress = {
            "completed": completed,
            "total": max(total, 1),
            "source": source_label,
            "found": len(all_seen),
            "deduped": stats["deduped"],
            "matched": stats["matched"],
            "displayed": stats["displayed"],
            "success": stats["success"],
            "failed": stats["failed"],
        }
        self.emit("daily_batch", scored, progress)
        self.emit("daily_progress", progress)


class HistoricalSurveyRunner:
    def __init__(
        self,
        task_name: str,
        from_date: date,
        until_date: date,
        sources: dict[str, bool],
        settings: dict[str, Any],
        emit,
        should_stop,
    ) -> None:
        self.task_name = task_name
        self.from_date = from_date
        self.until_date = until_date
        self.sources = sources
        self.settings = settings
        self.emit = emit
        self.should_stop = should_stop
        self.db = PaperDatabase()
        self.keyword_filter = KeywordFilter(load_keywords())

    def run(self) -> None:
        try:
            all_seen: list[Paper] = []
            stats = Counter()
            rows_per_query = int(self.settings.get("crossref", {}).get("rows_per_query", 20))
            max_queries = int(self.settings.get("crossref", {}).get("max_queries_per_run", 200))
            delay = float(self.settings.get("crossref", {}).get("request_delay_seconds", 0.5))
            network = self.settings.get("network", {})
            timeout = int(network.get("historical_timeout_seconds", 60))
            max_retries = int(network.get("max_retries", 3))
            retry_delay = int(network.get("retry_delay_seconds", 3))
            performance = self.settings.get("performance", {})
            max_workers = max(1, min(5, int(performance.get("max_workers", 3))))
            cache_settings = self.settings.get("cache", {})
            cache_enabled = bool(cache_settings.get("enabled", True))
            queries = build_search_queries_from_keywords(load_keywords(), max_queries=max_queries)
            top_journals = [journal for journal in load_sources().get("top_journals", []) if journal.get("crossref_enabled")]
            total_steps = (len(top_journals) * len(queries) if self.sources.get("crossref") else 0)
            total_steps += 1 if self.sources.get("arxiv") else 0
            total_steps += 1 if self.sources.get("rss") else 0
            completed = 0
            start_time = time.monotonic()
            self.emit("survey_progress", {"completed": 0, "total": max(total_steps, 1), "journal": "准备", "query": "准备检索"})

            if self.sources.get("arxiv") and not self.should_stop():
                try:
                    batch = ArxivClient(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent(
                        max(1, (self.until_date - self.from_date).days), 1000
                    )
                    stats["success"] += 1
                except Exception as exc:
                    batch = []
                    stats["failed"] += 1
                    stats["failed_query_count"] += 1
                    if "timeout" in str(exc).lower():
                        stats["timeouts"] += 1
                    logger.warning("Survey arXiv failed: %s", exc)
                completed += 1
                self._handle_batch(batch, all_seen, stats, completed, total_steps, "arXiv", "arXiv")

            if self.sources.get("rss") and not self.should_stop():
                try:
                    rss = JournalRssFetcher(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent(
                        max(1, (self.until_date - self.from_date).days)
                    )
                    batch = rss.papers
                    stats["success"] += 1
                    stats["failed"] += int(rss.stats.failed_sources)
                    stats["failed_query_count"] += int(rss.stats.failed_sources)
                except Exception as exc:
                    batch = []
                    stats["failed"] += 1
                    stats["failed_query_count"] += 1
                    if "timeout" in str(exc).lower():
                        stats["timeouts"] += 1
                    logger.warning("Survey RSS failed: %s", exc)
                completed += 1
                self._handle_batch(batch, all_seen, stats, completed, total_steps, "顶级期刊", "最新文章")

            if self.sources.get("crossref") and not self.should_stop():
                tasks: list[tuple[dict[str, Any], str, list[str]]] = []
                for journal in top_journals:
                    issns = journal.get("issn") or []
                    if isinstance(issns, str):
                        issns = [issns]
                    if issns:
                        for query in queries:
                            tasks.append((journal, query, issns))
                    else:
                        completed += len(queries)
                        stats["failed"] += len(queries)
                        stats["failed_query_count"] += len(queries)

                pending: dict[Future, tuple[dict[str, Any], str, tuple[str, str, str, str, str]]] = {}
                task_index = 0
                batch_papers: list[Paper] = []

                def submit_next(executor: ThreadPoolExecutor) -> None:
                    nonlocal task_index, completed
                    if self.should_stop() or task_index >= len(tasks):
                        return
                    journal, query, issns = tasks[task_index]
                    task_index += 1
                    cache_key = ("crossref", str(journal.get("name")), query, self.from_date.isoformat(), self.until_date.isoformat())
                    if cache_enabled and self.db.is_query_cached_today(*cache_key):
                        completed += 1
                        stats["cached"] += 1
                        stats["cache_hit"] += 1
                        self._emit_progress(stats, completed, total_steps, str(journal.get("name")), query, all_seen)
                        submit_next(executor)
                        return
                    future = executor.submit(
                        CrossrefClient(timeout=timeout, rows=rows_per_query, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_journal_works,
                        str(journal.get("name")),
                        issns,
                        query,
                        self.from_date,
                        self.until_date,
                    )
                    pending[future] = (journal, query, cache_key)

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    for _ in range(min(max_workers, len(tasks))):
                        submit_next(executor)
                    while pending and not self.should_stop():
                        done, _ = wait(pending.keys(), timeout=0.2, return_when=FIRST_COMPLETED)
                        for future in done:
                            journal, query, cache_key = pending.pop(future)
                            batch: list[Paper] = []
                            status = "ok"
                            try:
                                result = future.result()
                                batch = result.papers
                                stats["success"] += 1
                                stats["failed"] += len(result.failed_requests)
                                stats["failed_query_count"] += len(result.failed_requests)
                            except Exception as exc:
                                status = str(exc)
                                stats["failed"] += 1
                                stats["failed_query_count"] += 1
                                if "timeout" in str(exc).lower():
                                    stats["timeouts"] += 1
                                logger.warning("Survey Crossref failed: %s", exc)
                            self.db.mark_query_cache(*cache_key, result_count=len(batch), status=status)
                            completed += 1
                            batch_papers.extend(batch)
                            if len(batch_papers) >= 10:
                                self._handle_batch(batch_papers, all_seen, stats, completed, total_steps, str(journal.get("name")), query)
                                batch_papers = []
                            else:
                                self._emit_progress(stats, completed, total_steps, str(journal.get("name")), query, all_seen)
                            if delay > 0:
                                time.sleep(delay)
                            submit_next(executor)
                if batch_papers:
                    self._handle_batch(batch_papers, all_seen, stats, completed, total_steps, "顶级期刊", "批量结果")

                if stats.get("cache_hit"):
                    cached = self.db.load_papers_for_period(
                        self.from_date.isoformat(),
                        self.until_date.isoformat(),
                        ("crossref", "journal_rss", "arxiv"),
                    )
                    if cached:
                        self._handle_batch(cached, all_seen, stats, completed, total_steps, "\u672c\u5730\u7f13\u5b58", "\u4eca\u65e5\u5df2\u7f13\u5b58\u7ed3\u679c")

            scored = score_and_tag(dedupe_papers(all_seen), self.keyword_filter, keep_unmatched=False)
            storage = self.db.upsert_papers_with_stats(scored)
            stats["deduped"] = len(scored)
            stats["displayed"] = len(scored)
            stats["inserted"] = storage.inserted_count
            stats["updated"] = storage.updated_count
            stats["elapsed_seconds"] = int(time.monotonic() - start_time)
            stats["status"] = "stopped" if self.should_stop() else ("partial_completed" if stats["failed"] else "completed")
            self.emit("survey_finished", dict(stats))
        except Exception as exc:
            logger.error("Historical survey failed: %s\n%s", exc, traceback.format_exc())
            self.emit("survey_failed", str(exc))

    def _handle_batch(
        self,
        batch: list[Paper],
        all_seen: list[Paper],
        stats: Counter,
        completed: int,
        total: int,
        journal: str,
        query: str,
    ) -> None:
        all_seen.extend(batch)
        scored = score_and_tag(dedupe_papers(all_seen), self.keyword_filter, keep_unmatched=False)
        storage = self.db.upsert_papers_with_stats(scored)
        stats["deduped"] = len(scored)
        stats["matched"] = len(scored)
        stats["displayed"] = len(scored)
        stats["inserted"] += storage.inserted_count
        stats["updated"] += storage.updated_count
        self.emit("survey_batch", scored, dict(stats))
        self._emit_progress(stats, completed, total, journal, query, all_seen)

    def _emit_progress(self, stats: Counter, completed: int, total: int, journal: str, query: str, all_seen: list[Paper]) -> None:
        self.emit(
            "survey_progress",
            {
                "completed": completed,
                "total": max(total, 1),
                "journal": journal,
                "query": query,
                "found": len(all_seen),
                "deduped": stats["deduped"],
                "matched": stats["matched"],
                "displayed": stats["displayed"],
                "success": stats["success"],
                "failed": stats["failed"],
                "cache_hit": stats["cache_hit"],
                "cached": stats["cached"],
                "timeouts": stats["timeouts"],
            },
        )


class MainWindow(tk.Tk):
    def __init__(self, first_run_needed: bool = False) -> None:
        enable_windows_high_dpi()
        super().__init__()
        self.title("PaperRadar")
        self._apply_responsive_window_size()
        try:
            self.tk.call("tk", "scaling", max(1.15, self.winfo_fpixels("1i") / 72))
        except tk.TclError:
            pass
        self.option_add("*Font", "{Microsoft YaHei UI} 10")
        # The packaged executable provides the app icon. Avoid forcing the old
        # Tk titlebar icon when running from source.

        self.db = PaperDatabase()
        self.settings = load_settings()
        self.keyword_filter = KeywordFilter(load_keywords())
        self.ui_queue: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.stop_daily_event = threading.Event()
        self.stop_survey_event = threading.Event()
        self.daily_thread: threading.Thread | None = None
        self.survey_thread: threading.Thread | None = None
        self.all_daily_papers: list[Paper] = []
        self.all_survey_papers: list[Paper] = []
        self.daily_papers: list[Paper] = []
        self.survey_papers: list[Paper] = []
        self.selected_paper: Paper | None = None
        self.validated_profile: dict[str, Any] | None = None
        self.normalized_profile_yaml = ""
        self.theme_mode = "dark"
        self.colors = self._palette(self.theme_mode)

        self._build_ui()
        self.refresh_profile_page()
        self.after(120, self._drain_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self.exit_app)
        if first_run_needed:
            self.after(300, self.show_first_run_wizard)

    def _apply_responsive_window_size(self) -> None:
        screen_w = max(self.winfo_screenwidth(), 1024)
        screen_h = max(self.winfo_screenheight(), 720)
        width = min(1560, max(1000, screen_w - 120))
        height = min(900, max(640, screen_h - 140))
        min_w = min(980, max(860, screen_w - 260))
        min_h = min(640, max(560, screen_h - 260))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min_w, min_h)

    def _palette(self, mode: str = "dark") -> dict[str, str]:
        return {
            "bg": "#f6f8fb",
            "workspace": "#f8fafc",
            "sidebar": "#eef4fb",
            "sidebar2": "#ffffff",
            "surface": "#ffffff",
            "surface2": "#f5f8fc",
            "surface3": "#e8f1ff",
            "text": "#172033",
            "muted": "#66758f",
            "inverse": "#172033",
            "inverse_muted": "#667085",
            "border": "#e3eaf3",
            "primary": "#2563eb",
            "primary_hover": "#1d4ed8",
            "accent": "#0f766e",
            "accent_soft": "#e6f7f4",
            "danger": "#b42318",
            "danger_soft": "#fff1f0",
            "success": "#15803d",
            "success_soft": "#eaf7ef",
            "warning": "#b45309",
            "warning_soft": "#fff7e6",
            "table_alt": "#fbfdff",
        }

    def _build_ui(self) -> None:
        self._configure_styles()
        self.configure(bg=self.colors["bg"])
        self.shell = ttk.Frame(self, style="Page.TFrame")
        self.shell.pack(fill="both", expand=True)
        self.shell.columnconfigure(0, minsize=252, weight=0)
        self.shell.columnconfigure(1, weight=1)
        self.shell.rowconfigure(0, weight=1)

        self.sidebar = ttk.Frame(self.shell, style="Sidebar.TFrame", padding=(12, 12))
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        brand = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        brand.pack(fill="x")
        self.logo_canvas = tk.Canvas(brand, width=30, height=30, bd=0, highlightthickness=0, bg=self.colors["sidebar"])
        self.logo_canvas.pack(side="left", padx=(0, 8))
        self._draw_logo(self.logo_canvas)
        brand_text = ttk.Frame(brand, style="Sidebar.TFrame")
        brand_text.pack(side="left", fill="x", expand=True)
        ttk.Label(brand_text, text="PaperRadar", style="SidebarBrand.TLabel").pack(anchor="w")
        ttk.Label(brand_text, text="\u6587\u732e\u96f7\u8fbe", style="SidebarMuted.TLabel").pack(anchor="w", pady=(1, 0))

        ttk.Frame(self.sidebar, style="SidebarRule.TFrame", height=1).pack(fill="x", pady=(14, 10))
        ttk.Label(self.sidebar, text="\u5de5\u4f5c\u53f0", style="SidebarSection.TLabel").pack(anchor="w", pady=(0, 6))
        self.nav_buttons: dict[str, tk.Button] = {}
        for key, label in [("daily", "\u4eca\u65e5\u53d1\u73b0"), ("survey", "\u5386\u53f2\u8c03\u7814"), ("profile", "\u7814\u7a76\u65b9\u5411")]:
            self.nav_buttons[key] = self._nav_button(self.sidebar, key, label)

        ttk.Frame(self.sidebar, style="Sidebar.TFrame").pack(fill="both", expand=True)
        local = ttk.Frame(self.sidebar, style="SidebarCard.TFrame", padding=(12, 10))
        local.pack(fill="x", pady=(12, 0))
        ttk.Label(local, text="\u672c\u5730\u6a21\u5f0f", style="SidebarCardTitle.TLabel").pack(anchor="w")
        ttk.Label(local, text="\u6570\u636e\u3001Profile \u548c\u62a5\u544a\u5747\u4fdd\u5b58\u5728\u672c\u673a", style="SidebarCardMuted.TLabel", wraplength=190).pack(anchor="w", pady=(4, 0))

        self.content = ttk.Frame(self.shell, style="Workspace.TFrame")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self.daily_tab = ttk.Frame(self.content, style="Workspace.TFrame")
        self.survey_tab = ttk.Frame(self.content, style="Workspace.TFrame")
        self.profile_tab = ttk.Frame(self.content, style="Workspace.TFrame")
        self.choice_buttons: list[tk.Button] = []
        self.check_buttons: list[tuple[tk.Button, tk.BooleanVar, str]] = []
        self.scroll_canvases: list[tk.Canvas] = []
        for frame in [self.daily_tab, self.survey_tab, self.profile_tab]:
            frame.grid(row=0, column=0, sticky="nsew")
        self._build_daily_tab()
        self._build_survey_tab()
        self._build_profile_tab()
        self._select_tab("daily")

    def _draw_logo(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        canvas.create_rectangle(1, 1, 33, 33, fill=self.colors["primary"], outline="", width=0)
        canvas.create_oval(9, 8, 23, 22, outline="#ffffff", width=2)
        canvas.create_line(21, 21, 28, 28, fill="#ffffff", width=2, capstyle="round")
        canvas.create_line(8, 27, 14, 27, fill=self.colors["accent_soft"], width=2, capstyle="round")

    def _nav_button(self, parent: ttk.Frame, key: str, text: str) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            bd=0,
            padx=16,
            pady=13,
            cursor="hand2",
            anchor="w",
            font=("Microsoft YaHei UI", 11, "bold"),
            command=lambda: self._select_tab(key),
        )
        button.pack(fill="x", pady=(0, 8))
        return button

    def _style_plain_button(self, button: tk.Button, selected: bool = False) -> None:
        button.configure(
            bg=self.colors["surface3"] if selected else self.colors["sidebar"],
            fg=self.colors["primary"] if selected else self.colors["text"],
            activebackground=self.colors["surface3"],
            activeforeground=self.colors["primary"],
            highlightthickness=2 if selected else 0,
            highlightbackground=self.colors["primary"],
            highlightcolor=self.colors["primary"],
            relief="flat",
        )

    def _cycle_value(self, var: tk.StringVar, values: list[str]) -> None:
        if not values:
            return
        try:
            index = values.index(var.get())
        except ValueError:
            index = -1
        var.set(values[(index + 1) % len(values)])

    def _select_tab(self, key: str) -> None:
        frames = {"daily": self.daily_tab, "survey": self.survey_tab, "profile": self.profile_tab}
        self.current_tab = key
        frames[key].tkraise()
        for nav_key, button in self.nav_buttons.items():
            self._style_plain_button(button, selected=nav_key == key)

    def _configure_styles(self) -> None:
        colors = self.colors
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure(".", font=("Microsoft YaHei UI", 10), background=colors["workspace"], foreground=colors["text"])
        self.style.configure("Page.TFrame", background=colors["bg"])
        self.style.configure("Workspace.TFrame", background=colors["workspace"])
        self.style.configure("Sidebar.TFrame", background=colors["sidebar"])
        self.style.configure("SidebarRule.TFrame", background=colors["border"])
        self.style.configure("SidebarCard.TFrame", background=colors["sidebar2"], relief="solid", borderwidth=1, bordercolor=colors["border"])
        self.style.configure("Card.TFrame", background=colors["surface"], relief="solid", borderwidth=1, bordercolor=colors["border"])
        self.style.configure("Header.TFrame", background=colors["surface"], relief="solid", borderwidth=1, bordercolor=colors["border"])
        self.style.configure("Table.TFrame", background=colors["surface"], relief="solid", borderwidth=1, bordercolor=colors["border"])
        self.style.configure("Brand.TLabel", background=colors["surface"], foreground=colors["text"], font=("Microsoft YaHei UI", 16, "bold"))
        self.style.configure("SidebarBrand.TLabel", background=colors["sidebar"], foreground=colors["text"], font=("Microsoft YaHei UI", 14, "bold"))
        self.style.configure("SidebarMuted.TLabel", background=colors["sidebar"], foreground=colors["muted"], font=("Microsoft YaHei UI", 9))
        self.style.configure("SidebarSection.TLabel", background=colors["sidebar"], foreground=colors["muted"], font=("Microsoft YaHei UI", 9, "bold"))
        self.style.configure("SidebarCardTitle.TLabel", background=colors["sidebar2"], foreground=colors["text"], font=("Microsoft YaHei UI", 10, "bold"))
        self.style.configure("SidebarCardMuted.TLabel", background=colors["sidebar2"], foreground=colors["muted"], font=("Microsoft YaHei UI", 9))
        self.style.configure("Title.TLabel", background=colors["surface"], foreground=colors["text"], font=("Microsoft YaHei UI", 14, "bold"))
        self.style.configure("DetailTitle.TLabel", background=colors["surface"], foreground=colors["text"], font=("Microsoft YaHei UI", 13, "bold"))
        self.style.configure("HeroTitle.TLabel", background=colors["surface"], foreground=colors["text"], font=("Microsoft YaHei UI", 16, "bold"))
        self.style.configure("Muted.TLabel", background=colors["surface"], foreground=colors["muted"])
        self.style.configure("TopMuted.TLabel", background=colors["surface"], foreground=colors["muted"], font=("Microsoft YaHei UI", 9))
        self.style.configure("Body.TLabel", background=colors["surface"], foreground=colors["text"])
        self.style.configure("Metric.TLabel", background=colors["surface2"], foreground=colors["text"], padding=(10, 7), font=("Microsoft YaHei UI", 10))
        self.style.configure("Primary.TButton", background=colors["primary"], foreground="#ffffff", padding=(14, 8), font=("Microsoft YaHei UI", 10), relief="flat", borderwidth=0)
        self.style.map("Primary.TButton", background=[("active", colors["primary_hover"]), ("disabled", "#d0d7de")], foreground=[("disabled", "#667085")])
        self.style.configure("Danger.TButton", background=colors["danger_soft"], foreground=colors["danger"], padding=(14, 8), font=("Microsoft YaHei UI", 10), relief="flat", borderwidth=0)
        self.style.map("Danger.TButton", background=[("active", "#f3c7c2"), ("disabled", colors["surface3"])], foreground=[("disabled", "#98a2b3")])
        self.style.configure("Secondary.TButton", background=colors["surface3"], foreground=colors["text"], padding=(14, 8), font=("Microsoft YaHei UI", 10), relief="flat", borderwidth=0)
        self.style.map("Secondary.TButton", background=[("active", "#dcecff")], foreground=[("active", colors["primary"])])
        self.style.configure("TCheckbutton", background=colors["surface"], foreground=colors["text"], indicatorcolor=colors["surface"], indicatordiameter=14, padding=(8, 5))
        self.style.map("TCheckbutton", background=[("active", colors["surface2"])], foreground=[("active", colors["text"])], indicatorcolor=[("selected", colors["primary"]), ("!selected", colors["surface"])])
        self.style.configure("TEntry", fieldbackground=colors["surface"], foreground=colors["text"], bordercolor=colors["border"], lightcolor=colors["border"], darkcolor=colors["border"], padding=(9, 7), insertcolor=colors["text"])
        self.style.configure("TSpinbox", fieldbackground=colors["surface"], foreground=colors["text"], bordercolor=colors["border"], lightcolor=colors["border"], darkcolor=colors["border"], arrowsize=0, padding=(8, 6))
        self.style.configure("Treeview", background=colors["surface"], fieldbackground=colors["surface"], foreground=colors["text"], rowheight=36, borderwidth=0, relief="flat", bordercolor=colors["surface"], lightcolor=colors["surface"], darkcolor=colors["surface"], font=("Microsoft YaHei UI", 10))
        self.style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", colors["text"])])
        self.style.configure("Treeview.Heading", background=colors["surface2"], foreground=colors["muted"], padding=(10, 8), font=("Microsoft YaHei UI", 10, "bold"), relief="flat", borderwidth=0, bordercolor=colors["surface"], lightcolor=colors["surface"], darkcolor=colors["surface"])
        self.style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        self.style.layout("Horizontal.TScrollbar", [("Horizontal.Scrollbar.trough", {"sticky": "ew", "children": [("Horizontal.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        self.style.configure("Vertical.TScrollbar", background="#c9d7eb", troughcolor="#edf3fa", bordercolor="#f7fbff", arrowcolor="#f7fbff", relief="flat", width=14, arrowsize=1, gripcount=0)
        self.style.configure("Horizontal.TScrollbar", background="#c9d7eb", troughcolor="#edf3fa", bordercolor="#f7fbff", arrowcolor="#f7fbff", relief="flat", width=14, arrowsize=1, gripcount=0)
        self.style.map("Vertical.TScrollbar", background=[("active", colors["primary_hover"])])
        self.style.map("Horizontal.TScrollbar", background=[("active", colors["primary_hover"])])
        self.style.configure("Horizontal.TProgressbar", background=colors["primary"], troughcolor="#f7fbff", bordercolor="#f7fbff", lightcolor=colors["primary"], darkcolor=colors["primary"])

    def _style_text_widget(self, widget: tk.Text | scrolledtext.ScrolledText | None) -> None:
        if widget is None:
            return
        widget.configure(
            bg=self.colors["surface"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            selectbackground="#dbeafe",
            selectforeground=self.colors["text"],
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            font=("Microsoft YaHei UI", 10),
        )

    def _page_header(self, parent: ttk.Frame, title: str, subtitle: str) -> None:
        header = ttk.Frame(parent, style="Header.TFrame", padding=(18, 16))
        header.pack(fill="x", padx=18, pady=(14, 8))
        ttk.Label(header, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text=subtitle, style="Muted.TLabel", wraplength=440, justify="left").pack(anchor="w", fill="x", pady=(6, 0))

    def _card(self, parent: ttk.Frame, title: str | None = None) -> ttk.Frame:
        outer = ttk.Frame(parent, style="Card.TFrame", padding=(16, 12))
        if title:
            ttk.Label(outer, text=title, style="Body.TLabel", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 10))
        return outer

    def _scrollable_panel(self, parent: ttk.Frame) -> tuple[ttk.Frame, ttk.Frame]:
        return self._scrollable_workspace(parent, min_width=320)

    def _scrollable_workspace(self, parent: ttk.Frame, min_width: int = 1080) -> tuple[ttk.Frame, ttk.Frame]:
        outer = ttk.Frame(parent, style="Workspace.TFrame")
        canvas = tk.Canvas(outer, bd=0, highlightthickness=0, bg=self.colors["workspace"], yscrollincrement=24, xscrollincrement=24)
        vscroll = ttk.Scrollbar(outer, orient="vertical", style="Vertical.TScrollbar", command=canvas.yview)
        hscroll = ttk.Scrollbar(outer, orient="horizontal", style="Horizontal.TScrollbar", command=canvas.xview)
        inner = ttk.Frame(canvas, style="Workspace.TFrame")
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        def sync_scroll_region(_event: tk.Event | None = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def sync_inner_width(event: tk.Event) -> None:
            canvas.itemconfigure(window_id, width=max(event.width, min_width))

        def wheel(event: tk.Event) -> str:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        def shift_wheel(event: tk.Event) -> str:
            canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        inner.bind("<Configure>", sync_scroll_region)
        canvas.bind("<Configure>", sync_inner_width)
        for widget in (canvas, inner):
            widget.bind("<MouseWheel>", wheel)
            widget.bind("<Shift-MouseWheel>", shift_wheel)
        self.scroll_canvases.append(canvas)
        return outer, inner

    def _scrollable_workspace(self, parent: ttk.Frame, min_width: int = 1180) -> tuple[ttk.Frame, ttk.Frame]:
        outer = ttk.Frame(parent, style="Workspace.TFrame")
        canvas = tk.Canvas(outer, bd=0, highlightthickness=0, bg=self.colors["workspace"], yscrollincrement=28, xscrollincrement=28)
        vscroll = ttk.Scrollbar(outer, orient="vertical", style="Vertical.TScrollbar", command=canvas.yview)
        hscroll = ttk.Scrollbar(outer, orient="horizontal", style="Horizontal.TScrollbar", command=canvas.xview)
        inner = ttk.Frame(canvas, style="Workspace.TFrame")
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        def sync_scroll_region(_event: tk.Event | None = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def sync_inner_width(event: tk.Event) -> None:
            canvas.itemconfigure(window_id, width=max(event.width, min_width))

        def wheel(event: tk.Event) -> str:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        def shift_wheel(event: tk.Event) -> str:
            canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        inner.bind("<Configure>", sync_scroll_region)
        canvas.bind("<Configure>", sync_inner_width)
        for widget in (canvas, inner):
            widget.bind("<MouseWheel>", wheel)
            widget.bind("<Shift-MouseWheel>", shift_wheel)
        self.scroll_canvases.append(canvas)
        return outer, inner

    def _check_pill(self, parent: ttk.Frame, text: str, var: tk.BooleanVar) -> tk.Button:
        button = tk.Button(
            parent,
            bd=0,
            padx=14,
            pady=9,
            cursor="hand2",
            anchor="w",
            font=("Microsoft YaHei UI", 10, "bold"),
            command=lambda: self._toggle_check_pill(var),
        )
        self.check_buttons.append((button, var, text))
        var.trace_add("write", lambda *_args, b=button, v=var, label=text: self._style_check_pill(b, v, label))
        self._style_check_pill(button, var, text)
        return button

    def _toggle_check_pill(self, var: tk.BooleanVar) -> None:
        var.set(not var.get())

    def _style_check_pill(self, button: tk.Button, var: tk.BooleanVar, text: str) -> None:
        selected = bool(var.get())
        button.configure(
            text=f"{text}\uff1a{'\u5df2\u542f\u7528' if selected else '\u672a\u542f\u7528'}",
            bg=self.colors["success_soft"] if selected else self.colors["surface2"],
            fg=self.colors["success"] if selected else self.colors["muted"],
            activebackground=self.colors["success_soft"] if selected else self.colors["surface3"],
            activeforeground=self.colors["success"] if selected else self.colors["text"],
            highlightthickness=0,
            relief="flat",
        )

    def _build_daily_tab(self) -> None:
        shell, body = self._scrollable_workspace(self.daily_tab, min_width=1080)
        shell.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        hero = self._card(body)
        hero.pack(fill="x", padx=18, pady=(18, 10))
        hero.columnconfigure(0, weight=1)
        hero_left = ttk.Frame(hero, style="Card.TFrame")
        hero_left.grid(row=0, column=0, sticky="ew")
        ttk.Label(hero_left, text="\u4eca\u65e5\u53d1\u73b0", style="HeroTitle.TLabel").pack(anchor="w")
        ttk.Label(hero_left, text="\u628a\u65b0\u8bba\u6587\u3001\u76f8\u5173\u6027\u8bc4\u5206\u548c\u53ef\u8bfb\u6458\u8981\u96c6\u4e2d\u5230\u4e00\u4e2a\u5de5\u4f5c\u53f0\u3002\u5148\u8fd0\u884c\u68c0\u7d22\uff0c\u518d\u7b5b\u9009\u9700\u8981\u7cbe\u8bfb\u7684\u7ed3\u679c\u3002", style="Muted.TLabel", wraplength=680, justify="left").pack(anchor="w", pady=(6, 0))
        hero_actions = ttk.Frame(hero, style="Card.TFrame")
        hero_actions.grid(row=0, column=1, sticky="e", padx=(20, 0))
        self.daily_run_btn = ttk.Button(hero_actions, text="\u7acb\u5373\u68c0\u67e5", style="Primary.TButton", command=self.run_daily)
        self.daily_stop_btn = ttk.Button(hero_actions, text="\u505c\u6b62", style="Danger.TButton", command=self.stop_daily, state="disabled")
        self.daily_run_btn.pack(side="left", padx=(0, 8))
        self.daily_stop_btn.pack(side="left")

        metrics = ttk.Frame(body, style="Workspace.TFrame")
        metrics.pack(fill="x", padx=18, pady=(0, 10))
        for index in range(5):
            metrics.columnconfigure(index, weight=1, uniform="metric")
        self.daily_last_var = tk.StringVar(value="\u4e0a\u6b21\u68c0\u67e5\uff1a\u4ece\u672a")
        self.daily_found_var = tk.StringVar(value="\u672c\u6b21\u53d1\u73b0\uff1a0")
        self.daily_high_var = tk.StringVar(value="\u9ad8\u76f8\u5173\uff1a0")
        self.daily_skim_var = tk.StringVar(value="\u503c\u5f97\u626b\u8bfb\uff1a0")
        self.daily_status_var = tk.StringVar(value="\u5c31\u7eea")
        for index, var in enumerate([self.daily_last_var, self.daily_found_var, self.daily_high_var, self.daily_skim_var, self.daily_status_var]):
            card = self._card(metrics)
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 8 if index < 4 else 0))
            ttk.Label(card, textvariable=var, style="Metric.TLabel", wraplength=185).pack(fill="x")

        control_grid = ttk.Frame(body, style="Workspace.TFrame")
        control_grid.pack(fill="x", padx=18, pady=(0, 10))
        control_grid.columnconfigure(0, weight=2)
        control_grid.columnconfigure(1, weight=2)
        control_grid.columnconfigure(2, weight=3)

        settings = self._card(control_grid, "\u68c0\u7d22\u53c2\u6570")
        settings.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.daily_days_var = tk.StringVar(value=str(min(int(self.settings.get("days_back", 7)), 30)))
        self.daily_min_score_var = tk.IntVar(value=20)
        row = ttk.Frame(settings, style="Card.TFrame")
        row.pack(fill="x")
        self._labeled_combo(row, "\u6700\u8fd1\u5929\u6570", self.daily_days_var, ["1", "3", "7", "14", "30"]).pack(side="left", padx=(0, 10))
        self._labeled_spin(row, "\u6700\u4f4e\u5206", self.daily_min_score_var, 20, 100).pack(side="left")
        self.daily_min_score_var.trace_add("write", lambda *_: self.refresh_daily_display())

        sources = self._card(control_grid, "\u6570\u636e\u6765\u6e90")
        sources.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        self.daily_arxiv_var = tk.BooleanVar(value=True)
        self.daily_top_journals_var = tk.BooleanVar(value=True)
        self._check_pill(sources, "\u9884\u5370\u672c\uff08arXiv\uff09", self.daily_arxiv_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._check_pill(sources, "\u9876\u7ea7\u671f\u520a", self.daily_top_journals_var).pack(side="left", fill="x", expand=True)

        progress = self._card(control_grid, "\u8fd0\u884c\u72b6\u6001")
        progress.grid(row=0, column=2, sticky="nsew")
        self.daily_progress = ttk.Progressbar(progress, maximum=1)
        self.daily_progress_var = tk.StringVar(value="\u5c31\u7eea")
        ttk.Label(progress, textvariable=self.daily_progress_var, style="Muted.TLabel", wraplength=440).pack(anchor="w", fill="x", pady=(8, 0))

        quick = self._card(body, "\u5e38\u7528\u64cd\u4f5c")
        quick.pack(fill="x", padx=18, pady=(0, 10))
        for button in [
            ttk.Button(quick, text="\u751f\u6210\u4eca\u65e5\u62a5\u544a", style="Secondary.TButton", command=self.generate_daily_report),
            ttk.Button(quick, text="\u6253\u5f00\u62a5\u544a\u6587\u4ef6\u5939", style="Secondary.TButton", command=self.open_report_folder),
            ttk.Button(quick, text="\u67e5\u770b\u68c0\u7d22\u8303\u56f4", style="Secondary.TButton", command=lambda: self.show_search_scope("daily")),
        ]:
            button.pack(side="left", padx=(0, 8))

        self._research_focus_strip(body, "daily")
        self._build_result_tools(body, "daily")
        self.daily_tree, self.daily_detail_text = self._build_results_area(body, "daily")

    def _build_survey_tab(self) -> None:
        shell, body = self._scrollable_workspace(self.survey_tab, min_width=1080)
        shell.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        hero = self._card(body)
        hero.pack(fill="x", padx=18, pady=(18, 10))
        hero.columnconfigure(0, weight=1)
        hero_left = ttk.Frame(hero, style="Card.TFrame")
        hero_left.grid(row=0, column=0, sticky="ew")
        ttk.Label(hero_left, text="\u5386\u53f2\u8c03\u7814", style="HeroTitle.TLabel").pack(anchor="w")
        ttk.Label(hero_left, text="\u9762\u5411\u5f00\u9898\u3001\u7efc\u8ff0\u548c\u65b9\u5411\u590d\u76d8\u7684\u6279\u91cf\u68c0\u7d22\u5de5\u4f5c\u533a\u3002\u7ed3\u679c\u4f1a\u6301\u7eed\u5165\u5e93\uff0c\u505c\u6b62\u540e\u5df2\u4fdd\u5b58\u5185\u5bb9\u4ecd\u4fdd\u7559\u3002", style="Muted.TLabel", wraplength=680, justify="left").pack(anchor="w", pady=(6, 0))
        hero_actions = ttk.Frame(hero, style="Card.TFrame")
        hero_actions.grid(row=0, column=1, sticky="e", padx=(20, 0))
        self.survey_run_btn = ttk.Button(hero_actions, text="\u5f00\u59cb\u8c03\u7814", style="Primary.TButton", command=self.run_survey)
        self.survey_stop_btn = ttk.Button(hero_actions, text="\u505c\u6b62", style="Danger.TButton", command=self.stop_survey, state="disabled")
        self.survey_run_btn.pack(side="left", padx=(0, 8))
        self.survey_stop_btn.pack(side="left")

        control_grid = ttk.Frame(body, style="Workspace.TFrame")
        control_grid.pack(fill="x", padx=18, pady=(0, 10))
        for index in range(3):
            control_grid.columnconfigure(index, weight=1, uniform="survey_controls")

        settings = self._card(control_grid, "\u8c03\u7814\u53c2\u6570")
        settings.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.survey_name_var = tk.StringVar(value="\u5f53\u524d\u65b9\u5411\u5386\u53f2\u8c03\u7814")
        self.survey_range_var = tk.StringVar(value="\u6700\u8fd1 365 \u5929")
        self.survey_min_score_var = tk.IntVar(value=20)
        self._labeled_entry(settings, "\u540d\u79f0", self.survey_name_var, 22).pack(fill="x", pady=(0, 8))
        row = ttk.Frame(settings, style="Card.TFrame")
        row.pack(fill="x")
        self._labeled_combo(row, "\u8303\u56f4", self.survey_range_var, ["\u6700\u8fd1 90 \u5929", "\u6700\u8fd1 365 \u5929", "\u6700\u8fd1 3 \u5e74"]).pack(side="left", padx=(0, 10))
        self._labeled_spin(row, "\u6700\u4f4e\u5206", self.survey_min_score_var, 20, 100).pack(side="left")
        self.survey_min_score_var.trace_add("write", lambda *_: self.refresh_survey_display())

        sources = self._card(control_grid, "\u6570\u636e\u6765\u6e90")
        sources.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        self.survey_arxiv_var = tk.BooleanVar(value=False)
        self.survey_top_journals_var = tk.BooleanVar(value=True)
        self._check_pill(sources, "\u9884\u5370\u672c\uff08arXiv\uff09", self.survey_arxiv_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._check_pill(sources, "\u9876\u7ea7\u671f\u520a", self.survey_top_journals_var).pack(side="left", fill="x", expand=True)

        progress = self._card(control_grid, "\u8fd0\u884c\u72b6\u6001")
        progress.grid(row=0, column=2, sticky="nsew")
        self.survey_progress = ttk.Progressbar(progress, maximum=1)
        self.survey_status_var = tk.StringVar(value="\u5c31\u7eea；\u82e5\u4eca\u65e5\u5df2\u6709\u76f8\u540c\u8c03\u7814\u7f13\u5b58\uff0c\u5c06\u76f4\u63a5\u590d\u7528\u3002")
        self.survey_counts_var = tk.StringVar(value="\u5173\u952e\u8fd0\u884c\u4fe1\u606f：\u5df2\u53d1\u73b0 0；\u6210\u529f 0；\u5931\u8d25 0；\u4eca\u65e5\u7f13\u5b58 0")
        ttk.Label(progress, textvariable=self.survey_status_var, style="Muted.TLabel", wraplength=390).pack(anchor="w", fill="x", pady=(8, 4))
        ttk.Label(progress, textvariable=self.survey_counts_var, style="Muted.TLabel", wraplength=390).pack(anchor="w", fill="x")

        quick = self._card(body, "\u5e38\u7528\u64cd\u4f5c")
        quick.pack(fill="x", padx=18, pady=(0, 10))
        for button in [
            ttk.Button(quick, text="\u751f\u6210\u8c03\u7814\u62a5\u544a", style="Secondary.TButton", command=self.generate_survey_report),
            ttk.Button(quick, text="\u6253\u5f00\u62a5\u544a\u6587\u4ef6\u5939", style="Secondary.TButton", command=self.open_report_folder),
            ttk.Button(quick, text="\u67e5\u770b\u68c0\u7d22\u8303\u56f4", style="Secondary.TButton", command=lambda: self.show_search_scope("survey")),
        ]:
            button.pack(side="left", padx=(0, 8))

        self._research_focus_strip(body, "survey")
        self._build_result_tools(body, "survey")
        self.survey_tree, self.survey_detail_text = self._build_results_area(body, "survey")

    def _research_focus_strip(self, parent: ttk.Frame, prefix: str) -> None:
        title = "今日论文信号" if prefix == "daily" else "历史文献地图"
        message = (
            "先运行检索，再通过分数、来源和关键词快速收敛需要精读的论文。"
            if prefix == "daily"
            else "用时间范围和最低分控制检索密度，适合做开题、综述和方向复盘。"
        )
        strip = ttk.Frame(parent, style="Card.TFrame", padding=(16, 10))
        strip.pack(fill="x", padx=18, pady=(10, 4))
        ttk.Label(strip, text=title, style="Body.TLabel", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left", padx=(0, 14))
        ttk.Label(strip, text=message, style="Muted.TLabel", wraplength=760).pack(side="left", fill="x", expand=True)

    def _build_profile_tab(self) -> None:
        shell, body = self._scrollable_workspace(self.profile_tab, min_width=1120)
        shell.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        hero = self._card(body)
        hero.pack(fill="x", padx=18, pady=(18, 10))
        ttk.Label(hero, text="\u7814\u7a76\u65b9\u5411", style="HeroTitle.TLabel").pack(anchor="w")
        ttk.Label(hero, text="\u7ba1\u7406 Profile\u3001\u5173\u952e\u8bcd\u548c AI \u8f85\u52a9\u5bfc\u5165\u3002\u5f53\u524d\u65b9\u5411\u4f1a\u51b3\u5b9a\u6bcf\u65e5\u53d1\u73b0\u548c\u5386\u53f2\u8c03\u7814\u7684\u68c0\u7d22\u4e0e\u8bc4\u5206\u3002", style="Muted.TLabel", wraplength=820, justify="left").pack(anchor="w", pady=(6, 0))

        status = self._card(body, "\u5f53\u524d Profile")
        status.pack(fill="x", padx=18, pady=(0, 10))
        self.profile_status_var = tk.StringVar(value="")
        ttk.Label(status, textvariable=self.profile_status_var, style="Metric.TLabel", wraplength=1040).pack(fill="x")
        actions = ttk.Frame(status, style="Card.TFrame")
        actions.pack(fill="x", pady=(10, 0))
        for button in [
            ttk.Button(actions, text="\u8bbe\u4e3a\u5f53\u524d\u65b9\u5411", style="Primary.TButton", command=self.set_selected_profile_active),
            ttk.Button(actions, text="\u590d\u5236\u5f53\u524d Profile", style="Secondary.TButton", command=self.copy_current_profile),
            ttk.Button(actions, text="\u5bfc\u51fa Profile", style="Secondary.TButton", command=self.export_selected_profile),
            ttk.Button(actions, text="\u5220\u9664 Profile", style="Danger.TButton", command=self.delete_selected_profile),
        ]:
            button.pack(side="left", padx=(0, 8))

        table_card = self._card(body, "Profile \u5217\u8868")
        table_card.pack(fill="x", padx=18, pady=(0, 10))
        self.profile_tree = ttk.Treeview(table_card, columns=("name", "id", "desc", "queries", "keywords", "active"), show="headings", height=4)
        for key, text, width in [
            ("name", "\u663e\u793a\u540d\u79f0", 170),
            ("id", "Profile ID", 180),
            ("desc", "\u63cf\u8ff0", 360),
            ("queries", "\u68c0\u7d22\u5f0f", 90),
            ("keywords", "\u5173\u952e\u8bcd\u7ec4", 360),
            ("active", "\u5f53\u524d", 80),
        ]:
            self.profile_tree.heading(key, text=text)
            self.profile_tree.column(key, width=width, anchor="center")
        self.profile_tree.pack(fill="x")
        self.profile_tree.bind("<<TreeviewSelect>>", lambda _event: self._on_profile_selected())
        self.profile_tree.bind("<Double-1>", lambda _event: self._show_tree_cell_popup(self.profile_tree))

        keyword_editor = self._card(body, "\u5173\u952e\u8bcd\u5de5\u4f5c\u53f0")
        keyword_editor.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.keyword_editor_status_var = tk.StringVar(value="\u5148\u9009\u62e9\u7814\u7a76\u65b9\u5411\uff1b\u4e0a\u65b9\u8868\u683c\u7ba1\u7406\u5df2\u6709\u5173\u952e\u8bcd\uff0c\u4e0b\u65b9\u8868\u5355\u7528\u4e8e\u65b0\u589e\u5173\u952e\u8bcd\u3002")
        ttk.Label(keyword_editor, textvariable=self.keyword_editor_status_var, style="Metric.TLabel", wraplength=1040).pack(fill="x", pady=(0, 8))
        editor_body = ttk.Frame(keyword_editor, style="Card.TFrame")
        editor_body.pack(fill="both", expand=True)
        self.keyword_tree = ttk.Treeview(editor_body, columns=("group", "priority", "term"), show="headings", height=6)
        for key, text, width in [("group", "\u5206\u7ec4", 180), ("priority", "\u6743\u91cd", 100), ("term", "\u5df2\u6709\u5173\u952e\u8bcd", 720)]:
            self.keyword_tree.heading(key, text=text)
            self.keyword_tree.column(key, width=width, anchor="w" if key == "term" else "center")
        self.keyword_tree.pack(side="left", fill="both", expand=True)
        keyword_scroll = ttk.Scrollbar(editor_body, orient="vertical", style="Vertical.TScrollbar", command=self.keyword_tree.yview)
        self.keyword_tree.configure(yscrollcommand=keyword_scroll.set)
        keyword_scroll.pack(side="right", fill="y")
        self.keyword_tree.bind("<<TreeviewSelect>>", lambda _event: self._on_keyword_selected())

        edit_grid = ttk.Frame(keyword_editor, style="Card.TFrame")
        edit_grid.pack(fill="x", pady=(10, 0))
        edit_grid.columnconfigure(0, weight=1)
        edit_grid.columnconfigure(1, weight=1)

        existing_card = ttk.Frame(edit_grid, style="Card.TFrame")
        existing_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ttk.Label(existing_card, text="\u7f16\u8f91\u9009\u4e2d\u5173\u952e\u8bcd", style="Body.TLabel", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
        existing_row = ttk.Frame(existing_card, style="Card.TFrame")
        existing_row.pack(fill="x")
        self.keyword_group_var = tk.StringVar(value="core")
        self.keyword_priority_var = tk.StringVar(value="medium")
        self.keyword_term_var = tk.StringVar(value="")
        self._labeled_entry(existing_row, "\u5206\u7ec4", self.keyword_group_var, 16).pack(side="left", padx=(0, 8))
        self._labeled_combo(existing_row, "\u6743\u91cd", self.keyword_priority_var, ["high", "medium", "low", "exclude"]).pack(side="left", padx=(0, 8))
        self._labeled_entry(existing_row, "\u5173\u952e\u8bcd", self.keyword_term_var, 26).pack(side="left", fill="x", expand=True)
        existing_actions = ttk.Frame(existing_card, style="Card.TFrame")
        existing_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(existing_actions, text="\u4fdd\u5b58\u4fee\u6539", style="Primary.TButton", command=self.update_profile_keyword).pack(side="left", padx=(0, 8))
        ttk.Button(existing_actions, text="\u5220\u9664\u5173\u952e\u8bcd", style="Danger.TButton", command=self.delete_profile_keyword).pack(side="left")

        add_card = ttk.Frame(edit_grid, style="Card.TFrame")
        add_card.grid(row=0, column=1, sticky="nsew")
        ttk.Label(add_card, text="\u65b0\u589e\u5173\u952e\u8bcd", style="Body.TLabel", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
        add_row = ttk.Frame(add_card, style="Card.TFrame")
        add_row.pack(fill="x")
        self.new_keyword_group_var = tk.StringVar(value="core")
        self.new_keyword_priority_var = tk.StringVar(value="medium")
        self.new_keyword_term_var = tk.StringVar(value="")
        self._labeled_entry(add_row, "\u5206\u7ec4", self.new_keyword_group_var, 16).pack(side="left", padx=(0, 8))
        self._labeled_combo(add_row, "\u6743\u91cd", self.new_keyword_priority_var, ["high", "medium", "low", "exclude"]).pack(side="left", padx=(0, 8))
        self._labeled_entry(add_row, "\u65b0\u5173\u952e\u8bcd", self.new_keyword_term_var, 26).pack(side="left", fill="x", expand=True)
        add_actions = ttk.Frame(add_card, style="Card.TFrame")
        add_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(add_actions, text="\u6dfb\u52a0\u5230\u5217\u8868", style="Secondary.TButton", command=self.add_profile_keyword).pack(side="left", padx=(0, 8))
        ttk.Button(add_actions, text="\u4fdd\u5b58\u5168\u90e8\u5173\u952e\u8bcd", style="Primary.TButton", command=self.save_keyword_editor_profile).pack(side="left")

        prompt = self._card(body, "AI \u63d0\u793a\u8bcd\u751f\u6210")
        prompt.pack(fill="x", padx=18, pady=(0, 10))
        prompt_row = ttk.Frame(prompt, style="Card.TFrame")
        prompt_row.pack(fill="x")
        self.profile_direction_var = tk.StringVar()
        self._labeled_entry(prompt_row, "\u7814\u7a76\u65b9\u5411", self.profile_direction_var, 38).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Button(prompt_row, text="\u751f\u6210\u5e76\u590d\u5236 AI \u63d0\u793a\u8bcd", style="Primary.TButton", command=self.generate_and_copy_profile_prompt).pack(side="left")

        importer = self._card(body, "Profile \u6279\u91cf\u5bfc\u5165")
        importer.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.profile_yaml_text = scrolledtext.ScrolledText(importer, height=8, wrap="word", bg=self.colors["surface"], fg=self.colors["text"], insertbackground=self.colors["text"])
        self._style_text_widget(self.profile_yaml_text)
        self.profile_yaml_text.pack(fill="both", expand=True)
        import_actions = ttk.Frame(importer, style="Card.TFrame")
        import_actions.pack(fill="x", pady=(10, 8))
        for button in [
            ttk.Button(import_actions, text="\u7c98\u8d34\u526a\u8d34\u677f\u5185\u5bb9", style="Secondary.TButton", command=self.paste_profile_yaml),
            ttk.Button(import_actions, text="\u89e3\u6790\u5e76\u9884\u89c8", style="Primary.TButton", command=self.validate_profile_input),
            ttk.Button(import_actions, text="\u4fdd\u5b58\u5e76\u8bbe\u4e3a\u5f53\u524d\u65b9\u5411", style="Primary.TButton", command=lambda: self.save_validated_profile(make_active=True)),
        ]:
            button.pack(side="left", padx=(0, 8))
        self.profile_validation_var = tk.StringVar(value="\u5c1a\u672a\u89e3\u6790\uff0c\u8bf7\u5148\u7c98\u8d34 Profile \u914d\u7f6e\u5e76\u70b9\u51fb\u89e3\u6790\u5e76\u9884\u89c8\u3002")
        ttk.Label(importer, textvariable=self.profile_validation_var, style="Metric.TLabel", wraplength=1040).pack(fill="x")

    def _labeled_entry(self, parent: ttk.Frame, label: str, var: tk.StringVar, width: int) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame")
        ttk.Label(frame, text=label, style="Body.TLabel").pack(side="left", padx=(0, 6))
        ttk.Entry(frame, textvariable=var, width=width).pack(side="left")
        return frame

    def _labeled_combo(self, parent: ttk.Frame, label: str, var: tk.StringVar, values: list[str]) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame")
        ttk.Label(frame, text=label, style="Body.TLabel").pack(side="left", padx=(0, 6))
        button = tk.Button(
            frame,
            textvariable=var,
            bd=0,
            padx=18,
            pady=10,
            width=max(9, min(14, max((len(str(value)) for value in values), default=7) + 2)),
            cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold"),
            command=lambda: self._cycle_value(var, values),
        )
        self.choice_buttons.append(button)
        self._style_plain_button(button)
        button.pack(side="left")
        return frame

    def _labeled_spin(self, parent: ttk.Frame, label: str, var: tk.IntVar, from_: int, to: int) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame")
        ttk.Label(frame, text=label, style="Body.TLabel").pack(side="left", padx=(0, 6))
        entry = ttk.Entry(frame, textvariable=var, width=6)
        entry.pack(side="left")
        entry.bind("<FocusOut>", lambda _event: var.set(min(max(self._safe_int(var.get(), from_), from_), to)))
        return frame

    def _build_result_tools(self, parent: ttk.Frame, prefix: str) -> None:
        tools = self._card(parent, "结果筛选")
        tools.pack(fill="x", padx=18, pady=(10, 6))
        top = ttk.Frame(tools, style="Card.TFrame")
        top.pack(fill="x")
        search_var = tk.StringVar()
        source_var = tk.StringVar(value="全部来源")
        ttk.Label(top, text="关键词", style="Body.TLabel").pack(side="left", padx=(0, 8))
        search_entry = ttk.Entry(top, textvariable=search_var, width=48)
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        search_entry.bind("<Return>", lambda _event, p=prefix: self._direct_search(p))
        self._labeled_combo(top, "来源", source_var, ["全部来源", "预印本（arXiv）", "顶级期刊"]).pack(side="left", padx=(0, 10))
        ttk.Button(top, text="运行检索", style="Primary.TButton", command=lambda p=prefix: self._direct_search(p)).pack(side="left", padx=(0, 8))
        ttk.Button(top, text="清空", style="Secondary.TButton", command=lambda p=prefix: self._clear_result_filters(p)).pack(side="left")

        bottom = ttk.Frame(tools, style="Card.TFrame")
        bottom.pack(fill="x", pady=(12, 0))
        summary_var = tk.StringVar(value="当前显示 0 篇；高相关 0 篇")
        signal_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=summary_var, style="Metric.TLabel").pack(side="left", fill="x", expand=True)
        if prefix == "daily":
            self.daily_filter_var = search_var
            self.daily_source_filter_var = source_var
            self.daily_summary_var = summary_var
            self.daily_signal_var = signal_var
            search_var.trace_add("write", lambda *_: self.refresh_daily_display())
            source_var.trace_add("write", lambda *_: self.refresh_daily_display())
        else:
            self.survey_filter_var = search_var
            self.survey_source_filter_var = source_var
            self.survey_summary_var = summary_var
            self.survey_signal_var = signal_var
            search_var.trace_add("write", lambda *_: self.refresh_survey_display())
            source_var.trace_add("write", lambda *_: self.refresh_survey_display())

    def _clear_result_filters(self, prefix: str) -> None:
        if prefix == "daily":
            self.daily_filter_var.set("")
            self.daily_source_filter_var.set("全部来源")
            self.refresh_daily_display()
        else:
            self.survey_filter_var.set("")
            self.survey_source_filter_var.set("全部来源")
            self.refresh_survey_display()

    def _direct_search(self, prefix: str) -> None:
        if prefix == "daily":
            if self.daily_thread and self.daily_thread.is_alive():
                return
            self.run_daily()
        else:
            if self.survey_thread and self.survey_thread.is_alive():
                return
            self.run_survey()

    def _build_results_area(self, parent: ttk.Frame, prefix: str) -> tuple[ttk.Treeview, tk.Text]:
        outer = ttk.Frame(parent, style="Page.TFrame")
        outer.pack(fill="both", expand=True, padx=18, pady=(4, 0))
        outer.rowconfigure(0, weight=3)
        outer.rowconfigure(1, weight=2)
        outer.columnconfigure(0, weight=1)

        table_card = ttk.Frame(outer, style="Table.TFrame", padding=(12, 10))
        table_card.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        table_title = "\u4eca\u65e5\u8bba\u6587\u5217\u8868" if prefix == "daily" else "\u5386\u53f2\u8c03\u7814\u7ed3\u679c"
        ttk.Label(table_card, text=table_title, style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        tree = ttk.Treeview(table_card, columns=RESULT_COLUMNS, show="headings", height=8)
        headings = {
            "score": "\u5206\u6570",
            "source": "\u6765\u6e90",
            "type": "\u7c7b\u578b",
            "title": "\u6807\u9898",
            "authors": "\u4f5c\u8005",
            "date": "\u53d1\u5e03\u65e5\u671f",
            "keywords": "\u547d\u4e2d\u5173\u952e\u8bcd",
            "action": "\u64cd\u4f5c",
        }
        widths = {"score": 72, "source": 128, "type": 112, "title": 500, "authors": 220, "date": 118, "keywords": 260, "action": 92}
        for col in RESULT_COLUMNS:
            tree.heading(col, text=headings[col], command=lambda c=col: self._sort_tree(tree, c, False))
            anchor = "w" if col in {"title", "authors", "keywords"} else "center"
            tree.column(col, width=widths[col], minwidth=76, anchor=anchor, stretch=False)
        yscroll = ttk.Scrollbar(table_card, orient="vertical", style="Vertical.TScrollbar", command=tree.yview)
        xscroll = ttk.Scrollbar(table_card, orient="horizontal", style="Horizontal.TScrollbar", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=1, column=0, sticky="nsew")
        yscroll.grid(row=1, column=1, sticky="ns", padx=(8, 0))
        xscroll.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        table_card.rowconfigure(1, weight=1)
        table_card.columnconfigure(0, weight=1)
        tree.tag_configure("odd", background=self.colors["table_alt"])
        tree.tag_configure("high", background=self.colors["success_soft"], foreground=self.colors["text"])
        tree.tag_configure("skim", background=self.colors["warning_soft"], foreground=self.colors["text"])
        tree.tag_configure("empty", background=self.colors["surface"], foreground=self.colors["muted"])
        tree.bind("<<TreeviewSelect>>", lambda _event, t=tree, p=prefix: self._select_result(t, p))
        tree.bind("<ButtonRelease-1>", lambda event, t=tree: self._open_tree_link_on_click(event, t), add="+")
        tree.bind("<Double-1>", lambda _event, t=tree: self._open_selected_tree_link(t))

        detail_card = ttk.Frame(outer, style="Card.TFrame", padding=(18, 14))
        detail_card.grid(row=1, column=0, sticky="nsew")
        title_var = tk.StringVar(value="\u9009\u62e9\u4e00\u7bc7\u8bba\u6587\u540e\uff0c\u8fd9\u91cc\u4f1a\u663e\u793a\u8bba\u6587\u8be6\u60c5")
        meta_var = tk.StringVar(value="\u6458\u8981\u3001\u547d\u4e2d\u5173\u952e\u8bcd\u3001\u8bc4\u5206\u4f9d\u636e\u548c\u5916\u90e8\u94fe\u63a5\u4f1a\u5728\u8fd9\u91cc\u96c6\u4e2d\u5448\u73b0\u3002")
        if prefix == "daily":
            self.daily_detail_title_var = title_var
            self.daily_detail_meta_var = meta_var
        else:
            self.survey_detail_title_var = title_var
            self.survey_detail_meta_var = meta_var
        ttk.Label(detail_card, textvariable=title_var, style="DetailTitle.TLabel", wraplength=1120, justify="left").pack(anchor="w")
        ttk.Label(detail_card, textvariable=meta_var, style="Muted.TLabel", wraplength=1120, justify="left").pack(anchor="w", pady=(6, 10))
        text = tk.Text(detail_card, height=7, wrap="word", bg=self.colors["surface"], fg=self.colors["text"], insertbackground=self.colors["text"])
        text.insert("1.0", "\u672a\u9009\u62e9\u8bba\u6587\u3002\u8bf7\u5728\u4e0a\u65b9\u5217\u8868\u4e2d\u9009\u62e9\u4e00\u7bc7\u8bba\u6587\uff0cPaperRadar \u4f1a\u663e\u793a\u6458\u8981\u3001\u5173\u952e\u8bcd\u547d\u4e2d\u548c\u8bc4\u5206\u62c6\u89e3\u3002")
        text.configure(state="disabled")
        self._style_text_widget(text)
        text.pack(fill="both", expand=True)
        actions = ttk.Frame(detail_card, style="Card.TFrame")
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="\u6253\u5f00\u94fe\u63a5", style="Secondary.TButton", command=self.open_selected_link).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="\u590d\u5236\u5f15\u7528\uff08\u5373\u5c06\u652f\u6301\uff09", style="Secondary.TButton", state="disabled").pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="\u52a0\u5165\u5173\u6ce8\uff08\u5373\u5c06\u652f\u6301\uff09", style="Secondary.TButton", state="disabled").pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="\u52a0\u5165\u62a5\u544a\uff08\u5373\u5c06\u652f\u6301\uff09", style="Secondary.TButton", state="disabled").pack(side="left")
        return tree, text

    def _emit(self, *message: Any) -> None:
        self.ui_queue.put(message)

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                message = self.ui_queue.get_nowait()
                self._handle_ui_message(message)
        except queue.Empty:
            pass
        self.after(120, self._drain_ui_queue)

    def _handle_ui_message(self, message: tuple[Any, ...]) -> None:
        kind = message[0]
        if kind == "daily_batch":
            self.all_daily_papers = message[1]
            self.refresh_daily_display()
        elif kind == "daily_progress":
            self.on_daily_progress(message[1])
        elif kind == "daily_finished":
            self.on_daily_finished(message[1], message[2])
        elif kind == "daily_failed":
            self.on_daily_failed(message[1])
        elif kind == "survey_batch":
            self.all_survey_papers = message[1]
            self.refresh_survey_display()
        elif kind == "survey_progress":
            self.on_survey_progress(message[1])
        elif kind == "survey_finished":
            self.on_survey_finished(message[1])
        elif kind == "survey_failed":
            self.on_survey_failed(message[1])

    def run_daily(self) -> None:
        if self.daily_thread and self.daily_thread.is_alive():
            return
        if not self._require_active_profile():
            return
        sources = {
            "arxiv": self.daily_arxiv_var.get(),
            "rss": self.daily_top_journals_var.get(),
            "crossref": self.daily_top_journals_var.get(),
        }
        if not any(sources.values()):
            messagebox.showinfo("未选择数据源", "请至少选择一个检索数据源。", parent=self)
            return
        self.stop_daily_event.clear()
        self.all_daily_papers = []
        self.daily_papers = []
        self.populate_table(self.daily_tree, [])
        self.daily_progress.configure(maximum=1, value=0)
        self.daily_progress_var.set("正在准备检索")
        self.daily_status_var.set("正在检索")
        self.daily_run_btn.configure(state="disabled")
        self.daily_stop_btn.configure(state="normal")
        runner = DailyRadarRunner(int(self.daily_days_var.get()), sources, self.settings, self._emit, self.stop_daily_event.is_set)
        self.daily_thread = threading.Thread(target=runner.run, daemon=True)
        self.daily_thread.start()

    def stop_daily(self) -> None:
        self.stop_daily_event.set()
        self.daily_status_var.set("正在停止")

    def on_daily_progress(self, progress: dict[str, Any]) -> None:
        total = int(progress.get("total", 1))
        completed = int(progress.get("completed", 0))
        self.daily_progress.configure(maximum=max(total, 1), value=completed)
        self.daily_progress_var.set(
            f"{progress.get('source', '正在检索')}：{completed} / {max(total, 1)}；已发现：{progress.get('found', 0)}；"
            f"去重后：{progress.get('deduped', 0)}；命中：{progress.get('matched', 0)}；"
            f"已显示：{len(self.daily_papers)}；成功：{progress.get('success', 0)}；失败：{progress.get('failed', 0)}"
        )
        self.daily_status_var.set("正在检索")

    def on_daily_finished(self, papers: list[Paper], stats: dict[str, Any]) -> None:
        self.all_daily_papers = papers
        self.refresh_daily_display()
        self.daily_last_var.set(f"上次检查：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.daily_found_var.set(f"本次发现：{len(self.daily_papers)} / 入库候选：{len(self.all_daily_papers)}")
        self.daily_high_var.set(f"高相关：{sum(1 for paper in self.daily_papers if paper.relevance_score >= 60)}")
        self.daily_skim_var.set(f"值得扫读：{sum(1 for paper in self.daily_papers if 40 <= paper.relevance_score < 60)}")
        self.daily_status_var.set("已完成")
        self.daily_progress.configure(maximum=1, value=1)
        self.daily_progress_var.set(
            f"完成；已发现：{sum(int(stats.get(key, 0)) for key in ['arxiv', 'rss', 'crossref'])}；"
            f"入库候选：{len(self.all_daily_papers)}；当前显示：{len(self.daily_papers)}；失败：{stats.get('failed', 0)}"
        )
        self.daily_run_btn.configure(state="normal")
        self.daily_stop_btn.configure(state="disabled")

    def on_daily_failed(self, message: str) -> None:
        self.daily_status_var.set("失败")
        self.daily_progress_var.set(f"失败：{message}")
        self.daily_run_btn.configure(state="normal")
        self.daily_stop_btn.configure(state="disabled")
        messagebox.showwarning("每日雷达失败", message, parent=self)

    def run_survey(self) -> None:
        if self.survey_thread and self.survey_thread.is_alive():
            return
        if not self._require_active_profile():
            return
        sources = {"crossref": self.survey_top_journals_var.get(), "arxiv": self.survey_arxiv_var.get(), "rss": self.survey_top_journals_var.get()}
        if not any(sources.values()):
            messagebox.showinfo("未选择数据源", "请至少选择一个检索数据源。", parent=self)
            return
        self.stop_survey_event.clear()
        self.survey_progress.configure(maximum=1, value=0)
        self.survey_status_var.set("正在启动")
        self.survey_run_btn.configure(state="disabled")
        self.survey_stop_btn.configure(state="normal")
        from_date, until_date = self._survey_dates()
        runner = HistoricalSurveyRunner(
            self.survey_name_var.get() or "当前方向历史调研",
            from_date,
            until_date,
            sources,
            self.settings,
            self._emit,
            self.stop_survey_event.is_set,
        )
        self.survey_thread = threading.Thread(target=runner.run, daemon=True)
        self.survey_thread.start()

    def stop_survey(self) -> None:
        self.stop_survey_event.set()
        self.survey_status_var.set("正在停止，已保存的结果会保留")

    def on_survey_progress(self, progress: dict[str, Any]) -> None:
        total = int(progress.get("total", 1))
        completed = int(progress.get("completed", 0))
        self.survey_progress.configure(maximum=max(total, 1), value=completed)
        self.survey_status_var.set(f"正在检索：{progress.get('journal')} × {progress.get('query')}；进度：{completed} / {total}")
        self.survey_counts_var.set(
            f"进度：{completed} / {total}；已发现：{progress.get('found', 0)}；去重后：{progress.get('deduped', 0)}；"
            f"命中：{progress.get('matched', 0)}；已显示：{len(self.survey_papers)}；"
            f"成功：{progress.get('success', 0)}；失败：{progress.get('failed', 0)}；缓存：{progress.get('cache_hit', progress.get('cached', 0))}；"
            f"超时：{progress.get('timeouts', 0)}"
        )

    def on_survey_finished(self, stats: dict[str, Any]) -> None:
        if stats.get("status") == "stopped":
            self.survey_status_var.set("已停止，本次已保存部分结果。")
        elif stats.get("status") == "partial_completed":
            self.survey_status_var.set("部分完成，有失败；已保存成功获取的结果。")
        else:
            self.survey_status_var.set("已完成")
        self.survey_run_btn.configure(state="normal")
        self.survey_stop_btn.configure(state="disabled")

    def on_survey_failed(self, message: str) -> None:
        self.survey_status_var.set("失败")
        self.survey_run_btn.configure(state="normal")
        self.survey_stop_btn.configure(state="disabled")
        messagebox.showwarning("历史调研失败", message, parent=self)

    def refresh_daily_display(self) -> None:
        min_score = self._safe_int(self.daily_min_score_var.get(), 20)
        base = [paper for paper in self.all_daily_papers if paper.matched_keywords and paper.relevance_score >= min_score]
        self.daily_papers = [paper for paper in base if self._paper_matches_filters(paper, self.daily_filter_var.get(), self.daily_source_filter_var.get())]
        self.populate_table(self.daily_tree, self.daily_papers)
        self._update_result_summary("daily", len(self.daily_papers), len(base), len(self.all_daily_papers))
        self._update_signal_panel("daily", self.daily_papers)
        if self.all_daily_papers:
            self.daily_found_var.set(f"本次发现：{len(self.daily_papers)} / 入库候选：{len(self.all_daily_papers)}")
            self.daily_high_var.set(f"高相关：{sum(1 for paper in self.daily_papers if paper.relevance_score >= 60)}")
            self.daily_skim_var.set(f"值得扫读：{sum(1 for paper in self.daily_papers if 40 <= paper.relevance_score < 60)}")

    def refresh_survey_display(self) -> None:
        min_score = self._safe_int(self.survey_min_score_var.get(), 20)
        matched = [paper for paper in self.all_survey_papers if paper.matched_keywords]
        base = [paper for paper in matched if paper.relevance_score >= min_score]
        self.survey_papers = [paper for paper in base if self._paper_matches_filters(paper, self.survey_filter_var.get(), self.survey_source_filter_var.get())]
        self.populate_table(self.survey_tree, self.survey_papers)
        self._update_result_summary("survey", len(self.survey_papers), len(base), len(self.all_survey_papers))
        self._update_signal_panel("survey", self.survey_papers)

    def _paper_matches_filters(self, paper: Paper, query: str, source_label: str) -> bool:
        if not self._source_filter_matches(paper, source_label):
            return False
        q = query.strip().lower()
        if not q:
            return True
        haystack = "\n".join(
            [
                paper.title,
                paper.authors,
                paper.abstract,
                paper.journal_or_source,
                paper.primary_category_text,
                paper.matched_keywords_text,
                self._source_type_label(paper.source_type),
                paper.doi,
            ]
        ).lower()
        return q in haystack

    def _source_filter_matches(self, paper: Paper, label: str) -> bool:
        if label == "全部来源":
            return True
        if label == "预印本（arXiv）":
            return paper.source_type == "arxiv"
        if label == "顶级期刊":
            return paper.source_type in {"crossref", "journal_rss"}
        return True

    def _update_result_summary(self, prefix: str, visible: int, filtered_base: int, total: int) -> None:
        target = self.daily_summary_var if prefix == "daily" else self.survey_summary_var
        high_count = sum(1 for paper in (self.daily_papers if prefix == "daily" else self.survey_papers) if paper.relevance_score > 80)
        hidden = max(filtered_base - visible, 0)
        target.set(f"当前显示 {visible} 篇；高相关 {high_count} 篇；筛选隐藏 {hidden} 篇；候选库 {total} 篇")

    def _update_signal_panel(self, prefix: str, papers: list[Paper]) -> None:
        target = self.daily_summary_var if prefix == "daily" else self.survey_summary_var
        high_count = sum(1 for paper in papers if paper.relevance_score > 80)
        target.set(f"当前显示 {len(papers)} 篇；高相关 {high_count} 篇")
        (self.daily_signal_var if prefix == "daily" else self.survey_signal_var).set("")

    def populate_table(self, tree: ttk.Treeview, papers: list[Paper]) -> None:
        for item in tree.get_children():
            tree.delete(item)
        if not papers:
            tree.insert(
                "",
                "end",
                iid="empty",
                values=("", "", "", "\u8fd8\u6ca1\u6709\u7b26\u5408\u6761\u4ef6\u7684\u8bba\u6587", "\u8fd0\u884c\u68c0\u7d22\u6216\u653e\u5bbd\u7b5b\u9009\u6761\u4ef6\u540e\u518d\u67e5\u770b", "", "", ""),
                tags=("empty",),
            )
            return
        for index, paper in enumerate(papers):
            values = (
                f"{int(paper.relevance_score)}",
                paper.journal_or_source or "\u672a\u77e5",
                self._source_type_label(paper.source_type),
                paper.title,
                paper.authors,
                format_date_only(paper.published_date),
                paper.matched_keywords_text,
                "\u6253\u5f00" if paper.url else "\u65e0\u94fe\u63a5",
            )
            if paper.relevance_score >= 60:
                tags = ("high",)
            elif paper.relevance_score >= 40:
                tags = ("skim",)
            else:
                tags = ("odd",) if index % 2 else ()
            tree.insert("", "end", iid=str(index), values=values, tags=tags)

    def _select_result(self, tree: ttk.Treeview, prefix: str) -> None:
        selection = tree.selection()
        if not selection:
            return
        if selection[0] == "empty":
            return
        index = int(selection[0])
        papers = self.daily_papers if prefix == "daily" else self.survey_papers
        if index >= len(papers):
            return
        self.selected_paper = papers[index]
        self._show_detail(self.selected_paper, prefix)

    def _show_detail(self, paper: Paper, prefix: str) -> None:
        title_var = self.daily_detail_title_var if prefix == "daily" else self.survey_detail_title_var
        meta_var = self.daily_detail_meta_var if prefix == "daily" else self.survey_detail_meta_var
        text = self.daily_detail_text if prefix == "daily" else self.survey_detail_text
        doi_state = "\u5df2\u6536\u5f55 DOI" if paper.doi else "\u6682\u65e0 DOI"
        title_var.set(paper.title or "\u672a\u547d\u540d\u8bba\u6587")
        meta_var.set(
            f"\u5206\u6570 {int(paper.relevance_score)} \u00b7 {paper.journal_or_source or '\u672a\u77e5\u6765\u6e90'} \u00b7 {self._source_type_label(paper.source_type)} \u00b7 "
            f"\u53d1\u5e03\u65e5\u671f {format_date_only(paper.published_date)} \u00b7 {doi_state}\n"
            f"\u4f5c\u8005\uff1a{paper.authors or '\u672a\u77e5'}\n"
            f"\u547d\u4e2d\u5173\u952e\u8bcd\uff1a{paper.matched_keywords_text or '\u65e0'}"
        )
        body = (
            f"\u6458\u8981\n{paper.abstract or '\u8be5\u6570\u636e\u6e90\u672a\u63d0\u4f9b\u5b8c\u6574\u6458\u8981\u3002'}\n\n"
            f"\u4e3a\u4ec0\u4e48\u503c\u5f97\u5173\u6ce8\n{paper.reason_zh or '\u6682\u65e0\u76f8\u5173\u6027\u8bf4\u660e\u3002'}\n\n"
            f"\u8bc4\u5206\u4f9d\u636e\n{self._score_breakdown_text(paper)}\n\n"
            f"\u5916\u90e8\u94fe\u63a5\u72b6\u6001\n{'\u53ef\u6253\u5f00' if paper.url else '\u8be5\u6761\u76ee\u6682\u7f3a\u5916\u90e8\u94fe\u63a5'}"
        )
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", body)
        text.configure(state="disabled")

    def _score_breakdown_text(self, paper: Paper) -> str:
        data = paper.score_breakdown or {}
        if not data:
            return "暂无评分拆解"
        yes_no = lambda value: "是" if bool(value) else "否"
        return (
            f"关键词分：{data.get('keyword_score', 0)}\n"
            f"组合加分：{data.get('combo_bonus', 0)}\n"
            f"来源加分：{data.get('source_quality_score', 0)}\n"
            f"排除词扣分：{data.get('penalty_score', 0)}\n"
            f"标题强相关保护：{yes_no(data.get('strong_title_hit'))}"
            f"{'，保底到 ' + str(data.get('title_floor_applied')) + ' 分' if data.get('title_floor_applied') else ''}\n"
            f"宽泛单关键词封顶：{yes_no(data.get('broad_single_term_cap'))}\n"
            f"仅平台/器件词封顶：{yes_no(data.get('supporting_only_cap'))}\n"
            f"无研究关键词封顶：{yes_no(data.get('no_positive_keyword_cap'))}\n"
            f"最终分数：{data.get('final_score', paper.relevance_score)}"
        )

    def _sort_tree(self, tree: ttk.Treeview, col: str, reverse: bool) -> None:
        def sort_value(item: str) -> Any:
            value = tree.set(item, col)
            if col == "score":
                return self._safe_int(value, 0)
            return value.lower()

        items = sorted(tree.get_children(""), key=sort_value, reverse=reverse)
        for index, item in enumerate(items):
            tree.move(item, "", index)
        tree.heading(col, command=lambda: self._sort_tree(tree, col, not reverse))

    def _show_tree_cell_popup(self, tree: ttk.Treeview) -> None:
        selection = tree.selection()
        if not selection:
            return
        values = tree.item(selection[0], "values")
        text = "\n\n".join(str(value) for value in values if value)
        popup = tk.Toplevel(self)
        popup.title("单元格内容")
        popup.geometry("640x300")
        popup.configure(bg=self.colors["bg"])
        box = scrolledtext.ScrolledText(popup, wrap="word", bg=self.colors["surface"], fg=self.colors["text"], insertbackground=self.colors["text"])
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.insert("1.0", text)
        box.configure(state="disabled")

    def _paper_for_tree_row(self, tree: ttk.Treeview, row_id: str) -> Paper | None:
        if not row_id or row_id == "empty":
            return None
        try:
            index = int(row_id)
        except ValueError:
            return None
        if tree is getattr(self, "daily_tree", None):
            papers = self.daily_papers
        elif tree is getattr(self, "survey_tree", None):
            papers = self.survey_papers
        else:
            papers = []
        return papers[index] if 0 <= index < len(papers) else None

    def _open_selected_tree_link(self, tree: ttk.Treeview) -> None:
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("\u672a\u9009\u62e9\u8bba\u6587", "\u8bf7\u5148\u5728\u5217\u8868\u4e2d\u9009\u62e9\u4e00\u7bc7\u8bba\u6587\u3002", parent=self)
            return
        paper = self._paper_for_tree_row(tree, selection[0])
        if paper:
            self._open_url_safely(paper.url)

    def _open_tree_link_on_click(self, event: tk.Event, tree: ttk.Treeview) -> None:
        region = tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        row_id = tree.identify_row(event.y)
        column_id = tree.identify_column(event.x)
        if not row_id or column_id != f"#{RESULT_COLUMNS.index('action') + 1}":
            return
        tree.selection_set(row_id)
        paper = self._paper_for_tree_row(tree, row_id)
        if paper:
            self.selected_paper = paper
            self._open_url_safely(paper.url)

    def open_selected_link(self) -> None:
        if not self.selected_paper:
            messagebox.showinfo("\u672a\u9009\u62e9\u8bba\u6587", "\u8bf7\u5148\u5728\u5217\u8868\u4e2d\u9009\u62e9\u4e00\u7bc7\u8bba\u6587\u3002", parent=self)
            return
        self._open_url_safely(self.selected_paper.url)

    def _open_url_safely(self, url: str) -> None:
        parsed = urlparse(str(url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            messagebox.showinfo("链接不可用", "该论文没有可用链接。", parent=self)
            return
        open_url(str(url))

    def _survey_dates(self) -> tuple[date, date]:
        today = date.today()
        text = self.survey_range_var.get()
        if "90" in text:
            return today - timedelta(days=90), today
        if "365" in text:
            return today - timedelta(days=365), today
        if "3 年" in text:
            return today - timedelta(days=365 * 3), today
        return today - timedelta(days=365), today

    def show_search_scope(self, mode: str) -> None:
        profile = load_active_profile()
        sources = load_sources()
        selected_sources: list[str] = []
        journals: list[str] = []
        if mode == "daily":
            if self.daily_arxiv_var.get():
                selected_sources.append("预印本（arXiv）")
            top_enabled = self.daily_top_journals_var.get()
        else:
            if self.survey_arxiv_var.get():
                selected_sources.append("预印本（arXiv）")
            top_enabled = self.survey_top_journals_var.get()
        if top_enabled:
            selected_sources.append("顶级期刊")
            journals.extend(str(source.get("name")) for source in sources.get("journal_sources", []) if source.get("enabled") and source.get("name"))
            journals.extend(str(source.get("name")) for source in sources.get("top_journals", []) if source.get("crossref_enabled") and source.get("name"))

        keywords = profile_to_keywords(profile)
        match_terms: list[str] = []
        for group, terms in keywords.items():
            if group != "exclude":
                match_terms.extend(terms)
        queries = [str(query) for query in profile.get("search_queries") or [] if str(query).strip()]
        content = (
            f"当前研究方向：{profile.get('display_name') or profile.get('profile_id') or '未命名'}\n\n"
            f"数据来源\n{self._block(selected_sources, '暂未选择数据来源', 20)}\n\n"
            f"会检索的期刊\n{self._block(list(dict.fromkeys(journals)), '预印本不按期刊筛选；若未选择顶级期刊，则不会显示期刊列表。', 80)}\n\n"
            f"远程检索关键词\n{self._block(queries, '当前 Profile 没有配置 search_queries', 80)}\n\n"
            f"本地相关性关键词\n{self._block(list(dict.fromkeys(match_terms)), '当前 Profile 没有配置 keyword_groups', 120)}"
        )
        self._text_dialog("当前检索范围", content)

    def _block(self, values: list[str], empty: str, limit: int) -> str:
        if not values:
            return empty
        shown = values[:limit]
        suffix = f"\n... 另有 {len(values) - limit} 项" if len(values) > limit else ""
        return "\n".join(str(value) for value in shown) + suffix

    def _text_dialog(self, title: str, content: str) -> None:
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("880x560")
        dialog.configure(bg=self.colors["bg"])
        text = scrolledtext.ScrolledText(dialog, wrap="word", bg=self.colors["surface"], fg=self.colors["text"], insertbackground=self.colors["text"])
        text.pack(fill="both", expand=True, padx=14, pady=14)
        text.insert("1.0", content)
        text.configure(state="disabled")
        ttk.Button(dialog, text="关闭", style="Secondary.TButton", command=dialog.destroy).pack(anchor="e", padx=14, pady=(0, 14))

    def refresh_profile_page(self) -> None:
        active = load_active_profile()
        active_id = active.get("profile_id") if active else ""
        if active:
            groups = active.get("keyword_groups") or {}
            queries = active.get("search_queries") or []
            self.profile_status_var.set(
                f"当前方向：{active.get('display_name') or active.get('profile_id')}；Profile ID：{active.get('profile_id')}；"
                f"检索式：{len(queries) if isinstance(queries, list) else 0}；关键词组：{len(groups) if isinstance(groups, dict) else 0}\n"
                f"{active.get('description') or ''}"
            )
        else:
            self.profile_status_var.set("当前没有激活的研究方向。请导入或创建一个 Profile 后设为当前方向。")
        for item in self.profile_tree.get_children():
            self.profile_tree.delete(item)
        self.profile_tree.tag_configure("active", background="#2f6fd6", foreground="#ffffff")
        active_iid = ""
        for row, profile in enumerate(load_all_profiles()):
            groups = profile.get("keyword_groups") or {}
            queries = profile.get("search_queries") or []
            is_active = profile.get("profile_id") == active_id
            values = (
                profile.get("display_name", ""),
                profile.get("profile_id", ""),
                profile.get("description", ""),
                str(len(queries) if isinstance(queries, list) else 0),
                self._profile_keyword_terms_text(groups),
                "是" if is_active else "",
            )
            iid = str(row)
            self.profile_tree.insert("", "end", iid=iid, values=values, tags=("active",) if is_active else ())
            if is_active:
                active_iid = iid
        if active_iid and not self.profile_tree.selection():
            self.profile_tree.selection_set(active_iid)
            self.profile_tree.focus(active_iid)
        self.keyword_filter = KeywordFilter(load_keywords())
        self._on_profile_selected()

    def _profile_keyword_terms_text(self, groups: Any) -> str:
        terms: list[str] = []
        if isinstance(groups, dict):
            for group in groups.values():
                if isinstance(group, dict):
                    for term in group.get("terms") or []:
                        text = str(term).strip()
                        if text and any(ch.isascii() and ch.isalpha() for ch in text):
                            terms.append(text)
        return ", ".join(terms)

    def _on_profile_selected(self) -> None:
        if not hasattr(self, "keyword_tree"):
            return
        profile = self.selected_profile()
        self.keyword_editor_profile = copy.deepcopy(profile) if profile else None
        self._reload_keyword_editor()

    def _reload_keyword_editor(self) -> None:
        if not hasattr(self, "keyword_tree"):
            return
        for item in self.keyword_tree.get_children():
            self.keyword_tree.delete(item)
        self.keyword_rows: list[tuple[str, str, int]] = []
        profile = getattr(self, "keyword_editor_profile", None)
        if not profile:
            self.keyword_editor_status_var.set("选择一个研究方向后，可在这里修改关键词。")
            return
        groups = profile.get("keyword_groups") or {}
        if isinstance(groups, dict):
            for group_name, group in groups.items():
                if not isinstance(group, dict):
                    continue
                priority = str(group.get("priority") or "medium")
                for index, term in enumerate(group.get("terms") or []):
                    iid = str(len(self.keyword_rows))
                    self.keyword_rows.append(("keyword", str(group_name), index))
                    self.keyword_tree.insert("", "end", iid=iid, values=(group_name, priority, str(term)))
        excludes = profile.get("exclude_terms") or []
        if isinstance(excludes, list):
            for index, term in enumerate(excludes):
                iid = str(len(self.keyword_rows))
                self.keyword_rows.append(("exclude", "exclude", index))
                self.keyword_tree.insert("", "end", iid=iid, values=("exclude", "exclude", str(term)))
        total = len(self.keyword_rows)
        self.keyword_editor_status_var.set(f"正在编辑：{profile.get('display_name') or profile.get('profile_id')}；关键词：{total}")

    def _on_keyword_selected(self) -> None:
        if not hasattr(self, "keyword_tree"):
            return
        selection = self.keyword_tree.selection()
        if not selection:
            return
        values = self.keyword_tree.item(selection[0], "values")
        if len(values) >= 3:
            self.keyword_group_var.set(str(values[0]))
            self.keyword_priority_var.set(str(values[1]))
            self.keyword_term_var.set(str(values[2]))

    def _editor_profile(self) -> dict[str, Any] | None:
        profile = getattr(self, "keyword_editor_profile", None)
        if profile:
            return profile
        self._on_profile_selected()
        return getattr(self, "keyword_editor_profile", None)

    def _ensure_keyword_group(self, profile: dict[str, Any], group_name: str, priority: str) -> dict[str, Any]:
        groups = profile.setdefault("keyword_groups", {})
        if not isinstance(groups, dict):
            groups = {}
            profile["keyword_groups"] = groups
        group = groups.setdefault(group_name, {"priority": priority if priority in {"high", "medium", "low"} else "medium", "terms": []})
        if not isinstance(group, dict):
            group = {"priority": priority if priority in {"high", "medium", "low"} else "medium", "terms": []}
            groups[group_name] = group
        group["priority"] = priority if priority in {"high", "medium", "low"} else str(group.get("priority") or "medium")
        if not isinstance(group.get("terms"), list):
            group["terms"] = []
        return group

    def add_profile_keyword(self) -> None:
        profile = self._editor_profile()
        term = self.new_keyword_term_var.get().strip()
        if not profile or not term:
            self.keyword_editor_status_var.set("请输入要新增的关键词。")
            return
        group_name = self.new_keyword_group_var.get().strip() or "core"
        priority = self.new_keyword_priority_var.get().strip() or "medium"
        added = False
        if priority == "exclude" or group_name == "exclude":
            excludes = profile.setdefault("exclude_terms", [])
            if not isinstance(excludes, list):
                excludes = []
                profile["exclude_terms"] = excludes
            if term.lower() not in {str(item).lower() for item in excludes}:
                excludes.append(term)
                added = True
        else:
            group = self._ensure_keyword_group(profile, group_name, priority)
            terms = group["terms"]
            if term.lower() not in {str(item).lower() for item in terms}:
                terms.append(term)
                added = True
        self.new_keyword_term_var.set("")
        self._reload_keyword_editor()
        self.keyword_editor_status_var.set(f"已新增关键词：{term}" if added else f"关键词已存在：{term}")

    def update_profile_keyword(self) -> None:
        profile = self._editor_profile()
        selection = self.keyword_tree.selection() if hasattr(self, "keyword_tree") else ()
        term = self.keyword_term_var.get().strip()
        if not profile or not selection:
            self.keyword_editor_status_var.set("请先在表格中选择一个已有关键词。")
            return
        if not term:
            self.keyword_editor_status_var.set("关键词不能为空。")
            return
        row = self.keyword_rows[int(selection[0])]
        kind, old_group, index = row
        priority = self.keyword_priority_var.get().strip() or "medium"
        new_group = self.keyword_group_var.get().strip() or old_group
        if kind == "exclude":
            excludes = profile.get("exclude_terms") or []
            if 0 <= index < len(excludes):
                excludes.pop(index)
        else:
            groups = profile.get("keyword_groups") or {}
            old_terms = groups.get(old_group, {}).get("terms", []) if isinstance(groups.get(old_group), dict) else []
            if 0 <= index < len(old_terms):
                old_terms.pop(index)
        if priority == "exclude" or new_group == "exclude":
            excludes = profile.setdefault("exclude_terms", [])
            if isinstance(excludes, list) and term.lower() not in {str(item).lower() for item in excludes}:
                excludes.append(term)
        else:
            group = self._ensure_keyword_group(profile, new_group, priority)
            if term.lower() not in {str(item).lower() for item in group["terms"]}:
                group["terms"].append(term)
        self._cleanup_empty_keyword_groups(profile)
        self._reload_keyword_editor()
        self.keyword_editor_status_var.set(f"已更新选中关键词：{term}")

    def delete_profile_keyword(self) -> None:
        profile = self._editor_profile()
        selection = self.keyword_tree.selection() if hasattr(self, "keyword_tree") else ()
        if not profile or not selection:
            self.keyword_editor_status_var.set("\u8bf7\u5148\u5728\u8868\u683c\u4e2d\u9009\u62e9\u8981\u5220\u9664\u7684\u5df2\u6709\u5173\u952e\u8bcd\u3002")
            return
        kind, group_name, index = self.keyword_rows[int(selection[0])]
        preview = ""
        if kind == "exclude":
            excludes = profile.get("exclude_terms") or []
            if 0 <= index < len(excludes):
                preview = str(excludes[index])
        else:
            groups = profile.get("keyword_groups") or {}
            group = groups.get(group_name)
            terms = group.get("terms", []) if isinstance(group, dict) else []
            if 0 <= index < len(terms):
                preview = str(terms[index])
        if not messagebox.askyesno(
            "\u786e\u8ba4\u5220\u9664\u5173\u952e\u8bcd",
            f"\u786e\u5b9a\u5220\u9664\u5173\u952e\u8bcd\uff1a{preview or '\u672a\u77e5'}\uff1f\n\n\u5220\u9664\u540e\u9700\u70b9\u51fb\u201c\u4fdd\u5b58\u5168\u90e8\u5173\u952e\u8bcd\u201d\u624d\u4f1a\u5199\u5165 Profile\u3002",
            parent=self,
        ):
            return
        deleted = ""
        if kind == "exclude":
            excludes = profile.get("exclude_terms") or []
            if 0 <= index < len(excludes):
                deleted = str(excludes.pop(index))
        else:
            groups = profile.get("keyword_groups") or {}
            group = groups.get(group_name)
            terms = group.get("terms", []) if isinstance(group, dict) else []
            if 0 <= index < len(terms):
                deleted = str(terms.pop(index))
        self._cleanup_empty_keyword_groups(profile)
        self.keyword_term_var.set("")
        self._reload_keyword_editor()
        self.keyword_editor_status_var.set(f"\u5df2\u5220\u9664\u5173\u952e\u8bcd\uff1a{deleted}\uff1b\u8bf7\u4fdd\u5b58\u5168\u90e8\u5173\u952e\u8bcd\u4ee5\u751f\u6548\u3002" if deleted else "\u672a\u5220\u9664\u4efb\u4f55\u5173\u952e\u8bcd\u3002")

    def _cleanup_empty_keyword_groups(self, profile: dict[str, Any]) -> None:
        groups = profile.get("keyword_groups") or {}
        if not isinstance(groups, dict):
            return
        for group_name in list(groups.keys()):
            group = groups.get(group_name)
            if isinstance(group, dict) and not group.get("terms"):
                groups.pop(group_name, None)

    def save_keyword_editor_profile(self) -> None:
        profile = self._editor_profile()
        if not profile:
            return
        path = save_profile(profile)
        active = load_active_profile()
        if active.get("profile_id") == profile.get("profile_id"):
            self.keyword_filter = KeywordFilter(load_keywords())
        self.refresh_profile_page()
        messagebox.showinfo("关键词已保存", f"关键词已写入 Profile：\n{path}", parent=self)

    def selected_profile(self) -> dict[str, Any] | None:
        selection = self.profile_tree.selection()
        profiles = load_all_profiles()
        if not selection:
            return load_active_profile()
        index = int(selection[0])
        return profiles[index] if 0 <= index < len(profiles) else None

    def set_selected_profile_active(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        set_active_profile(str(profile.get("profile_id")))
        self.settings = load_settings()
        self.keyword_filter = KeywordFilter(load_keywords())
        self.refresh_profile_page()
        messagebox.showinfo("已切换", "当前研究方向已更新。每日雷达和历史调研将使用新的 Profile。", parent=self)

    def copy_current_profile(self) -> None:
        profile = load_active_profile()
        if not profile:
            messagebox.showinfo("没有当前方向", "当前没有可复制的研究方向 Profile。", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False))
        messagebox.showinfo("已复制", "当前 Profile YAML 已复制到剪贴板。", parent=self)

    def export_selected_profile(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="导出 Profile",
            initialfile=f"{profile.get('profile_id', 'profile')}.yaml",
            filetypes=[("YAML", "*.yaml *.yml")],
        )
        if not filename:
            return
        Path(filename).write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
        messagebox.showinfo("已导出", f"Profile 已导出到：\n{filename}", parent=self)

    def delete_selected_profile(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        profile_id = str(profile.get("profile_id", ""))
        message = f"确定删除 Profile：{profile_id}？"
        if profile_id == DEFAULT_PROFILE_ID:
            message += "\n\n这是内置默认光计算 Profile。删除后软件不会自动重新创建。"
        if not messagebox.askyesno("确认删除", message, parent=self):
            return
        delete_profile(profile_id)
        self.settings = load_settings()
        self.refresh_profile_page()

    def generate_and_copy_profile_prompt(self) -> None:
        prompt = generate_profile_prompt(self.profile_direction_var.get())
        self.clipboard_clear()
        self.clipboard_append(prompt)
        messagebox.showinfo("提示词已复制", "提示词已复制。请粘贴到任意大语言模型中生成 PaperRadar Profile YAML。", parent=self)

    def paste_profile_yaml(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        self.profile_yaml_text.delete("1.0", "end")
        self.profile_yaml_text.insert("1.0", text)

    def validate_profile_input(self) -> None:
        source_text = self.profile_yaml_text.get("1.0", "end").strip()
        if not source_text:
            self.profile_validation_var.set("\u8bf7\u5148\u7c98\u8d34 AI \u751f\u6210\u6216\u624b\u52a8\u7f16\u5199\u7684 Profile \u914d\u7f6e\u3002")
            return
        result = validate_profile_yaml(source_text, self.profile_direction_var.get())
        self.validated_profile = result.profile if result.ok else None
        self.normalized_profile_yaml = result.normalized_yaml if result.ok else ""
        if result.ok and result.profile:
            groups = result.profile.get("keyword_groups") or {}
            queries = result.profile.get("search_queries") or []
            excludes = result.profile.get("exclude_terms") or []
            journals = result.profile.get("recommended_journals") or []
            existing_ids = {str(profile.get("profile_id")) for profile in load_all_profiles()}
            will_cover = str(result.profile.get("profile_id")) in existing_ids
            warning_text = "\n".join(result.warnings) if result.warnings else "\u65e0"
            self.profile_validation_var.set(
                f"\u89e3\u6790\u6210\u529f\uff0c\u5df2\u751f\u6210\u53ef\u9884\u89c8\u7684 Profile\u3002\n"
                f"Profile ID\uff1a{result.profile.get('profile_id')}\uff1b\u663e\u793a\u540d\u79f0\uff1a{result.profile.get('display_name')}\n"
                f"\u68c0\u7d22\u5f0f\uff1a{len(queries)}\uff1b\u5173\u952e\u8bcd\u7ec4\uff1a{len(groups)}\uff1b\u6392\u9664\u8bcd\uff1a{len(excludes)}\uff1b\u671f\u520a\uff1a{len(journals)}\n"
                f"\u662f\u5426\u8986\u76d6\u73b0\u6709 Profile\uff1a{'\u662f' if will_cover else '\u5426'}\n"
                f"\u6f5c\u5728\u95ee\u9898\uff1a{warning_text}"
            )
        else:
            details = "\n".join(result.errors)
            if result.raw_error:
                details += f"\n\n\u539f\u59cb\u89e3\u6790\u9519\u8bef\uff1a{result.raw_error}"
            self.profile_validation_var.set("\u89e3\u6790\u5931\u8d25\uff1a\n" + details)

    def save_validated_profile(self, make_active: bool) -> None:
        if not self.validated_profile:
            self.validate_profile_input()
        if not self.validated_profile:
            return
        profile_id = str(self.validated_profile.get("profile_id", ""))
        existing_ids = {str(profile.get("profile_id")) for profile in load_all_profiles()}
        if profile_id in existing_ids:
            if not messagebox.askyesno(
                "\u786e\u8ba4\u8986\u76d6 Profile",
                f"Profile {profile_id} \u5df2\u5b58\u5728\u3002\n\n\u4fdd\u5b58\u540e\u4f1a\u8986\u76d6\u73b0\u6709\u914d\u7f6e\uff1b\u5982\u8bbe\u4e3a\u5f53\u524d\u65b9\u5411\uff0c\u5c06\u5f71\u54cd\u4eca\u65e5\u53d1\u73b0\u548c\u5386\u53f2\u8c03\u7814\u7684\u7b5b\u9009\u7ed3\u679c\u3002\n\n\u662f\u5426\u7ee7\u7eed\uff1f",
                parent=self,
            ):
                return
        elif make_active:
            if not messagebox.askyesno(
                "\u786e\u8ba4\u8bbe\u4e3a\u5f53\u524d\u65b9\u5411",
                "\u4fdd\u5b58\u5e76\u8bbe\u4e3a\u5f53\u524d\u65b9\u5411\u540e\uff0c\u4eca\u65e5\u53d1\u73b0\u548c\u5386\u53f2\u8c03\u7814\u5c06\u4f7f\u7528\u65b0 Profile \u8fdb\u884c\u7b5b\u9009\u3002\u662f\u5426\u7ee7\u7eed\uff1f",
                parent=self,
            ):
                return
        path = save_profile(self.validated_profile)
        if make_active:
            set_active_profile(profile_id)
            self.settings = load_settings()
            self.keyword_filter = KeywordFilter(load_keywords())
        self.refresh_profile_page()
        messagebox.showinfo("\u5df2\u4fdd\u5b58", f"Profile \u5df2\u4fdd\u5b58\u5230\uff1a\n{path}", parent=self)

    def show_first_run_wizard(self) -> None:
        use_default = messagebox.askyesno(
            "欢迎使用 PaperRadar",
            "使用每日雷达或历史调研前，请先确认研究方向 Profile。\n\n是否先使用内置默认方向：光计算？",
            parent=self,
        )
        if use_default:
            ensure_default_profile_available(force=True)
            set_active_profile(DEFAULT_PROFILE_ID)
            self.refresh_profile_page()
        else:
            self._select_tab("profile")

    def _require_active_profile(self) -> bool:
        profile = load_active_profile()
        profile_id = str(profile.get("profile_id") or "").strip()
        has_keywords = bool(profile_to_keywords(profile))
        has_queries = bool(profile.get("search_queries"))
        if profile_id and (has_keywords or has_queries):
            return True
        messagebox.showinfo("请先配置研究方向", "当前没有可用的研究方向 Profile。请先进入研究方向配置，导入或创建一个研究方向。", parent=self)
        self._select_tab("profile")
        return False

    def generate_daily_report(self) -> None:
        if not self.daily_papers:
            messagebox.showinfo("暂无可生成的报告", "当前没有可导出的每日结果。请先运行检索，或放宽筛选条件后再试。", parent=self)
            return
        path = generate_daily_report(self.daily_papers)
        messagebox.showinfo("报告已生成", f"报告已保存到：\n{path}", parent=self)

    def generate_survey_report(self) -> None:
        if not self.survey_papers:
            messagebox.showinfo("暂无可生成的报告", "当前没有可导出的历史调研结果。请先运行调研，或放宽筛选条件后再试。", parent=self)
            return
        from_date, until_date = self._survey_dates()
        path = generate_survey_report(self.survey_papers, self.survey_name_var.get() or "当前方向历史调研", from_date, until_date)
        messagebox.showinfo("报告已生成", f"报告已保存到：\n{path}", parent=self)

    def open_report_folder(self) -> None:
        open_folder(REPORTS_DIR)

    def _source_type_label(self, source_type: str) -> str:
        return {"arxiv": "预印本（arXiv）", "journal_rss": "顶级期刊", "crossref": "顶级期刊"}.get(source_type, source_type or "未知")

    def _switch_theme(self) -> None:
        self.theme_mode = "dark"
        self.colors = self._palette("dark")
        self._configure_styles()
        self.configure(bg=self.colors["bg"])
        if hasattr(self, "logo_canvas"):
            self.logo_canvas.configure(bg=self.colors["sidebar"])
            self._draw_logo(self.logo_canvas)
        for button in getattr(self, "choice_buttons", []):
            self._style_plain_button(button)
        for button, var, label in getattr(self, "check_buttons", []):
            self._style_check_pill(button, var, label)
        for canvas in getattr(self, "scroll_canvases", []):
            canvas.configure(bg=self.colors["workspace"])
        self._select_tab(getattr(self, "current_tab", "daily"))
        for text_widget in (
            getattr(self, "daily_detail_text", None),
            getattr(self, "survey_detail_text", None),
            getattr(self, "profile_yaml_text", None),
        ):
            self._style_text_widget(text_widget)
        self.populate_table(self.daily_tree, self.daily_papers)
        self.populate_table(self.survey_tree, self.survey_papers)

    def _safe_int(self, value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError, tk.TclError):
            return fallback

    def exit_app(self) -> None:
        self.stop_daily_event.set()
        self.stop_survey_event.set()
        self.destroy()

