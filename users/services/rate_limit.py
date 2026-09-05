"""
Simple process-local rate limiter for auth-sensitive endpoints.

This is a containment control for Phase 1. A shared-store limiter (Redis)
belongs with the broader Phase 10 rate-limit work.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_buckets: dict[str, list[float]] = {}


def check_rate_limit(key: str, limit: int = 8, window_seconds: int = 300) -> bool:
    """
    Return True if the call is allowed.

    `limit` successful recordings are allowed per `window_seconds`.
    """
    if not key:
        return True
    now = time.time()
    with _lock:
        stamps = [t for t in _buckets.get(key, []) if now - t < window_seconds]
        if len(stamps) >= limit:
            _buckets[key] = stamps
            return False
        stamps.append(now)
        _buckets[key] = stamps
        if len(_buckets) > 8000:
            stale = [
                bucket_key
                for bucket_key, values in _buckets.items()
                if not values or now - values[-1] > window_seconds
            ]
            for bucket_key in stale[:2000]:
                _buckets.pop(bucket_key, None)
        return True


def reset_rate_limits() -> None:
    with _lock:
        _buckets.clear()


def client_ip(request) -> str:
    forwarded = ""
    if request is not None:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "") or ""
        if forwarded:
            return forwarded.split(",")[0].strip() or "unknown"
        return (request.META.get("REMOTE_ADDR") or "unknown").strip() or "unknown"
    return "unknown"
