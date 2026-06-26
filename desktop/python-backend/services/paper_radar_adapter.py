from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paper_radar.database import PaperDatabase
from paper_radar.models import Paper
from paper_radar.services import DailySearchService, HistoricalSurveyService
from paper_radar.profile_manager import (
    delete_profile,
    load_active_profile,
    load_all_profiles,
    save_profile,
    set_active_profile,
)


def _split_authors(value: str) -> list[str]:
    return [item.strip() for item in (value or "").replace(";", ",").split(",") if item.strip()]


def _source_label(paper: Paper) -> str:
    source_type = (paper.source_type or "").strip().lower()
    source = (paper.journal_or_source or "").strip().strip("|｜:：")
    lower = source.lower()

    if source_type == "arxiv" or "arxiv" in lower:
        return "arXiv"
    if "nature communications" in lower or lower == "nature comm.":
        return "Nature Comm."
    if lower == "nature":
        return "Nature"

    broken_markers = ("�", "鐨", "椤", "鏈", "鍒")
    generic_values = {"", "other", "top journal", "top journals", "顶级期刊"}
    if not source or lower in generic_values or any(marker in source for marker in broken_markers):
        return "期刊名缺失"
    return source[:40]


def _paper_status(score: int) -> str:
    if score >= 80:
        return "worth-reading"
    if score > 0:
        return "candidate"
    return "stored"


def paper_to_api(paper: Paper) -> dict[str, Any]:
    title = paper.title or "未命名论文"
    identity = paper.doi or paper.arxiv_id or paper.url or title
    return {
        "id": str(abs(hash(identity))),
        "title": title,
        "authors": _split_authors(paper.authors),
        "source": _source_label(paper),
        "publishedDate": (paper.published_date or "")[:10],
        "score": int(paper.relevance_score or 0),
        "matchedKeywords": list(paper.matched_keywords or []),
        "abstract": paper.abstract or "暂无摘要。",
        "url": paper.url or None,
        "doi": paper.doi or None,
        "status": _paper_status(int(paper.relevance_score or 0)),
    }


def _source_summary(papers: list[Paper], source_key: str, label: str) -> dict[str, Any]:
    if source_key == "arxiv":
        count = sum(1 for paper in papers if (paper.source_type or "") == "arxiv")
    else:
        count = sum(1 for paper in papers if (paper.source_type or "") in {"crossref", "journal_rss"})
    return {
        "label": label,
        "enabled": True,
        "status": "success" if count else "pending",
        "fetched": count,
        "stored": count,
        "displayed": count,
        "failed": 0,
        "error": None,
    }


def paper_summary(papers: list[Paper]) -> dict[str, Any]:
    return {
        "totalFetched": len(papers),
        "candidateCount": len(papers),
        "displayedCount": len(papers),
        "hiddenCount": 0,
        "failedCount": 0,
        "sources": {
            "arxiv": _source_summary(papers, "arxiv", "arXiv"),
            "journals": _source_summary(papers, "journals", "顶级期刊"),
        },
    }


def load_today_payload(min_score: int = 0) -> dict[str, Any]:
    papers = PaperDatabase().load_papers(min_score=min_score)
    return {"papers": [paper_to_api(paper) for paper in papers], "summary": paper_summary(papers)}


def load_history_payload(days: int = 365, min_score: int = 0) -> dict[str, Any]:
    until = date.today()
    since = until - timedelta(days=max(1, days))
    papers = [paper for paper in PaperDatabase().load_papers_for_period(since.isoformat(), until.isoformat(), ("arxiv", "crossref", "journal_rss")) if int(paper.relevance_score or 0) >= min_score]
    return {"papers": [paper_to_api(paper) for paper in papers], "summary": paper_summary(papers)}


def _profile_keywords(profile: dict[str, Any]) -> list[dict[str, str]]:
    keywords: list[dict[str, str]] = []
    groups = profile.get("keyword_groups") or {}
    if isinstance(groups, dict):
        for group_name, group in groups.items():
            if not isinstance(group, dict):
                continue
            weight = str(group.get("priority") or "medium")
            if weight not in {"high", "medium", "low"}:
                weight = "medium"
            for term in group.get("terms") or []:
                text = str(term).strip()
                if text:
                    keywords.append({"group": str(group_name), "weight": weight, "text": text})
    return keywords


def profile_to_api(profile: dict[str, Any], active_id: str) -> dict[str, Any]:
    keywords = _profile_keywords(profile)
    return {
        "id": str(profile.get("profile_id") or ""),
        "name": str(profile.get("display_name") or profile.get("profile_id") or "未命名方向"),
        "description": str(profile.get("description") or ""),
        "queryCount": len(profile.get("search_queries") or []),
        "keywordGroupCount": len(profile.get("keyword_groups") or {}),
        "isCurrent": str(profile.get("profile_id") or "") == active_id,
        "keywords": keywords,
    }


def load_profiles_payload() -> dict[str, Any]:
    active = load_active_profile()
    active_id = str(active.get("profile_id") or "")
    profiles = load_all_profiles()
    return {"profiles": [profile_to_api(profile, active_id) for profile in profiles]}


def save_profile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(payload.get("id") or payload.get("profile_id") or "").strip()
    profile = {
        "profile_version": 1,
        "profile_id": profile_id,
        "display_name": str(payload.get("name") or payload.get("display_name") or profile_id),
        "description": str(payload.get("description") or ""),
        "search_queries": payload.get("search_queries") or [],
        "keyword_groups": payload.get("keyword_groups") or {},
        "exclude_terms": payload.get("exclude_terms") or [],
        "recommended_journals": payload.get("recommended_journals") or [],
    }
    save_profile(profile)
    if bool(payload.get("isCurrent") or payload.get("is_current")):
        set_active_profile(profile_id)
    return {"accepted": True, "profile": profile_to_api(profile, profile_id if payload.get("isCurrent") else "")}


def delete_profile_payload(profile_id: str) -> dict[str, Any]:
    delete_profile(profile_id)
    return {"accepted": True, "profile_id": profile_id}





def _normalize_source_status(raw: dict[str, Any], label: str) -> dict[str, Any]:
    status = str(raw.get("status") or "pending")
    if status == "empty":
        status = "success"
    if status not in {"success", "partial", "failed", "timeout", "disabled", "pending"}:
        status = "pending"
    return {
        "label": label,
        "enabled": bool(raw.get("enabled", True)),
        "status": status,
        "fetched": int(raw.get("raw", raw.get("fetched", 0)) or 0),
        "stored": int(raw.get("stored", 0) or 0),
        "displayed": int(raw.get("stored", raw.get("displayed", 0)) or 0),
        "failed": int(raw.get("failed", 0) or 0),
        "error": raw.get("reason") or raw.get("error") or None,
    }


def summary_from_run(papers: list[Paper], stats: dict[str, Any]) -> dict[str, Any]:
    source_status = stats.get("source_status") or {}
    return {
        "totalFetched": int(stats.get("raw", len(papers)) or 0),
        "candidateCount": int(stats.get("deduped", len(papers)) or 0),
        "displayedCount": int(stats.get("displayed", len(papers)) or 0),
        "hiddenCount": 0,
        "failedCount": int(stats.get("failed", 0) or 0),
        "sources": {
            "arxiv": _normalize_source_status(source_status.get("arxiv", {}), "arXiv"),
            "journals": _normalize_source_status(source_status.get("top", {}), "顶级期刊"),
        },
    }


def run_today_check_payload(days_back: int = 7, min_score: int = 0, arxiv: bool = True, journals: bool = True) -> dict[str, Any]:
    service = DailySearchService(
        days_back=max(1, int(days_back or 7)),
        sources={"arxiv": bool(arxiv), "rss": bool(journals), "crossref": bool(journals)},
    )
    result = service.run()
    papers = [paper for paper in result.papers if int(paper.relevance_score or 0) >= int(min_score or 0)]
    return {"papers": [paper_to_api(paper) for paper in papers], "summary": summary_from_run(papers, result.stats)}


def run_history_survey_payload(days: int = 365, min_score: int = 0, arxiv: bool = True, journals: bool = True, task_name: str = "当前方向历史调研") -> dict[str, Any]:
    until = date.today()
    since = until - timedelta(days=max(1, int(days or 365)))
    service = HistoricalSurveyService(
        task_name=task_name or "当前方向历史调研",
        from_date=since,
        until_date=until,
        sources={"arxiv": bool(arxiv), "rss": bool(journals), "crossref": bool(journals)},
    )
    result = service.run()
    papers = [paper for paper in result.papers if int(paper.relevance_score or 0) >= int(min_score or 0)]
    return {"papers": [paper_to_api(paper) for paper in papers], "summary": summary_from_run(papers, result.stats)}


