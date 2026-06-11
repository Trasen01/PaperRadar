from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import mktime
from typing import Any

import requests
from dateutil import parser as date_parser
from requests.exceptions import SSLError

from .models import Paper
from .network import retry_call
from .settings import load_sources
from .utils import normalize_space

try:
    import feedparser
except ImportError:  # pragma: no cover - only used when dependency is missing.
    feedparser = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - fallback keeps the app usable.
    BeautifulSoup = None

logger = logging.getLogger(__name__)


@dataclass
class JournalSourceStats:
    name: str
    feed_url: str = ""
    enabled: bool = False
    fetched_raw_count: int = 0
    parsed_count: int = 0
    failed_parse_count: int = 0
    before_date_filter_count: int = 0
    after_date_filter_count: int = 0
    date_filtered_count: int = 0
    missing_date_count: int = 0
    status: str = "skipped"
    error: str = ""


@dataclass
class JournalFetchStats:
    enabled_sources: int = 0
    failed_sources: int = 0
    skipped_sources: int = 0
    fetched_papers: int = 0
    source_stats: list[JournalSourceStats] = field(default_factory=list)


@dataclass
class JournalFetchResult:
    papers: list[Paper]
    stats: JournalFetchStats


class JournalRssFetcher:
    def __init__(self, timeout: int = 20, max_retries: int = 3, retry_delay_seconds: int = 3) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

    def fetch_recent(self, days_back: int = 7, max_results: int | None = None) -> JournalFetchResult:
        if feedparser is None:
            logger.warning("RSS_DIAG feedparser is not installed; journal RSS sources are skipped")
            return JournalFetchResult(papers=[], stats=JournalFetchStats())

        sources = load_sources().get("journal_sources", [])
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(days_back, 0))
        stats = JournalFetchStats()
        stats.enabled_sources = sum(1 for source in sources if self._source_enabled(source))
        papers: list[Paper] = []

        logger.info("RSS_FETCH enabled_journal_sources=%s", stats.enabled_sources)
        for source in sources:
            source_name = str(source.get("name", "Unknown")) if isinstance(source, dict) else "Invalid source"
            if not self._source_enabled(source):
                stats.source_stats.append(JournalSourceStats(name=source_name, enabled=False))
                continue

            feed_urls = self._source_feed_urls(source)
            source_stat = JournalSourceStats(name=source_name, enabled=True, feed_url=feed_urls[0] if feed_urls else "")
            stats.source_stats.append(source_stat)
            logger.info("RSS_SOURCE name=%s urls=%s", source_name, feed_urls)

            if not feed_urls:
                stats.skipped_sources += 1
                source_stat.status = "skipped_empty_feed_url"
                source_stat.error = "feed_url is empty"
                logger.warning("RSS_SOURCE_SKIPPED name=%s reason=empty_feed_url", source_name)
                continue

            try:
                feed_papers = self._fetch_source(source, feed_urls, cutoff, source_stat)
                source_stat.status = "ok"
                papers.extend(feed_papers)
            except Exception as exc:
                stats.failed_sources += 1
                source_stat.status = "failed"
                source_stat.error = str(exc)
                logger.warning("RSS_SOURCE_FAILED name=%s error=%s", source_name, exc)

        stats.fetched_papers = len(papers)
        logger.info(
            "RSS_FETCH_DONE enabled=%s failed=%s skipped=%s fetched_papers=%s",
            stats.enabled_sources,
            stats.failed_sources,
            stats.skipped_sources,
            stats.fetched_papers,
        )
        return JournalFetchResult(papers=papers, stats=stats)

    def enabled_source_count(self) -> int:
        return sum(1 for source in load_sources().get("journal_sources", []) if self._source_enabled(source))

    def _source_enabled(self, source: Any) -> bool:
        return (
            isinstance(source, dict)
            and bool(source.get("enabled"))
            and str(source.get("type") or "").lower() == "rss"
        )

    def _source_feed_urls(self, source: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for value in [source.get("feed_url"), *(source.get("alternate_feed_urls") or [])]:
            url = normalize_space(str(value or ""))
            if url and url not in urls:
                urls.append(url)
        return urls

    def _fetch_source(
        self,
        source: dict[str, Any],
        feed_urls: list[str],
        cutoff: datetime,
        source_stat: JournalSourceStats,
    ) -> list[Paper]:
        last_error: Exception | None = None
        parsed = None
        used_url = ""
        for feed_url in feed_urls:
            try:
                response = self._get(feed_url)
                response.raise_for_status()
                parsed = feedparser.parse(response.content)
                used_url = feed_url
                break
            except Exception as exc:
                last_error = exc
                logger.warning("RSS_SOURCE_URL_FAILED name=%s url=%s error=%s", source.get("name", "Unknown"), feed_url, exc)
        if parsed is None:
            raise last_error or RuntimeError("No usable feed URL")

        source_stat.feed_url = used_url
        if parsed.bozo:
            logger.warning("RSS_PARSE_WARNING name=%s bozo_exception=%s", source.get("name", "Unknown"), parsed.bozo_exception)

        papers = self._papers_from_parsed_feed(source, parsed, cutoff, source_stat)
        logger.info(
            "RSS_SOURCE_COUNTS name=%s raw=%s parsed=%s parse_failed=%s before_date=%s after_date=%s date_filtered=%s missing_date=%s",
            source_stat.name,
            source_stat.fetched_raw_count,
            source_stat.parsed_count,
            source_stat.failed_parse_count,
            source_stat.before_date_filter_count,
            source_stat.after_date_filter_count,
            source_stat.date_filtered_count,
            source_stat.missing_date_count,
        )
        return papers

    def parse_feed_content(
        self,
        source: dict[str, Any],
        content: bytes | str,
        days_back: int = 365,
    ) -> JournalFetchResult:
        if feedparser is None:
            return JournalFetchResult(papers=[], stats=JournalFetchStats())
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(days_back, 0))
        parsed = feedparser.parse(content)
        source_stat = JournalSourceStats(
            name=str(source.get("name") or "Unknown Journal"),
            feed_url=str(source.get("feed_url") or ""),
            enabled=True,
        )
        papers = self._papers_from_parsed_feed(source, parsed, cutoff, source_stat)
        stats = JournalFetchStats(
            enabled_sources=1,
            fetched_papers=len(papers),
            source_stats=[source_stat],
        )
        return JournalFetchResult(papers=papers, stats=stats)

    def _papers_from_parsed_feed(
        self,
        source: dict[str, Any],
        parsed: Any,
        cutoff: datetime,
        source_stat: JournalSourceStats,
    ) -> list[Paper]:
        entries = list(getattr(parsed, "entries", []) or [])
        source_stat.fetched_raw_count = len(entries)
        source_stat.before_date_filter_count = len(entries)
        papers: list[Paper] = []
        for entry in entries:
            try:
                paper = self._parse_entry(source, entry)
            except Exception as exc:
                source_stat.failed_parse_count += 1
                logger.warning("RSS_ENTRY_PARSE_FAILED source=%s error=%s", source_stat.name, exc)
                continue

            published_dt = parse_entry_date(entry)
            if published_dt is None:
                source_stat.missing_date_count += 1
            elif published_dt < cutoff:
                source_stat.date_filtered_count += 1
                continue
            source_stat.parsed_count += 1
            papers.append(paper)

        source_stat.after_date_filter_count = len(papers)
        return papers

    def _get(self, feed_url: str) -> requests.Response:
        def request_once() -> requests.Response:
            try:
                return requests.get(
                    feed_url,
                    timeout=self.timeout,
                    headers={"User-Agent": "PaperRadar/1.0"},
                )
            except SSLError as exc:
                logger.warning("SSL verification failed for %s, retrying without verification: %s", feed_url, exc)
                return requests.get(
                    feed_url,
                    timeout=self.timeout,
                    headers={"User-Agent": "PaperRadar/1.0"},
                    verify=False,
                )

        return retry_call(
            request_once,
            source_type="journal_rss",
            query=feed_url,
            timeout=self.timeout,
            max_retries=self.max_retries,
            retry_delay_seconds=self.retry_delay_seconds,
        )

    def _parse_entry(self, source: dict[str, Any], entry: Any) -> Paper:
        source_name = normalize_space(str(source.get("name") or "Unknown Journal"))
        source_quality = int(source.get("quality_score") or 0)
        title = normalize_space(entry.get("title", ""))
        url = normalize_space(entry.get("link", ""))
        summary = extract_entry_summary(entry)
        published_dt = parse_entry_date(entry)
        published = published_dt.isoformat() if published_dt else ""
        updated_dt = _struct_or_text_date(entry.get("updated_parsed") or entry.get("updated"))
        updated = updated_dt.isoformat() if updated_dt else ""
        authors = self._authors(entry)
        doi = self._doi(entry)
        subject_hint = normalize_space(str(source.get("subject_hint") or ""))
        field_relevant = bool(source.get("field_relevant"))
        primary_category = "顶级光学期刊" if field_relevant else (subject_hint or "期刊论文")
        categories = [primary_category]

        return Paper(
            title=title,
            authors=authors,
            abstract=summary,
            published_date=published,
            updated_date=updated,
            url=url,
            doi=doi,
            journal_or_source=source_name,
            source_type="journal_rss",
            source_quality_score=source_quality,
            categories=categories,
            primary_category=primary_category,
        )

    def _authors(self, entry: Any) -> str:
        authors = entry.get("authors") or []
        names = []
        for author in authors:
            if isinstance(author, dict):
                names.append(normalize_space(author.get("name", "")))
        if names:
            return ", ".join(name for name in names if name)
        return normalize_space(entry.get("author", ""))

    def _doi(self, entry: Any) -> str:
        candidates = [
            entry.get("prism_doi"),
            entry.get("dc_identifier"),
            entry.get("id"),
            entry.get("guid"),
        ]
        for value in candidates:
            text = normalize_space(str(value or ""))
            if "10." in text:
                return text.split("doi:")[-1].strip()
        return ""


def parse_entry_date(entry: Any) -> datetime | None:
    for key in ["published_parsed", "updated_parsed"]:
        parsed = _struct_or_text_date(entry.get(key))
        if parsed:
            return parsed
    for key in ["published", "updated", "pubDate", "created", "dc_date"]:
        parsed = _struct_or_text_date(entry.get(key))
        if parsed:
            return parsed
    return None


def _struct_or_text_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        if hasattr(value, "tm_year"):
            parsed = datetime.fromtimestamp(mktime(value), timezone.utc)
        else:
            parsed = date_parser.parse(str(value))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def extract_entry_summary(entry: Any) -> str:
    value = entry.get("summary") or entry.get("description") or ""
    if not value:
        content = entry.get("content") or []
        if content and isinstance(content, list):
            first = content[0]
            if isinstance(first, dict):
                value = first.get("value") or ""
    if not value:
        value = entry.get("subtitle") or ""
    return _clean_html(value)


def _clean_html(value: Any) -> str:
    text = html.unescape(str(value or ""))
    if BeautifulSoup is not None:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    return normalize_space(text)
