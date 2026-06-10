from optical_radar.keyword_filter import KeywordFilter
from optical_radar.models import Paper
from optical_radar.scorer import relevance_label, score_paper
from optical_radar.settings import DEFAULT_KEYWORDS


def _score(paper: Paper) -> tuple[int, str, dict[str, list[str]]]:
    matcher = KeywordFilter(DEFAULT_KEYWORDS)
    locations = matcher.match_with_locations(paper)
    matches = matcher.flatten_location_matches(locations)
    return (*score_paper(paper, matches, matcher.title_matches(paper), locations), matches)


def test_strong_optical_computing_paper_scores_high():
    paper = Paper(
        title="Photonic Neural Network for Optical Matrix Multiplication",
        abstract="We demonstrate photonic computing with a programmable photonic processor.",
    )
    score, reason, matches = _score(paper)

    assert score >= 80
    assert relevance_label(score) == "Highly Relevant"
    assert "optical_neural_networks" in matches
    assert "linear_algebra_computing" in matches
    assert reason.startswith("命中关键词：")
    assert "photonic neural network" in reason
    assert "建议" not in reason


def test_supporting_platform_only_is_not_scored_too_high():
    paper = Paper(
        title="Metasurface and Microring Resonator Array Device",
        abstract="The device uses an MZI mesh and silicon photonics for optical characterization.",
    )
    score, reason, matches = _score(paper)

    assert "supporting_platforms" in matches
    assert score <= 45
    assert reason.startswith("命中关键词：")
    assert "metasurface" in reason
    assert "建议" not in reason


def test_top_journal_unrelated_paper_is_not_high_score():
    paper = Paper(
        title="Molecular Biology of Cell Differentiation",
        abstract="This study reports clinical imaging biomarkers in tissue samples.",
        source_type="journal_rss",
        source_quality_score=20,
        journal_or_source="Nature",
    )
    score, reason, matches = _score(paper)

    assert score < 10
    assert relevance_label(score) == "Low Relevance"
    assert "exclude" in matches
    assert reason.startswith("命中关键词：")
    assert "clinical imaging" in reason
    assert "减分" not in reason


def test_abstract_matrix_or_neural_network_hit_enters_candidate():
    paper = Paper(
        title="Integrated Photonic Circuit for AI",
        abstract="The abstract demonstrates photonic matrix multiplication and a photonic neural network.",
    )
    score, reason, matches = _score(paper)

    assert score >= 40
    assert "linear_algebra_computing" in matches
    assert "optical_neural_networks" in matches
    assert reason.startswith("命中关键词：")
    assert "photonic matrix multiplication" in reason
    assert "建议" not in reason


def test_exclude_terms_reduce_score_without_deleting_candidate():
    related = Paper(
        title="Optical Computing for Biomedical Imaging",
        abstract="We use photonic matrix multiplication for inference, but the application is microscopy.",
    )
    clean = Paper(
        title="Optical Computing Processor",
        abstract="We use photonic matrix multiplication for inference.",
    )
    related_score, _, related_matches = _score(related)
    clean_score, _, clean_matches = _score(clean)

    assert "exclude" in related_matches
    assert "linear_algebra_computing" in related_matches
    assert related_score < clean_score
    assert related_score > 0
    assert "linear_algebra_computing" in clean_matches
