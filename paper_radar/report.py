from __future__ import annotations

from datetime import date
from pathlib import Path

from .models import Paper
from .profile_manager import load_active_profile
from .scorer import relevance_label
from .utils import REPORTS_DIR, ensure_directories, format_date_only


def generate_markdown_report(
    papers: list[Paper],
    total_fetched: int = 0,
    new_papers: int = 0,
    displayed_papers: int | None = None,
    report_date: date | None = None,
    source_stats: dict[str, int] | None = None,
) -> Path:
    ensure_directories()
    report_date = report_date or date.today()
    displayed_papers = len(papers) if displayed_papers is None else displayed_papers
    source_stats = source_stats or {}
    path = REPORTS_DIR / f"{report_date.isoformat()}_PaperRadar_digest.md"

    groups = {
        "Highly Relevant": [p for p in papers if p.relevance_score >= 80],
        "Relevant": [p for p in papers if 60 <= p.relevance_score < 80],
        "Possibly Relevant": [p for p in papers if 40 <= p.relevance_score < 60],
    }

    lines: list[str] = [f"# PaperRadar Digest - {report_date.isoformat()}", "", *_profile_lines(), ""]
    for heading, group_papers in groups.items():
        lines.extend([f"## {heading}", ""])
        if not group_papers:
            lines.extend(["No papers.", ""])
            continue
        for paper in group_papers:
            lines.extend(_paper_block(paper))

    lines.extend(
        [
            "## Statistics",
            f"- Total fetched: {total_fetched}",
            f"- arXiv fetched: {int(source_stats.get('arxiv_fetched', 0))}",
            f"- RSS daily monitor fetched: {int(source_stats.get('journal_fetched', 0))}",
            f"- Crossref top journal history fetched: {int(source_stats.get('crossref_fetched', 0))}",
            f"- Enabled top journal sources: {int(source_stats.get('enabled_journal_sources', 0))}",
            f"- Failed top journal sources: {int(source_stats.get('failed_journal_sources', 0))}",
            f"- New papers: {new_papers}",
            f"- Displayed papers: {displayed_papers}",
            f"- Highly relevant: {len(groups['Highly Relevant'])}",
            f"- Relevant: {len(groups['Relevant'])}",
            f"- Possibly relevant: {len(groups['Possibly Relevant'])}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def generate_daily_report(papers: list[Paper], report_date: date | None = None) -> Path:
    ensure_directories()
    report_date = report_date or date.today()
    path = REPORTS_DIR / f"{report_date.isoformat()}_daily_radar_report.md"
    high = [p for p in papers if p.relevance_score >= 60]
    skim = [p for p in papers if 40 <= p.relevance_score < 60]
    lines = [
        "# PaperRadar 每日文献雷达报告",
        "",
        *_profile_lines(),
        "",
        f"- 日期: {report_date.isoformat()}",
        f"- 高相关论文: {len(high)}",
        f"- 值得扫读论文: {len(skim)}",
        "",
        "## 今日/本次高相关论文",
        "",
    ]
    for paper in high:
        lines.extend(_paper_block(paper))
    lines.extend(["## 值得扫读论文", ""])
    for paper in skim:
        lines.extend(_paper_block(paper))
    lines.extend(["## 数据源统计", ""])
    for source, count in _count_by_source_type(papers).items():
        lines.append(f"- {source}: {count}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def generate_survey_report(
    papers: list[Paper],
    task_name: str,
    from_date: date,
    until_date: date,
    report_date: date | None = None,
    run_stats: dict[str, int] | None = None,
) -> Path:
    ensure_directories()
    report_date = report_date or date.today()
    run_stats = run_stats or {}
    path = REPORTS_DIR / f"{report_date.isoformat()}_literature_survey_report.md"
    high = [p for p in papers if p.relevance_score >= 60]
    possible = [p for p in papers if 40 <= p.relevance_score < 60]
    low = [p for p in papers if p.relevance_score < 40]
    lines = [
        "# PaperRadar 历史文献调研报告",
        "",
        *_profile_lines(),
        "",
        f"- 调研名称: {task_name}",
        f"- 时间范围: {from_date.isoformat()} 至 {until_date.isoformat()}",
        f"- 总检索/显示数量: {len(papers)}",
        f"- 高相关数量: {len(high)}",
        f"- 可能相关数量: {len(possible)}",
        f"- 低相关数量: {len(low)}",
        f"- 成功查询数: {int(run_stats.get('success', 0))}",
        f"- 失败查询数: {int(run_stats.get('failed_query_count', run_stats.get('failed', 0)))}",
        f"- 超时次数: {int(run_stats.get('timeouts', 0))}",
        "",
        "## 按期刊统计",
        "",
    ]
    for source, count in _count_by_journal(papers).items():
        lines.append(f"- {source}: {count}")
    lines.extend(["", "## 按年份统计", ""])
    for year, count in _count_by_year(papers).items():
        lines.append(f"- {year}: {count}")
    lines.extend(["", "## 高相关论文列表", ""])
    for paper in high:
        lines.extend(_paper_block(paper))
    lines.extend(["## 可能相关论文列表", ""])
    for paper in possible:
        lines.extend(_paper_block(paper))
    lines.extend(["## 低相关论文数量统计", "", f"- 低相关论文数量: {len(low)}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _paper_block(paper: Paper) -> list[str]:
    return [
        f"### {paper.title or 'Untitled'}",
        f"- Source: {paper.journal_or_source or 'Unknown'}",
        f"- Source Type: {_source_type_label(paper.source_type)}",
        f"- Score: {paper.relevance_score} ({relevance_label(paper.relevance_score)})",
        f"- Authors: {paper.authors}",
        f"- Published: {format_date_only(paper.published_date)}",
        f"- DOI: {paper.doi or 'Unknown'}",
        f"- Category: {paper.primary_category_text}",
        f"- URL: {paper.url}",
        f"- Matched Keywords: {paper.matched_keywords_text}",
        f"- Matched Fields: {paper.matched_fields_text or 'Unknown'}",
        f"- Why relevant: {paper.reason_zh}",
        f"- Abstract: {paper.abstract or '该数据源未提供完整摘要。'}",
        "",
    ]


def _profile_lines() -> list[str]:
    profile = load_active_profile()
    return [
        f"- 当前研究方向: {profile.get('display_name', 'Unknown')}",
        f"- Profile ID: {profile.get('profile_id', 'unknown')}",
        f"- Profile 描述: {profile.get('description', '')}",
    ]


def _count_by_source_type(papers: list[Paper]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paper in papers:
        label = _source_type_label(paper.source_type)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _count_by_journal(papers: list[Paper]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paper in papers:
        key = paper.journal_or_source or "Unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0]))


def _count_by_year(papers: list[Paper]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paper in papers:
        year = format_date_only(paper.published_date)[:4]
        if not year.isdigit():
            year = "Unknown"
        counts[year] = counts.get(year, 0) + 1
    return dict(sorted(counts.items(), reverse=True))


def _source_type_label(source_type: str) -> str:
    if source_type == "arxiv":
        return "arXiv"
    if source_type == "journal_rss":
        return "RSS Daily Monitor"
    if source_type == "crossref":
        return "Crossref Top Journal History"
    return source_type or "Unknown"
