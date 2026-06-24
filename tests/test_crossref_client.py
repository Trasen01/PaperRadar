from __future__ import annotations

from datetime import date

from paper_radar.crossref_client import CrossrefClient


def test_fetch_journal_works_returns_result_without_missing_method(monkeypatch):
    client = CrossrefClient(rows=1, sleep_seconds=0)

    def fake_query(journal, issns, query, from_date, until_date):
        assert journal["name"] == "Nature"
        assert issns == ["0028-0836"]
        assert query == "photonic computing"
        assert from_date == date(2026, 1, 1)
        assert until_date == date(2026, 6, 23)
        return [
            {
                "title": ["Photonic computing test"],
                "author": [{"given": "Ada", "family": "Lovelace"}],
                "DOI": "10.1000/test",
                "URL": "https://doi.org/10.1000/test",
                "published-online": {"date-parts": [[2026, 6, 1]]},
                "container-title": ["Nature"],
                "subject": ["Optics"],
            }
        ]

    monkeypatch.setattr(client, "_query", fake_query)

    result = client.fetch_journal_works(
        "Nature",
        ["0028-0836"],
        "photonic computing",
        date(2026, 1, 1),
        date(2026, 6, 23),
    )

    assert result.failed_requests == []
    assert len(result.papers) == 1
    assert result.papers[0].title == "Photonic computing test"
    assert result.papers[0].url == "https://doi.org/10.1000/test"
    assert result.query_stats[0].parsed_count == 1
