from optical_radar.keyword_filter import KeywordFilter
from optical_radar.models import Paper
from optical_radar.settings import DEFAULT_KEYWORDS


def test_keyword_filter_matches_phrases_case_insensitive():
    paper = Paper(
        title="Integrated Photonic Neural Network with an MZI Mesh",
        abstract="We demonstrate optical computing using programmable photonics.",
        categories=["physics.optics"],
    )
    matcher = KeywordFilter(DEFAULT_KEYWORDS)
    matches = matcher.match(paper)

    assert "integrated photonic neural network" in matches["optical_neural_networks"]
    assert "optical computing" in matches["high_precision_core"]
    assert "MZI mesh" in matches["supporting_platforms"]
    assert "programmable photonics" in matches["supporting_platforms"]


def test_keyword_filter_records_title_and_abstract_locations():
    paper = Paper(
        title="A Photonic Processor",
        abstract="The abstract reports photonic matrix multiplication and photonic neural network inference.",
    )
    matcher = KeywordFilter(DEFAULT_KEYWORDS)
    locations = matcher.match_with_locations(paper)
    matches = matcher.flatten_location_matches(locations)

    assert "photonic processor" in locations["processors_and_architectures"]["title"]
    assert "photonic matrix multiplication" in locations["linear_algebra_computing"]["abstract"]
    assert "photonic neural network" in matches["optical_neural_networks"]


def test_keyword_filter_records_exclude_without_deleting():
    paper = Paper(
        title="Optical Computing for Biomedical Imaging",
        abstract="This paper uses photonic matrix multiplication.",
        categories=["physics.optics"],
    )
    matcher = KeywordFilter(DEFAULT_KEYWORDS)
    matches = matcher.match(paper)

    assert "optical computing" in matches["high_precision_core"]
    assert "photonic matrix multiplication" in matches["linear_algebra_computing"]
    assert "biomedical imaging" in matches["exclude"]
