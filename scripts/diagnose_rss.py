from __future__ import annotations

import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_radar.journal_fetcher import extract_entry_summary  # noqa: E402
from paper_radar.settings import load_sources  # noqa: E402

try:
    import feedparser
except ImportError:
    feedparser = None


def main() -> int:
    print("PaperRadar RSS 诊断工具")
    print(f"项目目录: {ROOT}")
    if feedparser is None:
        print("错误: 未安装 feedparser")
        return 1

    sources = load_sources().get("journal_sources", [])
    if not sources:
        print("未发现 journal_sources 配置。")
        return 0

    for index, source in enumerate(sources, start=1):
        diagnose_source(index, source)
    return 0


def diagnose_source(index: int, source: dict) -> None:
    name = source.get("name", "Unknown")
    enabled = bool(source.get("enabled"))
    feed_url = str(source.get("feed_url") or "").strip()
    print("\n" + "=" * 80)
    print(f"[{index}] 源名称: {name}")
    print(f"enabled: {enabled}")
    print(f"feed_url 是否为空: {not bool(feed_url)}")
    print(f"feed_url: {feed_url or '(空)'}")

    if not enabled:
        print("最终状态: 跳过：源未启用")
        return
    if not feed_url:
        print("最终状态: 跳过：feed_url 为空")
        return

    try:
        response = requests.get(feed_url, timeout=20, headers={"User-Agent": "PaperRadar/1.0"})
        print(f"HTTP 状态码: {response.status_code}")
        print(f"content-type: {response.headers.get('content-type', '(无)')}")
        preview = response.text[:300].replace("\r", " ").replace("\n", " ")
        print(f"下载内容前 300 字符: {preview}")
        response.raise_for_status()
    except Exception as exc:
        print(f"网络失败: {type(exc).__name__}: {exc}")
        print("最终状态: 不可用")
        return

    try:
        parsed = feedparser.parse(response.content)
        entries = list(getattr(parsed, "entries", []) or [])
        print(f"feedparser 是否识别为 feed: {bool(getattr(parsed, 'feed', None) or entries)}")
        print(f"feedparser.bozo: {bool(getattr(parsed, 'bozo', False))}")
        if getattr(parsed, "bozo", False):
            print(f"bozo_exception: {getattr(parsed, 'bozo_exception', '')}")
        print(f"解析到的 entries 数量: {len(entries)}")
    except Exception as exc:
        print(f"解析失败: {type(exc).__name__}: {exc}")
        print("最终状态: 不可用")
        return

    for entry_index, entry in enumerate(entries[:5], start=1):
        summary = extract_entry_summary(entry)
        print(f"\n  Entry {entry_index}")
        print(f"  title: {entry.get('title', '')}")
        print(f"  link: {entry.get('link', '')}")
        print(f"  published / updated: {entry.get('published') or entry.get('updated') or entry.get('pubDate') or '(无)'}")
        print(f"  summary 是否为空: {not bool(summary)}")
        print(f"  summary 前 200 字符: {summary[:200]}")

    if entries:
        print("最终状态: 可用")
    else:
        print("最终状态: 不可用：entries=0")


if __name__ == "__main__":
    raise SystemExit(main())
