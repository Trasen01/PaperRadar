from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from optical_radar.database import PaperDatabase
from optical_radar.keyword_filter import KeywordFilter
from optical_radar.main_window import score_and_tag
from optical_radar.settings import load_keywords


def main() -> int:
    db = PaperDatabase()
    papers = db.load_papers(min_score=0)
    before_by_title = {paper.title: int(paper.relevance_score or 0) for paper in papers}
    keyword_filter = KeywordFilter(load_keywords())
    rescored = score_and_tag(papers, keyword_filter, keep_unmatched=True)
    stats = db.upsert_papers_with_stats(rescored)
    dropped_below_20 = sum(
        1
        for paper in rescored
        if int(paper.relevance_score or 0) < 20 and before_by_title.get(paper.title, 0) >= 20
    )
    high_relevant = sum(1 for paper in rescored if int(paper.relevance_score or 0) >= 60)

    print(f"重新评分论文数量: {len(rescored)}")
    print(f"分数下降到 20 以下的数量: {dropped_below_20}")
    print(f"仍然高相关的数量: {high_relevant}")
    print(f"数据库更新: inserted={stats.inserted_count}, updated={stats.updated_count}, skipped={stats.skipped_count}")
    print(f"数据库路径: {db.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
