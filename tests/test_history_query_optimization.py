from pathlib import Path

import yaml

from optical_radar import crossref_client
from optical_radar.cache_manager import enforce_cache_limit
from optical_radar.profile_terms import sanitize_search_queries


def test_sanitize_search_queries_filters_journals_and_broad_terms():
    queries, removed = sanitize_search_queries(
        [
            "Nature",
            "Science",
            "Optica",
            "Light",
            "photonics",
            "integrated photonics",
            "silicon photonics",
            "metasurface",
            "thin-film lithium niobate modulator",
        ],
        max_queries=20,
    )
    assert queries == [
        "integrated photonics",
        "silicon photonics",
        "metasurface",
        "thin-film lithium niobate modulator",
    ]
    assert "Nature" in removed
    assert "Science" in removed
    assert "Optica" in removed
    assert "Light" in removed


def test_remote_queries_use_active_profile_search_queries_not_keyword_groups(monkeypatch):
    monkeypatch.setattr(
        crossref_client,
        "active_profile_search_queries",
        lambda max_queries=40: ["thin-film lithium niobate modulator", "Nature"],
    )
    profile_keywords = {
        "core": [f"keyword {index}" for index in range(80)],
        "exclude": ["biomedical imaging"],
    }
    queries = crossref_client.build_search_queries_from_keywords(profile_keywords, max_queries=20)
    assert queries == ["thin-film lithium niobate modulator"]


def test_search_queries_are_truncated_to_20(monkeypatch):
    monkeypatch.setattr(
        crossref_client,
        "active_profile_search_queries",
        lambda max_queries=40: [f"specific research query {index}" for index in range(25)],
    )
    queries = crossref_client.build_search_queries_from_keywords({}, max_queries=20)
    assert len(queries) == 20


def test_default_optical_profile_removes_overbroad_terms():
    profile = yaml.safe_load(Path("resources/default_profiles/optical_computing.yaml").read_text(encoding="utf-8"))
    queries = {str(query).lower() for query in profile["search_queries"]}
    terms = {
        str(term).lower()
        for group in profile["keyword_groups"].values()
        for term in group.get("terms", [])
    }
    forbidden = {"metasurface", "metasurfaces", "integrated photonics", "silicon photonics"}
    assert not forbidden & queries
    assert not forbidden & terms


def test_cache_manager_only_cleans_cache_dir(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    old_file = cache_dir / "old.bin"
    old_file.write_bytes(b"x" * 2048)

    protected_dirs = ["profiles", "data", "reports", "logs"]
    for name in protected_dirs:
        directory = tmp_path / name
        directory.mkdir()
        (directory / "keep.txt").write_text("keep", encoding="utf-8")

    result = enforce_cache_limit(max_size_gb=0.0000001, cache_dir=cache_dir)
    assert result.triggered
    assert result.deleted_files >= 1
    for name in protected_dirs:
        assert (tmp_path / name / "keep.txt").exists()
