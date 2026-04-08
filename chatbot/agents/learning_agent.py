"""
Learning Agent — persists gap / trace events for directory coverage analysis.

Non-blocking: failures only hit debug logs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

AGENT_LOG = "[BraeloAgent:Learning]"


class LearningAgent:
    COLLECTION = "learning_logs"

    def log_interaction(
        self,
        *,
        session_id: str,
        user_id: str,
        message: str,
        route: str,
        source: str,
        gap_detected: bool,
        location_source: str,
        search_params: dict | None,
        response_valid: bool,
        detected_language: str,
        meta: dict | None = None,
    ) -> None:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.utcnow(),
            "session_id": session_id or "",
            "user_id": user_id or "",
            "message": (message or "")[:500],
            "route": route,
            "source": source,
            "gap_detected": gap_detected,
            "location_source": location_source,
            "search_params": dict(search_params or {}),
            "response_valid": response_valid,
            "detected_language": detected_language,
            "needs_db_update": gap_detected,
            "meta": dict(meta or {}),
        }
        coll = self._get_collection()
        try:
            if coll is not None:
                coll.insert_one(log_entry)
        except Exception as e:
            logger.debug("%s insert skipped: %s", AGENT_LOG, e)

        if gap_detected:
            logger.info(
                "%s GAP message_preview=%r route=%s source=%s params=%s",
                AGENT_LOG,
                (message or "")[:80],
                route,
                source,
                log_entry.get("search_params"),
            )

    def get_gap_summary(self, days: int = 7) -> dict:
        coll = self._get_collection()
        if coll is None:
            return {"error": "learning_logs_unavailable", "total_gaps": 0, "recent_gaps": []}
        try:
            since = datetime.utcnow() - timedelta(days=max(1, int(days)))
            gaps = list(
                coll.find(
                    {"gap_detected": True, "timestamp": {"$gte": since}},
                    {"message": 1, "search_params": 1, "timestamp": 1, "route": 1, "source": 1},
                )
                .sort("timestamp", -1)
                .limit(100)
            )
            return {
                "total_gaps": len(gaps),
                "top_missing_categories": self._count_nested(gaps, "search_params", "category"),
                "top_missing_locations": self._count_nested(gaps, "search_params", "city"),
                "recent_gaps": [
                    {
                        "message": g.get("message"),
                        "route": g.get("route"),
                        "source": g.get("source"),
                        "category": (g.get("search_params") or {}).get("category"),
                        "city": (g.get("search_params") or {}).get("city"),
                        "timestamp": g.get("timestamp").isoformat() if g.get("timestamp") else None,
                    }
                    for g in gaps[:15]
                ],
            }
        except Exception as e:
            logger.exception("%s get_gap_summary failed", AGENT_LOG)
            return {"error": str(e), "total_gaps": 0, "recent_gaps": []}

    def _count_nested(self, gaps: list, key: str, subkey: str) -> list:
        from collections import Counter

        vals = []
        for g in gaps:
            d = g.get(key) or {}
            if isinstance(d, dict):
                v = d.get(subkey) or "unknown"
                vals.append(str(v))
        return Counter(vals).most_common(8)

    def _get_collection(self):
        if not getattr(django_settings, "BRAELO_LEARNING_LOG_TO_MONGO", True):
            return None
        try:
            if getattr(django_settings, "USE_MONGO", False):
                from chatbot.mongo_db import get_db

                db = get_db()
                return db[self.COLLECTION]
        except Exception:
            pass
        try:
            from pymongo import MongoClient

            uri = getattr(django_settings, "MONGO_URI", None) or getattr(
                django_settings, "CUSTOMCONNSTR_MONGO_URI", None
            )
            db_name = getattr(django_settings, "MONGO_DB_NAME", "braelo")
            if uri:
                return MongoClient(uri, serverSelectionTimeoutMS=3000)[db_name][self.COLLECTION]
        except Exception:
            pass
        return None
