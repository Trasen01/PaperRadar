from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import Paper
from .utils import DATA_DIR, ensure_directories, title_hash

logger = logging.getLogger(__name__)


@dataclass
class UpsertStats:
    total: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0


class PaperDatabase:
    def __init__(self, db_path: Path | None = None) -> None:
        ensure_directories()
        self.db_path = db_path or (DATA_DIR / "papers.sqlite")
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    arxiv_id TEXT,
                    title_hash TEXT,
                    title TEXT NOT NULL,
                    authors TEXT,
                    abstract TEXT,
                    published_date TEXT,
                    updated_date TEXT,
                    url TEXT,
                    doi TEXT,
                    journal_or_source TEXT,
                    source_type TEXT,
                    source_quality_score INTEGER,
                    categories TEXT,
                    primary_category TEXT,
                    matched_keywords TEXT,
                    matched_fields TEXT,
                    relevance_score INTEGER,
                    reason_zh TEXT,
                    score_breakdown TEXT,
                    first_seen_at TEXT,
                    last_seen_at TEXT
                )
                """
            )
            self._ensure_column(conn, "doi", "TEXT")
            self._ensure_column(conn, "journal_or_source", "TEXT")
            self._ensure_column(conn, "source_type", "TEXT")
            self._ensure_column(conn, "source_quality_score", "INTEGER")
            self._ensure_column(conn, "matched_fields", "TEXT")
            self._ensure_column(conn, "score_breakdown", "TEXT")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_arxiv_id ON papers(arxiv_id)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_title_hash ON papers(title_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_url ON papers(url)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS search_query_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT,
                    journal_name TEXT,
                    query TEXT,
                    from_date TEXT,
                    until_date TEXT,
                    cache_key TEXT,
                    last_run_at TEXT,
                    result_count INTEGER,
                    status TEXT,
                    cached_result_path TEXT,
                    error_message TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_search_query_cache_key
                ON search_query_cache(source_type, journal_name, query, from_date, until_date)
                """
            )
            existing_cache_cols = {row["name"] for row in conn.execute("PRAGMA table_info(search_query_cache)").fetchall()}
            for column, column_type in {
                "cache_key": "TEXT",
                "cached_result_path": "TEXT",
                "error_message": "TEXT",
            }.items():
                if column not in existing_cache_cols:
                    conn.execute(f"ALTER TABLE search_query_cache ADD COLUMN {column} {column_type}")

    def _ensure_column(self, conn: sqlite3.Connection, column: str, column_type: str) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(papers)").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE papers ADD COLUMN {column} {column_type}")

    def upsert_papers(self, papers: list[Paper]) -> tuple[int, int]:
        stats = self.upsert_papers_with_stats(papers)
        return stats.total, stats.inserted_count

    def upsert_papers_with_stats(self, papers: list[Paper]) -> UpsertStats:
        stats = UpsertStats(total=len(papers))
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            for paper in papers:
                if not paper.title:
                    stats.skipped_count += 1
                    continue
                existing = self._find_existing(conn, paper)
                if existing:
                    if self._source_priority(existing["source_type"]) > self._source_priority(paper.source_type):
                        stats.skipped_count += 1
                        continue
                    conn.execute(
                        """
                        UPDATE papers
                        SET title=?, authors=?, abstract=?, published_date=?, updated_date=?, url=?,
                            doi=?, journal_or_source=?, source_type=?, source_quality_score=?,
                            categories=?, primary_category=?, matched_keywords=?, matched_fields=?, relevance_score=?,
                            reason_zh=?, score_breakdown=?, last_seen_at=?
                        WHERE id=?
                        """,
                        self._paper_values(paper) + (now, existing["id"]),
                    )
                    stats.updated_count += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO papers (
                            arxiv_id, title_hash, title, authors, abstract, published_date, updated_date,
                            url, doi, journal_or_source, source_type, source_quality_score,
                            categories, primary_category, matched_keywords, matched_fields, relevance_score,
                            reason_zh, score_breakdown, first_seen_at, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            paper.arxiv_id or None,
                            title_hash(paper.title),
                            *self._paper_values(paper),
                            now,
                            now,
                        ),
                    )
                    stats.inserted_count += 1
        return stats

    def _find_existing(self, conn: sqlite3.Connection, paper: Paper) -> sqlite3.Row | None:
        if paper.arxiv_id:
            row = conn.execute("SELECT id, source_type FROM papers WHERE arxiv_id=?", (paper.arxiv_id,)).fetchone()
            if row:
                return row
        if paper.doi:
            row = conn.execute("SELECT id, source_type FROM papers WHERE lower(doi)=lower(?)", (paper.doi,)).fetchone()
            if row:
                return row
        if paper.url:
            row = conn.execute("SELECT id, source_type FROM papers WHERE url=?", (paper.url,)).fetchone()
            if row:
                return row
        return conn.execute("SELECT id, source_type FROM papers WHERE title_hash=?", (title_hash(paper.title),)).fetchone()

    @staticmethod
    def _source_priority(source_type: str | None) -> int:
        return {"crossref": 3, "journal_rss": 2, "arxiv": 1}.get(source_type or "", 0)

    def _paper_values(self, paper: Paper) -> tuple:
        return (
            paper.title,
            paper.authors,
            paper.abstract,
            paper.published_date,
            paper.updated_date,
            paper.url,
            paper.doi,
            paper.journal_or_source,
            paper.source_type,
            int(paper.source_quality_score),
            json.dumps(paper.categories, ensure_ascii=False),
            paper.primary_category,
            json.dumps(paper.matched_keywords, ensure_ascii=False),
            json.dumps(paper.matched_fields, ensure_ascii=False),
            int(paper.relevance_score),
            paper.reason_zh,
            json.dumps(paper.score_breakdown, ensure_ascii=False),
        )

    def load_papers(self, min_score: int = 0) -> list[Paper]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM papers
                WHERE relevance_score >= ?
                ORDER BY relevance_score DESC, published_date DESC
                """,
                (min_score,),
            ).fetchall()
        return [self._row_to_paper(row) for row in rows]

    def load_papers_for_period(self, from_date: str, until_date: str, source_types: tuple[str, ...]) -> list[Paper]:
        if not source_types:
            return []
        placeholders = ",".join("?" for _ in source_types)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM papers
                WHERE substr(published_date, 1, 10) >= ?
                  AND substr(published_date, 1, 10) <= ?
                  AND source_type IN ({placeholders})
                ORDER BY relevance_score DESC, published_date DESC
                """,
                (from_date, until_date, *source_types),
            ).fetchall()
        return [self._row_to_paper(row) for row in rows]

    def is_query_cached_today(
        self,
        source_type: str,
        journal_name: str,
        query: str,
        from_date: str,
        until_date: str,
    ) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT last_run_at, status FROM search_query_cache
                WHERE source_type=? AND journal_name=? AND query=? AND from_date=? AND until_date=?
                """,
                (source_type, journal_name, query, from_date, until_date),
            ).fetchone()
        if not row or row["status"] != "ok":
            return False
        try:
            last_run = datetime.fromisoformat(row["last_run_at"])
            return last_run.date() == datetime.now().date()
        except Exception:
            return False

    def is_query_cached(
        self,
        source_type: str,
        journal_name: str,
        query: str,
        from_date: str,
        until_date: str,
        cache_hours: int,
    ) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT last_run_at, status FROM search_query_cache
                WHERE source_type=? AND journal_name=? AND query=? AND from_date=? AND until_date=?
                """,
                (source_type, journal_name, query, from_date, until_date),
            ).fetchone()
        if not row or row["status"] != "ok":
            return False
        try:
            last_run = datetime.fromisoformat(row["last_run_at"])
            age_hours = (datetime.now() - last_run).total_seconds() / 3600
            return age_hours <= cache_hours
        except Exception:
            return False

    def mark_query_cache(
        self,
        source_type: str,
        journal_name: str,
        query: str,
        from_date: str,
        until_date: str,
        result_count: int,
        status: str,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        cache_key = "|".join([source_type, journal_name, query, from_date, until_date])
        error_message = status if status != "ok" else ""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO search_query_cache (
                    source_type, journal_name, query, from_date, until_date, cache_key, last_run_at, result_count, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, journal_name, query, from_date, until_date)
                DO UPDATE SET cache_key=excluded.cache_key, last_run_at=excluded.last_run_at, result_count=excluded.result_count, status=excluded.status, error_message=excluded.error_message
                """,
                (source_type, journal_name, query, from_date, until_date, cache_key, now, int(result_count), status, error_message),
            )

    def _row_to_paper(self, row: sqlite3.Row) -> Paper:
        return Paper(
            title=row["title"] or "",
            authors=row["authors"] or "",
            abstract=row["abstract"] or "",
            published_date=row["published_date"] or "",
            updated_date=row["updated_date"] or "",
            url=row["url"] or "",
            arxiv_id=row["arxiv_id"] or "",
            doi=row["doi"] or "",
            journal_or_source=row["journal_or_source"] or ("arXiv" if row["arxiv_id"] else ""),
            source_type=row["source_type"] or ("arxiv" if row["arxiv_id"] else "journal_rss"),
            source_quality_score=int(row["source_quality_score"] or (5 if row["arxiv_id"] else 0)),
            categories=json.loads(row["categories"] or "[]"),
            primary_category=row["primary_category"] or "",
            matched_keywords=json.loads(row["matched_keywords"] or "[]"),
            matched_fields=json.loads(row["matched_fields"] or "[]") if "matched_fields" in row.keys() else [],
            relevance_score=int(row["relevance_score"] or 0),
            reason_zh=row["reason_zh"] or "",
            score_breakdown=json.loads(row["score_breakdown"] or "{}") if "score_breakdown" in row.keys() else {},
        )
