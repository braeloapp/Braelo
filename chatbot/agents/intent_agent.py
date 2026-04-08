"""
Intent Agent — enriches structured intent with exploration / purchase hints.
Wraps interpreting existing structured output only (no extra GPT calls here).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

AGENT_LOG = "[BraeloAgent:Intent]"


@dataclass
class IntentOutput:
    primary_intent: str
    category_hint: str
    subcategory_hint: str
    purchase_ready: bool
    just_exploring: bool
    needs_refinement: bool
    raw_structured: dict
    meta: dict = field(default_factory=dict)


class IntentAgent:
    PURCHASE_SIGNALS = (
        "hire",
        "book",
        "schedule",
        "appointment",
        "contact",
        "call now",
        "how much",
        "price",
        "cost",
        "available",
        "contratar",
        "agendar",
        "quanto custa",
        "disponível",
        "precio",
        "costo",
    )

    EXPLORATION_SIGNALS = (
        "what kind",
        "types of",
        "options",
        "tell me about",
        "how does",
        "wondering",
        "just looking",
        "browsing",
        "what are",
    )

    def run(
        self,
        message: str,
        structured_output: dict | None = None,
    ) -> IntentOutput:
        msg_lower = (message or "").lower()
        raw = dict(structured_output or {})

        category = (
            (raw.get("category") or "").strip()
            or (raw.get("biz_cat") or "").strip()
        )
        subcategory = (
            (raw.get("subcategory") or "").strip()
            or (raw.get("biz_sub") or "").strip()
        )

        purchase_ready = any(s in msg_lower for s in self.PURCHASE_SIGNALS)
        just_exploring = any(s in msg_lower for s in self.EXPLORATION_SIGNALS)

        from chatbot.services.business_search_service import convert_query_to_portuguese_fields

        parsed = convert_query_to_portuguese_fields(message or "")
        needs_refinement = (
            not (parsed.get("category_pt") or parsed.get("category_en"))
            and not category
        )

        out = IntentOutput(
            primary_intent=(raw.get("intent") or "unknown").strip(),
            category_hint=category,
            subcategory_hint=subcategory,
            purchase_ready=purchase_ready,
            just_exploring=just_exploring,
            needs_refinement=needs_refinement,
            raw_structured=raw,
            meta={"parsed_has_category": not needs_refinement},
        )
        if getattr(django_settings, "BRAELO_AGENT_DEBUG", True):
            logger.info(
                "%s primary=%s cat_hint=%s sub_hint=%s purchase=%s explore=%s refine=%s",
                AGENT_LOG,
                out.primary_intent,
                out.category_hint,
                out.subcategory_hint,
                out.purchase_ready,
                out.just_exploring,
                out.needs_refinement,
            )
        return out
