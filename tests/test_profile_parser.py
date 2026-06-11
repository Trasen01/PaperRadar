import re

import yaml

from paper_radar.profile_manager import generate_profile_prompt, make_profile_id, parse_profile_input


VALID_YAML = """
profile_version: 1
profile_id: lithium_niobate_modulator
display_name: 铌酸锂调制器
description: Thin-film lithium niobate electro-optic modulators.
search_queries:
  - lithium niobate modulator
  - thin-film lithium niobate electro-optic modulator
  - TFLN modulator
  - LNOI modulator
  - high-speed lithium niobate modulator
  - lithium niobate Mach-Zehnder modulator
  - lithium niobate ring modulator
  - traveling-wave lithium niobate modulator
keyword_groups:
  core:
    priority: high
    terms:
      - lithium niobate modulator
      - electro-optic modulator
  platform:
    priority: medium
    terms:
      - thin-film lithium niobate
      - LNOI
exclude_terms:
  - quantum memory
recommended_journals:
  - Nature Photonics
"""


def test_valid_yaml_parses():
    result = parse_profile_input(VALID_YAML)
    assert result.ok
    assert result.profile["profile_id"] == "lithium_niobate_modulator"


def test_markdown_fenced_yaml_parses():
    result = parse_profile_input(f"Here is YAML:\n```yaml\n{VALID_YAML}\n```")
    assert result.ok
    assert result.profile["display_name"] == "铌酸锂调制器"


def test_missing_profile_version_is_completed():
    text = VALID_YAML.replace("profile_version: 1\n", "")
    result = parse_profile_input(text)
    assert result.ok
    assert result.profile["profile_version"] == 1
    assert result.warnings


def test_missing_search_queries_generated_from_keyword_groups():
    text = re.sub(r"search_queries:\n(?:  - .+\n)+", "", VALID_YAML)
    result = parse_profile_input(text)
    assert result.ok
    assert "lithium niobate modulator" in result.profile["search_queries"]


def test_keyword_list_fallback_generates_profile():
    text = """
    lithium niobate IQ modulator
    lithium niobate ring modulator
    LiNbO3 electro-optic modulator
    thin-film lithium niobate modulator
    TFLN modulator
    """
    result = parse_profile_input(text, research_direction_hint="铌酸锂调制器")
    assert result.ok
    assert result.parse_mode == "关键词列表自动转换"
    assert result.profile["profile_id"] == "lithium_niobate_modulator"
    assert len(result.profile["search_queries"]) >= 3


def test_broken_keyword_groups_fallback_case():
    text = '''
    "lithium niobate IQ modulator"

    "lithium niobate ring modulator"

    keyword_groups:
    "lithium niobate modulator"
    "LiNbO3 electro-optic modulator"
    '''
    result = parse_profile_input(text, research_direction_hint="铌酸锂调制器")
    assert result.ok
    assert result.parse_mode == "关键词列表自动转换"
    assert "LiNbO3 electro-optic modulator" in result.profile["keyword_groups"]["core"]["terms"]


def test_meaningless_text_fails_friendly():
    result = parse_profile_input("hello\nok\nmisc")
    assert not result.ok
    assert "当前内容不是合法" in "\n".join(result.errors)


def test_normalized_yaml_can_be_loaded():
    result = parse_profile_input(VALID_YAML)
    loaded = yaml.safe_load(result.normalized_yaml)
    assert loaded["profile_id"] == "lithium_niobate_modulator"


def test_recommended_journals_include_nature_science_and_stay_under_10():
    result = parse_profile_input(VALID_YAML)
    assert result.ok
    journals = result.profile["recommended_journals"]
    assert journals[:2] == ["Nature", "Science"]
    assert len(journals) <= 10


def test_recommended_journals_are_truncated_to_10():
    journals = "\n".join(f"  - Journal {index}" for index in range(12))
    text = VALID_YAML.replace("  - Nature Photonics\n", journals + "\n")
    result = parse_profile_input(text)
    assert result.ok
    assert result.profile["recommended_journals"][:2] == ["Nature", "Science"]
    assert len(result.profile["recommended_journals"]) == 10


def test_keyword_groups_are_limited_to_10():
    groups = "\n".join(
        f"  group_{index}:\n    priority: medium\n    terms:\n      - keyword {index}"
        for index in range(12)
    )
    text = f"""
profile_version: 1
profile_id: many_groups
display_name: Many Groups
description: Test profile.
search_queries:
  - keyword 1
keyword_groups:
{groups}
exclude_terms: []
recommended_journals:
  - Optica
"""
    result = parse_profile_input(text)
    assert result.ok
    assert len(result.profile["keyword_groups"]) == 10


def test_profile_prompt_requires_group_limit_and_top_journals():
    prompt = generate_profile_prompt("ultrafast photonics")
    assert "directly copyable into PaperRadar without editing" in prompt
    assert "external AI app's Copy button or copy shortcut" in prompt
    assert "Output ONLY the YAML content" in prompt
    assert "Do NOT output multiple candidate versions" in prompt
    assert "MUST NOT exceed 10 groups" in prompt
    assert "MUST include Nature and Science" in prompt
    assert "no more than 10 journals" in prompt
    assert "search_queries ONLY for remote database retrieval" in prompt
    assert "keyword_groups for local keyword matching" in prompt
    assert "recommended_journals are only journal recommendations" in prompt
    assert "must NOT be repeated in search_queries or keyword_groups" in prompt


def test_profile_id_is_lower_snake_case():
    profile_id = make_profile_id("铌酸锂 IQ 调制器")
    assert re.match(r"^[a-z][a-z0-9_]*$", profile_id)
