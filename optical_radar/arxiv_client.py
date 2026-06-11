from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

import requests
from dateutil import parser as date_parser

from .models import Paper
from .network import retry_call
from .profile_manager import active_profile_search_queries
from .profile_terms import sanitize_search_queries
from .utils import normalize_space

logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
DEFAULT_CATEGORIES = ["physics.optics", "cs.ET", "cs.AI", "cs.LG", "quant-ph"]
DEFAULT_QUERY_TERMS = [
    "optical computing",
    "photonic computing",
    "optical neural network",
    "photonic neural network",
]


class ArxivClient:
    def __init__(self, timeout: int = 20, max_retries: int = 3, retry_delay_seconds: int = 3) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

    def fetch_recent(self, days_back: int = 7, max_results: int = 100) -> list[Paper]:
        category_query = " OR ".join(f"cat:{cat}" for cat in DEFAULT_CATEGORIES)
        terms, removed = sanitize_search_queries(active_profile_search_queries(max_queries=40), max_queries=20)
        if removed:
            logger.info("ARXIV_SEARCH_QUERY_FILTERED removed=%s final=%s", removed, terms)
        terms = terms or DEFAULT_QUERY_TERMS
        term_query = " OR ".join(f'all:"{term}"' for term in terms)
        search_query = f"({category_query}) AND ({term_query})"
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = f"{ARXIV_API_URL}?{urlencode(params)}"
        logger.info("Fetching arXiv: %s", url)
        response = retry_call(
            lambda: requests.get(url, timeout=self.timeout),
            source_type="arxiv",
            query=search_query,
            timeout=self.timeout,
            max_retries=self.max_retries,
            retry_delay_seconds=self.retry_delay_seconds,
        )
        response.raise_for_status()

        cutoff = datetime.now(timezone.utc) - timedelta(days=max(days_back, 0))
        papers: list[Paper] = []
        root = ET.fromstring(response.text)
        for entry in root.findall("atom:entry", ARXIV_NS):
            try:
                paper = self._parse_entry(entry)
                published_dt = date_parser.parse(paper.published_date)
                if published_dt.tzinfo is None:
                    published_dt = published_dt.replace(tzinfo=timezone.utc)
                if published_dt >= cutoff:
                    papers.append(paper)
            except Exception:
                logger.exception("Failed to parse arXiv entry")
        return papers

    def _parse_entry(self, entry: ET.Element) -> Paper:
        entry_id = self._text(entry, "atom:id")
        arxiv_id = entry_id.rstrip("/").split("/")[-1] if entry_id else ""
        title = normalize_space(self._text(entry, "atom:title"))
        abstract = normalize_space(self._text(entry, "atom:summary"))
        published = self._text(entry, "atom:published")
        updated = self._text(entry, "atom:updated")
        authors = ", ".join(
            normalize_space(author.findtext("atom:name", default="", namespaces=ARXIV_NS))
            for author in entry.findall("atom:author", ARXIV_NS)
        )
        categories = [
            category.attrib.get("term", "")
            for category in entry.findall("atom:category", ARXIV_NS)
            if category.attrib.get("term")
        ]
        primary_category_elem = entry.find("arxiv:primary_category", ARXIV_NS)
        primary_category = ""
        if primary_category_elem is not None:
            primary_category = primary_category_elem.attrib.get("term", "")
        url = entry_id
        for link in entry.findall("atom:link", ARXIV_NS):
            if link.attrib.get("rel") == "alternate":
                url = link.attrib.get("href", url)
                break
        return Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            published_date=published,
            updated_date=updated,
            url=url,
            arxiv_id=arxiv_id,
            journal_or_source="arXiv",
            source_type="arxiv",
            source_quality_score=5,
            categories=categories,
            primary_category=primary_category or (categories[0] if categories else ""),
        )

    def _text(self, entry: ET.Element, path: str) -> str:
        return entry.findtext(path, default="", namespaces=ARXIV_NS) or ""
