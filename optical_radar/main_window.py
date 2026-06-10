from __future__ import annotations

import logging
import traceback
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QDate, QSettings, QThread, Signal, Qt
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
            queries = build_search_queries_from_keywords(load_keywords(), max_queries=max_queries)
            top_journals = [j for j in load_sources().get("top_journals", []) if j.get("crossref_enabled")]
            total_steps = (len(top_journals) * len(queries) if self.sources.get("crossref") else 0)
            if self.sources.get("arxiv"):
                total_steps += 1
            if self.sources.get("rss"):
                total_steps += 1
            completed = 0
            logger.info("SURVEY_START name=%s from=%s until=%s total_steps=%s sources=%s", self.task_name, self.from_date, self.until_date, total_steps, self.sources)
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
                self._handle_batch(rss.papers, all_seen, stats, completed, total_steps, "RSS 每日监控", "RSS")

            if self.sources.get("crossref"):
                client = CrossrefClient(timeout=timeout, rows=rows_per_query, sleep_seconds=delay, max_retries=max_retries, retry_delay_seconds=retry_delay)
                for journal in top_journals:
                    if self.cancel_requested:
                        break
                    issns = journal.get("issn") or []
                    if not issns:
                        completed += len(queries)
                        stats["failed"] += len(queries)
                        continue
                    for query in queries:
                        if self.cancel_requested:
                            break
                        cache_key = ("crossref", str(journal.get("name")), query, self.from_date.isoformat(), self.until_date.isoformat())
                        cached = False
                        if not self.ignore_cache and self.db.is_query_cached(*cache_key, cache_hours=cache_hours):
                            cached = True
                            items: list[dict[str, Any]] = []
                        else:
                            try:
                                items = client._query(journal, issns, query, self.from_date, self.until_date)
                                self.db.mark_query_cache(*cache_key, result_count=len(items), status="ok")
                                stats["success"] += 1
                            except Exception as exc:
                                items = []
                                stats["failed"] += 1
                                stats["failed_query_count"] += 1
                                if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                                    stats["timeouts"] += 1
                                self.db.mark_query_cache(*cache_key, result_count=0, status=f"failed:{exc}")
                                logger.warning("SURVEY_QUERY_FAILED source_type=crossref journal=%s query=%s timeout=%s error=%s", journal.get("name"), query, timeout, exc)
                        batch = [client._item_to_paper(journal, item) for item in items]
                        completed += 1
                        if cached:
                            stats["cached"] += 1
                        self._handle_batch(batch, all_seen, stats, completed, total_steps, str(journal.get("name")), query, cached=cached)

            if self.cancel_requested:
                status = "stopped"
            elif stats["failed"]:
                status = "partial_completed"
            else:
                status = "completed"
            stats["status"] = status
            logger.info("SURVEY_DONE status=%s stats=%s", status, dict(stats))
            self.finished_ok.emit(dict(stats))
        except Exception as exc:
            logger.error("Survey failed: %s\n%s", exc, traceback.format_exc())
            self.failed.emit(str(exc))

    def _handle_batch(self, batch: list[Paper], all_seen: list[Paper], stats: Counter, completed: int, total: int, journal: str, query: str, cached: bool = False) -> None:
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
            "cached": cached,
            "cancel_requested": self.cancel_requested,
        }
        logger.info("SURVEY_BATCH %s", progress)
        self.batch_results_ready.emit(scored, progress)
        self.progress_updated.emit(progress)


class MainWindow(QMainWindow):
    def __init__(self, first_run_needed: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("PaperRadar / 文献雷达")
        self.resize(1200, 780)
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
        self.normalized_profile_yaml = ""
        self.allow_exit = False
        self.tray: RadarTrayIcon | None = None
        self.validated_profile: dict[str, Any] | None = None

        self._build_ui()
        self._setup_tray()
        self.refresh_profile_page()
        if first_run_needed:
            self.show_first_run_wizard()

    def _build_ui(self) -> None:
        self.setStyleSheet(self._style_sheet())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_daily_tab(), "每日雷达")
        self.tabs.addTab(self._build_survey_tab(), "历史调研")
        self.tabs.addTab(self._build_profile_tab(), "研究方向配置")
        self.setCentralWidget(self.tabs)

    def _build_daily_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        status = QGroupBox("状态")
        status_layout = QHBoxLayout(status)
        self.daily_last_label = QLabel("上次检查：从未")
        self.daily_found_label = QLabel("本次发现：0")
        self.daily_high_label = QLabel("高相关：0")
        self.daily_skim_label = QLabel("值得扫读：0")
        self.daily_status_label = QLabel("就绪")
        self.daily_status_label.setObjectName("statusPill")
        for widget in [self.daily_last_label, self.daily_found_label, self.daily_high_label, self.daily_skim_label, self.daily_status_label]:
            status_layout.addWidget(widget)
        status_layout.addStretch(1)
        root.addWidget(status)

        settings = QGroupBox("检索设置")
        row = QHBoxLayout(settings)
        self.daily_days = QComboBox()
        self.daily_days.addItems(["1", "3", "7", "14", "30"])
        self.daily_days.setCurrentText(str(min(int(self.settings.get("days_back", 7)), 30)))
        self.daily_min_score = QSpinBox()
        self.daily_min_score.setRange(20, 100)
        self.daily_min_score.setValue(20)
        self.daily_arxiv = QCheckBox("arXiv")
        self.daily_arxiv.setChecked(True)
        self.daily_rss = QCheckBox("RSS 每日监控")
        self.daily_rss.setChecked(True)
        self.daily_crossref = QCheckBox("Crossref 近期检索")
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
        self.daily_run_btn = QPushButton("立即检查")
        self.daily_stop_btn = QPushButton("停止")
        self.daily_stop_btn.setEnabled(False)
        self.daily_report_btn = QPushButton("生成今日报告")
        self.daily_open_reports_btn = QPushButton("打开报告文件夹")
        for button in [self.daily_run_btn, self.daily_stop_btn, self.daily_report_btn, self.daily_open_reports_btn]:
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

        self.daily_table, self.daily_detail, self.daily_open_link_btn = self._make_results_area()
        root.addWidget(self.daily_table_splitter)

        self.daily_run_btn.clicked.connect(self.run_daily)
        self.daily_stop_btn.clicked.connect(self.stop_daily)
        self.daily_report_btn.clicked.connect(self.generate_daily_report)
        self.daily_open_reports_btn.clicked.connect(self.open_report_folder)
        self.daily_table.itemSelectionChanged.connect(lambda: self.on_selection_changed(self.daily_table, self.daily_papers))
        self.daily_table.cellClicked.connect(lambda row, col: self.on_table_cell_clicked(self.daily_table, row, col))
        self.daily_min_score.valueChanged.connect(lambda _: self.refresh_daily_display())
        return page

    def _build_survey_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        settings = QGroupBox("调研设置")
        row = QHBoxLayout(settings)
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
        self.survey_crossref = QCheckBox("Crossref 顶刊历史检索")
        self.survey_crossref.setChecked(True)
        self.survey_arxiv = QCheckBox("arXiv")
        self.survey_arxiv.setToolTip("arXiv 历史检索可能较慢，如仅需顶刊调研，可只选择 Crossref 顶刊历史检索。")
        self.survey_rss = QCheckBox("RSS 每日监控")
        self.survey_ignore_cache = QCheckBox("忽略缓存，重新检索")
        source_row.addWidget(self.survey_crossref)
        source_row.addWidget(self.survey_arxiv)
        source_row.addWidget(self.survey_rss)
        source_row.addWidget(QLabel("期刊集合：顶级期刊"))
        source_row.addWidget(self.survey_ignore_cache)
        source_row.addStretch(1)
        root.addWidget(source_box)

        actions = QHBoxLayout()
        self.survey_run_btn = QPushButton("开始调研")
        self.survey_stop_btn = QPushButton("停止")
        self.survey_stop_btn.setEnabled(False)
        self.survey_report_btn = QPushButton("生成调研报告")
        self.survey_open_reports_btn = QPushButton("打开报告文件夹")
        for button in [self.survey_run_btn, self.survey_stop_btn, self.survey_report_btn, self.survey_open_reports_btn]:
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

        progress_box = QGroupBox("进度")
        progress_layout = QVBoxLayout(progress_box)
        self.survey_progress = QProgressBar()
        self.survey_status = QLabel("就绪")
        self.survey_counts = QLabel("进度：0 / 0；已发现：0；去重后：0；命中：0；已显示：0；成功：0；失败：0；超时：0")
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
        self.survey_range.currentTextChanged.connect(self._sync_survey_date_controls)
        self._sync_survey_date_controls()
        self.survey_table.itemSelectionChanged.connect(lambda: self.on_selection_changed(self.survey_table, self.survey_papers))
        self.survey_table.cellClicked.connect(lambda row, col: self.on_table_cell_clicked(self.survey_table, row, col))
        self.survey_min_score.valueChanged.connect(lambda _: self.refresh_survey_display())
        return page

    def _build_profile_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        status = QGroupBox("当前 Profile")
        status_layout = QVBoxLayout(status)
        self.profile_status_label = QLabel("")
        self.profile_status_label.setWordWrap(True)
        status_layout.addWidget(self.profile_status_label)
        status_actions = QHBoxLayout()
        self.profile_set_active_btn = QPushButton("设为当前方向")
        self.profile_copy_btn = QPushButton("复制当前 Profile")
        self.profile_export_btn = QPushButton("导出 Profile")
        self.profile_delete_btn = QPushButton("删除 Profile")
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
        self.profile_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.profile_table.verticalHeader().setDefaultSectionSize(44)
        self.profile_table.setMinimumHeight(178)
        root.addWidget(self.profile_table)

        prompt_box = QGroupBox("AI 提示词生成")
        prompt_layout = QHBoxLayout(prompt_box)
        self.profile_direction_input = QLineEdit()
        self.profile_direction_input.setPlaceholderText("输入研究方向，例如：超快光子学")
        self.profile_generate_prompt_btn = QPushButton("生成并复制 AI 提示词")
        prompt_layout.addWidget(QLabel("研究方向"))
        prompt_layout.addWidget(self.profile_direction_input)
        prompt_layout.addWidget(self.profile_generate_prompt_btn)
        root.addWidget(prompt_box)

        import_box = QGroupBox("Profile 粘贴导入")
        import_layout = QVBoxLayout(import_box)
        self.profile_yaml_text = QTextEdit()
        self.profile_yaml_text.setPlaceholderText("在这里粘贴外部 AI 生成的 PaperRadar Profile YAML")
        import_layout.addWidget(self.profile_yaml_text)
        import_actions = QHBoxLayout()
        self.profile_paste_btn = QPushButton("粘贴剪贴板内容")
        self.profile_validate_btn = QPushButton("智能解析并预览")
        self.profile_save_active_btn = QPushButton("保存并设为当前方向")
        for button in [self.profile_paste_btn, self.profile_validate_btn, self.profile_save_active_btn]:
            import_actions.addWidget(button)
        import_actions.addStretch(1)
        import_layout.addLayout(import_actions)
        self.profile_validation_label = QLabel("尚未校验")
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
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(42)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(0, 80)
        table.setColumnWidth(1, 150)
        table.setColumnWidth(2, 110)
        table.setColumnWidth(3, 280)
        table.setColumnWidth(4, 220)
        table.setColumnWidth(5, 110)
        table.setColumnWidth(6, 120)
        table.setColumnWidth(7, 220)
        table.setColumnWidth(8, 220)
        self._restore_table_widths(table, prefix)
        header.sectionResized.connect(lambda *_: self._save_table_widths(table, prefix))
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
            self.survey_status.setText("正在启动；arXiv 历史检索可能较慢，如仅需顶刊调研，可只选择 Crossref。")
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
            f"成功：{progress.get('success', 0)}；失败：{progress.get('failed', 0)}；超时：{progress.get('timeouts', 0)}"
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
                paper.url,
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
                if col == 8 and paper.url:
                    font = QFont(item.font())
                    font.setUnderline(True)
                    item.setFont(font)
                    item.setForeground(QBrush(QColor("#2563eb")))
                    item.setToolTip("点击打开链接")
                table.setItem(row, col, item)
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.SortOrder.DescendingOrder)

    def on_table_cell_clicked(self, table: QTableWidget, row: int, col: int) -> None:
        item = table.item(row, col)
        if not item:
            return
        text = item.text()
        if not text:
            return
        key = (id(table), row, col)
        if self.cell_popup and self.cell_popup.isVisible() and self.cell_popup_key == key:
            self.cell_popup.close()
            self.cell_popup = None
            self.cell_popup_key = None
            return
        if self.cell_popup:
            self.cell_popup.close()
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
            "使用 PaperRadar 前，需要先配置研究方向 Profile。\n\n"
            "你可以使用系统内置默认方向：光计算；也可以创建自己的研究方向，例如铌酸锂调制器、拓扑光子学、超导量子比特等。\n\n"
            "软件会根据当前 Profile 进行文献检索、关键词匹配、相关性评分和报告生成。"
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
        return {"arxiv": "arXiv", "journal_rss": "RSS 每日监控", "crossref": "顶刊历史检索"}.get(source_type, source_type or "未知")

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
        QWidget { background: #f3f6fa; color: #263241; font-size: 13px; }
        QTabWidget::pane, QGroupBox, QWidget#paperCard { background: #ffffff; border: 1px solid #d8e0ea; border-radius: 8px; }
        QGroupBox { margin-top: 8px; font-weight: 700; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; background: #ffffff; }
        QPushButton { background: #2563eb; color: white; border: 1px solid #1d4ed8; border-radius: 8px; padding: 8px 14px; font-weight: 600; }
        QPushButton:disabled { background: #e5e7eb; color: #94a3b8; border-color: #cbd5e1; }
        QLineEdit, QSpinBox, QComboBox, QDateEdit { background: #ffffff; color: #263241; border: 1px solid #cbd5e1; border-radius: 7px; padding: 6px 8px; min-height: 22px; }
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QDateEdit:focus { border-color: #60a5fa; }
        QSpinBox::up-button, QSpinBox::down-button { width: 0; border: 0; }
        QComboBox { padding-right: 34px; }
        QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 30px; border-left: 1px solid #dbe3ee; border-top-right-radius: 7px; border-bottom-right-radius: 7px; background: #f1f5f9; }
        QComboBox::drop-down:hover { background: #e8f1ff; }
        QComboBox::down-arrow { width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #475569; margin-right: 9px; }
        QComboBox QAbstractItemView { background: #ffffff; color: #263241; border: 1px solid #cbd5e1; border-radius: 8px; padding: 4px; outline: 0; selection-background-color: #dbeafe; selection-color: #111827; }
        QDateEdit::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 30px; border-left: 1px solid #dbe3ee; border-top-right-radius: 7px; border-bottom-right-radius: 7px; background: #f1f5f9; }
        QDateEdit::drop-down:hover { background: #e8f1ff; }
        QDateEdit::down-arrow { width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #475569; margin-right: 9px; }
        QCheckBox { spacing: 8px; }
        QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #cbd5e1; background: #ffffff; }
        QCheckBox::indicator:checked { background: #2563eb; border-color: #1d4ed8; image: url("__CHECKMARK_PATH__"); }
        QLabel#statusPill { color: #1d4ed8; background: #eaf2ff; border: 1px solid #bfdbfe; border-radius: 12px; padding: 5px 12px; font-weight: 600; }
        QTableWidget { background: #ffffff; alternate-background-color: #f8fafc; gridline-color: #e5eaf0; border: 1px solid #d8e0ea; border-radius: 8px; selection-background-color: #dbeafe; }
        QHeaderView::section { background: #eef3f8; color: #334155; border: 0; border-right: 1px solid #d8e0ea; border-bottom: 1px solid #d8e0ea; padding: 9px 8px; font-weight: 700; }
        QScrollBar:vertical { background: #eef3f8; width: 12px; margin: 2px; border-radius: 6px; }
        QScrollBar::handle:vertical { background: #c7d4e3; min-height: 32px; border-radius: 6px; }
        QScrollBar::handle:vertical:hover { background: #93b3d8; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: 0; background: transparent; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        QScrollBar:horizontal { background: #eef3f8; height: 12px; margin: 2px; border-radius: 6px; }
        QScrollBar::handle:horizontal { background: #c7d4e3; min-width: 32px; border-radius: 6px; }
        QScrollBar::handle:horizontal:hover { background: #93b3d8; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; border: 0; background: transparent; }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
        QLabel#paperTitle { color: #111827; font-size: 18px; font-weight: 700; }
        QLabel#paperMeta { color: #64748b; }
        QTextEdit { background: #ffffff; color: #263241; border: 1px solid #d8e0ea; border-radius: 8px; padding: 10px; }
        QDialog#cellPopup { background: #ffffff; border: 1px solid #bfdbfe; border-radius: 12px; }
        QLabel#cellPopupTitle { color: #1d4ed8; font-weight: 700; background: transparent; }
        QDialog#cellPopup QTextEdit { background: #f8fafc; border: 1px solid #dbe3ee; border-radius: 8px; padding: 10px; }
        """.replace("__CHECKMARK_PATH__", checkmark_path)

