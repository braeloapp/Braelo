"""
Service Search Agent — wraps search_business_directory_for_discovery (Tier 2a0).

Does not replace Mongo/SQL internals; returns a consistent envelope for logging,
validation, and learning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

AGENT_LOG = "[BraeloAgent:ServiceSearch]"


@dataclass
class ServiceSearchOutput:
    businesses: list
    see_more: bool
    location_note: Optional[str]
    source: str
    total_found: int
    search_params: dict
    fallback_used: bool
    gap_detected: bool
    meta: dict = field(default_factory=dict)


class ServiceSearchAgent:
    def run(
        self,
        *,
        message: str,
        category: Optional[str],
        subcategory: Optional[str],
        category_hint: Optional[str],
        state: Optional[str],
        city: Optional[str],
        county: Optional[str],
        zip_code: Optional[str],
        user_lat=None,
        user_lon=None,
        language: str,
        limit: int,
        offset: int,
        external_id: Optional[str],
        session_id: Optional[str],
    ) -> ServiceSearchOutput:
        from chatbot.services.business_matching import search_business_directory_for_discovery

        search_params = {
            "state": state,
            "city": city,
            "county": county,
            "zip_code": zip_code,
            "category": category,
            "subcategory": subcategory,
            "category_hint": category_hint,
            "user_lat": user_lat,
            "user_lon": user_lon,
            "limit": limit,
        }
        if getattr(django_settings, "BRAELO_AGENT_DEBUG", True):
            logger.info("%s discovery_params=%s", AGENT_LOG, search_params)

        raw = search_business_directory_for_discovery(
            message=message,
            category=category,
            subcategory=subcategory,
            category_hint=category_hint,
            state=state,
            city=city,
            county=county,
            zip_code=zip_code,
            user_lat=user_lat,
            user_lon=user_lon,
            language=language,
            limit=limit,
            offset=offset,
            external_id=external_id,
            session_id=session_id,
        )
        businesses = raw.get("businesses") or []
        n = len(businesses)
        src = (
            "braelo_directory_mongo"
            if getattr(django_settings, "USE_MONGO", False)
            else "braelo_directory_sql"
        )
        out = ServiceSearchOutput(
            businesses=businesses,
            see_more=bool(raw.get("see_more")),
            location_note=raw.get("location_note"),
            source=src,
            total_found=n,
            search_params=search_params,
            fallback_used=False,
            gap_detected=(n == 0),
            meta={"raw_keys": list(raw.keys()) if isinstance(raw, dict) else []},
        )
        if getattr(django_settings, "BRAELO_AGENT_DEBUG", True):
            logger.info(
                "%s source=%s n=%s gap=%s see_more=%s",
                AGENT_LOG,
                out.source,
                n,
                out.gap_detected,
                out.see_more,
            )
        return out
