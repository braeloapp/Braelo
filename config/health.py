"""
Liveness and readiness probes.

/healthz  — process is up (Azure / load balancer liveness)
/readyz   — dependency status: sqlite, mongodb, redis

Statuses: healthy | degraded | unavailable
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger("braelo.health")


def _ok(detail: str = "ok") -> dict:
    return {"status": "ok", "detail": detail}


def _fail(detail: str) -> dict:
    return {"status": "unavailable", "detail": detail}


def _check_sqlite() -> dict:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return _ok("sqlite")
    except Exception as exc:
        logger.exception("health.sqlite.failed")
        return _fail(exc.__class__.__name__)


def _check_mongo() -> dict:
    if getattr(settings, "DJANGO_SKIP_MONGOENGINE", False):
        return {"status": "skipped", "detail": "mongoengine disabled"}
    try:
        from mongoengine.connection import get_connection

        client = get_connection()
        client.admin.command("ping")
        return _ok("mongodb")
    except Exception as exc:
        logger.warning("health.mongo.failed: %s", exc.__class__.__name__)
        return _fail(exc.__class__.__name__)


def _check_redis() -> dict:
    url = (getattr(settings, "REDIS_URL", None) or "").strip()
    if not url:
        return {"status": "skipped", "detail": "REDIS_URL unset"}
    try:
        import redis

        client = redis.Redis.from_url(
            url, socket_connect_timeout=0.4, socket_timeout=0.4
        )
        client.ping()
        return _ok("redis")
    except Exception as exc:
        logger.warning("health.redis.failed: %s", exc.__class__.__name__)
        return _fail(exc.__class__.__name__)


def healthz(request):
    """Liveness: the Django process can serve HTTP."""
    return JsonResponse(
        {
            "status": "ok",
            "service": "braelo",
            "env": getattr(settings, "DJANGO_ENV", ""),
        }
    )


def readyz(request):
    """Readiness: distinguish healthy / degraded / unavailable."""
    checks = {
        "sqlite": _check_sqlite(),
        "mongodb": _check_mongo(),
        "redis": _check_redis(),
    }
    required = checks["sqlite"]["status"]
    optional_down = [
        name
        for name, payload in checks.items()
        if name != "sqlite" and payload["status"] == "unavailable"
    ]
    if required != "ok":
        overall = "unavailable"
        http_status = 503
    elif optional_down:
        overall = "degraded"
        http_status = 200
    else:
        overall = "healthy"
        http_status = 200
    return JsonResponse(
        {
            "status": overall,
            "service": "braelo",
            "env": getattr(settings, "DJANGO_ENV", ""),
            "checks": checks,
        },
        status=http_status,
    )
