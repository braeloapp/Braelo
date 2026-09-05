"""
Shared rate limiter for abuse-sensitive endpoints.

Production uses Redis (same REDIS_URL as Channels) so limits are shared
across workers. Django tests and hosts without Redis fall back to a
process-local window so CI stays deterministic.
"""

from __future__ import annotations

import os
import sys
import threading
import time

_lock = threading.Lock()
_buckets: dict[str, list[float]] = {}
_redis_client = None
_redis_disabled = False

REDIS_KEY_PREFIX = "braelo:rl:"


class RateLimitExceeded(Exception):
    """Raised when a named scope exceeds its allowed request window."""

    def __init__(self, message: str, retry_after: int = 60, scope: str = ""):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))
        self.scope = scope
        self.detail = {"detail": message}


# scope -> (limit, window_seconds)
RATE_LIMIT_POLICIES: dict[str, tuple[int, int]] = {
    "login": (8, 300),
    "admin-login": (8, 300),
    "signup": (5, 3600),
    "social-login": (8, 300),
    "phone-login": (8, 300),
    "token-refresh": (30, 300),
    "forgot-password": (5, 600),
    "password-otp": (8, 300),
    "email-verify-send": (3, 600),
    "email-verify": (8, 300),
    "feedback": (8, 600),
    "report": (8, 600),
    "support": (8, 600),
    "chat-create": (20, 300),
    "search": (30, 60),
    "chatbot": (20, 60),
}


def _is_testing() -> bool:
    if os.getenv("BRAELO_RATE_LIMIT_BACKEND", "").strip().lower() in (
        "memory",
        "local",
        "off",
    ):
        return True
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return len(sys.argv) > 1 and sys.argv[1] == "test"


def _get_redis():
    global _redis_client, _redis_disabled
    if _is_testing() or _redis_disabled:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        from django.conf import settings

        url = (getattr(settings, "REDIS_URL", None) or os.getenv("REDIS_URL") or "").strip()
        if not url:
            _redis_disabled = True
            return None
        client = redis.Redis.from_url(
            url,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception:
        _redis_disabled = True
        return None


def check_rate_limit(key: str, limit: int = 8, window_seconds: int = 300) -> bool:
    """
    Return True if the call is allowed.

    `limit` recordings are allowed per `window_seconds`.
    """
    if not key:
        return True
    client = _get_redis()
    if client is not None:
        try:
            redis_key = f"{REDIS_KEY_PREFIX}{key}"
            count = int(client.incr(redis_key))
            if count == 1:
                client.expire(redis_key, int(window_seconds))
            ttl = client.ttl(redis_key)
            if ttl is not None and int(ttl) < 0:
                client.expire(redis_key, int(window_seconds))
            return count <= int(limit)
        except Exception:
            pass
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
    client = _get_redis()
    if client is None:
        return
    try:
        keys = list(client.scan_iter(match=f"{REDIS_KEY_PREFIX}*", count=200))
        if keys:
            client.delete(*keys)
    except Exception:
        pass


def client_ip(request) -> str:
    forwarded = ""
    if request is not None:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "") or ""
        if forwarded:
            return forwarded.split(",")[0].strip() or "unknown"
        return (request.META.get("REMOTE_ADDR") or "unknown").strip() or "unknown"
    return "unknown"


def policy_for(scope: str) -> tuple[int, int]:
    return RATE_LIMIT_POLICIES.get(scope, (30, 60))


def enforce_rate_limit(request, scope: str, extra_key: str | None = None) -> None:
    """
    Enforce the named policy for this request.

    Always keys by client IP. When `extra_key` is provided (email, user id),
    that identity is limited independently so a shared NAT cannot starve one
    account and one account cannot spray from many IPs without bound.
    """
    limit, window = policy_for(scope)
    keys = []
    if request is not None:
        keys.append(f"{scope}:ip:{client_ip(request)}")
    if extra_key:
        keys.append(f"{scope}:id:{str(extra_key).strip().lower()}")
    if not keys:
        return
    for key in keys:
        if not check_rate_limit(key, limit=limit, window_seconds=window):
            raise RateLimitExceeded(
                "Too many requests. Please try again later.",
                retry_after=window,
                scope=scope,
            )
