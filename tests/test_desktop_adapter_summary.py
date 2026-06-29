from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop" / "python-backend"))

from paper_radar.models import Paper
from services.paper_radar_adapter import summary_from_run


def test_summary_from_run_reports_displayed_counts_after_score_filter() -> None:
    displayed_papers = [
        Paper(title="arxiv hit", source_type="arxiv", relevance_score=100),
        Paper(title="journal hit", source_type="crossref", journal_or_source="Nature", relevance_score=35),
    ]
    stats = {
        "raw": 160,
        "deduped": 160,
        "displayed": 160,
        "failed": 0,
        "source_status": {
            "arxiv": {"enabled": True, "status": "success", "raw": 26, "stored": 26, "failed": 0},
            "top": {"enabled": True, "status": "success", "raw": 134, "stored": 134, "failed": 0},
        },
    }

    summary = summary_from_run(displayed_papers, stats)

    assert summary["candidateCount"] == 160
    assert summary["displayedCount"] == 2
    assert summary["hiddenCount"] == 158
    assert summary["sources"]["arxiv"]["displayed"] == 1
    assert summary["sources"]["journals"]["displayed"] == 1
    assert summary["sources"]["journals"]["stored"] == 134


def test_summary_from_run_does_not_count_partial_source_as_fatal_failure() -> None:
    displayed_papers = [
        Paper(title="journal hit", source_type="crossref", journal_or_source="Nature", relevance_score=100),
    ]
    stats = {
        "raw": 189,
        "deduped": 188,
        "failed": 1,
        "source_status": {
            "arxiv": {"enabled": True, "status": "success", "raw": 5, "stored": 2, "failed": 0},
            "top": {
                "enabled": True,
                "status": "partial",
                "raw": 184,
                "stored": 186,
                "failed": 1,
                "reason": "Nature | photonic computing: 429 Client Error",
            },
        },
    }

    summary = summary_from_run(displayed_papers, stats)

    assert summary["failedCount"] == 0
    assert summary["sources"]["journals"]["status"] == "partial"
    assert summary["sources"]["journals"]["failed"] == 1
    assert "429 Client Error" in summary["sources"]["journals"]["error"]
