"""
Response Agent — builds assistant lead-in text for directory hits (Tier 2a0).

Full card payloads still come from existing business objects + _build_response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

AGENT_LOG = "[BraeloAgent:Response]"


@dataclass
class ResponseOutput:
    response_text: str
    source: str
    intent: str
    meta: dict = field(default_factory=dict)


class ResponseAgent:
    def build_directory_intro(
        self,
        *,
        language: str,
        category: str,
        subcategory: str,
        location_note: str | None,
        route_label: str,
    ) -> ResponseOutput:
        from chatbot import chat_flow as cf

        text = cf._directory_ui_intro(
            language,
            category=category or "",
            subcategory=subcategory or "",
            location_note=location_note,
        )
        out = ResponseOutput(
            response_text=text,
            source="braelo_directory",
            intent="location_business_search",
            meta={"route": route_label},
        )
        if getattr(django_settings, "BRAELO_AGENT_DEBUG", True):
            logger.info(
                "%s intro_len=%s intent=%s route=%s",
                AGENT_LOG,
                len(text or ""),
                out.intent,
                route_label,
            )
        return out
