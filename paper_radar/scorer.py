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

BROAD_STANDALONE_TERMS = {
    "optical computing",
    "photonic computing",
    "analog optical computing",
    "coherent optical computing",
    "all-optical computing",
    "optical information processing",
    "photonic information processing",
    "photonic processor",
    "optical processor",
    "photonic chip",
    "optical chip",
    "optics",
    "photonics",
}

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

    keyword_score = 0
    for group in MID_HIGH_GROUPS:
        keyword_score += _group_score(match_locations, group, title_weight=24, abstract_weight=16, max_score=42)
    for group in HIGH_VALUE_GROUPS:
        keyword_score += _group_score(match_locations, group, title_weight=30, abstract_weight=20, max_score=55)
    for group in SUPPORTING_GROUPS:
        keyword_score += _group_score(
            match_locations,
            group,
            title_weight=12,
            abstract_weight=10,
            metadata_weight=3,
            max_score=25,
        )

    known_groups = HIGH_VALUE_GROUPS | MID_HIGH_GROUPS | SUPPORTING_GROUPS | {"exclude"}
    custom_groups = set(match_locations) - known_groups
    for group in custom_groups:
        keyword_score += _group_score(match_locations, group, title_weight=26, abstract_weight=18, metadata_weight=4, max_score=50)

    if title_matches:
        keyword_score += min(len({keyword.lower() for keyword in title_matches}) * 8, 18)

    generic_groups = set(match_locations) - (SUPPORTING_GROUPS | {"exclude"})
    topic_groups = TOPIC_GROUPS | generic_groups
    has_topic_hit = _has_any(match_locations, topic_groups, include_metadata=False)
    has_supporting_hit = _has_any(match_locations, SUPPORTING_GROUPS, include_metadata=False)
    has_positive_keyword_hit = has_topic_hit or has_supporting_hit

    topic_hit_groups = _hit_groups(match_locations, topic_groups, include_metadata=False)
    positive_keywords = _positive_keywords(match_locations)
    title_topic_keywords = _keywords_in_locations(match_locations, topic_groups, {"title"})
    abstract_topic_keywords = _keywords_in_locations(match_locations, topic_groups, {"abstract"})

    combo_bonus = _combination_bonus(topic_hit_groups, title_topic_keywords, abstract_topic_keywords, positive_keywords)
    strong_title_hit = _has_strong_title_hit(match_locations, custom_groups)
    broad_single_term_cap = len(positive_keywords) == 1 and next(iter(positive_keywords)).lower() in BROAD_STANDALONE_TERMS

    penalty_score = min(_location_count(match_locations, "exclude") * 18, 45)
    source_quality_score = int(paper.source_quality_score or 0) if has_topic_hit else 0

    score = keyword_score + combo_bonus + source_quality_score - penalty_score

    title_floor_applied = 0
    if strong_title_hit and penalty_score < 30:
        title_floor_applied = 50 if source_quality_score else 45
        score = max(score, title_floor_applied)

    supporting_only_cap = False
    if has_supporting_hit and not has_topic_hit:
        score = min(score, 20)
        supporting_only_cap = True

    no_positive_keyword_cap = False
    if not has_positive_keyword_hit:
        score = min(score, 15)
        no_positive_keyword_cap = True

    if broad_single_term_cap:
        score = min(score, 35)

    score = max(0, min(100, score))
    paper.score_breakdown = {
        "keyword_score": int(keyword_score),
        "combo_bonus": int(combo_bonus),
        "source_quality_score": int(source_quality_score),
        "penalty_score": int(penalty_score),
        "title_floor_applied": int(title_floor_applied),
        "broad_single_term_cap": bool(broad_single_term_cap),
        "supporting_only_cap": bool(supporting_only_cap),
        "no_positive_keyword_cap": bool(no_positive_keyword_cap),
        "strong_title_hit": bool(strong_title_hit),
        "has_positive_keyword_hit": bool(has_positive_keyword_hit),
        "final_score": int(score),
    }
    reason = build_reason_zh(matches, match_locations, is_top_journal=paper.source_type in {"journal_rss", "crossref"})
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


def _hit_groups(
    match_locations: dict[str, dict[str, list[str]]],
    groups: set[str],
    include_metadata: bool = True,
) -> set[str]:
    allowed_locations = {"title", "abstract", "metadata"} if include_metadata else {"title", "abstract"}
    result: set[str] = set()
    for group in groups:
        for location, values in match_locations.get(group, {}).items():
            if location in allowed_locations and values:
                result.add(group)
                break
    return result


def _keywords_in_locations(
    match_locations: dict[str, dict[str, list[str]]],
    groups: set[str],
    locations: set[str],
) -> set[str]:
    keywords: set[str] = set()
    for group in groups:
        for location in locations:
            keywords.update(str(keyword).strip() for keyword in match_locations.get(group, {}).get(location, []) if str(keyword).strip())
    return keywords


def _positive_keywords(match_locations: dict[str, dict[str, list[str]]]) -> set[str]:
    keywords: set[str] = set()
    for group, locations in match_locations.items():
        if group == "exclude":
            continue
        for location in ("title", "abstract"):
            keywords.update(str(keyword).strip() for keyword in locations.get(location, []) if str(keyword).strip())
    return keywords


def _combination_bonus(
    topic_hit_groups: set[str],
    title_topic_keywords: set[str],
    abstract_topic_keywords: set[str],
    positive_keywords: set[str],
) -> int:
    bonus = 0
    if len(topic_hit_groups) >= 2:
        bonus += 12
    if title_topic_keywords and abstract_topic_keywords:
        bonus += 8
    if len(positive_keywords) >= 3:
        bonus += 8
    return min(bonus, 24)


def _has_strong_title_hit(match_locations: dict[str, dict[str, list[str]]], custom_groups: set[str]) -> bool:
    strong_groups = HIGH_VALUE_GROUPS | custom_groups
    title_keywords = _keywords_in_locations(match_locations, strong_groups, {"title"})
    return bool(title_keywords)


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
    if non_exclude_groups:
        return f"命中关键词：{_keyword_text(match_locations, exclude_group='exclude')}。"
    if match_locations.get("exclude"):
        return f"命中排除词：{_keyword_text(match_locations, only_group='exclude')}。"
    if is_top_journal:
        return "未命中当前研究关键词，仅保留来源信息。"
    return "未命中当前研究关键词。"


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
