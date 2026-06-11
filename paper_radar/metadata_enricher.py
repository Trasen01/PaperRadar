from __future__ import annotations

import html
from typing import Any

from .models import Paper
from .utils import normalize_space

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


def clean_abstract(value: Any) -> str:
    text = html.unescape(str(value or ""))
    if BeautifulSoup is not None:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    return normalize_space(text)


def enrich_paper_metadata(paper: Paper) -> Paper:
    if paper.abstract:
        return paper
    return paper
