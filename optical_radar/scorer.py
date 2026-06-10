from __future__ import annotations

from .models import Paper

HIGH_VALUE_GROUPS = {
    "optical_neural_networks",
    "linear_algebra_computing",
    "convolution_and_fourier",
    "equation_solver_and_analog",
    "processors_and_architectures",
    "neuromorphic_photonics",
}

MID_HIGH_GROUPS = {"high_precision_core"}
SUPPORTING_GROUPS = {"supporting_platforms"}
TOPIC_GROUPS = HIGH_VALUE_GROUPS | MID_HIGH_GROUPS

GROUP_LABELS = {
    "high_precision_core": "核心光计算",
    "optical_neural_networks": "光神经网络",
    "linear_algebra_computing": "线性代数/矩阵计算",
    "convolution_and_fourier": "卷积与傅里叶计算",
    "equation_solver_and_analog": "方程求解/模拟计算",
    "processors_and_architectures": "光子处理器/架构",
    "neuromorphic_photonics": "神经形态光子学",
    "supporting_platforms": "平台/器件",
    "exclude": "排除/弱相关",
}


def score_paper(
    paper: Paper,
    matches: dict[str, list[str]],
    title_matches: list[str] | None = None,
    match_locations: dict[str, dict[str, list[str]]] | None = None,
) -> tuple[int, str]:
    title_matches = title_matches or []
    match_locations = match_locations or _locations_from_flat(matches)

    score = 0
    for group in MID_HIGH_GROUPS:
        score += _group_score(match_locations, group, title_weight=24, abstract_weight=16, max_score=42)
    for group in HIGH_VALUE_GROUPS:
        score += _group_score(match_locations, group, title_weight=30, abstract_weight=20, max_score=55)
    for group in SUPPORTING_GROUPS:
        score += _group_score(match_locations, group, title_weight=12, abstract_weight=10, metadata_weight=3, max_score=25)
    known_groups = HIGH_VALUE_GROUPS | MID_HIGH_GROUPS | SUPPORTING_GROUPS | {"exclude"}
    for group in set(match_locations) - known_groups:
        score += _group_score(match_locations, group, title_weight=26, abstract_weight=18, metadata_weight=4, max_score=50)

    if title_matches:
        score += min(len(set(keyword.lower() for keyword in title_matches)) * 8, 18)

    exclude_count = _location_count(match_locations, "exclude")
    score -= min(exclude_count * 18, 45)

    generic_groups = set(match_locations) - (SUPPORTING_GROUPS | {"exclude"})
    has_topic_hit = _has_any(match_locations, TOPIC_GROUPS | generic_groups, include_metadata=False)
    has_supporting_hit = _has_any(match_locations, SUPPORTING_GROUPS, include_metadata=False)
    has_relevant_keyword = has_topic_hit or has_supporting_hit

    is_top_journal = paper.source_type == "journal_rss" and int(paper.source_quality_score or 0) > 0
    if has_topic_hit:
        score += int(paper.source_quality_score or 0)

    if has_supporting_hit and not has_topic_hit:
        score = min(score, 45)
    if not has_relevant_keyword:
        score = min(score, 35)

    score = max(0, min(100, score))
    reason = build_reason_zh(matches, match_locations, is_top_journal=is_top_journal)
    return score, reason


def _group_score(
    match_locations: dict[str, dict[str, list[str]]],
    group: str,
    title_weight: int,
    abstract_weight: int,
    max_score: int,
    metadata_weight: int = 0,
) -> int:
    locations = match_locations.get(group, {})
    title_score = len(set(locations.get("title", []))) * title_weight
    abstract_score = len(set(locations.get("abstract", []))) * abstract_weight
    metadata_score = len(set(locations.get("metadata", []))) * metadata_weight
    return min(title_score + abstract_score + metadata_score, max_score)


def _location_count(match_locations: dict[str, dict[str, list[str]]], group: str) -> int:
    locations = match_locations.get(group, {})
    return sum(len(set(values)) for values in locations.values())


def _has_any(
    match_locations: dict[str, dict[str, list[str]]],
    groups: set[str],
    include_metadata: bool = True,
) -> bool:
    allowed_locations = {"title", "abstract", "metadata"} if include_metadata else {"title", "abstract"}
    for group in groups:
        for location, values in match_locations.get(group, {}).items():
            if location in allowed_locations and values:
                return True
    return False


def _locations_from_flat(matches: dict[str, list[str]]) -> dict[str, dict[str, list[str]]]:
    return {
        group: {"abstract": list(values or [])}
        for group, values in matches.items()
        if values
    }


def build_reason_zh(
    matches: dict[str, list[str]],
    match_locations: dict[str, dict[str, list[str]]] | None = None,
    is_top_journal: bool = False,
) -> str:
    match_locations = match_locations or _locations_from_flat(matches)
    non_exclude_groups = [
        group
        for group in match_locations
        if group != "exclude" and any(match_locations[group].values())
    ]
    supporting_only = bool(non_exclude_groups) and all(group in SUPPORTING_GROUPS for group in non_exclude_groups)

    if non_exclude_groups:
        keyword_text = _keyword_text(match_locations, exclude_group="exclude")
        return f"命中关键词：{keyword_text}。"

    if match_locations.get("exclude"):
        return f"命中关键词：{_keyword_text(match_locations, only_group='exclude')}。"
    if is_top_journal:
        return "未命中当前关键词。"
    return "未命中当前关键词。"


def _location_text(locations: dict[str, list[str]]) -> str:
    parts = []
    if locations.get("title"):
        parts.append("标题")
    if locations.get("abstract"):
        parts.append("摘要")
    if locations.get("metadata"):
        parts.append("分类/来源")
    return "、".join(parts) or "未知位置"


def _keyword_text(
    match_locations: dict[str, dict[str, list[str]]],
    exclude_group: str | None = None,
    only_group: str | None = None,
) -> str:
    keywords: list[str] = []
    seen: set[str] = set()
    for group, locations in match_locations.items():
        if exclude_group and group == exclude_group:
            continue
        if only_group and group != only_group:
            continue
        for location in ["title", "abstract", "metadata"]:
            for keyword in locations.get(location, []):
                key = keyword.lower()
                if key not in seen:
                    seen.add(key)
                    keywords.append(keyword)
    return "、".join(keywords[:10]) if keywords else "无"


def relevance_label(score: int) -> str:
    if score >= 80:
        return "Highly Relevant"
    if score >= 60:
        return "Relevant"
    if score >= 40:
        return "Possibly Relevant"
    return "Low Relevance"
