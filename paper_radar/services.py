from __future__ import annotations

import logging
import threading
import time
import traceback
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from .arxiv_client import ArxivClient
from .crossref_client import CrossrefClient, build_search_queries_from_keywords
from .database import PaperDatabase
from .journal_fetcher import JournalRssFetcher
from .keyword_filter import KeywordFilter
from .models import Paper
from .profile_manager import load_active_profile, profile_to_keywords
from .report import generate_daily_report, generate_survey_report
from .scorer import score_paper
from .settings import load_keywords, load_settings, load_sources
from .utils import open_folder, open_url, title_hash, REPORTS_DIR

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str, Any], None]


@dataclass
class RunResult:
    papers: list[Paper]
    stats: dict[str, Any]


def has_active_profile() -> bool:
    profile = load_active_profile()
    profile_id = str(profile.get("profile_id") or "").strip()
    return bool(profile_id and (profile_to_keywords(profile) or profile.get("search_queries")))


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
                key_to_index.setdefault(key, index)
            continue
        existing = out[min(indexes)]
        _merge_paper(existing, paper)
        for key in keys:
            key_to_index.setdefault(key, min(indexes))
    return out


def _paper_identity_keys(paper: Paper) -> list[str]:
    keys: list[str] = []
    if paper.doi:
        keys.append("doi:" + paper.doi.lower().strip())
    if paper.arxiv_id:
        keys.append("arxiv:" + paper.arxiv_id.lower().strip())
    if paper.url:
        keys.append("url:" + paper.url.lower().strip())
    if paper.title:
        keys.append("title:" + title_hash(paper.title))
    return keys


def _merge_paper(target: Paper, incoming: Paper) -> None:
    if len(incoming.abstract or "") > len(target.abstract or ""):
        target.abstract = incoming.abstract
    for attr in ("doi", "url", "authors", "published_date", "updated_date", "journal_or_source", "primary_category"):
        if not getattr(target, attr) and getattr(incoming, attr):
            setattr(target, attr, getattr(incoming, attr))
    target.source_quality_score = max(int(target.source_quality_score), int(incoming.source_quality_score))
    target.categories = list(dict.fromkeys([*target.categories, *incoming.categories]))
    if target.source_type == "arxiv" and incoming.source_type != "arxiv":
        target.source_type = incoming.source_type


def matched_fields_from_locations(locations: dict[str, dict[str, list[str]]]) -> list[str]:
    fields: list[str] = []
    for field, label in [("title", "\u6807\u9898"), ("abstract", "\u6458\u8981"), ("metadata", "\u5206\u7c7b/\u5143\u6570\u636e")]:
        if any(values for group, locs in locations.items() if group != "exclude" for loc, values in locs.items() if loc == field):
            fields.append(label)
    return fields


def has_relevant_keyword(matches: dict[str, list[str]]) -> bool:
    return any(group != "exclude" and bool(values) for group, values in matches.items())


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
            paper.reason_zh = "\u672a\u547d\u4e2d\u5f53\u524d\u7814\u7a76\u5173\u952e\u8bcd\uff0c\u4ec5\u4f5c\u4e3a\u6765\u6e90\u5b58\u6863\u3002"
            paper.score_breakdown = {"keyword_score": 0, "source_quality_score": 0, "penalty_score": 0, "final_score": 0, "has_positive_keyword_hit": False}
            scored.append(paper)
            continue
        paper.matched_keywords = keyword_filter.flatten_matches(matches)
        paper.matched_fields = matched_fields_from_locations(locations)
        paper.relevance_score, paper.reason_zh = score_paper(paper, matches, keyword_filter.title_matches(paper), locations)
        scored.append(paper)
    scored.sort(key=lambda item: (int(item.relevance_score), item.published_date or ""), reverse=True)
    return scored


def _source_status(enabled: bool) -> dict[str, Any]:
    return {"enabled": enabled, "status": "pending" if enabled else "disabled", "raw": 0, "stored": 0, "failed": 0, "reason": ""}


def _mark_source_error(status: dict[str, Any], exc: Exception) -> None:
    message = str(exc) or exc.__class__.__name__
    status["failed"] = int(status.get("failed", 0)) + 1
    status["reason"] = message[:160]
    lower = message.lower()
    if "timeout" in lower or "timed out" in lower:
        status["status"] = "timeout"
    else:
        status["status"] = "failed"


def _finalize_source_status(status: dict[str, Any]) -> None:
    if not status.get("enabled"):
        status["status"] = "disabled"
    elif status.get("failed") and status.get("raw"):
        status["status"] = "partial"
    elif status.get("failed"):
        status["status"] = status.get("status") or "failed"
    elif int(status.get("raw", 0)) == 0:
        status["status"] = "empty"
        status.setdefault("reason", "no results")
    else:
        status["status"] = "success"


def _source_counts(papers: list[Paper]) -> dict[str, int]:
    arxiv = sum(1 for paper in papers if paper.source_type == "arxiv")
    top = sum(1 for paper in papers if paper.source_type in {"crossref", "journal_rss"})
    return {"arxiv": arxiv, "top": top}


class DailySearchService:
    def __init__(self, days_back: int, sources: dict[str, bool], settings: dict[str, Any] | None = None) -> None:
        self.days_back = days_back
        self.sources = sources
        self.settings = settings or load_settings()
        self.db = PaperDatabase()
        self.keyword_filter = KeywordFilter(load_keywords())

    def run(self, should_stop: Callable[[], bool] | None = None, progress: ProgressCallback | None = None) -> RunResult:
        should_stop = should_stop or (lambda: False)
        progress = progress or (lambda *_args: None)
        rows_per_query = int(self.settings.get("crossref", {}).get("rows_per_query", 20))
        max_queries = min(4, int(self.settings.get("crossref", {}).get("max_queries_per_run", 200)))
        network = self.settings.get("network", {})
        timeout = int(network.get("daily_timeout_seconds", 20))
        max_retries = int(network.get("max_retries", 3))
        retry_delay = int(network.get("retry_delay_seconds", 3))
        papers: list[Paper] = []
        stats = Counter()
        source_status = {"arxiv": _source_status(bool(self.sources.get("arxiv"))), "top": _source_status(bool(self.sources.get("rss") or self.sources.get("crossref")))}
        total_steps = sum(1 for key in ("arxiv", "rss", "crossref") if self.sources.get(key))
        completed = 0
        progress("progress", {"completed": 0, "total": max(total_steps, 1), "source": "\u51c6\u5907\u68c0\u7d22"})

        if self.sources.get("arxiv") and not should_stop():
            try:
                arxiv_client = ArxivClient(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay)
                batch = arxiv_client.fetch_recent(self.days_back, 300)
                source_status["arxiv"]["raw"] += len(batch)
                if arxiv_client.retry_failures:
                    source_status["arxiv"]["failed"] += arxiv_client.retry_failures
                    source_status["arxiv"]["reason"] = arxiv_client.last_retry_error[:160]
                    if "timeout" in arxiv_client.last_retry_error.lower() or "timed out" in arxiv_client.last_retry_error.lower():
                        source_status["arxiv"]["status"] = "timeout"
                stats["arxiv"] = len(batch)
                stats["success"] += 1
            except Exception as exc:
                batch = []
                stats["failed"] += 1
                _mark_source_error(source_status["arxiv"], exc)
                logger.warning("Daily arXiv failed: %s", exc)
            completed += 1
            self._handle_batch(batch, papers, stats, completed, total_steps, "arXiv", progress, source_status)
        if self.sources.get("rss") and not should_stop():
            failed_before = int(stats.get("failed", 0))
            try:
                rss = JournalRssFetcher(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent(self.days_back)
                batch = rss.papers
                stats["failed"] += int(rss.stats.failed_sources)
                source_status["top"]["raw"] += len(batch)
                source_status["top"]["failed"] += max(0, int(stats.get("failed", 0)) - failed_before)
                stats["rss"] = len(batch)
                stats["success"] += 1
            except Exception as exc:
                batch = []
                stats["failed"] += 1
                _mark_source_error(source_status["top"], exc)
                logger.warning("Daily RSS failed: %s", exc)
            completed += 1
            self._handle_batch(batch, papers, stats, completed, total_steps, "\u9876\u7ea7\u671f\u520a RSS", progress, source_status)
        if self.sources.get("crossref") and not should_stop():
            failed_before = int(stats.get("failed", 0))
            try:
                result = CrossrefClient(timeout=timeout, rows=rows_per_query, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent(self.days_back, max_queries=max_queries)
                batch = result.papers
                stats["failed"] += len(result.failed_requests)
                source_status["top"]["raw"] += len(batch)
                source_status["top"]["failed"] += max(0, int(stats.get("failed", 0)) - failed_before)
                stats["crossref"] = len(batch)
                stats["success"] += 1
            except Exception as exc:
                batch = []
                stats["failed"] += 1
                _mark_source_error(source_status["top"], exc)
                logger.warning("Daily Crossref failed: %s", exc)
            completed += 1
            self._handle_batch(batch, papers, stats, completed, total_steps, "\u9876\u7ea7\u671f\u520a Crossref", progress, source_status)

        scored = score_and_tag(dedupe_papers(papers), self.keyword_filter, keep_unmatched=True)
        storage = self.db.upsert_papers_with_stats(scored)
        counts = _source_counts(scored)
        source_status["arxiv"]["stored"] = counts["arxiv"]
        source_status["top"]["stored"] = counts["top"]
        for state in source_status.values():
            _finalize_source_status(state)
        stats["raw"] = sum(int(v.get("raw", 0)) for v in source_status.values())
        stats["deduped"] = len(scored)
        stats["displayed"] = len(scored)
        stats["inserted"] = storage.inserted_count
        stats["updated"] = storage.updated_count
        stats["source_status"] = source_status
        stats["source_counts"] = counts
        stats["high"] = sum(1 for paper in scored if paper.relevance_score >= 60)
        stats["skim"] = sum(1 for paper in scored if 40 <= paper.relevance_score < 60)
        return RunResult(scored, dict(stats))

    def _safe_fetch(self, label: str, stats: Counter, callback: Callable[[], list[Paper]]) -> list[Paper]:
        try:
            batch = callback()
            stats[label] = len(batch)
            stats["success"] += 1
            return batch
        except Exception as exc:
            stats["failed"] += 1
            logger.warning("Daily %s failed: %s", label, exc)
            return []

    def _handle_batch(self, batch: list[Paper], all_seen: list[Paper], stats: Counter, completed: int, total: int, source_label: str, progress: ProgressCallback, source_status: dict[str, dict[str, Any]] | None = None) -> None:
        all_seen.extend(batch)
        scored = score_and_tag(dedupe_papers(all_seen), self.keyword_filter, keep_unmatched=True)
        storage = self.db.upsert_papers_with_stats(scored)
        stats["deduped"] = len(scored)
        stats["matched"] = sum(1 for paper in scored if paper.matched_keywords)
        stats["displayed"] = len(scored)
        stats["inserted"] += storage.inserted_count
        stats["updated"] += storage.updated_count
        counts = _source_counts(scored)
        if source_status:
            source_status["arxiv"]["stored"] = counts["arxiv"]
            source_status["top"]["stored"] = counts["top"]
        payload = {"completed": completed, "total": max(total, 1), "source": source_label, "found": len(all_seen), "raw": sum(int(v.get("raw", 0)) for v in (source_status or {}).values()) if source_status else len(all_seen), "deduped": stats["deduped"], "matched": stats["matched"], "displayed": stats["displayed"], "success": stats["success"], "failed": stats["failed"], "source_status": source_status or {}, "source_counts": counts, "papers": scored}
        progress("batch", payload)
        progress("progress", payload)


class HistoricalSurveyService:
    def __init__(self, task_name: str, from_date: date, until_date: date, sources: dict[str, bool], settings: dict[str, Any] | None = None) -> None:
        self.task_name = task_name
        self.from_date = from_date
        self.until_date = until_date
        self.sources = sources
        self.settings = settings or load_settings()
        self.db = PaperDatabase()
        self.keyword_filter = KeywordFilter(load_keywords())

    def run(self, should_stop: Callable[[], bool] | None = None, progress: ProgressCallback | None = None) -> RunResult:
        should_stop = should_stop or (lambda: False)
        progress = progress or (lambda *_args: None)
        all_seen: list[Paper] = []
        stats = Counter()
        source_status = {"arxiv": _source_status(bool(self.sources.get("arxiv"))), "top": _source_status(bool(self.sources.get("rss") or self.sources.get("crossref")))}
        start_time = time.monotonic()
        rows_per_query = int(self.settings.get("crossref", {}).get("rows_per_query", 20))
        max_queries = int(self.settings.get("crossref", {}).get("max_queries_per_run", 200))
        delay = float(self.settings.get("crossref", {}).get("request_delay_seconds", 0.5))
        network = self.settings.get("network", {})
        timeout = int(network.get("historical_timeout_seconds", 60))
        max_retries = int(network.get("max_retries", 3))
        retry_delay = int(network.get("retry_delay_seconds", 3))
        max_workers = max(1, min(5, int(self.settings.get("performance", {}).get("max_workers", 3))))
        cache_enabled = bool(self.settings.get("cache", {}).get("enabled", True))
        queries = build_search_queries_from_keywords(load_keywords(), max_queries=max_queries)
        top_journals = [journal for journal in load_sources().get("top_journals", []) if journal.get("crossref_enabled")]
        total_steps = (len(top_journals) * len(queries) if self.sources.get("crossref") else 0) + (1 if self.sources.get("arxiv") else 0) + (1 if self.sources.get("rss") else 0)
        completed = 0
        progress("progress", {"completed": 0, "total": max(total_steps, 1), "journal": "\u51c6\u5907", "query": "\u51c6\u5907\u68c0\u7d22"})

        if self.sources.get("arxiv") and not should_stop():
            try:
                arxiv_client = ArxivClient(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay)
                batch = arxiv_client.fetch_recent(max(1, (self.until_date - self.from_date).days), 1000)
                source_status["arxiv"]["raw"] += len(batch)
                if arxiv_client.retry_failures:
                    source_status["arxiv"]["failed"] += arxiv_client.retry_failures
                    source_status["arxiv"]["reason"] = arxiv_client.last_retry_error[:160]
                    if "timeout" in arxiv_client.last_retry_error.lower() or "timed out" in arxiv_client.last_retry_error.lower():
                        source_status["arxiv"]["status"] = "timeout"
                stats["success"] += 1
            except Exception as exc:
                batch = []
                stats["failed"] += 1
                stats["failed_query_count"] += 1
                if "timeout" in str(exc).lower():
                    stats["timeouts"] += 1
                _mark_source_error(source_status["arxiv"], exc)
                logger.warning("Survey arXiv failed: %s", exc)
            completed += 1
            self._handle_batch(batch, all_seen, stats, completed, total_steps, "arXiv", "arXiv", progress)

        if self.sources.get("rss") and not should_stop():
            try:
                rss = JournalRssFetcher(timeout=timeout, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_recent(max(1, (self.until_date - self.from_date).days))
                batch = rss.papers
                source_status["top"]["raw"] += len(batch)
                stats["success"] += 1
                stats["failed"] += int(rss.stats.failed_sources)
                stats["failed_query_count"] += int(rss.stats.failed_sources)
            except Exception as exc:
                batch = []
                stats["failed"] += 1
                stats["failed_query_count"] += 1
                if "timeout" in str(exc).lower():
                    stats["timeouts"] += 1
                _mark_source_error(source_status["top"], exc)
                logger.warning("Survey RSS failed: %s", exc)
            completed += 1
            self._handle_batch(batch, all_seen, stats, completed, total_steps, "\u9876\u7ea7\u671f\u520a", "\u6700\u65b0\u6587\u7ae0", progress)

        if self.sources.get("crossref") and not should_stop():
            completed = self._run_crossref(top_journals, queries, all_seen, stats, completed, total_steps, rows_per_query, timeout, max_retries, retry_delay, max_workers, delay, cache_enabled, should_stop, progress)

        scored = score_and_tag(dedupe_papers(all_seen), self.keyword_filter, keep_unmatched=False)
        storage = self.db.upsert_papers_with_stats(scored)
        counts = _source_counts(scored)
        source_status["arxiv"]["stored"] = counts["arxiv"]
        source_status["top"]["stored"] = counts["top"]
        if source_status["top"].get("raw", 0) == 0 and counts["top"]:
            source_status["top"]["raw"] = counts["top"]
        if source_status["top"].get("enabled") and stats.get("failed") and not source_status["top"].get("failed"):
            arxiv_failed = int(source_status["arxiv"].get("failed", 0) or 0)
            source_status["top"]["failed"] = max(0, int(stats.get("failed", 0)) - arxiv_failed)
        for state in source_status.values():
            _finalize_source_status(state)
        stats["raw"] = sum(int(v.get("raw", 0)) for v in source_status.values())
        stats["deduped"] = len(scored)
        stats["displayed"] = len(scored)
        stats["inserted"] = storage.inserted_count
        stats["updated"] = storage.updated_count
        stats["elapsed_seconds"] = int(time.monotonic() - start_time)
        stats["source_status"] = source_status
        stats["source_counts"] = counts
        stats["status"] = "stopped" if should_stop() else ("partial_completed" if stats["failed"] else "completed")
        return RunResult(scored, dict(stats))

    def _run_crossref(self, top_journals: list[dict[str, Any]], queries: list[str], all_seen: list[Paper], stats: Counter, completed: int, total_steps: int, rows_per_query: int, timeout: int, max_retries: int, retry_delay: int, max_workers: int, delay: float, cache_enabled: bool, should_stop: Callable[[], bool], progress: ProgressCallback) -> int:
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
            if should_stop() or task_index >= len(tasks):
                return
            journal, query, issns = tasks[task_index]
            task_index += 1
            cache_key = ("crossref", str(journal.get("name")), query, self.from_date.isoformat(), self.until_date.isoformat())
            if cache_enabled and self.db.is_query_cached_today(*cache_key):
                completed += 1
                stats["cached"] += 1
                stats["cache_hit"] += 1
                self._emit_progress(stats, completed, total_steps, str(journal.get("name")), query, all_seen, progress)
                submit_next(executor)
                return
            future = executor.submit(CrossrefClient(timeout=timeout, rows=rows_per_query, max_retries=max_retries, retry_delay_seconds=retry_delay).fetch_journal_works, str(journal.get("name")), issns, query, self.from_date, self.until_date)
            pending[future] = (journal, query, cache_key)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for _ in range(min(max_workers, len(tasks))):
                submit_next(executor)
            while pending and not should_stop():
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
                        self._handle_batch(batch_papers, all_seen, stats, completed, total_steps, str(journal.get("name")), query, progress)
                        batch_papers = []
                    else:
                        self._emit_progress(stats, completed, total_steps, str(journal.get("name")), query, all_seen, progress)
                    if delay > 0:
                        time.sleep(delay)
                    submit_next(executor)
        if batch_papers:
            self._handle_batch(batch_papers, all_seen, stats, completed, total_steps, "\u9876\u7ea7\u671f\u520a", "\u6279\u91cf\u7ed3\u679c", progress)
        if stats.get("cache_hit"):
            cached = self.db.load_papers_for_period(self.from_date.isoformat(), self.until_date.isoformat(), ("crossref", "journal_rss", "arxiv"))
            if cached:
                self._handle_batch(cached, all_seen, stats, completed, total_steps, "\u672c\u5730\u7f13\u5b58", "\u4eca\u65e5\u5df2\u7f13\u5b58\u7ed3\u679c", progress)
        return completed

    def _handle_batch(self, batch: list[Paper], all_seen: list[Paper], stats: Counter, completed: int, total: int, journal: str, query: str, progress: ProgressCallback) -> None:
        all_seen.extend(batch)
        scored = score_and_tag(dedupe_papers(all_seen), self.keyword_filter, keep_unmatched=False)
        storage = self.db.upsert_papers_with_stats(scored)
        stats["deduped"] = len(scored)
        stats["matched"] = len(scored)
        stats["displayed"] = len(scored)
        stats["inserted"] += storage.inserted_count
        stats["updated"] += storage.updated_count
        progress("batch", {"papers": scored, **dict(stats)})
        self._emit_progress(stats, completed, total, journal, query, all_seen, progress)

    def _emit_progress(self, stats: Counter, completed: int, total: int, journal: str, query: str, all_seen: list[Paper], progress: ProgressCallback) -> None:
        progress("progress", {"completed": completed, "total": max(total, 1), "journal": journal, "query": query, "found": len(all_seen), "deduped": stats.get("deduped", 0), "matched": stats.get("matched", 0), "displayed": stats.get("displayed", 0), "success": stats.get("success", 0), "failed": stats.get("failed", 0), "cached": stats.get("cached", 0), "cache_hit": stats.get("cache_hit", 0), "timeouts": stats.get("timeouts", 0)})


def generate_daily_report_file(papers: list[Paper]):
    return generate_daily_report(papers)


def generate_survey_report_file(papers: list[Paper], task_name: str, from_date: date, until_date: date):
    return generate_survey_report(papers, task_name, from_date, until_date)


def open_reports_folder() -> None:
    open_folder(REPORTS_DIR)


def open_paper_url(paper: Paper) -> None:
    if paper.url:
        open_url(paper.url)
