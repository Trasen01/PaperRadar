from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optical_radar.crossref_client import CrossrefClient, build_search_queries_from_keywords  # noqa: E402
from optical_radar.keyword_filter import KeywordFilter  # noqa: E402
from optical_radar.scorer import score_paper  # noqa: E402
from optical_radar.settings import load_keywords, load_sources  # noqa: E402
from optical_radar.utils import REPORTS_DIR, ensure_directories, format_date_only  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose PaperRadar Crossref top journal search.")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--max-queries", type=int, default=18)
    args = parser.parse_args()

    keywords = load_keywords()
    queries = build_search_queries_from_keywords(keywords, max_queries=args.max_queries)
    top_journals = [j for j in load_sources().get("top_journals", []) if j.get("crossref_enabled")]
    print(f"启用的 top_journals 数量: {len(top_journals)}")
    for journal in top_journals:
        print(f"- {journal.get('name')} ISSN={journal.get('issn')}")

    result = CrossrefClient(timeout=25, rows=20, sleep_seconds=0.1).fetch_recent(args.days, max_queries=args.max_queries)
    matcher = KeywordFilter(keywords)
    by_journal = Counter()
    abstract_by_journal = Counter()
    doi_by_journal = Counter()
    scored = []
    for paper in result.papers:
        locations = matcher.match_with_locations(paper)
        matches = matcher.flatten_location_matches(locations)
        paper.matched_keywords = matcher.flatten_matches(matches)
        paper.matched_fields = matched_fields_from_locations(locations)
        paper.relevance_score, paper.reason_zh = score_paper(paper, matches, matcher.title_matches(paper), locations)
        by_journal[paper.journal_or_source] += 1
        if paper.abstract:
            abstract_by_journal[paper.journal_or_source] += 1
        if paper.doi:
            doi_by_journal[paper.journal_or_source] += 1
        scored.append(paper)

    query_counts = defaultdict(list)
    for stat in result.query_stats:
        query_counts[stat.journal].append(stat)

    lines = ["# Crossref Diagnosis", "", f"- Days: {args.days}", f"- Queries: {len(queries)}", f"- Parsed unique papers: {len(result.papers)}", ""]
    print(f"成功解析去重后论文数量: {len(result.papers)}")
    print(f"请求失败数量: {len(result.failed_requests)}")

    for journal in top_journals:
        name = str(journal.get("name"))
        lines.extend([f"## {name}", "", f"- ISSN: {journal.get('issn')}", f"- Final papers: {by_journal[name]}", f"- With abstract: {abstract_by_journal[name]}", f"- Without abstract: {by_journal[name] - abstract_by_journal[name]}", f"- DOI count: {doi_by_journal[name]}", ""])
        print(f"{name}: final={by_journal[name]} abstract={abstract_by_journal[name]} no_abstract={by_journal[name]-abstract_by_journal[name]} doi={doi_by_journal[name]}")
        for stat in query_counts.get(name, []):
            print(f"  query={stat.query!r} raw={stat.raw_count} parsed={stat.parsed_count} abstract={stat.abstract_count} doi={stat.doi_count} error={stat.error}")
            lines.append(f"- `{stat.query}` raw={stat.raw_count}, parsed={stat.parsed_count}, abstract={stat.abstract_count}, doi={stat.doi_count}, error={stat.error or 'none'}")
        lines.append("")

    lines.extend(["## Top Scored Examples", ""])
    for paper in sorted(scored, key=lambda p: p.relevance_score, reverse=True)[:20]:
        print(f"TOP score={paper.relevance_score} source={paper.journal_or_source} date={format_date_only(paper.published_date)} title={paper.title[:120]}")
        lines.extend([
            f"### {paper.title}",
            f"- Source: {paper.journal_or_source}",
            f"- Date: {format_date_only(paper.published_date)}",
            f"- DOI: {paper.doi or 'Unknown'}",
            f"- Score: {paper.relevance_score}",
            f"- Keywords: {paper.matched_keywords_text or 'None'}",
            f"- Fields: {paper.matched_fields_text or 'None'}",
            f"- URL: {paper.url}",
            "",
        ])

    if result.failed_requests:
        lines.extend(["## Failures", ""])
        for failure in result.failed_requests:
            lines.append(f"- {failure}")

    ensure_directories()
    path = REPORTS_DIR / "crossref_diagnosis.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"诊断报告已生成: {path}")
    return 0


def matched_fields_from_locations(locations: dict[str, dict[str, list[str]]]) -> list[str]:
    fields = []
    for field, label in [("title", "标题"), ("abstract", "摘要"), ("metadata", "分类/元数据")]:
        if any(values for group, locs in locations.items() if group != "exclude" for loc, values in locs.items() if loc == field):
            fields.append(label)
    return fields


if __name__ == "__main__":
    raise SystemExit(main())
