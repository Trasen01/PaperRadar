from __future__ import annotations

import copy
import logging
import threading
import traceback
from datetime import date, datetime, timedelta
from typing import Any

import yaml
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paper_radar.models import Paper
from paper_radar.profile_manager import (
    delete_profile,
    generate_profile_prompt,
    load_active_profile,
    load_all_profiles,
    save_profile,
    set_active_profile,
    validate_profile_yaml,
)
from paper_radar.services import (
    DailySearchService,
    HistoricalSurveyService,
    generate_daily_report_file,
    generate_survey_report_file,
    has_active_profile,
    open_paper_url,
    open_reports_folder,
)
from paper_radar.settings import load_settings
from paper_radar.utils import APP_ICON_ICO_PATH, LOGS_DIR, open_folder

from .components import Badge, Button, Card, EmptyState, ErrorDialog, PageHeader, PaperDetailCard, PaperTable, StatCard, ToggleSwitch, hbox, source_type_label, vbox


class ServiceWorker(QObject):
    progress = Signal(str, object)
    finished = Signal(object)
    failed = Signal(str, str)

    def __init__(self, service: Any) -> None:
        super().__init__()
        self.service = service
        self.stop_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.run(self.stop_event.is_set, lambda kind, payload: self.progress.emit(kind, payload))
            self.finished.emit(result)
        except Exception as exc:
            details = traceback.format_exc()
            logging.exception("Background service failed")
            self.failed.emit(str(exc), details)

    def stop(self) -> None:
        self.stop_event.set()


class Page(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("PageCanvas")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("PageScroll")
        scroll.setWidgetResizable(True)
        canvas = QWidget()
        canvas.setObjectName("PageCanvas")
        self.layout = QVBoxLayout(canvas)
        self.layout.setContentsMargins(28, 24, 28, 24)
        self.layout.setSpacing(16)
        scroll.setWidget(canvas)
        root.addWidget(scroll)


class ResultsMixin:
    all_papers: list[Paper]
    papers: list[Paper]
    table: PaperTable
    detail: PaperDetailCard
    search_input: QLineEdit
    source_filter: QComboBox
    min_score: QComboBox

    def filtered_papers(self) -> list[Paper]:
        q = self.search_input.text().strip().lower()
        source = self.source_filter.currentText()
        min_score = int(self.min_score.currentText())
        out: list[Paper] = []
        for paper in self.all_papers:
            if paper.relevance_score < min_score:
                continue
            if source == "\u9884\u5370\u672c\uff08arXiv\uff09" and paper.source_type != "arxiv":
                continue
            if source == "\u9876\u7ea7\u671f\u520a" and paper.source_type not in {"crossref", "journal_rss"}:
                continue
            haystack = " ".join([paper.title, paper.authors, paper.abstract, paper.journal_or_source, paper.matched_keywords_text]).lower()
            if q and q not in haystack:
                continue
            out.append(paper)
        return out

    def _paper_source_counts(self, papers: list[Paper]) -> dict[str, int]:
        arxiv = sum(1 for paper in papers if paper.source_type == "arxiv")
        top = sum(1 for paper in papers if paper.source_type in {"crossref", "journal_rss"})
        return {"arxiv": arxiv, "top": top}

    def _status_label(self, state: dict[str, Any], name: str) -> str:
        status = str(state.get("status") or "pending")
        raw = int(state.get("raw", 0) or 0)
        stored = int(state.get("stored", 0) or 0)
        failed = int(state.get("failed", 0) or 0)
        reason = str(state.get("reason") or "").strip()
        labels = {
            "disabled": "\u672a\u542f\u7528",
            "pending": "\u7b49\u5f85\u4e2d",
            "success": "\u6210\u529f",
            "partial": "\u90e8\u5206\u6210\u529f",
            "failed": "\u68c0\u7d22\u5931\u8d25",
            "timeout": "\u8d85\u65f6",
            "empty": "\u65e0\u7ed3\u679c",
        }
        label = labels.get(status, status)
        detail = f"{name}\uff1a{label}\uff1b\u6293\u53d6 {raw}\uff0c\u5165\u5e93 {stored}\uff0c\u5931\u8d25 {failed}"
        if reason:
            detail += f"\uff1b\u539f\u56e0\uff1a{reason}"
        return detail

    def _update_source_summary(self, stats: dict[str, Any] | None = None) -> None:
        if not isinstance(stats, dict):
            stats = None
        stats = stats or getattr(self, "last_stats", {}) or {}
        all_counts = self._paper_source_counts(self.all_papers)
        shown_counts = self._paper_source_counts(self.papers)
        failed = int(stats.get("failed", 0) or 0)
        source_status = stats.get("source_status") or getattr(self, "source_status", {}) or {}
        arxiv_state = source_status.get("arxiv", {"enabled": self.arxiv.isChecked() if hasattr(self, "arxiv") else False, "status": "pending", "raw": all_counts["arxiv"], "stored": all_counts["arxiv"], "failed": 0})
        top_state = source_status.get("top", {"enabled": self.top.isChecked() if hasattr(self, "top") else False, "status": "pending", "raw": all_counts["top"], "stored": all_counts["top"], "failed": failed})
        source_line = (
            f"\u5f53\u524d\u663e\u793a {len(self.papers)} \u7bc7\uff1b\u5019\u9009 {len(self.all_papers)} \u7bc7\uff1b"
            f"arXiv \u663e\u793a {shown_counts['arxiv']} / \u5019\u9009 {all_counts['arxiv']}\uff1b"
            f"\u9876\u7ea7\u671f\u520a\u663e\u793a {shown_counts['top']} / \u5019\u9009 {all_counts['top']}\uff1b\u5931\u8d25 {failed}"
        )
        if hasattr(self, "source_summary"):
            self.source_summary.setText(source_line)
        if hasattr(self, "source_detail"):
            self.source_detail.setText(self._status_label(arxiv_state, "arXiv") + "\n" + self._status_label(top_state, "\u9876\u7ea7\u671f\u520a"))
        if hasattr(self, "arxiv_status"):
            self.arxiv_status.setText(self._status_label(arxiv_state, "arXiv"))
        if hasattr(self, "top_status"):
            self.top_status.setText(self._status_label(top_state, "\u9876\u7ea7\u671f\u520a"))

    def refresh_table(self) -> None:
        self.papers = self.filtered_papers()
        self.table.set_papers(self.papers)
        self.detail.set_paper(None)
        self.detail.setVisible(False)
        hidden = max(len(self.all_papers) - len(self.papers), 0)
        why = ""
        if hidden:
            reasons = []
            if int(self.min_score.currentText()) > 0:
                reasons.append(f"\u6700\u4f4e\u5206 {self.min_score.currentText()}")
            if self.source_filter.currentText() != "\u5168\u90e8\u6765\u6e90":
                reasons.append(self.source_filter.currentText())
            if self.search_input.text().strip():
                reasons.append("\u641c\u7d22\u6761\u4ef6")
            why = "\uff1b\u9690\u85cf " + str(hidden) + " \u7bc7\uff08" + "\u3001".join(reasons or ["\u5f53\u524d\u7b5b\u9009"]) + "\uff09"
        self.summary.setText(f"\u5f53\u524d\u663e\u793a {len(self.papers)} \u7bc7\uff0c\u5019\u9009 {len(self.all_papers)} \u7bc7{why}")
        self._update_source_summary()
        if hasattr(self, "empty_state"):
            self.empty_state.setVisible(len(self.papers) == 0)

    def selected_paper(self) -> Paper | None:
        return self.table.current_paper()

    def open_selected(self) -> None:
        paper = self.selected_paper()
        if not paper:
            QMessageBox.information(self, "未选择论文", "请先选择一篇论文。")
            return
        self.open_paper(paper)

    def open_paper(self, paper: Paper | None) -> None:
        if not paper:
            QMessageBox.information(self, "未选择论文", "请先选择一篇论文。")
            return
        if not paper.url:
            QMessageBox.information(self, "链接不可用", "该论文暂无可用链接。")
            return
        try:
            open_paper_url(paper)
        except Exception as exc:
            details = traceback.format_exc()
            logging.exception("Failed to open paper link")
            ErrorDialog(
                "打开失败",
                "无法使用系统默认浏览器打开论文链接。请复制链接后重试，或查看日志。",
                f"链接：{paper.url}\n\n错误：{exc}\n\n{details}",
                self,
                on_logs=lambda: open_folder(LOGS_DIR),
            ).exec()


class TodayPage(Page, ResultsMixin):
    def __init__(self, window: "PaperRadarQtWindow") -> None:
        super().__init__()
        self.window = window
        self.all_papers = []
        self.papers = []
        self.result_title = "\u4eca\u65e5\u8bba\u6587\u5217\u8868"
        self.empty_title = "\u8fd8\u6ca1\u6709\u8bba\u6587\u7ed3\u679c"
        self.empty_body = "\u70b9\u51fb\u201c\u7acb\u5373\u68c0\u67e5\u201d\uff0cPaperRadar \u4f1a\u81ea\u52a8\u68c0\u7d22\u4e0e\u4f60\u7814\u7a76\u65b9\u5411\u76f8\u5173\u7684\u6700\u65b0\u8bba\u6587\u3002"
        self.empty_action_text = "\u7acb\u5373\u68c0\u67e5"
        self.report_button_text = "\u751f\u6210\u4eca\u65e5\u62a5\u544a"
        self.run_btn = Button("\u7acb\u5373\u68c0\u67e5", "primary")
        self.stop_btn = Button("\u505c\u6b62", "secondary")
        self.stop_btn.setEnabled(False)
        self.layout.addWidget(PageHeader("\u4eca\u65e5\u53d1\u73b0", "\u81ea\u52a8\u68c0\u7d22\u4e0e\u4f60\u7814\u7a76\u65b9\u5411\u76f8\u5173\u7684\u6700\u65b0\u8bba\u6587\uff0c\u5e76\u7b5b\u9009\u51fa\u503c\u5f97\u5173\u6ce8\u7684\u5de5\u4f5c\u3002", [self.run_btn, self.stop_btn]))
        self.stats = self._build_stats()
        self.layout.addLayout(self.stats["layout"])
        self._build_tools()
        self._build_results()
        self.run_btn.clicked.connect(self.run_daily)
        self.stop_btn.clicked.connect(self.stop_running)

    def _build_stats(self) -> dict[str, Any]:
        row = QHBoxLayout()
        row.setSpacing(12)
        cards = {
            "last": StatCard("\u4e0a\u6b21\u68c0\u67e5", "\u4ece\u672a", "\u672c\u5730\u65f6\u95f4"),
            "found": StatCard("\u672c\u6b21\u53d1\u73b0", "0", "\u7bc7\u5019\u9009\u8bba\u6587"),
            "high": StatCard("\u503c\u5f97\u5173\u6ce8", "0", "\u7bc7\u9ad8\u76f8\u5173\u8bba\u6587"),
            "status": StatCard("\u8fd0\u884c\u72b6\u6001", "\u5c31\u7eea", "\u6570\u636e\u6e90\u6b63\u5e38"),
        }
        for card in cards.values():
            row.addWidget(card)
        cards["layout"] = row
        return cards

    def _build_tools(self) -> None:
        card = Card("\u68c0\u7d22\u5de5\u5177", "")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.days = QComboBox()
        self.days.addItems(["1", "3", "7", "14", "30"])
        self.days.setCurrentText("7")
        self.min_score = QComboBox()
        self.min_score.addItems(["0", "10", "20", "30", "40", "50", "60", "70", "80", "90"])
        self.min_score.setCurrentText("20")
        self.days.setFixedWidth(126)
        self.min_score.setFixedWidth(126)
        self.arxiv = ToggleSwitch("arXiv", True)
        self.top = ToggleSwitch("顶级期刊", True)
        for label, widget in [("\u6700\u8fd1\u5929\u6570", self.days), ("\u6700\u4f4e\u5206", self.min_score)]:
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(4)
            lab = QLabel(label)
            lab.setObjectName("SmallMuted")
            box_layout.addWidget(lab)
            box_layout.addWidget(widget)
            row.addWidget(box)
        row.addWidget(self.arxiv)
        row.addWidget(self.top)
        row.addStretch(1)
        card.body.addLayout(row)
        self.arxiv_status = QLabel("arXiv\uff1a\u7b49\u5f85\u4e2d\uff1b\u6293\u53d6 0\uff0c\u5165\u5e93 0\uff0c\u5931\u8d25 0")
        self.top_status = QLabel("\u9876\u7ea7\u671f\u520a\uff1a\u7b49\u5f85\u4e2d\uff1b\u6293\u53d6 0\uff0c\u5165\u5e93 0\uff0c\u5931\u8d25 0")
        for label in (self.arxiv_status, self.top_status):
            label.setObjectName("SmallMuted")
            label.setWordWrap(True)
            card.body.addWidget(label)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setVisible(False)
        card.body.addWidget(self.progress)
        self.run_log = QLabel("\u5c31\u7eea")
        self.run_log.setObjectName("Muted")
        self.run_log.setWordWrap(True)
        self.run_log.setVisible(False)
        card.body.addWidget(self.run_log)
        self.layout.addWidget(card)
        self.min_score.currentIndexChanged.connect(self.refresh_table)
        self.arxiv.toggled.connect(lambda _checked=False: self._update_source_summary())
        self.top.toggled.connect(lambda _checked=False: self._update_source_summary())

    def _build_results(self) -> None:
        card = Card(self.result_title)
        actions = QHBoxLayout()
        self.summary = QLabel("\u5f53\u524d\u663e\u793a 0 \u7bc7\uff0c\u5019\u9009 0 \u7bc7")
        self.summary.setObjectName("Muted")
        actions.addWidget(self.summary, 1)
        report = Button(self.report_button_text)
        folder = Button("\u6253\u5f00\u62a5\u544a\u6587\u4ef6\u5939")
        actions.addWidget(report)
        actions.addWidget(folder)
        card.body.addLayout(actions)
        self.source_summary = QLabel("\u5f53\u524d\u663e\u793a 0 \u7bc7\uff1b\u5019\u9009 0 \u7bc7\uff1barXiv \u663e\u793a 0 / \u5019\u9009 0\uff1b\u9876\u7ea7\u671f\u520a\u663e\u793a 0 / \u5019\u9009 0\uff1b\u5931\u8d25 0")
        self.source_summary.setObjectName("SmallMuted")
        self.source_summary.setWordWrap(True)
        self.source_detail = QLabel("arXiv\uff1a\u7b49\u5f85\u4e2d\uff1b\u6293\u53d6 0\uff0c\u5165\u5e93 0\uff0c\u5931\u8d25 0\n\u9876\u7ea7\u671f\u520a\uff1a\u7b49\u5f85\u4e2d\uff1b\u6293\u53d6 0\uff0c\u5165\u5e93 0\uff0c\u5931\u8d25 0")
        self.source_detail.setObjectName("SmallMuted")
        self.source_detail.setWordWrap(True)
        card.body.addWidget(self.source_summary)
        card.body.addWidget(self.source_detail)
        filters = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("\u641c\u7d22\u6807\u9898\u3001\u4f5c\u8005\u3001\u5173\u952e\u8bcd\u3001\u6458\u8981")
        self.source_filter = QComboBox()
        self.source_filter.addItems(["\u5168\u90e8\u6765\u6e90", "\u9884\u5370\u672c\uff08arXiv\uff09", "\u9876\u7ea7\u671f\u520a"])
        clear = Button("\u6e05\u7a7a")
        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.source_filter)
        filters.addWidget(clear)
        card.body.addLayout(filters)
        self.table = PaperTable()
        card.body.addWidget(self.table, 1)
        self.empty_state = EmptyState(self.empty_title, self.empty_body)
        self.empty_action = Button(self.empty_action_text, "primary")
        self.empty_state.body.addWidget(self.empty_action, 0, Qt.AlignCenter)
        card.body.addWidget(self.empty_state)
        self.layout.addWidget(card, 1)
        self.detail = PaperDetailCard()
        self.detail.setVisible(False)
        self.layout.addWidget(self.detail)
        self.search_input.textChanged.connect(self.refresh_table)
        self.source_filter.currentIndexChanged.connect(self.refresh_table)
        clear.clicked.connect(self.clear_filters)
        report.clicked.connect(self.generate_report)
        folder.clicked.connect(open_reports_folder)
        self.empty_action.clicked.connect(self.run_btn.click)
        self.table.itemSelectionChanged.connect(self.show_selected_detail)
        self.table.openRequested.connect(self.open_paper)
        self.detail.openRequested.connect(self.open_paper)
        self.table.cellDoubleClicked.connect(lambda *_: self.open_selected())
        self.refresh_table()

    def clear_filters(self) -> None:
        self.search_input.clear()
        self.source_filter.setCurrentIndex(0)
        self.refresh_table()

    def show_selected_detail(self) -> None:
        paper = self.selected_paper()
        self.detail.set_paper(paper)
        self.detail.setVisible(paper is not None)

    def stop_running(self) -> None:
        self.window.stop_worker()
        self.run_log.setText("正在停止，已获取的结果会保留。")
        self.stats["status"].set("正在停止", "保留当前结果")

    def run_daily(self) -> None:
        if not has_active_profile():
            QMessageBox.information(self, "\u8bf7\u5148\u914d\u7f6e\u7814\u7a76\u65b9\u5411", "\u5f53\u524d\u6ca1\u6709\u53ef\u7528\u7684 Profile\u3002")
            self.window.show_page("profile")
            return
        sources = {"arxiv": self.arxiv.isChecked(), "rss": self.top.isChecked(), "crossref": self.top.isChecked()}
        if not any(sources.values()):
            QMessageBox.information(self, "\u672a\u9009\u62e9\u6570\u636e\u6e90", "\u8bf7\u81f3\u5c11\u9009\u62e9\u4e00\u4e2a\u6570\u636e\u6e90\u3002")
            return
        self.last_stats = {}
        self.source_status = {}
        self.run_btn.setEnabled(False); self.stop_btn.setEnabled(True); self.progress.setVisible(True); self.run_log.setVisible(True); self.stats["status"].set("\u68c0\u7d22\u4e2d", "\u6b63\u5728\u66f4\u65b0\u7ed3\u679c")
        service = DailySearchService(int(self.days.currentText()), sources, load_settings())
        self.window.start_worker(service, self.on_progress, self.on_finished, self.on_failed)

    def on_progress(self, kind: str, payload: Any) -> None:
        if isinstance(payload, dict):
            total = max(int(payload.get("total", 1)), 1)
            completed = int(payload.get("completed", 0))
            self.progress.setMaximum(total)
            self.progress.setValue(completed)
            source = payload.get("source") or payload.get("journal") or "\u6b63\u5728\u5904\u7406"
            query = payload.get("query") or ""
            first_line = f"{source} {query}".strip()
            second_line = (
                f"\u8fdb\u5ea6\uff1a{completed} / {total}\uff1b"
                f"\u5df2\u53d1\u73b0\uff1a{payload.get('found', 0)}\uff1b"
                f"\u547d\u4e2d\uff1a{payload.get('matched', 0)}\uff1b"
                f"\u5931\u8d25\uff1a{payload.get('failed', 0)}"
            )
            self.last_stats = payload
            if payload.get("source_status"):
                self.source_status = payload.get("source_status")
            self.run_log.setText(first_line + chr(10) + second_line)
            self._update_source_summary(payload)
            if kind == "batch" and payload.get("papers"):
                self.all_papers = list(payload["papers"])
                self.refresh_table()

    def on_finished(self, result: Any) -> None:
        self.last_stats = result.stats
        self.source_status = result.stats.get("source_status", {})
        self.all_papers = result.papers
        self.refresh_table()
        self.stats["last"].set(datetime.now().strftime("%H:%M"), date.today().isoformat())
        self.stats["found"].set(str(result.stats.get("raw", len(result.papers))), "\u672c\u6b21\u6293\u53d6")
        self.stats["high"].set(str(sum(1 for p in result.papers if p.relevance_score >= 60)), "\u7bc7\u9ad8\u76f8\u5173\u8bba\u6587")
        self.stats["status"].set("\u5df2\u5b8c\u6210", f"\u663e\u793a {len(self.papers)}\uff1b\u5931\u8d25 {result.stats.get('failed', 0)}")
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        failed = int(result.stats.get("failed", 0) or 0)
        status_bits = []
        for name, key in [("arXiv", "arxiv"), ("\u9876\u7ea7\u671f\u520a", "top")]:
            state = (result.stats.get("source_status") or {}).get(key, {})
            if state:
                status_bits.append(self._status_label(state, name))
        self.run_log.setVisible(True)
        self.run_log.setText(f"\u5df2\u5b8c\u6210\uff1a\u5019\u9009 {len(result.papers)} \u7bc7\uff1b\u663e\u793a {len(self.papers)} \u7bc7\uff1b\u5931\u8d25 {failed}\n" + "\n".join(status_bits))

    def on_failed(self, message: str, details: str = "") -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.run_log.setVisible(True)
        if self.all_papers:
            self.refresh_table()
            self.stats["status"].set("统计异常", "结果已获取并保留")
            body = "检索过程中出现内部统计错误，部分结果已经获取并保留。请查看详情或日志。"
            self.run_log.setText(f"结果已获取：候选 {len(self.all_papers)} 篇；当前显示 {len(self.papers)} 篇。统计摘要异常：{message}")
        else:
            self.stats["status"].set("检索失败", "未获取到可展示结果")
            body = "检索过程中出现错误，当前没有获取到可展示结果。请查看详情或日志。"
            self.run_log.setText(f"检索失败：{message}")
        ErrorDialog(
            "检索失败",
            body,
            details or message,
            self,
            on_logs=lambda: open_folder(LOGS_DIR),
        ).exec()

    def generate_report(self) -> None:
        if not self.papers:
            QMessageBox.information(self, "\u6682\u65e0\u53ef\u751f\u6210\u7684\u62a5\u544a", "\u8bf7\u5148\u8fd0\u884c\u68c0\u7d22\u6216\u653e\u5bbd\u7b5b\u9009\u6761\u4ef6\u3002")
            return
        path = generate_daily_report_file(self.papers)
        QMessageBox.information(self, "\u62a5\u544a\u5df2\u751f\u6210", f"\u62a5\u544a\u5df2\u4fdd\u5b58\u5230\uff1a\n{path}")


class SurveyPage(TodayPage):
    def __init__(self, window: "PaperRadarQtWindow") -> None:
        Page.__init__(self)
        self.window = window
        self.all_papers = []
        self.papers = []
        self.result_title = "\u5386\u53f2\u8c03\u7814\u7ed3\u679c"
        self.empty_title = "\u8fd8\u6ca1\u6709\u5386\u53f2\u8c03\u7814\u7ed3\u679c"
        self.empty_body = "\u8bbe\u7f6e\u8c03\u7814\u8303\u56f4\u540e\uff0c\u70b9\u51fb\u201c\u5f00\u59cb\u8c03\u7814\u201d\u8fdb\u884c\u7cfb\u7edf\u68c0\u7d22\u3002"
        self.empty_action_text = "\u5f00\u59cb\u8c03\u7814"
        self.report_button_text = "\u751f\u6210\u8c03\u7814\u62a5\u544a"
        self.run_btn = Button("\u5f00\u59cb\u8c03\u7814", "primary")
        self.stop_btn = Button("\u505c\u6b62", "secondary"); self.stop_btn.setEnabled(False)
        self.layout.addWidget(PageHeader("\u5386\u53f2\u8c03\u7814", "\u9762\u5411\u66f4\u957f\u65f6\u95f4\u8303\u56f4\u8fdb\u884c\u7cfb\u7edf\u68c0\u7d22\uff0c\u9002\u5408\u5f00\u9898\u3001\u7efc\u8ff0\u548c\u65b9\u5411\u6478\u5e95\u3002", [self.run_btn, self.stop_btn]))
        self.stats = self._build_stats(); self.layout.addLayout(self.stats["layout"])
        self._build_survey_tools(); self._build_results()
        self.run_btn.clicked.connect(self.run_survey); self.stop_btn.clicked.connect(self.stop_running)

    def _build_stats(self) -> dict[str, Any]:
        row = QHBoxLayout()
        row.setSpacing(12)
        cards = {
            "last": StatCard("\u8c03\u7814\u8303\u56f4", "365 \u5929", "\u9ed8\u8ba4\u65f6\u95f4\u7a97\u53e3"),
            "found": StatCard("\u672c\u6b21\u53d1\u73b0", "0", "\u7bc7\u5386\u53f2\u5019\u9009"),
            "high": StatCard("\u5df2\u5165\u5e93", "0", "\u7bc7\u8c03\u7814\u7ed3\u679c"),
            "status": StatCard("\u8fd0\u884c\u72b6\u6001", "\u5c31\u7eea", "\u540c\u65e5\u8c03\u7814\u81ea\u52a8\u590d\u7528\u7f13\u5b58"),
        }
        for card in cards.values():
            row.addWidget(card)
        cards["layout"] = row
        return cards

    def _build_survey_tools(self) -> None:
        card = Card("\u8c03\u7814\u4efb\u52a1", "\u914d\u7f6e\u957f\u5468\u671f\u68c0\u7d22\u8303\u56f4\uff1b\u540c\u4e00\u5929\u76f8\u540c\u8c03\u7814\u4f1a\u81ea\u52a8\u590d\u7528\u7f13\u5b58\uff0c\u65e0\u9700\u624b\u52a8\u5ffd\u7565\u7f13\u5b58\u3002")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.task_name = QLineEdit("\u5f53\u524d\u65b9\u5411\u5386\u53f2\u8c03\u7814")
        self.range = QComboBox()
        self.range.addItems(["\u6700\u8fd1 90 \u5929", "\u6700\u8fd1 365 \u5929", "\u6700\u8fd1 3 \u5e74"])
        self.range.setCurrentIndex(1)
        self.min_score = QComboBox()
        self.min_score.addItems(["0", "10", "20", "30", "40", "50", "60", "70", "80", "90"])
        self.min_score.setCurrentText("20")
        self.range.setFixedWidth(150)
        self.min_score.setFixedWidth(126)
        self.arxiv = ToggleSwitch("arXiv", False)
        self.top = ToggleSwitch("顶级期刊", True)
        for label, widget, stretch in [
            ("\u4efb\u52a1\u540d\u79f0", self.task_name, 2),
            ("\u65f6\u95f4\u8303\u56f4", self.range, 1),
            ("\u6700\u4f4e\u5206", self.min_score, 0),
        ]:
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(6)
            lab = QLabel(label)
            lab.setObjectName("SmallMuted")
            box_layout.addWidget(lab)
            box_layout.addWidget(widget)
            row.addWidget(box, stretch)
        row.addWidget(self.arxiv)
        row.addWidget(self.top)
        card.body.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        card.body.addWidget(self.progress)
        self.run_log = QLabel("\u5c31\u7eea\uff1b\u4eca\u65e5\u5df2\u7f13\u5b58\u7684\u76f8\u540c\u8c03\u7814\u4f1a\u81ea\u52a8\u590d\u7528\u3002")
        self.run_log.setObjectName("Muted")
        self.run_log.setWordWrap(True)
        self.run_log.setVisible(False)
        card.body.addWidget(self.run_log)
        self.layout.addWidget(card)
        self.min_score.currentIndexChanged.connect(self.refresh_table)
        self.range.currentIndexChanged.connect(lambda: self.stats["last"].set(self.range.currentText().replace("\u6700\u8fd1 ", ""), "\u5f53\u524d\u8c03\u7814\u8303\u56f4"))

    def _dates(self) -> tuple[date, date]:
        today = date.today(); text = self.range.currentText()
        if "90" in text: return today - timedelta(days=90), today
        if "3" in text: return today - timedelta(days=365*3), today
        return today - timedelta(days=365), today

    def run_survey(self) -> None:
        if not has_active_profile():
            QMessageBox.information(self, "\u8bf7\u5148\u914d\u7f6e\u7814\u7a76\u65b9\u5411", "\u5f53\u524d\u6ca1\u6709\u53ef\u7528\u7684 Profile\u3002")
            self.window.show_page("profile"); return
        sources = {"arxiv": self.arxiv.isChecked(), "rss": self.top.isChecked(), "crossref": self.top.isChecked()}
        if not any(sources.values()):
            QMessageBox.information(self, "\u672a\u9009\u62e9\u6570\u636e\u6e90", "\u8bf7\u81f3\u5c11\u9009\u62e9\u4e00\u4e2a\u6570\u636e\u6e90\u3002"); return
        from_date, until_date = self._dates()
        self.last_stats = {}
        self.source_status = {}
        self.run_btn.setEnabled(False); self.stop_btn.setEnabled(True); self.progress.setVisible(True); self.run_log.setVisible(True); self.stats["last"].set(self.range.currentText().replace("\u6700\u8fd1 ", ""), "\u5f53\u524d\u8c03\u7814\u8303\u56f4"); self.stats["status"].set("\u8c03\u7814\u4e2d", "\u6b63\u5728\u7cfb\u7edf\u68c0\u7d22")
        service = HistoricalSurveyService(self.task_name.text(), from_date, until_date, sources, load_settings())
        self.window.start_worker(service, self.on_progress, self.on_finished, self.on_failed)

    def on_finished(self, result: Any) -> None:
        self.last_stats = result.stats
        self.source_status = result.stats.get("source_status", {})
        self.all_papers = result.papers
        self.refresh_table()
        self.stats["last"].set(self.range.currentText().replace("\u6700\u8fd1 ", ""), "\u672c\u6b21\u8c03\u7814\u8303\u56f4")
        self.stats["found"].set(str(result.stats.get("raw", len(result.papers))), "\u672c\u6b21\u6293\u53d6")
        self.stats["high"].set(str(len(result.papers)), "\u7bc7\u5df2\u5165\u5e93")
        self.stats["status"].set("\u5df2\u5b8c\u6210", f"\u663e\u793a {len(self.papers)}\uff1b\u5931\u8d25 {result.stats.get('failed', 0)}")
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        failed = int(result.stats.get("failed", 0) or 0)
        status_bits = []
        for name, key in [("arXiv", "arxiv"), ("\u9876\u7ea7\u671f\u520a", "top")]:
            state = (result.stats.get("source_status") or {}).get(key, {})
            if state:
                status_bits.append(self._status_label(state, name))
        self.run_log.setVisible(True)
        self.run_log.setText(f"\u5df2\u5b8c\u6210\uff1a\u5386\u53f2\u5019\u9009 {len(result.papers)} \u7bc7\uff1b\u663e\u793a {len(self.papers)} \u7bc7\uff1b\u5931\u8d25 {failed}\n" + "\n".join(status_bits))

    def generate_report(self) -> None:
        if not self.papers:
            QMessageBox.information(self, "\u6682\u65e0\u53ef\u751f\u6210\u7684\u62a5\u544a", "\u8bf7\u5148\u8fd0\u884c\u8c03\u7814\u6216\u653e\u5bbd\u7b5b\u9009\u6761\u4ef6\u3002"); return
        from_date, until_date = self._dates()
        path = generate_survey_report_file(self.papers, self.task_name.text(), from_date, until_date)
        QMessageBox.information(self, "\u62a5\u544a\u5df2\u751f\u6210", f"\u62a5\u544a\u5df2\u4fdd\u5b58\u5230\uff1a\n{path}")


class ProfilePage(Page):
    def __init__(self, window: "PaperRadarQtWindow") -> None:
        super().__init__()
        self.window = window
        self.validated_profile: dict[str, Any] | None = None
        self.keyword_profile: dict[str, Any] | None = None
        self.keyword_rows: list[tuple[str, str, int]] = []
        self.layout.addWidget(PageHeader("\u7814\u7a76\u65b9\u5411", "\u7ba1\u7406 Profile\u3001\u5173\u952e\u8bcd\u548c AI \u8f85\u52a9\u5bfc\u5165\uff0c\u51b3\u5b9a PaperRadar \u5982\u4f55\u7406\u89e3\u4f60\u7684\u7814\u7a76\u5174\u8da3\u3002"))
        self._build_profile_summary()
        self._build_profile_table()
        self._build_keyword_workbench()
        self._build_importer()
        self.refresh()

    def _build_profile_summary(self) -> None:
        self.summary_card = Card("\u5f53\u524d\u7814\u7a76\u65b9\u5411")
        shell = QFrame()
        shell.setObjectName("SummaryPanel")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(16, 14, 16, 14)
        shell_layout.setSpacing(10)
        top = QHBoxLayout()
        self.profile_name = QLabel("--")
        self.profile_name.setObjectName("ProfileTitle")
        self.profile_badge = Badge("\u5f53\u524d\u4f7f\u7528\u4e2d", "blue")
        top.addWidget(self.profile_name)
        top.addWidget(self.profile_badge)
        top.addStretch(1)
        shell_layout.addLayout(top)
        metrics = QHBoxLayout()
        self.profile_id_label = QLabel("Profile ID\uff1a--")
        self.profile_queries_label = QLabel("\u68c0\u7d22\u5f0f\uff1a0")
        self.profile_groups_label = QLabel("\u5173\u952e\u8bcd\u7ec4\uff1a0")
        for item in [self.profile_id_label, self.profile_queries_label, self.profile_groups_label]:
            item.setObjectName("Muted")
            metrics.addWidget(item)
        metrics.addStretch(1)
        shell_layout.addLayout(metrics)
        self.profile_description = QLabel("")
        self.profile_description.setObjectName("Muted")
        self.profile_description.setWordWrap(True)
        shell_layout.addWidget(self.profile_description)
        self.summary_card.body.addWidget(shell)
        row = QHBoxLayout()
        self.set_active_btn = Button("\u8bbe\u4e3a\u5f53\u524d\u65b9\u5411", "primary")
        self.copy_btn = Button("\u590d\u5236\u5f53\u524d Profile")
        self.delete_btn = Button("\u5220\u9664 Profile", "danger")
        row.addWidget(self.set_active_btn)
        row.addWidget(self.copy_btn)
        row.addStretch(1)
        row.addWidget(self.delete_btn)
        self.summary_card.body.addLayout(row)
        self.layout.addWidget(self.summary_card)
        self.set_active_btn.clicked.connect(self.set_selected_active)
        self.copy_btn.clicked.connect(self.copy_current)
        self.delete_btn.clicked.connect(self.delete_selected)

    def _build_profile_table(self) -> None:
        card = Card("Profile \u5217\u8868")
        self.profile_table = QTableWidget(0, 6)
        self.profile_table.setHorizontalHeaderLabels(["\u663e\u793a\u540d\u79f0", "Profile ID", "\u63cf\u8ff0", "\u68c0\u7d22\u5f0f", "\u5173\u952e\u8bcd\u7ec4", "\u5f53\u524d"])
        self.profile_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.profile_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.profile_table.verticalHeader().setVisible(False)
        self.profile_table.setAlternatingRowColors(True)
        self.profile_table.setShowGrid(False)
        self.profile_table.setMinimumHeight(220)
        self.profile_table.setMaximumHeight(310)
        self.profile_table.verticalHeader().setDefaultSectionSize(42)
        self.profile_table.verticalHeader().setMinimumSectionSize(42)
        self.profile_table.setColumnWidth(0, 160)
        self.profile_table.setColumnWidth(1, 190)
        self.profile_table.setColumnWidth(2, 380)
        self.profile_table.setColumnWidth(3, 90)
        self.profile_table.setColumnWidth(4, 100)
        self.profile_table.setColumnWidth(5, 118)
        card.body.addWidget(self.profile_table)
        self.layout.addWidget(card)
        self.profile_table.itemSelectionChanged.connect(self.load_selected_profile_keywords)

    def _build_keyword_workbench(self) -> None:
        card = Card("\u5173\u952e\u8bcd\u5de5\u4f5c\u53f0", "\u4ece Profile \u5217\u8868\u9009\u62e9\u7814\u7a76\u65b9\u5411\uff0c\u7ba1\u7406\u5176\u5173\u952e\u8bcd\u3002\u4fee\u6539\u540e\u9700\u70b9\u51fb\u4fdd\u5b58\u5168\u90e8\u5173\u952e\u8bcd\u624d\u4f1a\u751f\u6548\u3002")
        body = QHBoxLayout()
        self.keyword_table = QTableWidget(0, 4)
        self.keyword_table.setHorizontalHeaderLabels(["\u5206\u7ec4", "\u6743\u91cd", "\u5173\u952e\u8bcd", "\u64cd\u4f5c"])
        self.keyword_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.keyword_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.keyword_table.verticalHeader().setVisible(False)
        self.keyword_table.setAlternatingRowColors(True)
        self.keyword_table.setShowGrid(False)
        self.keyword_table.setMinimumHeight(280)
        self.keyword_table.verticalHeader().setDefaultSectionSize(42)
        self.keyword_table.verticalHeader().setMinimumSectionSize(42)
        self.keyword_table.setColumnWidth(0, 170)
        self.keyword_table.setColumnWidth(1, 112)
        self.keyword_table.setColumnWidth(2, 360)
        self.keyword_table.setColumnWidth(3, 104)
        self.keyword_table.itemSelectionChanged.connect(self.on_keyword_selected)
        body.addWidget(self.keyword_table, 3)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        edit = Card("\u7f16\u8f91\u5173\u952e\u8bcd")
        self.keyword_group = QLineEdit()
        self.keyword_priority = QComboBox()
        self.keyword_priority.addItems(["high", "medium", "low", "exclude"])
        self.keyword_term = QLineEdit()
        for label, widget in [("\u5206\u7ec4", self.keyword_group), ("\u6743\u91cd", self.keyword_priority), ("\u5173\u952e\u8bcd", self.keyword_term)]:
            row = QHBoxLayout()
            lab = QLabel(label)
            lab.setFixedWidth(72)
            row.addWidget(lab)
            row.addWidget(widget, 1)
            edit.body.addLayout(row)
        edit_actions = QHBoxLayout()
        save_edit = Button("\u4fdd\u5b58\u4fee\u6539", "primary")
        delete_kw = Button("\u5220\u9664\u5173\u952e\u8bcd", "danger")
        edit_actions.addWidget(save_edit)
        edit_actions.addWidget(delete_kw)
        edit_actions.addStretch(1)
        edit.body.addLayout(edit_actions)
        save_edit.clicked.connect(self.update_keyword)
        delete_kw.clicked.connect(self.delete_keyword)
        right_layout.addWidget(edit)

        add = Card("\u65b0\u589e\u5173\u952e\u8bcd")
        self.new_keyword_group = QLineEdit("core")
        self.new_keyword_priority = QComboBox()
        self.new_keyword_priority.addItems(["high", "medium", "low", "exclude"])
        self.new_keyword_term = QLineEdit()
        self.new_keyword_term.setPlaceholderText("English keyword or phrase")
        for label, widget in [("\u5206\u7ec4", self.new_keyword_group), ("\u6743\u91cd", self.new_keyword_priority), ("\u5173\u952e\u8bcd", self.new_keyword_term)]:
            row = QHBoxLayout()
            lab = QLabel(label)
            lab.setFixedWidth(72)
            row.addWidget(lab)
            row.addWidget(widget, 1)
            add.body.addLayout(row)
        add_actions = QHBoxLayout()
        add_btn = Button("\u6dfb\u52a0\u5173\u952e\u8bcd")
        save_all = Button("\u4fdd\u5b58\u5168\u90e8\u5173\u952e\u8bcd", "primary")
        add_actions.addWidget(add_btn)
        add_actions.addWidget(save_all)
        add_actions.addStretch(1)
        add.body.addLayout(add_actions)
        add_btn.clicked.connect(self.add_keyword)
        save_all.clicked.connect(self.save_keyword_profile)
        right_layout.addWidget(add)

        self.keyword_status = QLabel("\u4ece\u5de6\u4fa7\u9009\u62e9\u4e00\u4e2a\u5173\u952e\u8bcd\u8fdb\u884c\u7f16\u8f91\u3002")
        self.keyword_status.setObjectName("Muted")
        self.keyword_status.setWordWrap(True)
        right_layout.addWidget(self.keyword_status)
        body.addWidget(right, 2)
        card.body.addLayout(body)
        self.layout.addWidget(card)

    def _build_importer(self) -> None:
        card = Card("AI \u8f85\u52a9\u751f\u6210 Profile / Profile \u6279\u91cf\u5bfc\u5165", "\u8f93\u5165\u7814\u7a76\u65b9\u5411\uff0c\u751f\u6210\u53ef\u7c98\u8d34\u5230 AI \u7684\u63d0\u793a\u8bcd\uff1b\u7c98\u8d34\u6216\u624b\u5199 Profile YAML \u540e\u5148\u89e3\u6790\u9884\u89c8\uff0c\u518d\u4fdd\u5b58\u3002")
        row = QHBoxLayout()
        self.direction = QLineEdit()
        self.direction.setPlaceholderText("\u4f8b\uff1a\u5149\u8ba1\u7b97\u3001\u5149\u5b50\u795e\u7ecf\u7f51\u7edc")
        prompt_btn = Button("\u751f\u6210\u5e76\u590d\u5236 AI \u63d0\u793a\u8bcd", "primary")
        row.addWidget(self.direction, 1)
        row.addWidget(prompt_btn)
        card.body.addLayout(row)
        self.yaml_text = QPlainTextEdit()
        self.import_box = self.yaml_text
        self.yaml_text.setPlaceholderText("profile_version: 1\nprofile_id: ...\nsearch_queries:\n  - ...")
        self.yaml_text.setMinimumHeight(180)
        card.body.addWidget(self.yaml_text)
        actions = QHBoxLayout()
        parse_btn = Button("\u89e3\u6790\u5e76\u9884\u89c8", "primary")
        save_btn = Button("\u4fdd\u5b58\u5e76\u8bbe\u4e3a\u5f53\u524d\u65b9\u5411", "primary")
        actions.addWidget(parse_btn)
        actions.addWidget(save_btn)
        actions.addStretch(1)
        card.body.addLayout(actions)
        self.validation = QLabel("\u5c1a\u672a\u89e3\u6790")
        self.validation.setObjectName("Muted")
        self.validation.setWordWrap(True)
        card.body.addWidget(self.validation)
        self.layout.addWidget(card)
        prompt_btn.clicked.connect(self.copy_prompt)
        parse_btn.clicked.connect(self.validate_input)
        save_btn.clicked.connect(self.save_validated)

    def refresh(self) -> None:
        active = load_active_profile()
        active_id = active.get("profile_id") if active else ""
        if active:
            groups = active.get("keyword_groups") or {}
            queries = active.get("search_queries") or []
            self.profile_name.setText(str(active.get("display_name") or active_id))
            self.profile_id_label.setText(f"Profile ID\uff1a{active_id}")
            self.profile_queries_label.setText(f"\u68c0\u7d22\u5f0f\uff1a{len(queries)}")
            self.profile_groups_label.setText(f"\u5173\u952e\u8bcd\u7ec4\uff1a{len(groups)}")
            self.profile_description.setText(str(active.get("description") or "\u6682\u65e0\u63cf\u8ff0"))
            self.profile_badge.setVisible(True)
        else:
            self.profile_name.setText("\u672a\u9009\u62e9\u7814\u7a76\u65b9\u5411")
            self.profile_id_label.setText("Profile ID\uff1a--")
            self.profile_queries_label.setText("\u68c0\u7d22\u5f0f\uff1a0")
            self.profile_groups_label.setText("\u5173\u952e\u8bcd\u7ec4\uff1a0")
            self.profile_description.setText("\u5f53\u524d\u6ca1\u6709\u6fc0\u6d3b\u7684\u7814\u7a76\u65b9\u5411\u3002")
            self.profile_badge.setVisible(False)
        profiles = load_all_profiles()
        self.profile_table.setRowCount(len(profiles))
        active_row = -1
        for row, profile in enumerate(profiles):
            groups = profile.get("keyword_groups") or {}
            queries = profile.get("search_queries") or []
            is_active = profile.get("profile_id") == active_id
            description = str(profile.get("description", ""))
            short_description = description if len(description) <= 48 else description[:48] + "..."
            vals = [profile.get("display_name", ""), profile.get("profile_id", ""), short_description, str(len(queries)), str(len(groups))]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(str(val))
                item.setToolTip(description if col == 2 else str(val))
                if col >= 3:
                    item.setTextAlignment(Qt.AlignCenter)
                self.profile_table.setItem(row, col, item)
            if is_active:
                badge = Badge("\u5f53\u524d", "blue")
                wrap = QWidget()
                layout = QHBoxLayout(wrap)
                layout.setContentsMargins(6, 5, 6, 5)
                layout.addWidget(badge, 0, Qt.AlignVCenter | Qt.AlignCenter)
                layout.addStretch(1)
                self.profile_table.setCellWidget(row, 5, wrap)
                active_row = row
            else:
                self.profile_table.setItem(row, 5, QTableWidgetItem(""))
        self.profile_table.resizeRowsToContents()
        if active_row >= 0 and self.profile_table.currentRow() < 0:
            self.profile_table.setCurrentCell(active_row, 0)
        self.load_selected_profile_keywords()

    def selected_profile(self) -> dict[str, Any] | None:
        profiles = load_all_profiles()
        row = self.profile_table.currentRow()
        return profiles[row] if 0 <= row < len(profiles) else load_active_profile()

    def load_selected_profile_keywords(self) -> None:
        if not hasattr(self, "keyword_table"):
            return
        profile = self.selected_profile()
        self.keyword_profile = copy.deepcopy(profile) if profile else None
        self.populate_keywords()

    def populate_keywords(self) -> None:
        self.keyword_table.setRowCount(0)
        self.keyword_rows = []
        profile = self.keyword_profile
        if not profile:
            self.keyword_status.setText("\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a Profile\u3002")
            return
        rows: list[tuple[str, str, str, int]] = []
        groups = profile.get("keyword_groups") or {}
        if isinstance(groups, dict):
            for group_name, group in groups.items():
                if not isinstance(group, dict):
                    continue
                priority = str(group.get("priority") or "medium")
                terms = group.get("terms") or []
                for index, term in enumerate(terms):
                    rows.append((str(group_name), priority, str(term), index))
                    self.keyword_rows.append(("group", str(group_name), index))
        excludes = profile.get("exclude_terms") or []
        if isinstance(excludes, list):
            for index, term in enumerate(excludes):
                rows.append(("exclude", "exclude", str(term), index))
                self.keyword_rows.append(("exclude", "exclude", index))
        self.keyword_table.setRowCount(len(rows))
        for row, (group, priority, term, _index) in enumerate(rows):
            group_badge = Badge(group, "gray")
            priority_tone = {"high": "green", "medium": "blue", "low": "gray", "exclude": "red"}.get(priority, "gray")
            priority_badge = Badge(priority, priority_tone)
            for col, badge in [(0, group_badge), (1, priority_badge)]:
                wrap = QWidget()
                layout = QHBoxLayout(wrap)
                layout.setContentsMargins(6, 5, 6, 5)
                layout.addWidget(badge, 0, Qt.AlignVCenter | Qt.AlignLeft)
                layout.addStretch(1)
                self.keyword_table.setCellWidget(row, col, wrap)
                item = QTableWidgetItem("")
                item.setToolTip(badge.text())
                self.keyword_table.setItem(row, col, item)
            item = QTableWidgetItem(term)
            item.setToolTip(term)
            self.keyword_table.setItem(row, 2, item)
            edit_btn = Button("\u7f16\u8f91")
            edit_btn.setProperty("variant", "ghost")
            edit_btn.clicked.connect(lambda _=False, r=row: self.keyword_table.setCurrentCell(r, 0))
            self.keyword_table.setCellWidget(row, 3, edit_btn)
        self.keyword_table.resizeRowsToContents()
        self.keyword_status.setText(f"\u6b63\u5728\u7f16\u8f91\uff1a{profile.get('display_name') or profile.get('profile_id')}\uff1b\u5173\u952e\u8bcd {len(rows)} \u4e2a")

    def on_keyword_selected(self) -> None:
        row = self.keyword_table.currentRow()
        if row < 0 or row >= len(self.keyword_rows):
            return
        kind, group_name, index = self.keyword_rows[row]
        term = ""
        priority = "medium"
        if kind == "exclude":
            terms = (self.keyword_profile or {}).get("exclude_terms") or []
            term = str(terms[index]) if 0 <= index < len(terms) else ""
            priority = "exclude"
        else:
            group = ((self.keyword_profile or {}).get("keyword_groups") or {}).get(group_name) or {}
            terms = group.get("terms") or []
            term = str(terms[index]) if 0 <= index < len(terms) else ""
            priority = str(group.get("priority") or "medium")
        self.keyword_group.setText(group_name)
        self.keyword_priority.setCurrentText(priority)
        self.keyword_term.setText(term)

    def _remove_keyword_row(self, row: int) -> str:
        if not self.keyword_profile or row < 0 or row >= len(self.keyword_rows):
            return ""
        kind, group_name, index = self.keyword_rows[row]
        if kind == "exclude":
            terms = self.keyword_profile.get("exclude_terms") or []
            return str(terms.pop(index)) if 0 <= index < len(terms) else ""
        groups = self.keyword_profile.get("keyword_groups") or {}
        group = groups.get(group_name) or {}
        terms = group.get("terms") or []
        removed = str(terms.pop(index)) if 0 <= index < len(terms) else ""
        if not terms:
            groups.pop(group_name, None)
        return removed

    def _add_keyword_to_profile(self, group_name: str, priority: str, term: str) -> bool:
        if not self.keyword_profile or not term:
            return False
        if priority == "exclude" or group_name == "exclude":
            terms = self.keyword_profile.setdefault("exclude_terms", [])
            if term.lower() not in {str(item).lower() for item in terms}:
                terms.append(term)
                return True
            return False
        groups = self.keyword_profile.setdefault("keyword_groups", {})
        group = groups.setdefault(group_name or "core", {"priority": priority or "medium", "terms": []})
        group["priority"] = priority or group.get("priority") or "medium"
        terms = group.setdefault("terms", [])
        if term.lower() not in {str(item).lower() for item in terms}:
            terms.append(term)
            return True
        return False

    def update_keyword(self) -> None:
        row = self.keyword_table.currentRow()
        term = self.keyword_term.text().strip()
        if row < 0 or not term:
            self.keyword_status.setText("\u8bf7\u5148\u9009\u62e9\u5173\u952e\u8bcd\uff0c\u5e76\u786e\u4fdd\u5173\u952e\u8bcd\u4e0d\u4e3a\u7a7a\u3002")
            return
        self._remove_keyword_row(row)
        self._add_keyword_to_profile(self.keyword_group.text().strip() or "core", self.keyword_priority.currentText(), term)
        self.populate_keywords()
        self.keyword_status.setText(f"\u5df2\u66f4\u65b0\u5173\u952e\u8bcd\uff1a{term}\uff1b\u8bf7\u4fdd\u5b58\u5168\u90e8\u5173\u952e\u8bcd\u4ee5\u751f\u6548\u3002")

    def delete_keyword(self) -> None:
        row = self.keyword_table.currentRow()
        if row < 0:
            self.keyword_status.setText("\u8bf7\u5148\u9009\u62e9\u8981\u5220\u9664\u7684\u5173\u952e\u8bcd\u3002")
            return
        term = self.keyword_term.text().strip() or "\u672a\u77e5"
        if QMessageBox.question(self, "\u786e\u8ba4\u5220\u9664\u5173\u952e\u8bcd", f"\u786e\u5b9a\u5220\u9664\u5173\u952e\u8bcd\uff1a{term}\uff1f\n\n\u5220\u9664\u540e\u9700\u70b9\u51fb\u4fdd\u5b58\u5168\u90e8\u5173\u952e\u8bcd\u624d\u4f1a\u5199\u5165 Profile\u3002") != QMessageBox.Yes:
            return
        removed = self._remove_keyword_row(row)
        self.populate_keywords()
        self.keyword_status.setText(f"\u5df2\u5220\u9664\uff1a{removed}\uff1b\u8bf7\u4fdd\u5b58\u5168\u90e8\u5173\u952e\u8bcd\u4ee5\u751f\u6548\u3002")

    def add_keyword(self) -> None:
        term = self.new_keyword_term.text().strip()
        if not term:
            self.keyword_status.setText("\u8bf7\u8f93\u5165\u8981\u65b0\u589e\u7684\u5173\u952e\u8bcd\u3002")
            return
        added = self._add_keyword_to_profile(self.new_keyword_group.text().strip() or "core", self.new_keyword_priority.currentText(), term)
        self.new_keyword_term.clear()
        self.populate_keywords()
        self.keyword_status.setText(f"\u5df2\u65b0\u589e\u5173\u952e\u8bcd\uff1a{term}\uff1b\u8bf7\u4fdd\u5b58\u5168\u90e8\u5173\u952e\u8bcd\u4ee5\u751f\u6548\u3002" if added else f"\u5173\u952e\u8bcd\u5df2\u5b58\u5728\uff1a{term}")

    def save_keyword_profile(self) -> None:
        if not self.keyword_profile:
            return
        path = save_profile(self.keyword_profile)
        self.refresh()
        QMessageBox.information(self, "\u5173\u952e\u8bcd\u5df2\u4fdd\u5b58", f"\u5173\u952e\u8bcd\u5df2\u5199\u5165 Profile\uff1a\n{path}")

    def set_selected_active(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        set_active_profile(str(profile.get("profile_id")))
        self.refresh()
        QMessageBox.information(self, "\u5df2\u5207\u6362", "\u5f53\u524d\u7814\u7a76\u65b9\u5411\u5df2\u66f4\u65b0\u3002")

    def copy_current(self) -> None:
        profile = load_active_profile()
        if not profile:
            return
        QGuiApplication.clipboard().setText(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False))
        QMessageBox.information(self, "\u5df2\u590d\u5236", "Profile YAML \u5df2\u590d\u5236\u5230\u526a\u8d34\u677f\u3002")

    def delete_selected(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        profile_id = str(profile.get("profile_id"))
        if QMessageBox.question(self, "\u786e\u8ba4\u5220\u9664", f"\u786e\u5b9a\u5220\u9664 Profile\uff1a{profile_id}\uff1f") != QMessageBox.Yes:
            return
        delete_profile(profile_id)
        self.refresh()

    def copy_prompt(self) -> None:
        QGuiApplication.clipboard().setText(generate_profile_prompt(self.direction.text()))
        QMessageBox.information(self, "\u63d0\u793a\u8bcd\u5df2\u590d\u5236", "\u8bf7\u7c98\u8d34\u5230 AI \u5de5\u5177\u4e2d\u751f\u6210 Profile YAML\u3002")

    def validate_input(self) -> None:
        result = validate_profile_yaml(self.yaml_text.toPlainText(), self.direction.text())
        self.validated_profile = result.profile if result.ok else None
        if result.ok and result.profile:
            groups = result.profile.get("keyword_groups") or {}
            queries = result.profile.get("search_queries") or []
            exists = str(result.profile.get("profile_id")) in {str(p.get("profile_id")) for p in load_all_profiles()}
            cover = "\u662f" if exists else "\u5426"
            self.validation.setText(f"\u89e3\u6790\u6210\u529f\uff1a{result.profile.get('display_name')}\nProfile ID\uff1a{result.profile.get('profile_id')}\uff1b\u68c0\u7d22\u5f0f\uff1a{len(queries)}\uff1b\u5173\u952e\u8bcd\u7ec4\uff1a{len(groups)}\uff1b\u8986\u76d6\u73b0\u6709\uff1a{cover}")
        else:
            self.validation.setText("\u89e3\u6790\u5931\u8d25\uff1a\n" + "\n".join(result.errors))

    def save_validated(self) -> None:
        if not self.validated_profile:
            self.validate_input()
        if not self.validated_profile:
            return
        profile_id = str(self.validated_profile.get("profile_id"))
        exists = profile_id in {str(p.get("profile_id")) for p in load_all_profiles()}
        cover = "\u5c06\u8986\u76d6\u73b0\u6709 Profile\u3002" if exists else ""
        if QMessageBox.question(self, "\u786e\u8ba4\u4fdd\u5b58", f"{cover}\n\u4fdd\u5b58\u5e76\u8bbe\u4e3a\u5f53\u524d\u65b9\u5411\u540e\uff0c\u4eca\u65e5\u53d1\u73b0\u548c\u5386\u53f2\u8c03\u7814\u5c06\u4f7f\u7528\u65b0 Profile\u3002\u662f\u5426\u7ee7\u7eed\uff1f") != QMessageBox.Yes:
            return
        path = save_profile(self.validated_profile)
        set_active_profile(profile_id)
        self.refresh()
        QMessageBox.information(self, "\u5df2\u4fdd\u5b58", f"Profile \u5df2\u4fdd\u5b58\u5230\uff1a\n{path}")


class PaperRadarQtWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PaperRadar")
        icon = QIcon(str(APP_ICON_ICO_PATH))
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1440, 900); self.setMinimumSize(1180, 720)
        self.thread: QThread | None = None; self.worker: ServiceWorker | None = None
        root = QWidget(); root.setObjectName("AppRoot"); self.setCentralWidget(root)
        layout = QHBoxLayout(root); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        self.sidebar = self._build_sidebar(); layout.addWidget(self.sidebar)
        self.stack = QStackedWidget(); layout.addWidget(self.stack, 1)
        self.pages = {"daily": TodayPage(self), "survey": SurveyPage(self), "profile": ProfilePage(self)}
        for page in self.pages.values(): self.stack.addWidget(page)
        self.show_page("daily")

    def _build_sidebar(self) -> QFrame:
        side=QFrame(); side.setObjectName("Sidebar"); side.setFixedWidth(252); layout=QVBoxLayout(side); layout.setContentsMargins(18,18,18,18); layout.setSpacing(10)
        title=QLabel("PaperRadar"); title.setObjectName("BrandTitle"); sub=QLabel("\u6587\u732e\u96f7\u8fbe"); sub.setObjectName("BrandSubTitle"); layout.addWidget(title); layout.addWidget(sub); layout.addSpacing(16)
        self.nav={}
        for key,text in [("daily","\u4eca\u65e5\u53d1\u73b0"),("survey","\u5386\u53f2\u8c03\u7814"),("profile","\u7814\u7a76\u65b9\u5411")]:
            btn=Button(text); btn.setObjectName("NavButton"); btn.clicked.connect(lambda _=False,k=key:self.show_page(k)); layout.addWidget(btn); self.nav[key]=btn
        layout.addStretch(1); mode=Card("\u672c\u5730\u6a21\u5f0f", "Profile\u3001\u6570\u636e\u5e93\u548c\u62a5\u544a\u5747\u4fdd\u5b58\u5728\u672c\u673a\u3002"); layout.addWidget(mode)
        return side

    def show_page(self, key: str) -> None:
        self.stack.setCurrentWidget(self.pages[key])
        for nav_key, btn in self.nav.items():
            btn.setProperty("active", nav_key == key); btn.style().unpolish(btn); btn.style().polish(btn)
        if key == "profile": self.pages["profile"].refresh()

    def start_worker(self, service: Any, progress_cb, finished_cb, failed_cb) -> None:
        self.stop_worker(wait=False)
        self.thread = QThread(self); self.worker = ServiceWorker(service); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run); self.worker.progress.connect(progress_cb); self.worker.finished.connect(finished_cb); self.worker.failed.connect(failed_cb)
        self.worker.finished.connect(self.thread.quit); self.worker.failed.connect(self.thread.quit); self.thread.finished.connect(self.thread.deleteLater); self.thread.start()

    def stop_worker(self, wait: bool = False) -> None:
        if self.worker: self.worker.stop()
        if wait and self.thread: self.thread.quit(); self.thread.wait(3000)

    def closeEvent(self, event) -> None:
        self.stop_worker(wait=True); super().closeEvent(event)
