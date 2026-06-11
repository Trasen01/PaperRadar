from __future__ import annotations

import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)

JOURNAL_NAMES = {
    "nature",
    "science",
    "nature photonics",
    "nature communications",
    "science advances",
    "light: science & applications",
    "light science applications",
    "optica",
    "physical review letters",
    "prl",
    "advanced photonics",
    "laser & photonics reviews",
    "laser and photonics reviews",
    "acs photonics",
    "nanophotonics",
    "optics express",
    "photonics research",
    "apl photonics",
    "physical review applied",
    "physical review research",
    "ieee photonics technology letters",
    "journal of lightwave technology",
}

BROAD_SINGLE_TERMS = {
    "nature",
    "science",
    "light",
    "optics",
    "photonic",
    "photonics",
    "optical",
}


def normalize_term(term: str) -> str:
    value = re.sub(r"\s+", " ", str(term or "").strip().lower())
    value = value.replace("&", "and")
    value = re.sub(r"[^a-z0-9π\- ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def is_likely_journal_name(term: str) -> bool:
    normalized = normalize_term(term)
    raw = re.sub(r"\s+", " ", str(term or "").strip().lower())
    return raw in JOURNAL_NAMES or normalized in JOURNAL_NAMES


def is_too_broad_search_term(term: str) -> bool:
    normalized = normalize_term(term)
    return normalized in BROAD_SINGLE_TERMS or len(normalized) < 3


def filter_research_terms(terms: Iterable[str], *, for_query: bool = False) -> list[str]:
    filtered: list[str] = []
    removed: list[str] = []
    seen: set[str] = set()
    for term in terms:
        text = str(term or "").strip()
        key = normalize_term(text)
        if not text or key in seen:
            continue
        if is_likely_journal_name(text) or (for_query and is_too_broad_search_term(text)):
            removed.append(text)
            continue
        seen.add(key)
        filtered.append(text)
    if removed:
        logger.info("PROFILE_FILTERED_NON_RESEARCH_TERMS terms=%s", removed)
    return filtered


def sanitize_search_queries(queries: Iterable[str], *, max_queries: int = 20) -> tuple[list[str], list[str]]:
    raw_queries = [str(query or "").strip() for query in queries]
    sanitized: list[str] = []
    removed: list[str] = []
    seen: set[str] = set()
    for text in raw_queries:
        key = normalize_term(text)
        if not text or key in seen:
            if text:
                removed.append(text)
            continue
        if is_likely_journal_name(text) or is_too_broad_search_term(text):
            removed.append(text)
            continue
        seen.add(key)
        sanitized.append(text)
    if len(sanitized) > max_queries:
        removed.extend(sanitized[max_queries:])
        sanitized = sanitized[:max_queries]
    if removed:
        logger.warning(
            "SEARCH_QUERY_SANITIZED raw_count=%s filtered_count=%s removed=%s final=%s",
            len(raw_queries),
            len(sanitized),
            removed,
            sanitized,
        )
    return sanitized, removed
