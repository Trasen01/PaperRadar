from __future__ import annotations

from dataclasses import dataclass, field


_CATEGORY_REPLACEMENTS = {
    "顶级光子期刊": "顶级光学期刊",
}


def display_category(value: str) -> str:
    return _CATEGORY_REPLACEMENTS.get(value, value)


@dataclass
class Paper:
    title: str = ""
    authors: str = ""
    abstract: str = ""
    published_date: str = ""
    updated_date: str = ""
    url: str = ""
    arxiv_id: str = ""
    doi: str = ""
    journal_or_source: str = "arXiv"
    source_type: str = "arxiv"
    source_quality_score: int = 5
    categories: list[str] = field(default_factory=list)
    primary_category: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    matched_fields: list[str] = field(default_factory=list)
    relevance_score: int = 0
    reason_zh: str = ""

    @property
    def category_text(self) -> str:
        return ", ".join(display_category(category) for category in self.categories)

    @property
    def primary_category_text(self) -> str:
        return display_category(self.primary_category)

    @property
    def matched_keywords_text(self) -> str:
        return ", ".join(self.matched_keywords)

    @property
    def matched_fields_text(self) -> str:
        return ", ".join(self.matched_fields)
