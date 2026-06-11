from optical_radar.keyword_filter import KeywordFilter
from optical_radar.models import Paper
from optical_radar.profile_manager import parse_profile_input
from optical_radar.scorer import score_paper


PROFILE_TEXT = """
profile_version: 1
profile_id: lithium_niobate_modulators
display_name: Lithium Niobate Modulators
description: Thin-film lithium niobate electro-optic modulators.
search_queries:
  - Nature
  - Science
  - Optica
  - lithium niobate modulator
  - thin-film lithium niobate electro-optic modulator
keyword_groups:
  core:
    priority: high
    terms:
      - Nature
      - Science
      - Optica
      - lithium niobate modulator
      - thin-film lithium niobate electro-optic modulator
exclude_terms:
  - biomedical imaging
recommended_journals:
  - Nature
  - Science
  - Optica
  - Light: Science & Applications
"""


def _filter_from_profile() -> tuple[KeywordFilter, dict]:
    result = parse_profile_input(PROFILE_TEXT)
    assert result.ok
    groups = {
        name: list(group.get("terms") or [])
        for name, group in result.profile["keyword_groups"].items()
    }
    groups["exclude"] = result.profile["exclude_terms"]
    return KeywordFilter(groups), result.profile


def test_recommended_journals_do_not_become_keywords_or_queries():
    _, profile = _filter_from_profile()
    all_terms = [term for group in profile["keyword_groups"].values() for term in group["terms"]]
    lowered_terms = {term.lower() for term in all_terms}
    lowered_queries = {query.lower() for query in profile["search_queries"]}

    assert "nature" not in lowered_terms
    assert "science" not in lowered_terms
    assert "optica" not in lowered_terms
    assert "nature" not in lowered_queries
    assert "science" not in lowered_queries
    assert "optica" not in lowered_queries
    assert profile["recommended_journals"][:2] == ["Nature", "Science"]


def test_journal_source_nature_without_research_keywords_scores_low():
    keyword_filter, _ = _filter_from_profile()
    paper = Paper(
        title="Single-cell immune atlas of crop disease resistance",
        abstract="A biology and agriculture study with no electro-optic modulation content.",
        journal_or_source="Nature",
        source_type="crossref",
        source_quality_score=20,
        categories=["biology"],
    )
    locations = keyword_filter.match_with_locations(paper)
    matches = keyword_filter.flatten_location_matches(locations)
    score, _ = score_paper(paper, matches, keyword_filter.title_matches(paper), locations)

    assert paper.matched_keywords == []
    assert score <= 15
    assert paper.score_breakdown["has_positive_keyword_hit"] is False


def test_title_research_keyword_scores_high_even_from_top_journal():
    keyword_filter, _ = _filter_from_profile()
    paper = Paper(
        title="Thin-film lithium niobate modulator with low Vpi",
        abstract="An integrated electro-optic modulator for high-speed photonic systems.",
        journal_or_source="Nature Photonics",
        source_type="crossref",
        source_quality_score=20,
        categories=["optics"],
    )
    locations = keyword_filter.match_with_locations(paper)
    matches = keyword_filter.flatten_location_matches(locations)
    paper.matched_keywords = keyword_filter.flatten_matches(matches)
    score, _ = score_paper(paper, matches, keyword_filter.title_matches(paper), locations)

    assert "thin-film lithium niobate electro-optic modulator" not in paper.matched_keywords
    assert "lithium niobate modulator" in paper.matched_keywords
    assert score >= 40
    assert paper.score_breakdown["source_quality_score"] == 20


def test_abstract_research_keyword_matches():
    keyword_filter, _ = _filter_from_profile()
    paper = Paper(
        title="A compact integrated photonic device",
        abstract="We demonstrate a thin-film lithium niobate electro-optic modulator for high-speed operation.",
        journal_or_source="Science",
        source_type="crossref",
        source_quality_score=20,
        categories=["optics"],
    )
    locations = keyword_filter.match_with_locations(paper)
    matches = keyword_filter.flatten_location_matches(locations)
    paper.matched_keywords = keyword_filter.flatten_matches(matches)

    assert "thin-film lithium niobate electro-optic modulator" in paper.matched_keywords
    assert "Science" not in paper.matched_keywords


def test_combined_title_and_abstract_hits_get_combo_bonus():
    keyword_filter, _ = _filter_from_profile()
    paper = Paper(
        title="Lithium niobate modulator for compact photonic links",
        abstract="The thin-film lithium niobate electro-optic modulator shows low voltage operation.",
        journal_or_source="Nature Photonics",
        source_type="crossref",
        source_quality_score=20,
        categories=["optics"],
    )
    locations = keyword_filter.match_with_locations(paper)
    matches = keyword_filter.flatten_location_matches(locations)
    score, _ = score_paper(paper, matches, keyword_filter.title_matches(paper), locations)

    assert score >= 50
    assert paper.score_breakdown["combo_bonus"] > 0
    assert paper.score_breakdown["strong_title_hit"] is True


def test_broad_single_term_is_capped():
    keyword_filter = KeywordFilter({"core": ["photonic computing"], "exclude": []})
    paper = Paper(
        title="Photonic computing perspective",
        abstract="A short overview with no specific device, task, or architecture.",
        journal_or_source="Science",
        source_type="crossref",
        source_quality_score=20,
        categories=["optics"],
    )
    locations = keyword_filter.match_with_locations(paper)
    matches = keyword_filter.flatten_location_matches(locations)
    score, _ = score_paper(paper, matches, keyword_filter.title_matches(paper), locations)

    assert score <= 35
    assert paper.score_breakdown["broad_single_term_cap"] is True
