from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from .metadata_enricher import clean_abstract, enrich_paper_metadata
from .models import Paper
from .network import retry_call
from .profile_manager import active_profile_search_queries
from .profile_terms import filter_research_terms
from .settings import load_keywords, load_sources
from .utils import normalize_space

logger = logging.getLogger(__name__)

CROSSREF_API = "https://api.crossref.org/works"

DEFAULT_QUERIES = [
    "photonic computing",
    "optical computing",
    "optical neural network",
    "photonic neural network",
    "diffractive neural network",
    "photonic matrix multiplication",
    "optical matrix multiplication",
    "matrix-vector multiplication photonic",
    "optical convolution",
    "photonic convolution",
    "photonic processor",
    "programmable photonic processor",
    "photonic accelerator",
    "optical Ising machine",
    "photonic reservoir computing",
    "neuromorphic photonics",
    "optical equation solver",
    "wave-based computing",
]


@dataclass
class CrossrefQueryStat:
    journal: str
    query: str
    raw_count: int = 0
    parsed_count: int = 0
    abstract_count: int = 0
    doi_count: int = 0
    error: str = ""


@dataclass
class CrossrefResult:
    papers: list[Paper]
    query_stats: list[CrossrefQueryStat] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)


def build_search_queries_from_keywords(profile: dict[str, list[str]] | None = None, max_queries: int = 20) -> list[str]:
    fallback_terms: list[str] = []
    for group_name, group in (profile or {}).items():
        if str(group_name).lower() == "exclude":
            continue
        fallback_terms.extend(group or [])
    if fallback_terms:
        queries = filter_research_terms(fallback_terms, for_query=True)
        if queries:
            return queries[:max_queries]

    queries = filter_research_terms(active_profile_search_queries(max_queries=max_queries), for_query=True)
    if queries:
        return queries[:max_queries]
    return filter_research_terms(DEFAULT_QUERIES, for_query=True)[:max_queries]


class CrossrefClient:
    def __init__(self, timeout: int = 20, rows: int = 20, sleep_seconds: float = 0.15, max_retries: int = 3, retry_delay_seconds: int = 3) -> None:
        self.timeout = timeout
        self.rows = rows
        self.sleep_seconds = sleep_seconds
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "PaperRadar/2.0 (mailto:contact@example.com)"})

    def fetch_recent(self, days_back: int = 365, max_queries: int = 18) -> CrossrefResult:
        until = datetime.now(timezone.utc).date()
        start = until - timedelta(days=max(days_back, 0))
        return self.fetch(start, until, build_search_queries_from_keywords(load_keywords(), max_queries=max_queries))

    def fetch(self, from_date: date, until_date: date, queries: list[str]) -> CrossrefResult:
        sources = load_sources().get("top_journals", [])
        enabled = [source for source in sources if source.get("crossref_enabled")]
        papers: list[Paper] = []
        stats: list[CrossrefQueryStat] = []
        failures: list[str] = []
        logger.info("CROSSREF_START enabled_top_journals=%s from=%s until=%s queries=%s", len(enabled), from_date, until_date, len(queries))
        for journal in enabled:
            issns = journal.get("issn") or []
            if isinstance(issns, str):
                issns = [issns]
            if not issns:
                failures.append(f"{journal.get('name')}: missing ISSN")
                logger.warning("CROSSREF_SKIP journal=%s reason=missing_issn", journal.get("name"))
                continue
            for query in queries:
                stat = CrossrefQueryStat(journal=str(journal.get("name") or "Unknown"), query=query)
                stats.append(stat)
                try:
                    items = self._query(journal, issns, query, from_date, until_date)
                    stat.raw_count = len(items)
                    for item in items:
                        paper = self._item_to_paper(journal, item)
                        if not paper.title:
                            continue
                        stat.parsed_count += 1
                        if paper.abstract:
                            stat.abstract_count += 1
                        if paper.doi:
                            stat.doi_count += 1
                        papers.append(paper)
                except Exception as exc:
                    stat.error = str(exc)
                    failures.append(f"{journal.get('name')} | {query}: {exc}")
                    logger.warning("CROSSREF_QUERY_FAILED journal=%s query=%s error=%s", journal.get("name"), query, exc)
                time.sleep(self.sleep_seconds)
        deduped = self._dedupe(papers)
        logger.info("CROSSREF_DONE raw=%s deduped=%s failures=%s", len(papers), len(deduped), len(failures))
        return CrossrefResult(papers=deduped, query_stats=stats, failed_requests=failures)

    def _query(self, journal: dict[str, Any], issns: list[str], query: str, from_date: date, until_date: date) -> list[dict[str, Any]]:
        params = {
            "query.bibliographic": query,
            "filter": f"from-pub-date:{from_date.isoformat()},until-pub-date:{until_date.isoformat()},issn:{issns[0]},type:journal-article",
            "rows": self.rows,
            "select": "DOI,title,author,abstract,published-print,published-online,published,URL,container-title,ISSN,type,subject",
            "sort": "published",
            "order": "desc",
        }
        response = retry_call(
            lambda: self.session.get(CROSSREF_API, params=params, timeout=self.timeout),
            source_type="crossref",
            query=f"{journal.get('name')} | {query}",
            timeout=self.timeout,
            max_retries=self.max_retries,
            retry_delay_seconds=self.retry_delay_seconds,
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("items", []) or []

    def _item_to_paper(self, journal: dict[str, Any], item: dict[str, Any]) -> Paper:
        title = normalize_space(" ".join(item.get("title") or []))
        container = normalize_space(" ".join(item.get("container-title") or [])) or str(journal.get("name") or "")
        doi = normalize_space(item.get("DOI") or "")
        url = normalize_space(item.get("URL") or (f"https://doi.org/{doi}" if doi else ""))
        abstract = clean_abstract(item.get("abstract") or "")
        published = self._published_date(item)
        authors = self._authors(item)
        subjects = [normalize_space(str(value)) for value in item.get("subject") or [] if value]
        paper = Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            published_date=published,
            updated_date="",
            url=url,
            doi=doi,
            journal_or_source=str(journal.get("name") or container),
            source_type="crossref",
            source_quality_score=int(journal.get("quality_score") or 0),
            categories=subjects or ["期刊论文"],
            primary_category=subjects[0] if subjects else "期刊论文",
        )
        return enrich_paper_metadata(paper)

    def _authors(self, item: dict[str, Any]) -> str:
        names = []
        for author in item.get("author") or []:
            given = author.get("given") or ""
            family = author.get("family") or ""
            name = normalize_space(f"{given} {family}")
            if name:
                names.append(name)
        return ", ".join(names)

    def _published_date(self, item: dict[str, Any]) -> str:
        for key in ["published-online", "published-print", "published"]:
            parts = (item.get(key) or {}).get("date-parts") or []
            if parts and parts[0]:
                year = int(parts[0][0])
                month = int(parts[0][1]) if len(parts[0]) > 1 else 1
                day = int(parts[0][2]) if len(parts[0]) > 2 else 1
                return date(year, month, day).isoformat()
        return ""

    def _dedupe(self, papers: list[Paper]) -> list[Paper]:
        seen: set[str] = set()
        out: list[Paper] = []
        for paper in papers:
            key = paper.doi.lower() if paper.doi else (paper.url or paper.title.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(paper)
        return out
