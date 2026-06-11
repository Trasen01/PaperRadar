from pathlib import Path

from paper_radar.database import PaperDatabase
from paper_radar.journal_fetcher import JournalRssFetcher
from paper_radar.keyword_filter import KeywordFilter
from paper_radar.scorer import score_paper
from paper_radar.settings import DEFAULT_KEYWORDS
from paper_radar.utils import format_date_only


def test_sample_journal_feed_runs_without_arxiv_id(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "sample_journal_feed.xml"
    source = {
        "name": "Sample Journal",
        "type": "rss",
        "enabled": True,
        "feed_url": str(fixture),
        "quality_score": 18,
    }

    result = JournalRssFetcher().parse_feed_content(source, fixture.read_bytes(), days_back=30)

    assert result.stats.source_stats[0].fetched_raw_count == 3
    assert len(result.papers) == 3
    assert all(not paper.arxiv_id for paper in result.papers)
    assert all(paper.journal_or_source == "Sample Journal" for paper in result.papers)
    assert all(paper.source_type == "journal_rss" for paper in result.papers)
    assert format_date_only(result.papers[0].published_date) == "2026-06-01"

    matcher = KeywordFilter(DEFAULT_KEYWORDS)
    scored = []
    for paper in result.papers:
        locations = matcher.match_with_locations(paper)
        matches = matcher.flatten_location_matches(locations)
        paper.matched_keywords = matcher.flatten_matches(matches)
        paper.relevance_score, paper.reason_zh = score_paper(
            paper, matches, matcher.title_matches(paper), locations
        )
        scored.append((paper, matches))

    assert "optical_neural_networks" in scored[0][1]
    assert "linear_algebra_computing" in scored[0][1]
    assert "high_precision_core" in scored[1][1]
    assert "processors_and_architectures" in scored[1][1]
    assert scored[2][0].relevance_score < scored[0][0].relevance_score

    db = PaperDatabase(tmp_path / "papers.sqlite")
    stats = db.upsert_papers_with_stats(result.papers)
    loaded = db.load_papers(0)

    assert stats.inserted_count == 3
    assert len(loaded) == 3
    assert {paper.source_type for paper in loaded} == {"journal_rss"}
