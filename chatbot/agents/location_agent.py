"""
Location Agent — exposes a single structured view of location for agents / logs.

Tier 2a0 already merges geo in chat_flow; this agent records the resolved fields
without re-implementing that merge (avoids drift and bugs).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

AGENT_LOG = "[BraeloAgent:Location]"


@dataclass
class LocationOutput:
    city: str
    state: str
    county: str
    zip_code: str
    latitude: Optional[float]
    longitude: Optional[float]
    country: str
    source: str
    confidence: float
    is_session_inherited: bool
    meta: dict = field(default_factory=dict)


class LocationAgent:
    def run_from_pipeline(
        self,
        *,
        resolved_city: str,
        resolved_state: str,
        county: str,
        zip_code: str,
        latitude: Optional[float],
        longitude: Optional[float],
        country: str,
        user_location: dict[str, Any],
        explicit_profile_location: bool,
        message: str,
        session_id: str,
    ) -> LocationOutput:
        """
        Maps the already-merged Tier 2a0 resolution into LocationOutput for tracing.
        """
        src_parts = []
        if (user_location.get("latitude") is not None and user_location.get("longitude") is not None):
            src_parts.append("device_gps")
        if user_location.get("explicit_profile_location") or explicit_profile_location:
            src_parts.append("explicit_request_profile")
        if (message or "").strip():
            from chatbot.services.business_search_service import convert_query_to_portuguese_fields

            p = convert_query_to_portuguese_fields(message)
            if (p.get("city") or "").strip() or (p.get("state_en") or "").strip():
                src_parts.append("message_parse")

        try:
            from chatbot.chat_flow import _get_session_location

            sl = _get_session_location(session_id) or {}
            inherited = bool((sl.get("city") or sl.get("state")))
        except Exception:
            inherited = False

        source = "+".join(src_parts) if src_parts else "pipeline_merged"
        conf = 0.9 if (resolved_city or resolved_state or zip_code) else 0.35

        out = LocationOutput(
            city=(resolved_city or "").strip(),
            state=(resolved_state or "").strip(),
            county=(county or "").strip(),
            zip_code=(zip_code or "").strip(),
            latitude=latitude,
            longitude=longitude,
            country=(country or "US").strip() or "US",
            source=source,
            confidence=conf,
            is_session_inherited=inherited,
            meta={"session_has_cached_geo": inherited},
        )
        if getattr(django_settings, "BRAELO_AGENT_DEBUG", True):
            logger.info(
                "%s city=%r state=%r zip=%r lat=%s lon=%s source=%s inherited=%s",
                AGENT_LOG,
                out.city,
                out.state,
                out.zip_code,
                out.latitude,
                out.longitude,
                out.source,
                out.is_session_inherited,
            )
        return out
