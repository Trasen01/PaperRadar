from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .utils import CONFIG_DIR, RESOURCE_DIR, ensure_directories
from .version import __version__

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "app_version": __version__,
    "active_profile": "optical_computing",
    "first_run_completed": False,
    "days_back": 7,
    "max_results": 100,
    "min_score": 40,
    "auto_check_daily": False,
    "use_arxiv": True,
    "use_top_journals": True,
    "use_crossref": True,
    "show_arxiv": True,
    "show_top_journals": True,
    "show_crossref": True,
    "debug": {
        "keep_unmatched_journal_papers": True,
        "log_filtered_papers": True,
    },
    "crossref": {
        "rows_per_query": 20,
        "max_queries_per_run": 200,
        "request_delay_seconds": 0.5,
        "cache_hours": 24,
    },
}

DEFAULT_SOURCES = {
    "sources_version": 2,
    "journal_sources": [
        {
            "name": "Nature Photonics",
            "publisher": "Springer Nature",
            "type": "rss",
            "enabled": True,
            "feed_url": "https://www.nature.com/nphoton/journal/vaop/ncurrent/rss.rdf",
            "alternate_feed_urls": ["https://www.nature.com/nphoton/rss.rdf"],
            "homepage": "https://www.nature.com/nphoton/",
            "field_relevant": True,
            "quality_score": 20,
        },
        {
            "name": "Nature",
            "publisher": "Springer Nature",
            "type": "rss",
            "enabled": True,
            "feed_url": "https://www.nature.com/nature/rss.rdf",
            "homepage": "https://www.nature.com/",
            "quality_score": 20,
        },
        {
            "name": "Science",
            "publisher": "AAAS",
            "type": "rss",
            "enabled": True,
            "feed_url": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
            "homepage": "https://www.science.org/journal/science",
            "quality_score": 20,
        },
        {
            "name": "Nature Communications",
            "publisher": "Springer Nature",
            "type": "rss",
            "enabled": True,
            "feed_url": "https://www.nature.com/ncomms/rss.rdf",
            "homepage": "https://www.nature.com/ncomms/",
            "subject_hint": "optics and photonics",
            "quality_score": 18,
        },
        {
            "name": "Science Advances",
            "publisher": "AAAS",
            "type": "rss",
            "enabled": True,
            "feed_url": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv",
            "homepage": "https://www.science.org/journal/sciadv",
            "quality_score": 18,
        },
        {
            "name": "Light: Science & Applications",
            "publisher": "Springer Nature",
            "type": "rss",
            "enabled": True,
            "feed_url": "https://www.nature.com/lsa/rss.rdf",
            "homepage": "https://www.nature.com/lsa/",
            "field_relevant": True,
            "quality_score": 18,
        },
        {
            "name": "Optica",
            "publisher": "Optica Publishing Group",
            "type": "rss",
            "enabled": False,
            "feed_url": "",
            "homepage": "https://opg.optica.org/optica/home.cfm",
            "field_relevant": True,
            "quality_score": 18,
        },
        {
            "name": "Physical Review Letters",
            "publisher": "APS",
            "type": "rss",
            "enabled": False,
            "feed_url": "",
            "homepage": "https://journals.aps.org/prl/",
            "quality_score": 18,
        },
        {
            "name": "Advanced Photonics",
            "publisher": "SPIE / Chinese Laser Press",
            "type": "rss",
            "enabled": False,
            "feed_url": "",
            "homepage": "https://www.advancedphotonics.org/",
            "field_relevant": True,
            "quality_score": 17,
        },
        {
            "name": "Laser & Photonics Reviews",
            "publisher": "Wiley",
            "type": "rss",
            "enabled": False,
            "feed_url": "",
            "homepage": "https://onlinelibrary.wiley.com/journal/18638899",
            "field_relevant": True,
            "quality_score": 17,
        },
    ]
}

DEFAULT_SOURCES["top_journals"] = [
    {"name": "Nature Photonics", "publisher": "Springer Nature", "issn": ["1749-4885", "1749-4893"], "homepage": "https://www.nature.com/nphoton/", "crossref_enabled": True, "quality_score": 20},
    {"name": "Nature", "publisher": "Springer Nature", "issn": ["0028-0836", "1476-4687"], "homepage": "https://www.nature.com/", "crossref_enabled": True, "quality_score": 20},
    {"name": "Science", "publisher": "AAAS", "issn": ["0036-8075", "1095-9203"], "homepage": "https://www.science.org/journal/science", "crossref_enabled": True, "quality_score": 20},
    {"name": "Nature Communications", "publisher": "Springer Nature", "issn": ["2041-1723"], "homepage": "https://www.nature.com/ncomms/", "crossref_enabled": True, "quality_score": 18},
    {"name": "Science Advances", "publisher": "AAAS", "issn": ["2375-2548"], "homepage": "https://www.science.org/journal/sciadv", "crossref_enabled": True, "quality_score": 18},
    {"name": "Light: Science & Applications", "publisher": "Springer Nature", "issn": ["2047-7538"], "homepage": "https://www.nature.com/lsa/", "crossref_enabled": True, "quality_score": 18},
    {"name": "Optica", "publisher": "Optica Publishing Group", "issn": ["2334-2536"], "homepage": "https://opg.optica.org/optica/home.cfm", "crossref_enabled": True, "quality_score": 18},
    {"name": "Physical Review Letters", "publisher": "APS", "issn": ["0031-9007", "1079-7114"], "homepage": "https://journals.aps.org/prl/", "crossref_enabled": True, "quality_score": 18},
    {"name": "Advanced Photonics", "publisher": "SPIE / Chinese Laser Press", "issn": ["2577-5421"], "homepage": "https://www.advancedphotonics.org/", "crossref_enabled": True, "quality_score": 17},
    {"name": "Laser & Photonics Reviews", "publisher": "Wiley", "issn": ["1863-8880", "1863-8899"], "homepage": "https://onlinelibrary.wiley.com/journal/18638899", "crossref_enabled": True, "quality_score": 17},
]

DEFAULT_KEYWORDS = {
    "high_precision_core": [
        "photonic computing",
        "optical computing",
        "analog optical computing",
        "coherent optical computing",
        "all-optical computing",
        "optical information processing",
        "photonic information processing",
    ],
    "optical_neural_networks": [
        "optical neural network",
        "optical neural networks",
        "photonic neural network",
        "photonic neural networks",
        "integrated photonic neural network",
        "integrated photonic neural networks",
        "all-optical neural network",
        "all-optical neural networks",
        "diffractive neural network",
        "diffractive neural networks",
        "diffractive deep neural network",
        "optical deep learning",
        "photonic deep learning",
        "optical machine learning",
        "photonic machine learning",
        "optical inference",
        "photonic inference",
    ],
    "linear_algebra_computing": [
        "optical matrix multiplication",
        "photonic matrix multiplication",
        "optical matrix-vector multiplication",
        "photonic matrix-vector multiplication",
        "matrix-vector multiplication",
        "matrix-matrix multiplication",
        "optical tensor processing",
        "photonic tensor processing",
        "tensor processor",
        "photonic tensor processor",
        "photonic tensor core",
        "optical linear transformation",
        "photonic linear transformation",
        "optical multiply-accumulate",
        "photonic multiply-accumulate",
        "MAC operation",
        "vector-matrix multiplication",
        "multiply-accumulate",
    ],
    "convolution_and_fourier": [
        "optical convolution",
        "photonic convolution",
        "optical convolutional neural network",
        "photonic convolutional neural network",
        "Fourier optical computing",
        "Fourier optics computing",
        "optical Fourier transform",
        "photonic Fourier transform",
        "optical correlator",
        "photonic correlator",
        "optical convolution processor",
        "photonic convolution processor",
    ],
    "equation_solver_and_analog": [
        "optical solver",
        "photonic solver",
        "optical equation solver",
        "photonic equation solver",
        "optical differential equation solver",
        "photonic differential equation solver",
        "optical computing for differential equations",
        "photonic computing for differential equations",
        "analog optical solver",
        "wave-based computing",
        "wave computing",
        "Ising solver",
        "optical Ising machine",
        "photonic Ising machine",
        "coherent Ising machine",
    ],
    "processors_and_architectures": [
        "photonic processor",
        "optical processor",
        "photonic accelerator",
        "optical accelerator",
        "optical processing unit",
        "photonic processing unit",
        "OPU",
        "programmable photonic processor",
        "programmable optical processor",
        "integrated photonic processor",
        "photonic neural processor",
        "optical neural processor",
        "photonic AI accelerator",
        "optical AI accelerator",
        "photonic chip",
        "optical computing chip",
    ],
    "neuromorphic_photonics": [
        "neuromorphic photonics",
        "neuromorphic photonic computing",
        "optical neuromorphic computing",
        "photonic neuromorphic computing",
        "photonic reservoir computing",
        "optical reservoir computing",
        "optical neuron",
        "photonic neuron",
        "optical synapse",
        "photonic synapse",
        "spiking photonic neural network",
        "photonic spiking neural network",
        "excitable laser",
        "delay-based reservoir computing",
    ],
    "supporting_platforms": [
        "MZI mesh",
        "Mach-Zehnder mesh",
        "interferometer mesh",
        "microring weight bank",
        "microring resonator array",
        "silicon photonics",
        "integrated photonics",
        "programmable photonics",
        "diffractive optical element",
        "spatial light modulator",
        "SLM",
        "metasurface",
        "optical frequency comb",
        "frequency comb",
        "wavelength division multiplexing",
        "WDM",
        "electro-optic modulator",
        "phase-change photonics",
        "memristive photonics",
    ],
    "exclude": [
        "biomedical imaging",
        "bioimaging",
        "clinical imaging",
        "ophthalmology",
        "endoscopy",
        "microscopy",
        "optical coherence tomography",
        "OCT",
        "remote sensing",
        "lidar",
        "optical communication",
        "fiber communication",
        "free-space optical communication",
        "optical encryption",
        "image encryption",
        "solar cell",
        "photovoltaic",
        "photocatalysis",
        "quantum key distribution",
        "QKD",
    ],
}


def _load_yaml(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    ensure_directories()
    if not path.exists():
        bundled_path = RESOURCE_DIR / "config" / path.name
        if bundled_path.exists() and bundled_path != path:
            try:
                with bundled_path.open("r", encoding="utf-8") as f:
                    bundled_data = yaml.safe_load(f) or {}
                save_yaml(path, bundled_data)
                merged = dict(default)
                merged.update(bundled_data)
                return merged
            except Exception:
                logger.exception("Failed to copy bundled YAML: %s", bundled_path)
        save_yaml(path, default)
        return dict(default)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        merged = dict(default)
        merged.update(data)
        return merged
    except Exception:
        logger.exception("Failed to load YAML: %s", path)
        return dict(default)


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    ensure_directories()
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def load_settings() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "settings.yaml", DEFAULT_SETTINGS)


def save_settings(settings: dict[str, Any]) -> None:
    save_yaml(CONFIG_DIR / "settings.yaml", settings)


def load_keywords() -> dict[str, list[str]]:
    try:
        from .profile_manager import active_profile_keywords

        keywords = active_profile_keywords()
        if keywords:
            return keywords
    except Exception:
        logger.exception("Failed to load active profile keywords; falling back to keywords.yaml")
    data = _load_yaml(CONFIG_DIR / "keywords.yaml", DEFAULT_KEYWORDS)
    required_groups = set(DEFAULT_KEYWORDS)
    if not required_groups.issubset(set(data)):
        data = dict(DEFAULT_KEYWORDS)
        save_yaml(CONFIG_DIR / "keywords.yaml", data)
    return {key: list(value or []) for key, value in data.items()}


def load_sources() -> dict[str, Any]:
    data = _load_yaml(CONFIG_DIR / "sources.yaml", DEFAULT_SOURCES)
    original_data = dict(data)
    upgraded = int(data.get("sources_version") or 0) < int(DEFAULT_SOURCES["sources_version"])
    data = _upgrade_sources(data, force_default_enabled=upgraded)
    if upgraded or data != original_data:
        save_yaml(CONFIG_DIR / "sources.yaml", data)
    sources = data.get("journal_sources") or []
    if not isinstance(sources, list):
        sources = []
    top_journals = data.get("top_journals") or DEFAULT_SOURCES.get("top_journals", [])
    if not isinstance(top_journals, list):
        top_journals = []
    if "top_journals" not in data:
        data["top_journals"] = top_journals
        save_yaml(CONFIG_DIR / "sources.yaml", data)
    return {
        "sources_version": data.get("sources_version", DEFAULT_SOURCES["sources_version"]),
        "journal_sources": sources,
        "top_journals": top_journals,
    }


def _upgrade_sources(data: dict[str, Any], force_default_enabled: bool = False) -> dict[str, Any]:
    current_sources = data.get("journal_sources") or []
    if not isinstance(current_sources, list):
        current_sources = []

    by_name = {
        str(source.get("name", "")): dict(source)
        for source in current_sources
        if isinstance(source, dict)
    }
    upgraded: list[dict[str, Any]] = []
    for default_source in DEFAULT_SOURCES["journal_sources"]:
        name = str(default_source.get("name", ""))
        merged = dict(default_source)
        merged.update(by_name.get(name, {}))
        if default_source.get("enabled") and default_source.get("feed_url"):
            if force_default_enabled or name not in by_name:
                merged["enabled"] = True
            merged["feed_url"] = default_source["feed_url"]
            if default_source.get("alternate_feed_urls"):
                merged["alternate_feed_urls"] = default_source["alternate_feed_urls"]
        if default_source.get("field_relevant"):
            merged["field_relevant"] = True
        upgraded.append(merged)

    existing_names = {str(source.get("name", "")) for source in upgraded}
    for source in current_sources:
        if isinstance(source, dict) and str(source.get("name", "")) not in existing_names:
            upgraded.append(dict(source))

    result = dict(data)
    result["sources_version"] = DEFAULT_SOURCES["sources_version"]
    result["journal_sources"] = upgraded
    result.setdefault("top_journals", DEFAULT_SOURCES.get("top_journals", []))
    return result
