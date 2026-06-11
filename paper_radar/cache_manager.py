from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .utils import CACHE_DIR, ensure_directories

logger = logging.getLogger(__name__)


@dataclass
class CacheCleanupResult:
    cache_dir: Path
    size_before: int
    size_after: int
    deleted_files: int
    freed_bytes: int
    triggered: bool


def cache_size_bytes(cache_dir: Path = CACHE_DIR) -> int:
    if not cache_dir.exists():
        return 0
    total = 0
    for path in cache_dir.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def enforce_cache_limit(max_size_gb: float = 10, cache_dir: Path = CACHE_DIR) -> CacheCleanupResult:
    ensure_directories()
    cache_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = int(float(max_size_gb) * 1024 * 1024 * 1024)
    before = cache_size_bytes(cache_dir)
    if before <= max_bytes:
        result = CacheCleanupResult(cache_dir, before, before, 0, 0, False)
        logger.info("CACHE_SIZE dir=%s bytes=%s max_bytes=%s cleanup=false", cache_dir, before, max_bytes)
        return result

    files: list[tuple[float, Path, int]] = []
    for path in cache_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            files.append((stat.st_mtime, path, stat.st_size))
        except OSError:
            continue
    files.sort(key=lambda item: item[0])

    deleted = 0
    freed = 0
    current = before
    for _, path, size in files:
        if current <= max_bytes:
            break
        try:
            path.unlink()
            deleted += 1
            freed += size
            current -= size
        except OSError as exc:
            logger.warning("CACHE_CLEANUP_DELETE_FAILED path=%s error=%s", path, exc)

    after = cache_size_bytes(cache_dir)
    result = CacheCleanupResult(cache_dir, before, after, deleted, freed, True)
    logger.info(
        "CACHE_CLEANUP dir=%s before=%s after=%s max_bytes=%s deleted_files=%s freed_bytes=%s",
        cache_dir,
        before,
        after,
        max_bytes,
        deleted,
        freed,
    )
    return result
