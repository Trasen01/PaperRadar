from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .settings import load_settings, save_settings
from .profile_terms import filter_research_terms, is_likely_journal_name
from .utils import CONFIG_DIR, PROFILES_DIR, RESOURCE_DIR, ensure_directories
from .version import __version__

APP_VERSION = __version__
DEFAULT_PROFILE_ID = "optical_computing"


@dataclass
class ProfileValidationResult:
    ok: bool
    profile: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cleaned_yaml: str = ""
    normalized_yaml: str = ""
    parse_mode: str = ""
    raw_error: str = ""


def default_profile_resource_path() -> Path:
    return RESOURCE_DIR / "resources" / "default_profiles" / "optical_computing.yaml"


def default_profile_user_path() -> Path:
    return PROFILES_DIR / "optical_computing.yaml"


def ensure_default_profile_available() -> Path:
    ensure_directories()
    target = default_profile_user_path()
    if not target.exists():
        source = default_profile_resource_path()
        if source.exists():
            shutil.copy2(source, target)
        else:
            target.write_text(normalized_profile_yaml(_fallback_default_profile()), encoding="utf-8")
    return target


def initialize_profile_system() -> bool:
    ensure_directories()
    ensure_default_profile_available()
    settings_path = CONFIG_DIR / "settings.yaml"
    settings_existed = settings_path.exists()
    raw_active_profile = None
    if settings_existed:
        try:
            raw_data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
            if isinstance(raw_data, dict):
                raw_active_profile = raw_data.get("active_profile")
        except Exception:
            raw_active_profile = None
    settings = load_settings()
    first_run_needed = not settings_existed or not raw_active_profile
    settings.setdefault("active_profile", DEFAULT_PROFILE_ID)
    settings.setdefault("first_run_completed", False)
    settings["app_version"] = APP_VERSION
    save_settings(settings)
    return first_run_needed or not get_profile_path(str(settings.get("active_profile", DEFAULT_PROFILE_ID))).exists()


def get_profile_path(profile_id: str) -> Path:
    return PROFILES_DIR / f"{profile_id}.yaml"


def load_all_profiles() -> list[dict[str, Any]]:
    ensure_default_profile_available()
    profiles: list[dict[str, Any]] = []
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(data, dict):
            data["_path"] = str(path)
            profiles.append(data)
    return profiles


def load_active_profile() -> dict[str, Any]:
    settings = load_settings()
    profile_id = settings.get("active_profile") or DEFAULT_PROFILE_ID
    path = get_profile_path(str(profile_id))
    if not path.exists():
        path = ensure_default_profile_available()
        settings["active_profile"] = DEFAULT_PROFILE_ID
        save_settings(settings)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            data["_path"] = str(path)
            return data
    except Exception:
        pass
    fallback_path = default_profile_resource_path()
    fallback = yaml.safe_load(fallback_path.read_text(encoding="utf-8")) if fallback_path.exists() else _fallback_default_profile()
    fallback["_path"] = str(fallback_path)
    return fallback


def set_active_profile(profile_id: str) -> None:
    settings = load_settings()
    settings["active_profile"] = profile_id
    settings["first_run_completed"] = True
    settings["app_version"] = APP_VERSION
    save_settings(settings)


def profile_to_keywords(profile: dict[str, Any]) -> dict[str, list[str]]:
    keywords: dict[str, list[str]] = {}
    groups = profile.get("keyword_groups") or {}
    if isinstance(groups, dict):
        for group_name, group_data in groups.items():
            terms = (group_data or {}).get("terms") if isinstance(group_data, dict) else []
            if isinstance(terms, list):
                keywords[str(group_name)] = [str(term) for term in terms if str(term).strip()]
    exclude_terms = profile.get("exclude_terms") or []
    if isinstance(exclude_terms, list):
        keywords["exclude"] = [str(term) for term in exclude_terms if str(term).strip()]
    return keywords


def active_profile_keywords() -> dict[str, list[str]]:
    return profile_to_keywords(load_active_profile())


def active_profile_search_queries(max_queries: int = 20) -> list[str]:
    profile = load_active_profile()
    queries = profile.get("search_queries") or []
    if isinstance(queries, list):
        return [str(query) for query in queries if str(query).strip()][:max_queries]
    return []


def clean_ai_yaml_text(text: str) -> str:
    value = (text or "").replace("\ufeff", "").replace("\u200b", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    fence = re.search(r"```(?:yaml|yml)?\s*(.*?)```", value, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        value = fence.group(1).strip()
    starts = [idx for marker in ("profile_version:", "profile_id:", "search_queries:", "keyword_groups:") if (idx := value.find(marker)) >= 0]
    if starts:
        value = value[min(starts):]
    return value.strip()


def parse_profile_input(raw_text: str, research_direction_hint: str | None = None) -> ProfileValidationResult:
    cleaned = clean_ai_yaml_text(raw_text)
    raw_error = ""
    try:
        data = yaml.safe_load(cleaned) or {}
    except Exception as exc:
        data = None
        raw_error = str(exc)

    if isinstance(data, dict):
        result = _normalize_and_validate_profile(data, research_direction_hint)
        result.cleaned_yaml = cleaned
        result.raw_error = raw_error
        return result

    keywords = extract_keywords_from_text(raw_text)
    if detect_keyword_list(raw_text) and keywords:
        profile = _profile_from_keywords(keywords, research_direction_hint)
        result = _normalize_and_validate_profile(profile, research_direction_hint)
        result.cleaned_yaml = cleaned
        result.raw_error = raw_error
        result.parse_mode = "关键词列表自动转换"
        result.warnings.insert(0, "检测到粘贴内容不是完整 Profile，软件已自动从关键词列表生成临时 Profile。建议检查 search_queries 和 keyword_groups 后再保存。")
        return result

    result = ProfileValidationResult(ok=False, cleaned_yaml=cleaned, raw_error=raw_error)
    result.errors.append("当前内容不是合法的 PaperRadar Profile YAML。常见原因：AI 只输出了关键词列表；列表项缺少 '- '；缺少 profile_version、search_queries 或 keyword_groups；粘贴内容包含解释文字或 Markdown 代码块。")
    if raw_error:
        result.errors.append(f"原始解析错误：{raw_error}")
    result.errors.append("未能从当前文本中识别出有效关键词。请点击“生成并复制 AI 提示词”，重新让 AI 生成完整 Profile。")
    return result


def validate_profile_yaml(text: str, research_direction_hint: str | None = None) -> ProfileValidationResult:
    return parse_profile_input(text, research_direction_hint)


def _normalize_and_validate_profile(data: dict[str, Any], research_direction_hint: str | None = None) -> ProfileValidationResult:
    warnings: list[str] = []
    profile = _normalize_profile(dict(data), research_direction_hint, warnings)
    result = ProfileValidationResult(ok=False, profile=None, warnings=warnings, normalized_yaml=normalized_profile_yaml(profile))
    result.parse_mode = "自动补全 Profile" if warnings else "标准 Profile YAML"

    if not isinstance(profile.get("profile_version"), int):
        result.errors.append("profile_version 必须是整数。")
    if not re.match(r"^[a-z][a-z0-9_]*$", str(profile.get("profile_id", ""))):
        result.errors.append("profile_id 必须是 lower_snake_case 英文。")
    for key in ("display_name", "description"):
        if not isinstance(profile.get(key), str) or not profile.get(key, "").strip():
            result.errors.append(f"{key} 必须是非空字符串。")
    if not _is_str_list(profile.get("search_queries")):
        result.errors.append("search_queries 必须是字符串列表。")
    if not isinstance(profile.get("keyword_groups"), dict):
        result.errors.append("keyword_groups 必须是字典。")
    else:
        high_count = 0
        for group_name, group in profile["keyword_groups"].items():
            if not isinstance(group, dict):
                result.errors.append(f"keyword_groups.{group_name} 必须是字典。")
                continue
            priority = group.get("priority")
            if priority not in {"high", "medium", "low"}:
                result.errors.append(f"keyword_groups.{group_name}.priority 必须是 high / medium / low。")
            if priority == "high":
                high_count += 1
            if not _is_str_list(group.get("terms")):
                result.errors.append(f"keyword_groups.{group_name}.terms 必须是字符串列表。")
            elif len(group.get("terms") or []) > 30:
                result.warnings.append(f"{group_name} 的 terms 超过 30 条，可能导致匹配过宽。")
        if len(profile["keyword_groups"]) < 2:
            result.warnings.append("keyword_groups 少于 2 组，建议补充。")
        if high_count == 0:
            result.warnings.append("没有 high priority 关键词组，评分可能不够聚焦。")
    if not _is_str_list(profile.get("exclude_terms")):
        result.errors.append("exclude_terms 必须是字符串列表。")
    if not _is_str_list(profile.get("recommended_journals")):
        result.errors.append("recommended_journals 必须是字符串列表。")

    queries = profile.get("search_queries") or []
    if isinstance(queries, list):
        if len(queries) < 8:
            result.warnings.append("search_queries 少于 8 条，历史检索可能覆盖不足。")
        if len(queries) > 20:
            result.warnings.append("search_queries 超过 20 条，检索可能较慢。")
    if isinstance(profile.get("exclude_terms"), list) and len(profile["exclude_terms"]) > 30:
        result.warnings.append("exclude_terms 超过 30 条，可能减分过强。")

    result.ok = not result.errors
    result.profile = profile if result.ok else None
    if result.ok:
        result.normalized_yaml = normalized_profile_yaml(profile)
    return result


def _normalize_profile(data: dict[str, Any], hint: str | None, warnings: list[str]) -> dict[str, Any]:
    if "profile_version" not in data:
        data["profile_version"] = 1
        warnings.append("已自动补全 profile_version: 1。")
    if not data.get("profile_id"):
        data["profile_id"] = make_profile_id(str(data.get("display_name") or hint or ""))
        warnings.append("已自动生成 profile_id。")
    if not data.get("display_name"):
        data["display_name"] = hint or data["profile_id"]
        warnings.append("已自动补全 display_name。")
    if not data.get("description"):
        data["description"] = f"PaperRadar research profile for {data['display_name']}."
        warnings.append("已自动补全 description。")

    groups = data.get("keyword_groups")
    if not isinstance(groups, dict):
        queries = filter_research_terms(_as_str_list(data.get("search_queries")), for_query=True)
        data["keyword_groups"] = {"core": {"priority": "high", "terms": queries or [str(data["display_name"])]}}
        warnings.append("已根据 search_queries 自动生成 keyword_groups。")
    else:
        normalized_groups: dict[str, dict[str, Any]] = {}
        for name, group in groups.items():
            if isinstance(group, dict):
                terms = filter_research_terms(_as_str_list(group.get("terms")))
                priority = group.get("priority") if group.get("priority") in {"high", "medium", "low"} else "medium"
            elif isinstance(group, list):
                terms = filter_research_terms(_as_str_list(group))
                priority = "medium"
                warnings.append(f"已修复 keyword_groups.{name} 的结构。")
            else:
                terms = filter_research_terms([str(group)] if str(group).strip() else [])
                priority = "medium"
                warnings.append(f"已修复 keyword_groups.{name} 的结构。")
            if not terms:
                warnings.append(f"Filtered non-research journal/source terms from keyword_groups.{name}.")
                continue
            normalized_groups[str(name)] = {"priority": priority, "terms": terms}
            if len(normalized_groups) >= 10:
                warnings.append("keyword_groups 超过 10 组，已保留前 10 组。")
                break
        data["keyword_groups"] = normalized_groups

    if not _is_str_list(data.get("search_queries")):
        high_terms: list[str] = []
        for group in data["keyword_groups"].values():
            if group.get("priority") == "high":
                high_terms.extend(group.get("terms") or [])
        if not high_terms:
            for group in data["keyword_groups"].values():
                high_terms.extend(group.get("terms") or [])
        data["search_queries"] = filter_research_terms(_unique_strings(high_terms), for_query=True)[:15]
        warnings.append("已根据 keyword_groups 自动生成 search_queries。")

    data["search_queries"] = filter_research_terms(_unique_strings(_as_str_list(data.get("search_queries"))), for_query=True)[:20]
    data["exclude_terms"] = _unique_strings(_as_str_list(data.get("exclude_terms")))
    journals = _unique_strings(["Nature", "Science", *_as_str_list(data.get("recommended_journals"))])
    if len(journals) > 10:
        warnings.append("recommended_journals 必须不大于 10 个，已保留前 10 个。")
    data["recommended_journals"] = journals[:10]
    return _ordered_profile(data)


def detect_keyword_list(raw_text: str) -> bool:
    return len(extract_keywords_from_text(raw_text)) >= 3


def extract_keywords_from_text(raw_text: str) -> list[str]:
    lines = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    candidates: list[str] = []
    skip_titles = {
        "keyword_groups", "search_queries", "terms", "core", "methods", "platforms",
        "applications", "exclude_terms", "recommended_journals", "priority",
    }
    for line in lines:
        text = line.strip().strip("'\"`")
        text = re.sub(r"^\s*[-*]\s+", "", text)
        text = re.sub(r"^\s*\d+[\.\)、]\s*", "", text)
        text = text.strip().strip("'\"")
        if not text:
            continue
        key = text.rstrip(":").strip().lower()
        if key in skip_titles or text.endswith(":"):
            continue
        if ":" in text and not re.search(r"[A-Za-z].+['\"]?$", text):
            continue
        text = text.strip(",;")
        if len(text) < 3 or len(text) > 120:
            continue
        if not re.search(r"[A-Za-z]", text):
            continue
        if is_likely_journal_name(text):
            continue
        candidates.append(text)
    return filter_research_terms(_unique_strings(candidates), for_query=True)[:80]


def _profile_from_keywords(keywords: list[str], hint: str | None) -> dict[str, Any]:
    keywords = filter_research_terms(keywords, for_query=True)
    display_name = hint.strip() if hint and hint.strip() else "未命名研究方向"
    profile_id = make_profile_id(display_name or (keywords[0] if keywords else "profile"))
    core_terms = keywords[:20]
    related_terms = keywords[20:80]
    groups: dict[str, dict[str, Any]] = {"core": {"priority": "high", "terms": core_terms}}
    if related_terms:
        groups["related_terms"] = {"priority": "medium", "terms": related_terms}
    return {
        "profile_version": 1,
        "profile_id": profile_id,
        "display_name": display_name,
        "description": "Auto-generated PaperRadar profile from pasted keyword list.",
        "search_queries": keywords[:15],
        "keyword_groups": groups,
        "exclude_terms": [],
        "recommended_journals": [],
    }


def make_profile_id(value: str) -> str:
    text = value.lower()
    replacements = {
        "铌酸锂": "lithium_niobate",
        "调制器": "modulator",
        "超快": "ultrafast",
        "光子学": "photonics",
        "光学": "optics",
        "量子": "quantum",
    }
    for src, dst in replacements.items():
        text = text.replace(src, f" {dst} ")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    if not text or not re.match(r"^[a-z]", text):
        text = "profile_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    return text


def normalized_profile_yaml(profile: dict[str, Any]) -> str:
    return yaml.safe_dump(_ordered_profile(profile), allow_unicode=True, sort_keys=False, default_flow_style=False)


def _ordered_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_version": profile.get("profile_version", 1),
        "profile_id": profile.get("profile_id", ""),
        "display_name": profile.get("display_name", ""),
        "description": profile.get("description", ""),
        "search_queries": profile.get("search_queries") or [],
        "keyword_groups": profile.get("keyword_groups") or {},
        "exclude_terms": profile.get("exclude_terms") or [],
        "recommended_journals": profile.get("recommended_journals") or [],
    }


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip().strip("'\"")
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def save_profile(profile: dict[str, Any]) -> Path:
    ensure_directories()
    profile = _ordered_profile(profile)
    profile_id = str(profile["profile_id"])
    path = get_profile_path(profile_id)
    path.write_text(normalized_profile_yaml(profile), encoding="utf-8")
    return path


def delete_profile(profile_id: str) -> None:
    if profile_id == DEFAULT_PROFILE_ID:
        return
    path = get_profile_path(profile_id)
    if path.exists():
        path.unlink()
    settings = load_settings()
    if settings.get("active_profile") == profile_id:
        set_active_profile(DEFAULT_PROFILE_ID)


def make_profile_id(value: str) -> str:
    text = (value or "").lower()
    replacements = {
        "铌酸锂": "lithium_niobate",
        "调制器": "modulator",
        "超快": "ultrafast",
        "光子学": "photonics",
        "光学": "optics",
        "量子": "quantum",
    }
    for src, dst in replacements.items():
        text = text.replace(src, f" {dst} ")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    if not text or not re.match(r"^[a-z]", text):
        text = "profile_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    return text


def generate_profile_prompt(research_direction: str) -> str:
    direction = (research_direction or "").strip() or "your research direction"
    return f"""You are a scientific literature search expert. Generate a complete YAML research Profile for PaperRadar.

Research direction:
{direction}

Hard requirements:
1. The first line of your output MUST be exactly: profile_version: 1
2. Output one complete YAML document.
3. Make the output directly copyable into PaperRadar without editing.
4. Format the answer so the user can use the external AI app's Copy button or copy shortcut, if available, and paste the entire result directly into PaperRadar.
5. Output ONLY the YAML content from the first line to the last line.
6. Do NOT output Markdown code fences.
7. Do NOT output explanations, comments, introduction, closing text, or extra blank sections.
8. Do NOT output multiple candidate versions; output exactly one final Profile.
9. Do NOT output only a keyword list.
10. Do NOT omit any required field.
11. Required fields: profile_version, profile_id, display_name, description, search_queries, keyword_groups, exclude_terms, recommended_journals.
12. Every search_queries item must start with "- ".
13. Every keyword group must contain priority and terms.
14. Every terms item must start with "- ".
15. Self-check that the YAML is parseable before output.
16. If uncertain, generate reasonable placeholders instead of omitting fields.
17. Use English keywords because paper databases mainly use English metadata.
18. display_name may use Chinese.
19. search_queries should be precise, 8 to 15 items.
20. keyword_groups should contain 4 to 8 groups and MUST NOT exceed 10 groups.
21. priority must be high, medium, or low.
22. exclude_terms should contain 5 to 20 terms.
23. recommended_journals must be top journals for this exact research field, MUST include Nature and Science, and MUST contain no more than 10 journals.
24. Do not list broad low-quality venues or unrelated journals; recommended_journals should help search high-impact papers in this field.
25. profile_id must be lower_snake_case English.

Wrong example, do NOT output like this:

"lithium niobate modulator"
"thin-film lithium niobate modulator"

keyword_groups:
"electro-optic modulator"

The wrong example is not a complete YAML Profile.

Correct minimal example:

profile_version: 1
profile_id: lithium_niobate_modulator
display_name: 铌酸锂调制器
description: Thin-film lithium niobate electro-optic modulators.
search_queries:
  - lithium niobate modulator
  - thin-film lithium niobate electro-optic modulator
keyword_groups:
  core:
    priority: high
    terms:
      - lithium niobate modulator
      - electro-optic modulator
exclude_terms:
  - quantum memory
recommended_journals:
  - Nature
  - Science
  - Nature Photonics

Use this schema and fill it completely:

profile_version: 1
profile_id: lower_snake_case_english_id
display_name: 中文研究方向名称
description: English description of the research profile.
search_queries:
  - precise English search query 1
  - precise English search query 2
keyword_groups:
  core:
    priority: high
    terms:
      - term 1
      - term 2
  methods:
    priority: medium
    terms:
      - term 1
      - term 2
  platforms:
    priority: medium
    terms:
      - term 1
      - term 2
  applications:
    priority: low
    terms:
      - term 1
      - term 2
exclude_terms:
  - irrelevant term 1
  - irrelevant term 2
recommended_journals:
  - Nature
  - Science
  - top field journal 1
  - top field journal 2
"""
