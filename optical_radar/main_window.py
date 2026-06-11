from __future__ import annotations

import logging
import time
import traceback
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from PySide6.QtCore import QDate, QEvent, QSettings, QThread, Signal, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .arxiv_client import ArxivClient
from .cache_manager import cache_size_bytes, enforce_cache_limit
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
    get_profile_path,
    load_active_profile,
    load_all_profiles,
    profile_to_keywords,
    save_profile,
    set_active_profile,
    validate_profile_yaml,
)
from .report import generate_daily_report, generate_survey_report
from .scorer import score_paper
from .settings import load_keywords, load_settings, load_sources, save_settings
from .tray import RadarTrayIcon
from .utils import APP_ICON_PATH, REPORTS_DIR, format_date_only, open_folder, open_url, title_hash

logger = logging.getLogger(__name__)
RESULT_LINK_COLUMN = 8
LINK_URL_ROLE = Qt.ItemDataRole.UserRole.value + 1


class SortableTableItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value: Any | None = None) -> None:
        super().__init__(text)
        self.sort_value = sort_value if sort_value is not None else text

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, SortableTableItem):
            try:
                return self.sort_value < other.sort_value
            except TypeError:
                return str(self.sort_value) < str(other.sort_value)
        return super().__lt__(other)


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
        current = out[index]
        merged = _merge_duplicate_papers(current, paper)
        out[index] = merged
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

class DailyRadarWorker(QThread):
    finished_ok = Signal(list, dict)
    failed = Signal(str)

    def __init__(self, days_back: int, sources: dict[str, bool], settings: dict[str, Any]) -> None:
        super().__init__()
        self.days_back = days_back
        self.sources = sources
        self.settings = settings
        self.cancel_requested = False
        self.db = PaperDatabase()
        self.keyword_filter = KeywordFilter(load_keywords())

    def request_cancel(self) -> None:
        self.cancel_requested = True

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
            logger.info("DAILY_START days=%s sources=%s", self.days_back, self.sources)

            if self.sources.get("arxiv") and not self.cancel_requested:
                try:
                    arxiv_papers = ArxivClient(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent(self.days_back, 300)
                    stats["arxiv"] = len(arxiv_papers)
                    stats["success"] += 1
                    papers.extend(arxiv_papers)
                except Exception as exc:
                    stats["failed"] += 1
                    logger.warning("DAILY_SOURCE_FAILED source_type=arxiv error=%s", exc)

            if self.sources.get("rss") and not self.cancel_requested:
                try:
                    rss = JournalRssFetcher(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent(self.days_back)
                    stats["rss"] = len(rss.papers)
                    stats["success"] += 1
                    stats["failed"] += int(rss.stats.failed_sources)
                    papers.extend(rss.papers)
                except Exception as exc:
                    stats["failed"] += 1
                    logger.warning("DAILY_SOURCE_FAILED source_type=journal_rss error=%s", exc)

            if self.sources.get("crossref") and not self.cancel_requested:
                try:
                    crossref = CrossrefClient(timeout=timeout, rows=rows_per_query, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent(self.days_back, max_queries=max_queries)
                    stats["crossref"] = len(crossref.papers)
                    stats["success"] += 1
                    stats["failed"] += len(crossref.failed_requests)
                    papers.extend(crossref.papers)
                except Exception as exc:
                    stats["failed"] += 1
                    logger.warning("DAILY_SOURCE_FAILED source_type=crossref error=%s", exc)

            papers = dedupe_papers(papers)
            scored = score_and_tag(papers, self.keyword_filter, keep_unmatched=True)
            storage = self.db.upsert_papers_with_stats(scored)
            stats["deduped"] = len(scored)
            stats["displayed"] = len(scored)
            stats["inserted"] = storage.inserted_count
            stats["updated"] = storage.updated_count
            stats["high"] = sum(1 for paper in scored if paper.relevance_score >= 60)
            stats["skim"] = sum(1 for paper in scored if 40 <= paper.relevance_score < 60)
            logger.info("DAILY_DONE stats=%s", dict(stats))
            self.finished_ok.emit(scored, dict(stats))
        except Exception as exc:
            logger.error("Daily radar failed: %s\n%s", exc, traceback.format_exc())
            self.failed.emit(str(exc))


class HistoricalSurveyWorker(QThread):
    batch_results_ready = Signal(list, dict)
    progress_updated = Signal(dict)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        task_name: str,
        from_date: date,
        until_date: date,
        sources: dict[str, bool],
        ignore_cache: bool,
        settings: dict[str, Any],
    ) -> None:
        super().__init__()
        self.task_name = task_name
        self.from_date = from_date
        self.until_date = until_date
        self.sources = sources
        self.ignore_cache = ignore_cache
        self.settings = settings
        self.cancel_requested = False
        self.db = PaperDatabase()
        self.keyword_filter = KeywordFilter(load_keywords())

    def request_cancel(self) -> None:
        self.cancel_requested = True

    def run(self) -> None:
        try:
            all_seen: list[Paper] = []
            stats = Counter()
            rows_per_query = int(self.settings.get("crossref", {}).get("rows_per_query", 20))
            max_queries = int(self.settings.get("crossref", {}).get("max_queries_per_run", 200))
            delay = float(self.settings.get("crossref", {}).get("request_delay_seconds", 0.5))
            cache_hours = int(self.settings.get("crossref", {}).get("cache_hours", 24))
            network = self.settings.get("network", {})
            timeout = int(network.get("historical_timeout_seconds", 60))
            max_retries = int(network.get("max_retries", 3))
            retry_delay = int(network.get("retry_delay_seconds", 3))
            performance = self.settings.get("performance", {})
            max_workers = max(1, min(5, int(performance.get("max_workers", 3))))
            batch_update_size = max(1, int(performance.get("batch_update_size", 10)))
            cache_settings = self.settings.get("cache", {})
            cache_enabled = bool(cache_settings.get("enabled", True))
            cache_size = cache_size_bytes()
            queries = build_search_queries_from_keywords(load_keywords(), max_queries=max_queries)
            top_journals = [j for j in load_sources().get("top_journals", []) if j.get("crossref_enabled")]
            total_steps = (len(top_journals) * len(queries) if self.sources.get("crossref") else 0)
            if self.sources.get("arxiv"):
                total_steps += 1
            if self.sources.get("rss"):
                total_steps += 1
            completed = 0
            if total_steps > 200:
                logger.warning("SURVEY_LARGE_TASK total_steps=%s message=%s", total_steps, "当前检索任务较大，可能耗时较长。建议减少 search_queries 或期刊数量。")
            start_time = time.monotonic()
            logger.info(
                "SURVEY_START name=%s from=%s until=%s total_steps=%s sources=%s query_count=%s journal_count=%s max_workers=%s cache_hours=%s cache_dir=%s cache_size=%s cache_max_gb=%s",
                self.task_name,
                self.from_date,
                self.until_date,
                total_steps,
                self.sources,
                len(queries),
                len(top_journals),
                max_workers,
                cache_hours,
                cache_settings.get("cache_dir", "%APPDATA%/PaperRadar/cache"),
                cache_size,
                cache_settings.get("max_size_gb", 10),
            )
            logger.info("SURVEY_SEARCH_QUERIES queries=%s", queries)
            if self.sources.get("arxiv"):
                logger.info("SURVEY_ARXIV_NOTICE arXiv historical search may be slow; disable arXiv if only top-journal survey is needed.")

            if self.sources.get("arxiv") and not self.cancel_requested:
                try:
                    batch = ArxivClient(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent((self.until_date - self.from_date).days, 1000)
                    stats["success"] += 1
                except Exception as exc:
                    batch = []
                    stats["failed"] += 1
                    stats["failed_query_count"] += 1
                    if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                        stats["timeouts"] += 1
                    logger.warning("SURVEY_SOURCE_FAILED source_type=arxiv query=arXiv timeout=%s error=%s suggestion=%s", timeout, exc, "如果 arXiv 经常超时，可在历史调研中暂时取消勾选 arXiv。")
                completed += 1
                self._handle_batch(batch, all_seen, stats, completed, total_steps, "arXiv", "arXiv")

            if self.sources.get("rss") and not self.cancel_requested:
                try:
                    rss = JournalRssFetcher(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent((self.until_date - self.from_date).days)
                    stats["success"] += 1
                    stats["failed"] += int(rss.stats.failed_sources)
                    stats["failed_query_count"] += int(rss.stats.failed_sources)
                except Exception as exc:
                    rss = type("EmptyRss", (), {"papers": []})()
                    stats["failed"] += 1
                    stats["failed_query_count"] += 1
                    if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                        stats["timeouts"] += 1
                    logger.warning("SURVEY_SOURCE_FAILED source_type=journal_rss query=RSS timeout=%s error=%s", timeout, exc)
                completed += 1
                self._handle_batch(rss.papers, all_seen, stats, completed, total_steps, "期刊最新文章", "最新文章")

            if self.sources.get("crossref"):
                tasks: list[tuple[dict[str, Any], str, list[str]]] = []
                for journal in top_journals:
                    issns = journal.get("issn") or []
                    if isinstance(issns, str):
                        issns = [issns]
                    if not issns:
                        completed += len(queries)
                        stats["failed"] += len(queries)
                        stats["failed_query_count"] += len(queries)
                        continue
                    for query in queries:
                        tasks.append((journal, query, issns))

                pending: dict[Future, tuple[dict[str, Any], str, tuple[str, str, str, str, str]]] = {}
                task_index = 0
                batch_papers: list[Paper] = []
                batch_index = 0

                def submit_next(executor: ThreadPoolExecutor) -> None:
                    nonlocal task_index, completed, batch_index
                    if self.cancel_requested or task_index >= len(tasks):
                        return
                    journal, query, issns = tasks[task_index]
                    task_index += 1
                    cache_key = ("crossref", str(journal.get("name")), query, self.from_date.isoformat(), self.until_date.isoformat())
                    if not self.ignore_cache and cache_enabled and self.db.is_query_cached(*cache_key, cache_hours=cache_hours):
                        completed += 1
                        stats["cached"] += 1
                        stats["cache_hit"] += 1
                        logger.info("SURVEY_CACHE_HIT source_type=crossref journal=%s query=%s", journal.get("name"), query)
                        self._handle_batch([], all_seen, stats, completed, total_steps, str(journal.get("name")), query, cached=True, batch_index=batch_index, started_at=start_time)
                        batch_index += 1
                        return
                    stats["cache_miss"] += 1
                    logger.info("SURVEY_CACHE_MISS source_type=crossref journal=%s query=%s", journal.get("name"), query)
                    future = executor.submit(self._crossref_query_task, journal, issns, query, self.from_date, self.until_date, rows_per_query, timeout, delay, max_retries, retry_delay)
                    pending[future] = (journal, query, cache_key)

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    while len(pending) < max_workers and task_index < len(tasks) and not self.cancel_requested:
                        submit_next(executor)
                    while pending:
                        done, _ = wait(set(pending), return_when=FIRST_COMPLETED)
                        for future in done:
                            journal, query, cache_key = pending.pop(future)
                            completed += 1
                            try:
                                batch, item_count = future.result()
                                self.db.mark_query_cache(*cache_key, result_count=item_count, status="ok")
                                stats["success"] += 1
                                batch_papers.extend(batch)
                            except Exception as exc:
                                stats["failed"] += 1
                                stats["failed_query_count"] += 1
                                if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                                    stats["timeouts"] += 1
                                self.db.mark_query_cache(*cache_key, result_count=0, status=f"failed:{exc}")
                                logger.warning("SURVEY_QUERY_FAILED source_type=crossref journal=%s query=%s timeout=%s error=%s", journal.get("name"), query, timeout, exc)
                            if len(batch_papers) >= batch_update_size or completed % batch_update_size == 0 or completed >= total_steps:
                                self._handle_batch(batch_papers, all_seen, stats, completed, total_steps, str(journal.get("name")), query, cached=False, batch_index=batch_index, started_at=start_time)
                                batch_index += 1
                                batch_papers = []
                            while len(pending) < max_workers and task_index < len(tasks) and not self.cancel_requested:
                                submit_next(executor)
                    if batch_papers:
                        self._handle_batch(batch_papers, all_seen, stats, completed, total_steps, "顶刊历史检索", "批量结果", cached=False, batch_index=batch_index, started_at=start_time)

            if self.cancel_requested:
                status = "stopped"
            elif stats["failed"]:
                status = "partial_completed"
            else:
                status = "completed"
            stats["status"] = status
            try:
                if cache_enabled:
                    cleanup = enforce_cache_limit(float(cache_settings.get("max_size_gb", 10)))
                    stats["cache_size_bytes"] = cleanup.size_after
            except Exception:
                logger.warning("SURVEY_CACHE_CLEANUP_FAILED", exc_info=True)
            logger.info("SURVEY_DONE status=%s elapsed=%.1fs stats=%s", status, time.monotonic() - start_time, dict(stats))
            self.finished_ok.emit(dict(stats))
        except Exception as exc:
            logger.error("Survey failed: %s\n%s", exc, traceback.format_exc())
            self.failed.emit(str(exc))

    def _crossref_query_task(
        self,
        journal: dict[str, Any],
        issns: list[str],
        query: str,
        from_date: date,
        until_date: date,
        rows: int,
        timeout: int,
        delay: float,
        max_retries: int,
        retry_delay: int,
    ) -> tuple[list[Paper], int]:
        client = CrossrefClient(timeout=timeout, rows=rows, sleep_seconds=delay, max_retries=max_retries, retry_delay_seconds=retry_delay)
        items = client._query(journal, issns, query, from_date, until_date)
        return [client._item_to_paper(journal, item) for item in items], len(items)

    def _handle_batch(self, batch: list[Paper], all_seen: list[Paper], stats: Counter, completed: int, total: int, journal: str, query: str, cached: bool = False, batch_index: int = 0, started_at: float | None = None) -> None:
        stats["requests"] = completed
        stats["found"] += len(batch)
        all_seen.extend(batch)
        deduped = dedupe_papers(all_seen)
        scored = score_and_tag(deduped, self.keyword_filter, keep_unmatched=True)
        storage = self.db.upsert_papers_with_stats(scored)
        stats["deduped"] = len(scored)
        stats["matched"] = sum(1 for p in scored if p.matched_keywords)
        stats["inserted"] += storage.inserted_count
        stats["updated"] += storage.updated_count
        stats["displayed"] = len(scored)
        progress = {
            "completed": completed,
            "total": max(total, 1),
            "journal": journal,
            "query": query,
            "found": stats["found"],
            "deduped": stats["deduped"],
            "matched": stats["matched"],
            "displayed": stats["displayed"],
            "success": stats["success"],
            "failed": stats["failed"],
            "timeouts": stats["timeouts"],
            "failed_query_count": stats["failed_query_count"],
            "cache_hit": stats["cache_hit"],
            "cache_miss": stats["cache_miss"],
            "cached": cached,
            "batch_index": batch_index,
            "elapsed_seconds": round(time.monotonic() - started_at, 1) if started_at else 0,
            "cancel_requested": self.cancel_requested,
        }
        logger.info("SURVEY_BATCH %s", progress)
        self.batch_results_ready.emit(scored, progress)
        self.progress_updated.emit(progress)


class MainWindow(QMainWindow):
    def __init__(self, first_run_needed: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("PaperRadar")
        self.resize(1280, 820)
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))

        self.db = PaperDatabase()
        self.settings = load_settings()
        self.ui_settings = QSettings("PaperRadar", "PaperRadar")
        self.keyword_filter = KeywordFilter(load_keywords())
        self.daily_worker: DailyRadarWorker | None = None
        self.survey_worker: HistoricalSurveyWorker | None = None
        self.all_daily_papers: list[Paper] = []
        self.all_survey_papers: list[Paper] = []
        self.daily_papers: list[Paper] = []
        self.survey_papers: list[Paper] = []
        self.last_survey_stats: dict[str, Any] = {}
        self.selected_paper: Paper | None = None
        self.cell_popup: QDialog | None = None
        self.cell_popup_key: tuple[int, int, int] | None = None
        self.pending_cell_key: tuple[int, int, int] | None = None
        self.normalized_profile_yaml = ""
        self.allow_exit = False
        self.tray: RadarTrayIcon | None = None
        self.validated_profile: dict[str, Any] | None = None

        self._build_ui()
        QApplication.instance().installEventFilter(self)
        self._setup_tray()
        self.refresh_profile_page()
        if first_run_needed:
            self.show_first_run_wizard()

    def _build_ui(self) -> None:
        self.setStyleSheet(self._style_sheet())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_daily_tab(), "每日雷达")
        self.tabs.addTab(self._build_survey_tab(), "历史调研")
        self.tabs.addTab(self._build_profile_tab(), "研究方向配置")
        self.setCentralWidget(self.tabs)

    def _page_header(self, title_text: str, subtitle_text: str) -> QWidget:
        header = QWidget()
        header.setObjectName("pageHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(4)
        title = QLabel(title_text)
        title.setObjectName("pageTitle")
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return header

    def _metric_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("metricCard")
        label.setWordWrap(False)
        return label

    def _style_button(self, button: QPushButton, kind: str = "secondary") -> None:
        button.setObjectName(f"{kind}Button")

    def _build_daily_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)
        root.addWidget(self._page_header("每日雷达", "开始检查前，请先在“研究方向配置”中设置自己的研究方向。这里用于每天快速查看最近出现的新论文。"))

        status = QGroupBox("状态")
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(14, 18, 14, 14)
        status_layout.setSpacing(8)
        self.daily_last_label = self._metric_label("上次检查：从未")
        self.daily_found_label = self._metric_label("本次发现：0")
        self.daily_high_label = self._metric_label("高相关：0")
        self.daily_skim_label = self._metric_label("值得扫读：0")
        self.daily_status_label = QLabel("就绪")
        self.daily_status_label.setObjectName("statusPill")
        for widget in [self.daily_last_label, self.daily_found_label, self.daily_high_label, self.daily_skim_label, self.daily_status_label]:
            status_layout.addWidget(widget)
        status_layout.addStretch(1)
        root.addWidget(status)

        settings = QGroupBox("检索设置")
        row = QHBoxLayout(settings)
        row.setContentsMargins(14, 18, 14, 14)
        row.setSpacing(10)
        self.daily_days = QComboBox()
        self.daily_days.addItems(["1", "3", "7", "14", "30"])
        self.daily_days.setCurrentText(str(min(int(self.settings.get("days_back", 7)), 30)))
        self.daily_min_score = QSpinBox()
        self.daily_min_score.setRange(20, 100)
        self.daily_min_score.setValue(20)
        self.daily_arxiv = QCheckBox("预印本论文")
        self.daily_arxiv.setToolTip("来自 arXiv，适合快速发现尚未正式发表的新论文。")
        self.daily_arxiv.setChecked(True)
        self.daily_rss = QCheckBox("期刊最新文章")
        self.daily_rss.setToolTip("从期刊提供的最新文章列表中查看近期更新，不等同于完整历史检索。")
        self.daily_rss.setChecked(True)
        self.daily_crossref = QCheckBox("顶级期刊近期检索")
        self.daily_crossref.setToolTip("按当前研究方向关键词，在顶级期刊数据库中检索近期文章。")
        self.daily_crossref.setChecked(False)
        for label, widget in [("检索最近天数", self.daily_days), ("显示最低分", self.daily_min_score)]:
            row.addWidget(QLabel(label))
            row.addWidget(widget)
        row.addWidget(QLabel("检索数据源"))
        for widget in [self.daily_arxiv, self.daily_rss, self.daily_crossref]:
            row.addWidget(widget)
        row.addStretch(1)
        root.addWidget(settings)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.daily_run_btn = QPushButton("立即检查")
        self.daily_stop_btn = QPushButton("停止")
        self.daily_stop_btn.setEnabled(False)
        self.daily_report_btn = QPushButton("生成今日报告")
        self.daily_open_reports_btn = QPushButton("打开报告文件夹")
        self.daily_scope_btn = QPushButton("查看检索范围")
        self._style_button(self.daily_run_btn, "primary")
        self._style_button(self.daily_stop_btn, "danger")
        self._style_button(self.daily_report_btn)
        self._style_button(self.daily_open_reports_btn)
        self._style_button(self.daily_scope_btn)
        for button in [self.daily_run_btn, self.daily_stop_btn, self.daily_report_btn, self.daily_open_reports_btn, self.daily_scope_btn]:
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

        self.daily_table, self.daily_detail, self.daily_open_link_btn = self._make_results_area()
        root.addWidget(self.daily_table_splitter)

        self.daily_run_btn.clicked.connect(self.run_daily)
        self.daily_stop_btn.clicked.connect(self.stop_daily)
        self.daily_report_btn.clicked.connect(self.generate_daily_report)
        self.daily_open_reports_btn.clicked.connect(self.open_report_folder)
        self.daily_scope_btn.clicked.connect(lambda: self.show_search_scope("daily"))
        self.daily_table.cellClicked.connect(lambda row, col: self.on_table_cell_clicked(self.daily_table, row, col))
        self.daily_min_score.valueChanged.connect(lambda _: self.refresh_daily_display())
        return page

    def _build_survey_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)
        root.addWidget(self._page_header("历史调研", "开始调研前，请先在“研究方向配置”中设置自己的研究方向。这里用于系统检索一段时间内的相关论文。"))

        settings = QGroupBox("调研设置")
        row = QHBoxLayout(settings)
        row.setContentsMargins(14, 18, 14, 14)
        row.setSpacing(10)
        self.survey_name = QLineEdit("当前方向历史调研")
        self.survey_range = QComboBox()
        self.survey_range.addItems(["最近 90 天", "最近 365 天", "最近 3 年", "自定义"])
        self.survey_range.setCurrentText("最近 365 天")
        self.survey_from_label = QLabel("开始日期")
        self.survey_from = QDateEdit(QDate.currentDate().addDays(-365))
        self.survey_from.setCalendarPopup(True)
        self.survey_until_label = QLabel("结束日期")
        self.survey_until = QDateEdit(QDate.currentDate())
        self.survey_until.setCalendarPopup(True)
        self.survey_min_score = QSpinBox()
        self.survey_min_score.setRange(20, 100)
        self.survey_min_score.setValue(20)
        row.addWidget(QLabel("调研名称"))
        row.addWidget(self.survey_name)
        row.addWidget(QLabel("时间范围"))
        row.addWidget(self.survey_range)
        row.addWidget(self.survey_from_label)
        row.addWidget(self.survey_from)
        row.addWidget(self.survey_until_label)
        row.addWidget(self.survey_until)
        row.addWidget(QLabel("显示最低分"))
        row.addWidget(self.survey_min_score)
        root.addWidget(settings)

        source_box = QGroupBox("检索数据源")
        source_row = QHBoxLayout(source_box)
        source_row.setContentsMargins(14, 18, 14, 14)
        source_row.setSpacing(10)
        self.survey_crossref = QCheckBox("顶级期刊历史检索")
        self.survey_crossref.setToolTip("按当前研究方向关键词，在配置的顶级期刊中做系统检索。")
        self.survey_crossref.setChecked(True)
        self.survey_arxiv = QCheckBox("预印本论文")
        self.survey_arxiv.setToolTip("来自 arXiv；历史范围较长时可能较慢，如只做顶刊调研可不勾选。")
        self.survey_rss = QCheckBox("期刊最新文章")
        self.survey_rss.setToolTip("只适合补充最新文章动态，不适合作为完整历史调研来源。")
        self.survey_ignore_cache = QCheckBox("忽略缓存，重新检索")
        source_row.addWidget(self.survey_crossref)
        source_row.addWidget(self.survey_arxiv)
        source_row.addWidget(self.survey_rss)
        source_row.addWidget(QLabel("期刊集合：顶级期刊"))
        source_row.addWidget(self.survey_ignore_cache)
        source_row.addStretch(1)
        root.addWidget(source_box)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.survey_run_btn = QPushButton("开始调研")
        self.survey_stop_btn = QPushButton("停止")
        self.survey_stop_btn.setEnabled(False)
        self.survey_report_btn = QPushButton("生成调研报告")
        self.survey_open_reports_btn = QPushButton("打开报告文件夹")
        self.survey_scope_btn = QPushButton("查看检索范围")
        self._style_button(self.survey_run_btn, "primary")
        self._style_button(self.survey_stop_btn, "danger")
        self._style_button(self.survey_report_btn)
        self._style_button(self.survey_open_reports_btn)
        self._style_button(self.survey_scope_btn)
        for button in [self.survey_run_btn, self.survey_stop_btn, self.survey_report_btn, self.survey_open_reports_btn, self.survey_scope_btn]:
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

        progress_box = QGroupBox("进度")
        progress_layout = QVBoxLayout(progress_box)
        progress_layout.setContentsMargins(14, 18, 14, 14)
        progress_layout.setSpacing(8)
        self.survey_progress = QProgressBar()
        self.survey_status = QLabel("就绪")
        self.survey_status.setObjectName("progressStatus")
        self.survey_counts = QLabel("进度：0 / 0；已发现：0；去重后：0；命中：0；已显示：0；成功：0；失败：0；缓存：0；超时：0")
        self.survey_counts.setObjectName("progressCounts")
        progress_layout.addWidget(self.survey_progress)
        progress_layout.addWidget(self.survey_status)
        progress_layout.addWidget(self.survey_counts)
        root.addWidget(progress_box)

        self.survey_table, self.survey_detail, self.survey_open_link_btn = self._make_results_area(prefix="survey")
        root.addWidget(self.survey_table_splitter)

        self.survey_run_btn.clicked.connect(self.run_survey)
        self.survey_stop_btn.clicked.connect(self.stop_survey)
        self.survey_report_btn.clicked.connect(self.generate_survey_report)
        self.survey_open_reports_btn.clicked.connect(self.open_report_folder)
        self.survey_scope_btn.clicked.connect(lambda: self.show_search_scope("survey"))
        self.survey_range.currentTextChanged.connect(self._sync_survey_date_controls)
        self._sync_survey_date_controls()
        self.survey_table.cellClicked.connect(lambda row, col: self.on_table_cell_clicked(self.survey_table, row, col))
        self.survey_min_score.valueChanged.connect(lambda _: self.refresh_survey_display())
        return page

    def _build_profile_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)
        root.addWidget(self._page_header("研究方向配置", "管理检索 Profile，生成给外部 AI 的提示词，并导入规范化后的研究方向配置。"))

        status = QGroupBox("当前 Profile")
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(14, 18, 14, 14)
        status_layout.setSpacing(10)
        self.profile_status_label = QLabel("")
        self.profile_status_label.setObjectName("profileSummary")
        self.profile_status_label.setWordWrap(True)
        status_layout.addWidget(self.profile_status_label)
        status_actions = QHBoxLayout()
        self.profile_set_active_btn = QPushButton("设为当前方向")
        self.profile_copy_btn = QPushButton("复制当前 Profile")
        self.profile_export_btn = QPushButton("导出 Profile")
        self.profile_delete_btn = QPushButton("删除 Profile")
        self._style_button(self.profile_set_active_btn, "primary")
        self._style_button(self.profile_copy_btn)
        self._style_button(self.profile_export_btn)
        self._style_button(self.profile_delete_btn, "danger")
        for button in [self.profile_set_active_btn, self.profile_copy_btn, self.profile_export_btn, self.profile_delete_btn]:
            status_actions.addWidget(button)
        status_actions.addStretch(1)
        status_layout.addLayout(status_actions)
        root.addWidget(status)

        self.profile_table = QTableWidget(0, 6)
        self.profile_table.setHorizontalHeaderLabels(["显示名称", "Profile ID", "描述", "检索式", "关键词组", "当前"])
        self.profile_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.profile_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.profile_table.setAlternatingRowColors(True)
        profile_header = self.profile_table.horizontalHeader()
        profile_header.setStretchLastSection(False)
        for col in range(self.profile_table.columnCount()):
            profile_header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        profile_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col, width in {0: 150, 1: 170, 3: 96, 4: 320, 5: 72}.items():
            self.profile_table.setColumnWidth(col, width)
        self.profile_table.verticalHeader().setDefaultSectionSize(44)
        self.profile_table.setMinimumHeight(178)
        self.profile_table.viewport().installEventFilter(self)
        root.addWidget(self.profile_table)

        prompt_box = QGroupBox("AI 提示词生成")
        prompt_layout = QHBoxLayout(prompt_box)
        prompt_layout.setContentsMargins(14, 18, 14, 14)
        prompt_layout.setSpacing(10)
        self.profile_direction_input = QLineEdit()
        self.profile_direction_input.setPlaceholderText("输入研究方向，例如：超快光子学")
        self.profile_generate_prompt_btn = QPushButton("生成并复制 AI 提示词")
        self._style_button(self.profile_generate_prompt_btn, "primary")
        prompt_layout.addWidget(QLabel("研究方向"))
        prompt_layout.addWidget(self.profile_direction_input)
        prompt_layout.addWidget(self.profile_generate_prompt_btn)
        root.addWidget(prompt_box)

        import_box = QGroupBox("Profile 粘贴导入")
        import_layout = QVBoxLayout(import_box)
        import_layout.setContentsMargins(14, 18, 14, 14)
        import_layout.setSpacing(10)
        self.profile_yaml_text = QTextEdit()
        self.profile_yaml_text.setPlaceholderText("在这里粘贴外部 AI 生成的 PaperRadar Profile YAML")
        import_layout.addWidget(self.profile_yaml_text)
        import_actions = QHBoxLayout()
        self.profile_paste_btn = QPushButton("粘贴剪贴板内容")
        self.profile_validate_btn = QPushButton("智能解析并预览")
        self.profile_save_active_btn = QPushButton("保存并设为当前方向")
        self._style_button(self.profile_paste_btn)
        self._style_button(self.profile_validate_btn, "primary")
        self._style_button(self.profile_save_active_btn, "primary")
        for button in [self.profile_paste_btn, self.profile_validate_btn, self.profile_save_active_btn]:
            import_actions.addWidget(button)
        import_actions.addStretch(1)
        import_layout.addLayout(import_actions)
        self.profile_validation_label = QLabel("尚未校验")
        self.profile_validation_label.setObjectName("validationCard")
        self.profile_validation_label.setWordWrap(True)
        import_layout.addWidget(self.profile_validation_label)
        root.addWidget(import_box)

        self.profile_table.itemSelectionChanged.connect(self.on_profile_selection_changed)
        self.profile_table.cellClicked.connect(lambda row, col: self.on_table_cell_clicked(self.profile_table, row, col))
        self.profile_set_active_btn.clicked.connect(self.set_selected_profile_active)
        self.profile_copy_btn.clicked.connect(self.copy_current_profile)
        self.profile_export_btn.clicked.connect(self.export_selected_profile)
        self.profile_delete_btn.clicked.connect(self.delete_selected_profile)
        self.profile_generate_prompt_btn.clicked.connect(self.generate_and_copy_profile_prompt)
        self.profile_paste_btn.clicked.connect(self.paste_profile_yaml)
        self.profile_validate_btn.clicked.connect(self.validate_profile_input)
        self.profile_save_active_btn.clicked.connect(lambda: self.save_validated_profile(make_active=True))
        return page

    def _make_results_area(self, prefix: str = "daily") -> tuple[QTableWidget, QTextEdit, QPushButton]:
        splitter = QSplitter(Qt.Orientation.Vertical)
        table = QTableWidget(0, 9)
        table.setHorizontalHeaderLabels(["分数", "来源", "来源类型", "标题", "作者", "发布日期", "分类/DOI", "命中关键词", "链接"])
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setMouseTracking(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(42)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(60)
        self._apply_result_column_layout(table)
        self._restore_table_widths(table, prefix)
        self._apply_result_column_layout(table)
        header.sectionResized.connect(lambda *_: self._save_table_widths(table, prefix))
        table.cellEntered.connect(lambda row, col, t=table: self.on_result_cell_entered(t, row, col))
        table.viewport().installEventFilter(self)
        splitter.addWidget(table)
        detail_widget = QWidget()
        detail_widget.setObjectName("paperCard")
        detail_layout = QVBoxLayout(detail_widget)
        title = QLabel("选择一篇论文查看详情")
        title.setObjectName("paperTitle")
        title.setWordWrap(True)
        meta = QLabel("")
        meta.setObjectName("paperMeta")
        meta.setWordWrap(True)
        text = QTextEdit()
        text.setReadOnly(True)
        open_btn = QPushButton("打开链接")
        open_btn.setEnabled(False)
        detail_layout.addWidget(title)
        detail_layout.addWidget(meta)
        detail_layout.addWidget(text)
        splitter.addWidget(detail_widget)
        splitter.setSizes([430, 260])
        if prefix == "daily":
            self.daily_table_splitter = splitter
            self.daily_detail_title = title
            self.daily_detail_meta = meta
            self.daily_detail_text = text
        else:
            self.survey_table_splitter = splitter
            self.survey_detail_title = title
            self.survey_detail_meta = meta
            self.survey_detail_text = text
        return table, text, open_btn

    def run_daily(self) -> None:
        if self.daily_worker and self.daily_worker.isRunning():
            return
        self.daily_status_label.setText("正在检索")
        self.daily_run_btn.setEnabled(False)
        self.daily_stop_btn.setEnabled(True)
        sources = {"arxiv": self.daily_arxiv.isChecked(), "rss": self.daily_rss.isChecked(), "crossref": self.daily_crossref.isChecked()}
        self.daily_worker = DailyRadarWorker(int(self.daily_days.currentText()), sources, self.settings)
        self.daily_worker.finished_ok.connect(self.on_daily_finished)
        self.daily_worker.failed.connect(self.on_daily_failed)
        self.daily_worker.start()

    def stop_daily(self) -> None:
        if self.daily_worker and self.daily_worker.isRunning():
            self.daily_worker.request_cancel()
            self.daily_status_label.setText("正在停止")

    def on_daily_finished(self, papers: list[Paper], stats: dict) -> None:
        self.all_daily_papers = papers
        self.refresh_daily_display()
        self.daily_last_label.setText(f"上次检查：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.daily_found_label.setText(f"本次发现：{len(self.daily_papers)} / 入库候选 {len(self.all_daily_papers)}")
        self.daily_high_label.setText(f"高相关：{sum(1 for paper in self.daily_papers if paper.relevance_score >= 60)}")
        self.daily_skim_label.setText(f"值得扫读：{sum(1 for paper in self.daily_papers if 40 <= paper.relevance_score < 60)}")
        self.daily_status_label.setText("已完成")
        self.daily_run_btn.setEnabled(True)
        self.daily_stop_btn.setEnabled(False)

    def on_daily_failed(self, message: str) -> None:
        self.daily_status_label.setText("失败")
        self.daily_run_btn.setEnabled(True)
        self.daily_stop_btn.setEnabled(False)
        QMessageBox.warning(self, "每日雷达失败", message)

    def run_survey(self) -> None:
        if self.survey_worker and self.survey_worker.isRunning():
            return
        from_date, until_date = self._survey_dates()
        sources = {"crossref": self.survey_crossref.isChecked(), "arxiv": self.survey_arxiv.isChecked(), "rss": self.survey_rss.isChecked()}
        self.survey_progress.setValue(0)
        if sources.get("arxiv"):
            self.survey_status.setText("正在启动；预印本历史检索可能较慢，如只需顶级期刊调研，可只选择“顶级期刊历史检索”。")
        else:
            self.survey_status.setText("正在启动")
        self.survey_run_btn.setEnabled(False)
        self.survey_stop_btn.setEnabled(True)
        self.survey_worker = HistoricalSurveyWorker(
            self.survey_name.text() or "当前方向历史调研",
            from_date,
            until_date,
            sources,
            self.survey_ignore_cache.isChecked(),
            self.settings,
        )
        self.survey_worker.batch_results_ready.connect(self.on_survey_batch)
        self.survey_worker.progress_updated.connect(self.on_survey_progress)
        self.survey_worker.finished_ok.connect(self.on_survey_finished)
        self.survey_worker.failed.connect(self.on_survey_failed)
        self.survey_worker.start()

    def stop_survey(self) -> None:
        if self.survey_worker and self.survey_worker.isRunning():
            self.survey_worker.request_cancel()
            self.survey_status.setText("正在停止，已保存的结果会保留")

    def on_survey_batch(self, papers: list[Paper], progress: dict) -> None:
        self.all_survey_papers = papers
        self.refresh_survey_display()

    def on_survey_progress(self, progress: dict) -> None:
        total = int(progress.get("total", 1))
        completed = int(progress.get("completed", 0))
        self.survey_progress.setMaximum(total)
        self.survey_progress.setValue(completed)
        self.survey_status.setText(f"正在检索：{progress.get('journal')} × {progress.get('query')}；进度：{completed} / {total}")
        displayed_count = len(self.survey_papers)
        self.survey_counts.setText(
            f"进度：{completed} / {total}；已发现：{progress.get('found', 0)}；去重后：{progress.get('deduped', 0)}；"
            f"命中：{progress.get('matched', 0)}；已显示：{displayed_count}；"
            f"成功：{progress.get('success', 0)}；失败：{progress.get('failed', 0)}；缓存：{progress.get('cache_hit', progress.get('cached', 0))}；超时：{progress.get('timeouts', 0)}"
        )

    def refresh_daily_display(self) -> None:
        min_score = self.daily_min_score.value()
        self.daily_papers = [
            paper for paper in self.all_daily_papers
            if paper.matched_keywords and paper.relevance_score >= min_score
        ]
        self.populate_table(self.daily_table, self.daily_papers)
        if self.all_daily_papers:
            self.daily_found_label.setText(f"本次发现：{len(self.daily_papers)} / 入库候选 {len(self.all_daily_papers)}")
            self.daily_high_label.setText(f"高相关：{sum(1 for paper in self.daily_papers if paper.relevance_score >= 60)}")
            self.daily_skim_label.setText(f"值得扫读：{sum(1 for paper in self.daily_papers if 40 <= paper.relevance_score < 60)}")

    def refresh_survey_display(self) -> None:
        min_score = self.survey_min_score.value()
        matched = [paper for paper in self.all_survey_papers if paper.matched_keywords]
        self.survey_papers = [paper for paper in matched if paper.relevance_score >= min_score]
        self.populate_table(self.survey_table, self.survey_papers)

    def on_survey_finished(self, stats: dict) -> None:
        self.last_survey_stats = dict(stats)
        status = stats.get("status")
        if status == "stopped":
            self.survey_status.setText("已停止，本次已保存部分结果。")
        elif status == "partial_completed":
            self.survey_status.setText("部分完成，有失败；已保存成功获取的结果。")
        else:
            self.survey_status.setText("已完成")
        self.survey_run_btn.setEnabled(True)
        self.survey_stop_btn.setEnabled(False)

    def on_survey_failed(self, message: str) -> None:
        self.survey_status.setText("失败")
        self.survey_run_btn.setEnabled(True)
        self.survey_stop_btn.setEnabled(False)
        QMessageBox.warning(self, "历史调研失败", message)

    def show_search_scope(self, mode: str) -> None:
        profile = load_active_profile()
        sources = load_sources()
        selected_sources: list[str] = []
        journals: list[str] = []
        if mode == "daily":
            if self.daily_arxiv.isChecked():
                selected_sources.append("预印本论文")
            if self.daily_rss.isChecked():
                selected_sources.append("期刊最新文章")
                journals.extend(
                    str(source.get("name"))
                    for source in sources.get("journal_sources", [])
                    if source.get("enabled") and source.get("name")
                )
            if self.daily_crossref.isChecked():
                selected_sources.append("顶级期刊近期检索")
                journals.extend(
                    str(source.get("name"))
                    for source in sources.get("top_journals", [])
                    if source.get("crossref_enabled") and source.get("name")
                )
        else:
            if self.survey_crossref.isChecked():
                selected_sources.append("顶级期刊历史检索")
                journals.extend(
                    str(source.get("name"))
                    for source in sources.get("top_journals", [])
                    if source.get("crossref_enabled") and source.get("name")
                )
            if self.survey_arxiv.isChecked():
                selected_sources.append("预印本论文")
            if self.survey_rss.isChecked():
                selected_sources.append("期刊最新文章")
                journals.extend(
                    str(source.get("name"))
                    for source in sources.get("journal_sources", [])
                    if source.get("enabled") and source.get("name")
                )

        keywords = profile_to_keywords(profile)
        match_terms = []
        for group, terms in keywords.items():
            if group != "exclude":
                match_terms.extend(terms)
        queries = [str(query) for query in profile.get("search_queries") or [] if str(query).strip()]
        journals = list(dict.fromkeys(journals))
        match_terms = list(dict.fromkeys(match_terms))

        def block(values: list[str], empty: str, limit: int = 80) -> str:
            if not values:
                return empty
            shown = values[:limit]
            suffix = f"\n... 另有 {len(values) - limit} 项" if len(values) > limit else ""
            return "\n".join(f"- {value}" for value in shown) + suffix

        text = (
            f"当前研究方向：{profile.get('display_name') or profile.get('profile_id') or '未命名'}\n\n"
            f"已选择的数据来源：\n{block(selected_sources, '- 暂未选择数据来源')}\n\n"
            f"会检索的期刊：\n{block(journals, '- 预印本论文不按期刊筛选；若未选择期刊来源，则不会显示期刊列表。')}\n\n"
            f"用于远程检索的关键词/检索式：\n{block(queries, '- 当前 Profile 没有配置 search_queries')}\n\n"
            f"用于本地判断相关性的关键词：\n{block(match_terms, '- 当前 Profile 没有配置 keyword_groups')}"
        )
        QMessageBox.information(self, "当前检索范围", text)

    def _sync_survey_date_controls(self) -> None:
        custom = self.survey_range.currentText() == "自定义"
        for widget in [self.survey_from_label, self.survey_from, self.survey_until_label, self.survey_until]:
            widget.setVisible(custom)

    def _restore_table_widths(self, table: QTableWidget, prefix: str) -> None:
        widths = self.ui_settings.value(f"{prefix}/table_column_widths", [])
        if not isinstance(widths, list):
            return
        for col, width in enumerate(widths[:table.columnCount()]):
            try:
                width_value = int(width)
            except (TypeError, ValueError):
                continue
            if width_value > 20:
                table.setColumnWidth(col, width_value)

    def _save_table_widths(self, table: QTableWidget, prefix: str) -> None:
        widths = [table.columnWidth(col) for col in range(table.columnCount())]
        self.ui_settings.setValue(f"{prefix}/table_column_widths", widths)

    def _survey_dates(self) -> tuple[date, date]:
        today = date.today()
        text = self.survey_range.currentText()
        if "90" in text:
            return today - timedelta(days=90), today
        if "365" in text:
            return today - timedelta(days=365), today
        if "3 年" in text:
            return today - timedelta(days=365 * 3), today
        return self.survey_from.date().toPython(), self.survey_until.date().toPython()

    def populate_table(self, table: QTableWidget, papers: list[Paper]) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for row, paper in enumerate(papers):
            table.insertRow(row)
            values = [
                str(int(paper.relevance_score)),
                paper.journal_or_source or "未知",
                self._source_type_label(paper.source_type),
                paper.title,
                paper.authors,
                format_date_only(paper.published_date),
                paper.doi or paper.primary_category_text or "期刊论文",
                paper.matched_keywords_text,
                paper.url or "无链接",
            ]
            for col, value in enumerate(values):
                sort_value: Any = value
                if col == 0:
                    sort_value = int(paper.relevance_score)
                elif col == 5:
                    sort_value = format_date_only(paper.published_date)
                item = SortableTableItem(value, sort_value)
                item.setData(Qt.ItemDataRole.UserRole, row)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 0:
                    item.setData(Qt.ItemDataRole.DisplayRole, int(paper.relevance_score))
                    if paper.relevance_score >= 80:
                        item.setForeground(QBrush(QColor("#1d4ed8")))
                        item.setBackground(QBrush(QColor("#eaf2ff")))
                if col == RESULT_LINK_COLUMN:
                    item.setData(LINK_URL_ROLE, paper.url)
                    if paper.url:
                        font = QFont(item.font())
                        font.setUnderline(True)
                        item.setFont(font)
                        item.setForeground(QBrush(QColor("#2563eb")))
                        item.setToolTip(paper.url)
                    else:
                        item.setForeground(QBrush(QColor("#94a3b8")))
                        item.setToolTip("该论文没有可用链接")
                table.setItem(row, col, item)
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.SortOrder.DescendingOrder)
        self._apply_result_column_layout(table)

    def _apply_result_column_layout(self, table: QTableWidget) -> None:
        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setCascadingSectionResizes(True)
        header.setMinimumSectionSize(70)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        for col in range(table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        default_widths = {
            0: 70,
            1: 140,
            2: 110,
            3: 280,
            4: 220,
            5: 110,
            6: 160,
            7: 220,
            RESULT_LINK_COLUMN: 300,
        }
        for col, width in default_widths.items():
            if table.columnWidth(col) < 80:
                table.setColumnWidth(col, width)

    def _is_result_table(self, table: QTableWidget) -> bool:
        return table is self.daily_table or table is self.survey_table

    def _papers_for_table(self, table: QTableWidget) -> list[Paper]:
        if table is self.daily_table:
            return self.daily_papers
        if table is self.survey_table:
            return self.survey_papers
        return []

    def on_result_cell_entered(self, table: QTableWidget, row: int, col: int) -> None:
        item = table.item(row, col)
        if col == RESULT_LINK_COLUMN and item and item.data(LINK_URL_ROLE):
            table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            table.viewport().unsetCursor()

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            clicked_table = False
            for table in (getattr(self, "daily_table", None), getattr(self, "survey_table", None), getattr(self, "profile_table", None)):
                if table and watched is table.viewport():
                    clicked_table = True
                    position = event.position().toPoint() if hasattr(event, "position") else event.pos()
                    if table.itemAt(position) is None:
                        self._close_cell_popup()
                        self.pending_cell_key = None
                    break
            if (
                self.cell_popup
                and self.cell_popup.isVisible()
                and not clicked_table
                and not (isinstance(watched, QWidget) and (watched is self.cell_popup or self.cell_popup.isAncestorOf(watched)))
            ):
                self._close_cell_popup()
                self.pending_cell_key = None
        return super().eventFilter(watched, event)

    def on_table_cell_clicked(self, table: QTableWidget, row: int, col: int) -> None:
        item = table.item(row, col)
        if not item:
            return
        if self._is_result_table(table):
            if col == RESULT_LINK_COLUMN:
                self._open_link_from_table_item(table, row, col)
                return
            self._select_result_table_row(table, row)
        key = (id(table), row, col)
        if self.pending_cell_key != key:
            self.pending_cell_key = key
            self._close_cell_popup()
            return
        text = item.text()
        if not text:
            return
        if self.cell_popup and self.cell_popup.isVisible() and self.cell_popup_key == key:
            self._close_cell_popup()
            return
        self._close_cell_popup()
        self.cell_popup_key = key
        self.cell_popup = QDialog(self)
        self.cell_popup.setObjectName("cellPopup")
        self.cell_popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        layout = QVBoxLayout(self.cell_popup)
        layout.setContentsMargins(14, 12, 14, 12)
        title = QLabel(table.horizontalHeaderItem(col).text() if table.horizontalHeaderItem(col) else "内容")
        title.setObjectName("cellPopupTitle")
        content = QTextEdit()
        content.setReadOnly(True)
        content.setPlainText(text)
        content.setMinimumSize(360, 120)
        content.setMaximumSize(640, 300)
        layout.addWidget(title)
        layout.addWidget(content)
        pos = table.viewport().mapToGlobal(table.visualItemRect(item).bottomLeft())
        self.cell_popup.move(pos)
        self.cell_popup.show()

    def _close_cell_popup(self) -> None:
        if self.cell_popup:
            self.cell_popup.close()
        self.cell_popup = None
        self.cell_popup_key = None

    def _select_result_table_row(self, table: QTableWidget, row: int) -> None:
        papers = self._papers_for_table(table)
        item = table.item(row, 0)
        if not item:
            return
        row_index = item.data(Qt.ItemDataRole.UserRole)
        if row_index is None or row_index >= len(papers):
            return
        self.selected_paper = papers[row_index]
        target = "daily" if table is self.daily_table else "survey"
        self._show_detail(self.selected_paper, target)

    def _open_link_from_table_item(self, table: QTableWidget, row: int, col: int) -> None:
        item = table.item(row, col)
        url = item.data(LINK_URL_ROLE) if item else ""
        table.clearSelection()
        if not url:
            self.statusBar().showMessage("该论文没有可用链接", 3000)
            return
        parsed = urlparse(str(url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self.statusBar().showMessage("链接无效", 3000)
            return
        open_url(str(url))
        self.statusBar().showMessage("正在打开链接", 2000)

    def on_selection_changed(self, table: QTableWidget, papers: list[Paper]) -> None:
        items = table.selectedItems()
        if not items:
            return
        row_index = items[0].data(Qt.ItemDataRole.UserRole)
        if row_index is None or row_index >= len(papers):
            return
        self.selected_paper = papers[row_index]
        target = "daily" if table is self.daily_table else "survey"
        self._show_detail(self.selected_paper, target)

    def _show_detail(self, paper: Paper, target: str) -> None:
        title = self.daily_detail_title if target == "daily" else self.survey_detail_title
        meta = self.daily_detail_meta if target == "daily" else self.survey_detail_meta
        text = self.daily_detail_text if target == "daily" else self.survey_detail_text
        btn = self.daily_open_link_btn if target == "daily" else self.survey_open_link_btn
        title.setText(paper.title or "未命名论文")
        meta.setText(
            f"作者：{paper.authors or '未知'}\n来源：{paper.journal_or_source or '未知'}    来源类型：{self._source_type_label(paper.source_type)}\n"
            f"发布日期：{format_date_only(paper.published_date)}    DOI：{paper.doi or '未知'}\n"
            f"分数：{paper.relevance_score}    命中关键词：{paper.matched_keywords_text or '无'}    命中位置：{paper.matched_fields_text or '无'}"
        )
        text.setPlainText(
            f"摘要\n{paper.abstract or '该数据源未提供完整摘要。'}\n\n"
            f"相关性说明\n{paper.reason_zh or '暂无'}\n\n"
            f"链接\n{paper.url or '无'}"
        )
        btn.setEnabled(bool(paper.url))

    def generate_daily_report(self) -> None:
        path = generate_daily_report(self.daily_papers)
        QMessageBox.information(self, "报告已生成", f"报告已保存到：\n{path}")

    def generate_survey_report(self) -> None:
        from_date, until_date = self._survey_dates()
        path = generate_survey_report(self.survey_papers, self.survey_name.text(), from_date, until_date, run_stats=self.last_survey_stats)
        QMessageBox.information(self, "报告已生成", f"报告已保存到：\n{path}")

    def refresh_profile_page(self) -> None:
        if not hasattr(self, "profile_table"):
            return
        active = load_active_profile()
        active_id = active.get("profile_id", DEFAULT_PROFILE_ID)
        self.profile_status_label.setText(
            f"当前激活研究方向：{active.get('display_name', '未知')}\n"
            f"Profile ID：{active_id}\n"
            f"描述：{active.get('description', '')}"
        )
        profiles = load_all_profiles()
        self.profile_table.setRowCount(0)
        for row, profile in enumerate(profiles):
            self.profile_table.insertRow(row)
            groups = profile.get("keyword_groups") or {}
            queries = profile.get("search_queries") or []
            keyword_terms = self._profile_keyword_terms_text(groups)
            values = [
                profile.get("display_name", ""),
                profile.get("profile_id", ""),
                profile.get("description", ""),
                str(len(queries) if isinstance(queries, list) else 0),
                keyword_terms,
                "是" if profile.get("profile_id") == active_id else "",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, row)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.profile_table.setItem(row, col, item)
        self.keyword_filter = KeywordFilter(load_keywords())

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

    def selected_profile(self) -> dict[str, Any] | None:
        items = self.profile_table.selectedItems()
        if not items:
            return load_active_profile()
        row_index = items[0].data(Qt.ItemDataRole.UserRole)
        profiles = load_all_profiles()
        if row_index is None or row_index >= len(profiles):
            return None
        return profiles[row_index]

    def on_profile_selection_changed(self) -> None:
        return

    def set_selected_profile_active(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        set_active_profile(str(profile.get("profile_id")))
        self.settings = load_settings()
        self.keyword_filter = KeywordFilter(load_keywords())
        self.refresh_profile_page()
        QMessageBox.information(self, "已切换", "当前研究方向已更新。每日雷达和历史调研将使用新的 Profile。")

    def copy_current_profile(self) -> None:
        profile = load_active_profile()
        QApplication.clipboard().setText(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False))
        QMessageBox.information(self, "已复制", "当前 Profile YAML 已复制到剪贴板。")

    def export_selected_profile(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "导出 Profile", f"{profile.get('profile_id', 'profile')}.yaml", "YAML (*.yaml *.yml)")
        if not filename:
            return
        Path(filename).write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
        QMessageBox.information(self, "已导出", f"Profile 已导出到：\n{filename}")

    def delete_selected_profile(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        profile_id = str(profile.get("profile_id", ""))
        if profile_id == DEFAULT_PROFILE_ID:
            QMessageBox.information(self, "不能删除", "内置默认光计算 Profile 不建议删除。")
            return
        if QMessageBox.question(self, "确认删除", f"确定删除 Profile：{profile_id}？") != QMessageBox.StandardButton.Yes:
            return
        delete_profile(profile_id)
        self.refresh_profile_page()

    def generate_and_copy_profile_prompt(self) -> None:
        prompt = generate_profile_prompt(self.profile_direction_input.text())
        QApplication.clipboard().setText(prompt)
        QMessageBox.information(
            self,
            "提示词已复制",
            "提示词已复制。请粘贴到任意大语言模型中，让它生成 PaperRadar Profile YAML，然后将结果粘贴回本软件。",
        )

    def paste_profile_yaml(self) -> None:
        self.profile_yaml_text.setPlainText(QApplication.clipboard().text())

    def validate_profile_input(self) -> None:
        result = validate_profile_yaml(self.profile_yaml_text.toPlainText(), self.profile_direction_input.text())
        self.validated_profile = result.profile if result.ok else None
        self.normalized_profile_yaml = result.normalized_yaml if result.ok else ""
        if result.ok and result.profile:
            groups = result.profile.get("keyword_groups") or {}
            queries = result.profile.get("search_queries") or []
            excludes = result.profile.get("exclude_terms") or []
            journals = result.profile.get("recommended_journals") or []
            warning_text = "\n".join(result.warnings) if result.warnings else "无"
            self.profile_validation_label.setText(
                f"解析成功\n解析模式：{result.parse_mode or '标准 Profile YAML'}\nProfile ID：{result.profile.get('profile_id')}\n显示名称：{result.profile.get('display_name')}\n"
                f"search_queries：{len(queries)}；keyword_groups：{len(groups)}；exclude_terms：{len(excludes)}；recommended_journals：{len(journals)}\n"
                f"潜在问题：{warning_text}"
            )
        else:
            details = "\n".join(result.errors)
            if result.raw_error:
                details += f"\n\n原始解析错误：{result.raw_error}"
            self.profile_validation_label.setText("解析失败：\n" + details)

    def copy_normalized_profile_yaml(self) -> None:
        if not self.validated_profile:
            self.validate_profile_input()
        if not self.validated_profile:
            return
        QApplication.clipboard().setText(self.normalized_profile_yaml or yaml.safe_dump(self.validated_profile, allow_unicode=True, sort_keys=False))
        QMessageBox.information(self, "已复制", "规范化后的 Profile YAML 已复制到剪贴板。")

    def save_validated_profile(self, make_active: bool) -> None:
        if not self.validated_profile:
            self.validate_profile_input()
        if not self.validated_profile:
            return
        path = save_profile(self.validated_profile)
        if make_active:
            set_active_profile(str(self.validated_profile.get("profile_id")))
            self.settings = load_settings()
            self.keyword_filter = KeywordFilter(load_keywords())
        self.refresh_profile_page()
        QMessageBox.information(self, "已保存", f"Profile 已保存到：\n{path}")

    def show_first_run_wizard(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("欢迎使用 PaperRadar")
        box.setText(
            "使用每日雷达或历史调研前，请先确认研究方向 Profile。\n\n"
            "Profile 决定软件会用哪些关键词检索论文、如何判断相关性，以及报告里优先展示哪些结果。\n\n"
            "你可以先使用内置默认方向：光计算；也可以进入“研究方向配置”，创建自己的方向，例如超快光子学、铌酸锂调制器、拓扑光子学等。"
        )
        default_btn = box.addButton("使用默认光计算方向", QMessageBox.ButtonRole.AcceptRole)
        config_btn = box.addButton("去配置研究方向", QMessageBox.ButtonRole.ActionRole)
        box.exec()
        if box.clickedButton() == default_btn:
            ensure_default_profile_available()
            set_active_profile(DEFAULT_PROFILE_ID)
            self.refresh_profile_page()
        elif box.clickedButton() == config_btn:
            self.tabs.setCurrentIndex(2)
            self.profile_direction_input.setFocus()

    def open_report_folder(self) -> None:
        open_folder(REPORTS_DIR)

    def open_selected_link(self) -> None:
        if self.selected_paper and self.selected_paper.url:
            open_url(self.selected_paper.url)

    def _source_type_label(self, source_type: str) -> str:
        return {"arxiv": "预印本论文", "journal_rss": "期刊最新文章", "crossref": "顶刊历史检索"}.get(source_type, source_type or "未知")

    def _setup_tray(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = RadarTrayIcon(self, self.show_main_window, self.run_daily, self.open_report_folder, self.exit_app)
            self.tray.show()

    def show_main_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        if self.allow_exit or not self.tray:
            event.accept()
            return
        event.ignore()
        self.hide()

    def exit_app(self) -> None:
        self.allow_exit = True
        if self.survey_worker and self.survey_worker.isRunning():
            self.survey_worker.request_cancel()
            self.survey_worker.wait(3000)
        if self.daily_worker and self.daily_worker.isRunning():
            self.daily_worker.request_cancel()
            self.daily_worker.wait(3000)
        QApplication.quit()

    def _style_sheet(self) -> str:
        checkmark_path = str((APP_ICON_PATH.parent / "checkmark.svg").resolve()).replace("\\", "/")
        return """
        QWidget { background: #f4f7fb; color: #172033; font-size: 13px; font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", Arial; }
        QLabel { background: transparent; }
        QWidget#pageHeader {
            background: #ffffff;
            border: 1px solid #d9e3ef;
            border-radius: 12px;
        }
        QLabel#pageTitle {
            color: #0f172a;
            font-size: 22px;
            font-weight: 800;
        }
        QLabel#pageSubtitle {
            color: #64748b;
            font-size: 13px;
        }
        QTabWidget::pane {
            background: #f4f7fb;
            border-top: 1px solid #dbe4f0;
        }
        QTabBar {
            background: #eef4fb;
        }
        QTabBar::tab {
            background: transparent;
            color: #64748b;
            padding: 10px 18px;
            margin: 0 2px 0 0;
            border: 0;
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            font-weight: 700;
        }
        QTabBar::tab:selected {
            background: #ffffff;
            color: #0f172a;
            border: 1px solid #d9e3ef;
            border-bottom: 1px solid #ffffff;
        }
        QTabBar::tab:hover:!selected {
            background: #e7eef8;
            color: #1e3a8a;
        }
        QGroupBox, QWidget#paperCard {
            background: #ffffff;
            border: 1px solid #d9e3ef;
            border-radius: 12px;
        }
        QGroupBox {
            margin-top: 14px;
            color: #0f172a;
            font-weight: 800;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 14px;
            padding: 0 8px;
            background: #f4f7fb;
            color: #0f172a;
        }
        QLabel#metricCard {
            background: #f8fbff;
            border: 1px solid #e2eaf5;
            border-radius: 10px;
            color: #334155;
            padding: 8px 12px;
            font-weight: 700;
        }
        QLabel#statusPill {
            color: #1d4ed8;
            background: #eaf2ff;
            border: 1px solid #bfdbfe;
            border-radius: 14px;
            padding: 7px 14px;
            font-weight: 800;
        }
        QLabel#progressStatus {
            color: #1e3a8a;
            font-weight: 700;
        }
        QLabel#progressCounts, QLabel#profileSummary, QLabel#validationCard {
            background: #f8fbff;
            border: 1px solid #e2eaf5;
            border-radius: 10px;
            color: #334155;
            padding: 10px 12px;
        }
        QPushButton {
            background: #ffffff;
            color: #1e3a8a;
            border: 1px solid #c7d7ea;
            border-radius: 10px;
            padding: 9px 16px;
            min-height: 24px;
            font-weight: 800;
        }
        QPushButton:hover {
            background: #f1f6ff;
            border-color: #9db8dc;
        }
        QPushButton:pressed {
            background: #e7effc;
        }
        QPushButton#primaryButton {
            background: #2563eb;
            color: #ffffff;
            border: 1px solid #1d4ed8;
        }
        QPushButton#primaryButton:hover {
            background: #1d4ed8;
        }
        QPushButton#dangerButton {
            background: #ffffff;
            color: #b91c1c;
            border: 1px solid #fecaca;
        }
        QPushButton#dangerButton:hover {
            background: #fff1f2;
            border-color: #fca5a5;
        }
        QPushButton:disabled {
            background: #edf2f7;
            color: #94a3b8;
            border-color: #d8e2ee;
        }
        QLineEdit, QSpinBox, QComboBox, QDateEdit {
            background: #ffffff;
            color: #172033;
            border: 1px solid #cad8e8;
            border-radius: 10px;
            padding: 7px 10px;
            min-height: 26px;
            selection-background-color: #bfdbfe;
        }
        QLineEdit:hover, QSpinBox:hover, QComboBox:hover, QDateEdit:hover {
            border-color: #9fb7d4;
        }
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QDateEdit:focus {
            border: 1px solid #3b82f6;
            background: #fbfdff;
        }
        QSpinBox::up-button, QSpinBox::down-button { width: 0; border: 0; }
        QComboBox, QDateEdit { padding-right: 36px; }
        QComboBox::drop-down, QDateEdit::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 32px;
            border-left: 1px solid #e2e8f0;
            border-top-right-radius: 10px;
            border-bottom-right-radius: 10px;
            background: #f8fafc;
        }
        QComboBox::drop-down:hover, QDateEdit::drop-down:hover {
            background: #eef6ff;
        }
        QComboBox::down-arrow, QDateEdit::down-arrow {
            width: 0;
            height: 0;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #475569;
            margin-right: 10px;
        }
        QComboBox QAbstractItemView {
            background: #ffffff;
            color: #172033;
            border: 1px solid #cbd5e1;
            border-radius: 10px;
            padding: 6px;
            outline: 0;
            selection-background-color: #dbeafe;
            selection-color: #0f172a;
        }
        QCheckBox {
            color: #334155;
            spacing: 8px;
            font-weight: 600;
        }
        QCheckBox::indicator {
            width: 17px;
            height: 17px;
            border-radius: 5px;
            border: 1px solid #b8c8dc;
            background: #ffffff;
        }
        QCheckBox::indicator:hover {
            border-color: #60a5fa;
        }
        QCheckBox::indicator:checked {
            background: #2563eb;
            border-color: #1d4ed8;
            image: url("__CHECKMARK_PATH__");
        }
        QTableWidget {
            background: #ffffff;
            alternate-background-color: #f8fafc;
            gridline-color: #e8eef6;
            border: 1px solid #d9e3ef;
            border-radius: 12px;
            selection-background-color: #dbeafe;
            selection-color: #0f172a;
        }
        QTableWidget::item {
            padding: 8px;
            border: 0;
        }
        QTableWidget::item:selected {
            background: #dbeafe;
            color: #0f172a;
        }
        QHeaderView::section {
            background: #edf4fb;
            color: #26364d;
            border: 0;
            border-right: 1px solid #d9e3ef;
            border-bottom: 1px solid #d9e3ef;
            padding: 11px 8px;
            font-weight: 800;
        }
        QTableCornerButton::section {
            background: #edf4fb;
            border: 0;
            border-bottom: 1px solid #d9e3ef;
            border-right: 1px solid #d9e3ef;
        }
        QProgressBar {
            background: #edf3f9;
            border: 1px solid #d9e3ef;
            border-radius: 9px;
            height: 16px;
            color: #334155;
            text-align: center;
            font-weight: 700;
        }
        QProgressBar::chunk {
            background: #2563eb;
            border-radius: 8px;
        }
        QSplitter::handle {
            background: #e7edf5;
            border-radius: 3px;
            margin: 4px 0;
        }
        QSplitter::handle:hover {
            background: #cbdcf0;
        }
        QScrollBar:vertical {
            background: transparent;
            width: 12px;
            margin: 2px;
        }
        QScrollBar::handle:vertical {
            background: #c6d4e5;
            min-height: 34px;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical:hover { background: #8fb0d5; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: 0; background: transparent; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        QScrollBar:horizontal {
            background: transparent;
            height: 12px;
            margin: 2px;
        }
        QScrollBar::handle:horizontal {
            background: #c6d4e5;
            min-width: 34px;
            border-radius: 6px;
        }
        QScrollBar::handle:horizontal:hover { background: #8fb0d5; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; border: 0; background: transparent; }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
        QLabel#paperTitle {
            color: #0f172a;
            font-size: 18px;
            font-weight: 800;
        }
        QLabel#paperMeta {
            color: #52647a;
            line-height: 1.4;
        }
        QTextEdit {
            background: #ffffff;
            color: #172033;
            border: 1px solid #d9e3ef;
            border-radius: 12px;
            padding: 12px;
        }
        QTextEdit:focus {
            border: 1px solid #93c5fd;
        }
        QDialog#cellPopup {
            background: #ffffff;
            border: 1px solid #bfdbfe;
            border-radius: 14px;
        }
        QLabel#cellPopupTitle {
            color: #1d4ed8;
            font-weight: 800;
            background: transparent;
        }
        QDialog#cellPopup QTextEdit {
            background: #f8fbff;
            border: 1px solid #dbeafe;
            border-radius: 10px;
            padding: 10px;
        }
        """.replace("__CHECKMARK_PATH__", checkmark_path)


