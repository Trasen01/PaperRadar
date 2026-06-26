from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, Signal, QSize, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QHeaderView,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paper_radar.models import Paper
from paper_radar.utils import format_date_only


def vbox(widget: QWidget, margins=(0, 0, 0, 0), spacing: int = 10) -> QVBoxLayout:
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def hbox(widget: QWidget, margins=(0, 0, 0, 0), spacing: int = 10) -> QHBoxLayout:
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


class Button(QPushButton):
    def __init__(self, text: str, kind: str = "secondary", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        names = {"primary": "PrimaryButton", "secondary": "SecondaryButton", "danger": "DangerButton"}
        self.setObjectName(names.get(kind, "SecondaryButton"))


class ToggleSwitch(QPushButton):
    def __init__(self, label: str, checked: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self.setCheckable(True)
        super().setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(36)
        self.setFixedWidth(184 if len(label) >= 4 else 134)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def setChecked(self, checked: bool) -> None:  # type: ignore[override]
        super().setChecked(bool(checked))
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(184 if len(self.label) >= 4 else 134, 36)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        checked = super().isChecked()
        track_color = QColor("#2563EB" if checked else "#D7E0EA")
        if not enabled:
            track_color = QColor("#E4EAF2")
        if self.underMouse() and enabled:
            track_color = QColor("#1D4ED8" if checked else "#CBD8EA")
        track = QRectF(2, 7, 38, 22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 11, 11)
        knob_x = 21 if checked else 5
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(knob_x, 10, 16, 16))
        text_color = QColor("#344054" if enabled else "#98A2B3")
        painter.setPen(text_color)
        state = "已启用" if checked else "未启用"
        painter.drawText(QRectF(48, 0, self.width() - 50, self.height()), Qt.AlignVCenter | Qt.AlignLeft, f"{self.label}：{state}")

class ErrorDialog(QDialog):
    def __init__(self, title: str, body: str, details: str, parent: QWidget | None = None, on_logs=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(620)
        self.setObjectName("ModernDialog")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        body_label = QLabel(body)
        body_label.setObjectName("Muted")
        body_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(body_label)
        self.details = QPlainTextEdit(details)
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(150)
        layout.addWidget(self.details)
        buttons = QHBoxLayout()
        logs = Button("\u67e5\u770b\u65e5\u5fd7")
        copy = Button("\u590d\u5236\u9519\u8bef\u4fe1\u606f")
        ok = Button("\u786e\u5b9a", "primary")
        buttons.addWidget(logs)
        buttons.addWidget(copy)
        buttons.addStretch(1)
        buttons.addWidget(ok)
        layout.addLayout(buttons)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(details))
        if on_logs:
            logs.clicked.connect(on_logs)
        else:
            logs.setEnabled(False)
        ok.clicked.connect(self.accept)


class Badge(QLabel):
    def __init__(self, text: str, tone: str = "gray", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self.setProperty("tone", tone)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(24)
        self.setMinimumWidth(self._min_width(text))
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

    @staticmethod
    def _min_width(text: str) -> int:
        value = str(text or "")
        if value in {"当前", "high", "low"}:
            return 52
        if value in {"arXiv", "medium"}:
            return 72
        if value in {"顶级期刊", "Nature", "Nature Comm."}:
            return 96
        return min(max(len(value) * 10 + 26, 56), 160)


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.body = vbox(self, (16, 14, 16, 14), 10)
        if title:
            label = QLabel(title)
            label.setObjectName("SectionTitle")
            self.body.addWidget(label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            sub.setWordWrap(True)
            self.body.addWidget(sub)


class PageHeader(QFrame):
    def __init__(self, title: str, subtitle: str, actions: Iterable[QPushButton] = (), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HeaderCard")
        layout = hbox(self, (18, 14, 18, 14), 14)
        copy = QWidget()
        copy_layout = vbox(copy, (0, 0, 0, 0), 6)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSubtitle")
        subtitle_label.setWordWrap(True)
        copy_layout.addWidget(title_label)
        copy_layout.addWidget(subtitle_label)
        layout.addWidget(copy, 1)
        for action in actions:
            layout.addWidget(action)


class StatCard(QFrame):
    def __init__(self, label: str, value: str = "0", hint: str = "", tone: str = "blue", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MetricCard")
        layout = vbox(self, (14, 10, 14, 10), 4)
        self.label = QLabel(label)
        self.label.setObjectName("MetricLabel")
        self.value = QLabel(value)
        self.value.setObjectName("MetricValue")
        self.hint = QLabel(hint)
        self.hint.setObjectName("SmallMuted")
        self.hint.setWordWrap(True)
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        layout.addWidget(self.hint)
        self.setMinimumHeight(84)
        self.setMaximumHeight(98)

    def set(self, value: str, hint: str | None = None) -> None:
        self.value.setText(value)
        if hint is not None:
            self.hint.setText(hint)


class EmptyState(QFrame):
    def __init__(self, title: str, body: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyPanel")
        self.body = vbox(self, (28, 26, 28, 26), 10)
        layout = self.body
        t = QLabel(title)
        t.setObjectName("SectionTitle")
        b = QLabel(body)
        b.setObjectName("Muted")
        b.setWordWrap(True)
        layout.addWidget(t)
        layout.addWidget(b)


def normalize_badge_text(text: object) -> str:
    value = str(text or "").strip()
    for token in ("|", "\uff1a", ":"):
        if value.endswith(token):
            value = value[: -len(token)].strip()
    replacements = {
        "Nature Communication": "Nature Comm.",
        "Nature Communications": "Nature Comm.",
        "\u9884\u5370\u672c\uff08arXiv\uff09": "arXiv",
        "arXiv:": "arXiv",
        "arXiv\uff1a": "arXiv",
        "journal_rss": "\u9876\u7ea7\u671f\u520a",
        "crossref": "\u9876\u7ea7\u671f\u520a",
    }
    return replacements.get(value, value or "\u672a\u77e5")


def compact_authors(authors: str, limit: int = 3) -> str:
    parts = [part.strip() for part in (authors or "").replace(";", ",").split(",") if part.strip()]
    if len(parts) <= limit:
        return authors or "\u672a\u77e5"
    return ", ".join(parts[:limit]) + " \u7b49"


def compact_keywords(keywords: str, limit: int = 4) -> str:
    parts = [part.strip() for part in (keywords or "").replace(";", ",").split(",") if part.strip()]
    if len(parts) <= limit:
        return keywords or ""
    return ", ".join(parts[:limit]) + " ..."


def source_type_label(value: str) -> str:
    return {"arxiv": "arXiv", "crossref": "\u9876\u7ea7\u671f\u520a", "journal_rss": "\u9876\u7ea7\u671f\u520a"}.get(value or "", normalize_badge_text(value))


class PaperTable(QTableWidget):
    openRequested = Signal(object)
    COLUMNS = ["\u5206\u6570", "\u6765\u6e90", "\u6807\u9898", "\u4f5c\u8005", "\u53d1\u5e03\u65e5\u671f", "\u547d\u4e2d\u5173\u952e\u8bcd", "\u94fe\u63a5"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(self.COLUMNS), parent)
        self.papers: list[Paper] = []
        self.setHorizontalHeaderLabels(self.COLUMNS)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(False)
        self.setShowGrid(False)
        self.setMinimumHeight(430)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.verticalHeader().setDefaultSectionSize(42)
        self.verticalHeader().setMinimumSectionSize(42)
        self.horizontalHeader().setMinimumSectionSize(64)
        for col in (0, 1, 3, 4, 5, 6):
            self.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.setColumnWidth(0, 70)
        self.setColumnWidth(1, 140)
        self.setColumnWidth(3, 190)
        self.setColumnWidth(4, 110)
        self.setColumnWidth(5, 190)
        self.setColumnWidth(6, 96)

    def set_papers(self, papers: list[Paper]) -> None:
        self.papers = papers
        self.setRowCount(len(papers))
        for row, paper in enumerate(papers):
            self.setRowHeight(row, 42)
            self._set_badge(row, 0, str(int(paper.relevance_score)), self._score_tone(paper.relevance_score))
            source_label = "arXiv" if paper.source_type == "arxiv" else normalize_badge_text(paper.journal_or_source or "\u9876\u7ea7\u671f\u520a")
            self._set_badge(row, 1, source_label, "blue" if paper.source_type == "arxiv" else "green")
            for col, value in [
                (2, paper.title),
                (3, compact_authors(paper.authors)),
                (4, format_date_only(paper.published_date)),
                (5, compact_keywords(paper.matched_keywords_text)),
            ]:
                item = QTableWidgetItem(value)
                if col == 2:
                    tip = (paper.title or "\u672a\u547d\u540d\u8bba\u6587") + ("\\n\u53cc\u51fb\u6253\u5f00\u8bba\u6587\u94fe\u63a5" if paper.url else "\\n\u8be5\u8bba\u6587\u6682\u65e0\u53ef\u7528\u94fe\u63a5")
                    item.setToolTip(tip)
                    if paper.url:
                        item.setForeground(QColor("#1D4ED8"))
                else:
                    item.setToolTip(value)
                if col == 4:
                    item.setTextAlignment(Qt.AlignCenter)
                self.setItem(row, col, item)
            action = Button("\u6253\u5f00" if paper.url else "\u65e0\u94fe\u63a5", "secondary")
            action.setObjectName("TableActionButton")
            action.setStyleSheet("min-width: 68px; max-width: 68px; min-height: 28px; max-height: 28px; padding: 0px 8px; border-radius: 8px;")
            action.setEnabled(bool(paper.url))
            action.setFixedSize(68, 28)
            action.setToolTip("\u6253\u5f00\u8bba\u6587\u94fe\u63a5" if paper.url else "\u8be5\u8bba\u6587\u6682\u65e0\u53ef\u7528\u94fe\u63a5")
            action.clicked.connect(lambda _checked=False, p=paper: self.openRequested.emit(p))
            wrap = QWidget()
            layout = QHBoxLayout(wrap)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addStretch(1)
            layout.addWidget(action, 0, Qt.AlignCenter)
            layout.addStretch(1)
            self.setCellWidget(row, 6, wrap)
            self.setItem(row, 6, QTableWidgetItem(""))

    def _set_badge(self, row: int, col: int, text: str, tone: str) -> None:
        clean = normalize_badge_text(text)
        badge = Badge(clean, tone)
        badge.setToolTip(clean)
        wrap = QWidget()
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(0)
        layout.addWidget(badge, 0, Qt.AlignVCenter | Qt.AlignLeft)
        layout.addStretch(1)
        self.setCellWidget(row, col, wrap)
        item = QTableWidgetItem("")
        item.setToolTip(clean)
        self.setItem(row, col, item)

    @staticmethod
    def _score_tone(score: int | float) -> str:
        if score >= 60:
            return "green"
        if score >= 40:
            return "amber"
        return "gray"

    def current_paper(self) -> Paper | None:
        row = self.currentRow()
        return self.papers[row] if 0 <= row < len(self.papers) else None


class PaperDetailCard(Card):
    openRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("\u8bba\u6587\u8be6\u60c5", "\u9009\u62e9\u4e00\u7bc7\u8bba\u6587\u540e\uff0c\u8fd9\u91cc\u4f1a\u663e\u793a\u6458\u8981\u3001\u547d\u4e2d\u5173\u952e\u8bcd\u548c\u8bc4\u5206\u4f9d\u636e\u3002", parent)
        self.setObjectName("DetailCard")
        self.title = QLabel("\u5c1a\u672a\u9009\u62e9\u8bba\u6587")
        self.title.setObjectName("SectionTitle")
        self.title.setWordWrap(True)
        self.meta = QLabel("\u8bf7\u5728\u4e0a\u65b9\u5217\u8868\u4e2d\u9009\u62e9\u7ed3\u679c\u3002")
        self.meta.setObjectName("Muted")
        self.meta.setWordWrap(True)
        self.abstract = QLabel("")
        self.abstract.setObjectName("Muted")
        self.abstract.setWordWrap(True)
        self.open_button = Button("\u6253\u5f00\u8bba\u6587\u94fe\u63a5", "primary")
        self.open_button.setEnabled(False)
        self._paper: Paper | None = None
        self.body.addWidget(self.title)
        self.body.addWidget(self.meta)
        self.body.addWidget(self.abstract)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self.open_button)
        self.body.addLayout(actions)
        self.open_button.clicked.connect(lambda: self.openRequested.emit(self._paper) if self._paper else None)

    def set_paper(self, paper: Paper | None) -> None:
        self._paper = paper
        if not paper:
            self.title.setText("\u5c1a\u672a\u9009\u62e9\u8bba\u6587")
            self.meta.setText("\u8bf7\u5728\u4e0a\u65b9\u5217\u8868\u4e2d\u9009\u62e9\u7ed3\u679c\u3002")
            self.abstract.setText("")
            self.open_button.setText("\u6253\u5f00\u8bba\u6587\u94fe\u63a5")
            self.open_button.setEnabled(False)
            self.open_button.setToolTip("\u9009\u62e9\u8bba\u6587\u540e\u53ef\u6253\u5f00\u94fe\u63a5")
            return
        self.open_button.setText("\u6253\u5f00\u8bba\u6587\u94fe\u63a5" if paper.url else "\u6682\u65e0\u94fe\u63a5")
        self.open_button.setEnabled(bool(paper.url))
        self.open_button.setToolTip("\u6253\u5f00\u8bba\u6587\u94fe\u63a5" if paper.url else "\u8be5\u8bba\u6587\u6682\u65e0\u53ef\u7528\u94fe\u63a5")
        self.title.setText(paper.title or "\u672a\u547d\u540d\u8bba\u6587")
        self.meta.setText(
            f"\u5206\u6570 {int(paper.relevance_score)} \u00b7 "
            f"{normalize_badge_text(paper.journal_or_source or '\u672a\u77e5\u6765\u6e90')} \u00b7 "
            f"{source_type_label(paper.source_type)} \u00b7 {format_date_only(paper.published_date)}\n"
            f"\u4f5c\u8005\uff1a{paper.authors or '\u672a\u77e5'}\n"
            f"\u547d\u4e2d\u5173\u952e\u8bcd\uff1a{paper.matched_keywords_text or '\u65e0'}"
        )
        self.abstract.setText(f"\u6458\u8981\n{paper.abstract or '\u8be5\u6570\u636e\u6e90\u672a\u63d0\u4f9b\u5b8c\u6574\u6458\u8981\u3002'}\n\n\u8bc4\u5206\u8bf4\u660e\n{paper.reason_zh or '\u6682\u65e0'}")
