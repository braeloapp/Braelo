"""
What + Where Gate
Éllu must NEVER show results without knowing:
1. WHAT the user is looking for (intent + category)
2. WHERE they want to search (ZIP, city, state, landmark)

This gate runs before any search and returns a clarification
question if either piece is missing.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    can_search: bool         # True = both what+where known
    missing_what: bool       # True = don't know what they want
    missing_where: bool      # True = don't know where to search
    clarification_needed: str  # message to ask the user
    resolved_what: str       # extracted category/intent
    resolved_where: str      # extracted location


class WhatWhereGate:
    """
    Checks if we have both WHAT and WHERE before searching.
    Returns clarification message if either is missing.
    """

    def check(
        self,
        message: str,
        category: str,
        subcategory: str,
        city: str,
        state: str,
        zip_code: str,
        latitude: float,
        longitude: float,
        session_city: str,
        session_state: str,
        detected_language: str,
        is_business_search: bool,
        session_ctx: dict | None = None,
    ) -> GateResult:
        """
        Returns GateResult.
        If can_search=False → return clarification_needed to user.
        If can_search=True → proceed with search.
        """
        from chatbot.ellu.persona import get_phrase

        # Only apply gate for business searches
        # Knowledge/guidance questions don't need location gate
        if not is_business_search:
            return GateResult(
                can_search=True,
                missing_what=False,
                missing_where=False,
                clarification_needed="",
                resolved_what=category or "",
                resolved_where=city or state or "",
            )

        # ── Check WHAT ───────────────────────────────────────────
        has_what = bool(category or subcategory)
        
        # Try to extract from message if not already known
        if not has_what:
            from chatbot.services.business_search_service import (
                convert_query_to_portuguese_fields,
            )
            parsed = convert_query_to_portuguese_fields(message)
            has_what = bool(
                parsed.get("category_pt")
                or parsed.get("category_en")
            )
            if has_what:
                category = (
                    parsed.get("category_pt")
                    or parsed.get("category_en", "")
                )

        # ── Check WHERE ──────────────────────────────────────────
        has_where = bool(
            zip_code
            or city
            or state
            or (latitude and longitude)
            or session_city
            or session_state
        )

        if not has_where and session_ctx:
            loc = (session_ctx.get("last_location") or {}) if isinstance(session_ctx, dict) else {}
            scity = (loc.get("city") or "").strip()
            sstate = (loc.get("state") or "").strip()
            szip = (str(loc.get("zip_code") or "")).strip()
            if scity or sstate or szip:
                has_where = True
                logger.info(
                    "[WhatWhereGate] WHERE satisfied from session context "
                    "city=%r state=%r zip=%r",
                    scity,
                    sstate,
                    szip,
                )

        resolved_where = (
            zip_code
            or city
            or session_city
            or state
            or session_state
            or ""
        )
        if not resolved_where and session_ctx:
            loc2 = (session_ctx.get("last_location") or {}) if isinstance(session_ctx, dict) else {}
            resolved_where = (
                (str(loc2.get("zip_code") or "")).strip()
                or (loc2.get("city") or "").strip()
                or (loc2.get("state") or "").strip()
                or ""
            )

        logger.info(
            f"[WhatWhereGate] has_what={has_what} "
            f"has_where={has_where} "
            f"category={category} "
            f"where={resolved_where}"
        )

        # ── Both missing ─────────────────────────────────────────
        if not has_what and not has_where:
            msg = get_phrase(
                "ask_what_or_where", detected_language
            )
            return GateResult(
                can_search=False,
                missing_what=True,
                missing_where=True,
                clarification_needed=msg,
                resolved_what="",
                resolved_where="",
            )

        # ── Only WHAT missing ────────────────────────────────────
        if not has_what:
            msg = get_phrase("ask_what", detected_language)
            return GateResult(
                can_search=False,
                missing_what=True,
                missing_where=False,
                clarification_needed=msg,
                resolved_what="",
                resolved_where=resolved_where,
            )

        # ── Only WHERE missing ───────────────────────────────────
        if not has_where:
            msg = get_phrase("ask_location_any", detected_language)
            return GateResult(
                can_search=False,
                missing_what=False,
                missing_where=True,
                clarification_needed=msg,
                resolved_what=category or "",
                resolved_where="",
            )

        # ── Both present ─────────────────────────────────────────
        return GateResult(
            can_search=True,
            missing_what=False,
            missing_where=False,
            clarification_needed="",
            resolved_what=category or "",
            resolved_where=resolved_where,
        )
