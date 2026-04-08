"""
Decision Agent — routes the request to a processing path.
Does not generate user-facing answers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

AGENT_LOG = "[BraeloAgent:Decision]"

ROUTE_CASUAL = "casual"
ROUTE_KB_QUESTION = "kb_question"
ROUTE_SERVICE_SEARCH = "service_search"
ROUTE_LOCATION_QUERY = "location_query"
ROUTE_COMPARISON = "comparison"
ROUTE_CLARIFICATION = "clarification"
ROUTE_OFF_TOPIC = "off_topic"


@dataclass
class DecisionOutput:
    route: str
    confidence: float
    intent_label: str
    needs_location: bool
    needs_category: bool
    session_context: dict
    reasoning: str
    meta: dict = field(default_factory=dict)


class DecisionAgent:
    """
    Rule-first routing; uses existing structured classifier output when present.
    """

    COMPARISON_PATTERNS = (
        "compare ",
        " vs ",
        "versus",
        "difference between",
        "which one",
        "what's the difference",
        "comparar",
        "diferença entre",
    )

    def run(
        self,
        message: str,
        detected_language: str,
        session_id: str,
        session_context: dict | None,
        structured_output: dict | None = None,
    ) -> DecisionOutput:
        ctx = dict(session_context or {})
        msg = (message or "").strip()
        msg_lower = msg.lower()

        # Lazy imports — chat_flow is fully loaded when Tier 2a0 runs
        from chatbot.services.business_search_service import is_business_search_query
        from chatbot.chat_flow import is_location_based_query

        if structured_output:
            intent = (structured_output.get("intent") or "").strip()
            confidence = float(structured_output.get("confidence") or 0.5)

            if intent == "business_search" and confidence > 0.6:
                out = DecisionOutput(
                    route=ROUTE_SERVICE_SEARCH,
                    confidence=confidence,
                    intent_label="business_search",
                    needs_location=True,
                    needs_category=True,
                    session_context=ctx,
                    reasoning=f"structured intent={intent} conf={confidence}",
                )
                self._log(out)
                return out

            if intent == "information_request" and confidence > 0.6:
                out = DecisionOutput(
                    route=ROUTE_KB_QUESTION,
                    confidence=confidence,
                    intent_label="information_request",
                    needs_location=False,
                    needs_category=False,
                    session_context=ctx,
                    reasoning=f"structured intent={intent} conf={confidence}",
                )
                self._log(out)
                return out

            if intent == "business_comparison" and confidence > 0.6:
                out = DecisionOutput(
                    route=ROUTE_COMPARISON,
                    confidence=confidence,
                    intent_label="business_comparison",
                    needs_location=False,
                    needs_category=False,
                    session_context=ctx,
                    reasoning=f"structured intent={intent} conf={confidence}",
                )
                self._log(out)
                return out

            if intent == "off_topic" and confidence > 0.55:
                out = DecisionOutput(
                    route=ROUTE_OFF_TOPIC,
                    confidence=confidence,
                    intent_label="off_topic",
                    needs_location=False,
                    needs_category=False,
                    session_context=ctx,
                    reasoning=f"structured intent={intent} conf={confidence}",
                )
                self._log(out)
                return out

        if any(p in msg_lower for p in self.COMPARISON_PATTERNS):
            out = DecisionOutput(
                route=ROUTE_COMPARISON,
                confidence=0.78,
                intent_label="comparison_heuristic",
                needs_location=False,
                needs_category=False,
                session_context=ctx,
                reasoning="comparison pattern in message",
            )
            self._log(out)
            return out

        if is_business_search_query(msg):
            out = DecisionOutput(
                route=ROUTE_SERVICE_SEARCH,
                confidence=0.85,
                intent_label="service_search_heuristic",
                needs_location=True,
                needs_category=True,
                session_context=ctx,
                reasoning="is_business_search_query=true",
            )
            self._log(out)
            return out

        if is_location_based_query(msg):
            out = DecisionOutput(
                route=ROUTE_LOCATION_QUERY,
                confidence=0.82,
                intent_label="location_query_heuristic",
                needs_location=True,
                needs_category=False,
                session_context=ctx,
                reasoning="is_location_based_query=true",
            )
            self._log(out)
            return out

        out = DecisionOutput(
            route=ROUTE_KB_QUESTION,
            confidence=0.55,
            intent_label="default_kb_question",
            needs_location=False,
            needs_category=False,
            session_context=ctx,
            reasoning="default after no stronger signal (tier2a0 branch)",
        )
        self._log(out)
        return out

    def _log(self, out: DecisionOutput) -> None:
        if not getattr(django_settings, "BRAELO_AGENT_DEBUG", True):
            return
        logger.info(
            "%s route=%s label=%s conf=%.2f needs_loc=%s needs_cat=%s reason=%s",
            AGENT_LOG,
            out.route,
            out.intent_label,
            out.confidence,
            out.needs_location,
            out.needs_category,
            out.reasoning,
        )
