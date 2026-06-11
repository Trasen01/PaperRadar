from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_call(
    operation: Callable[[], T],
    *,
    source_type: str,
    query: str,
    timeout: int | float,
    max_retries: int = 3,
    retry_delay_seconds: int | float = 3,
) -> T:
    last_exc: Exception | None = None
    attempts = max(1, int(max_retries))
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "NETWORK_REQUEST_FAILED source_type=%s query=%s attempt=%s/%s timeout=%s exception=%s",
                source_type,
                query,
                attempt,
                attempts,
                timeout,
                exc,
            )
            if attempt < attempts:
                time.sleep(float(retry_delay_seconds))
    assert last_exc is not None
    raise last_exc
