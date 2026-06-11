from paper_radar.crossref_client import build_search_queries_from_keywords
from paper_radar.profile_manager import parse_profile_input
from paper_radar.profile_terms import is_likely_journal_name


def test_likely_journal_names_are_detected():
    for name in ["Nature", "Science", "Optica", "Light: Science & Applications", "Journal of Lightwave Technology"]:
        assert is_likely_journal_name(name)


def test_fallback_keyword_list_does_not_add_journals_to_keyword_groups():
    text = """
    lithium niobate IQ modulator
    thin-film lithium niobate electro-optic modulator
    LNOI Mach-Zehnder modulator
    recommended_journals:
    Nature
    Science
    Optica
    """
    result = parse_profile_input(text, research_direction_hint="Lithium Niobate Modulators")
    assert result.ok
    terms = [term for group in result.profile["keyword_groups"].values() for term in group["terms"]]
    queries = result.profile["search_queries"]

    assert "Nature" not in terms
    assert "Science" not in terms
    assert "Optica" not in terms
    assert "Nature" not in queries
    assert "Science" not in queries
    assert "Optica" not in queries


def test_build_search_queries_filters_journal_names_and_broad_terms():
    queries = build_search_queries_from_keywords(
        {
            "core": ["Nature", "Science", "Optica", "Light", "photonics", "thin-film lithium niobate modulator"],
        },
        max_queries=10,
    )
    lowered = {query.lower() for query in queries}
    assert "nature" not in lowered
    assert "science" not in lowered
    assert "optica" not in lowered
    assert "light" not in lowered
    assert "photonics" not in lowered
