"""
Intent classifier — decides when the pipeline should answer from KB + LLM *before*
the business directory (Mongo/SQL), even if a category and location are present.

Guidance questions like “how do I rent in Arizona?” must not be reduced to a raw
listing; directory matches are optional after Tier 2 (KB provider appendix).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

RESPOND_WITH_KNOWLEDGE = "knowledge"
RESPOND_WITH_BUSINESSES = "businesses"
RESPOND_WITH_BOTH = "both"

# User wants guidance first, maybe directory after KB (handled in chat_flow Tier 2).
_HYBRID_SUBSTRINGS = (
    "how do i find a good",
    "how to choose a",
    "what should i look for in a",
    "how do i pick a",
    "tips for choosing",
    "what makes a good",
    "cómo encontrar un buen",
    "como encontrar um bom",
)

_GUIDANCE_SUBSTRINGS = (
    "advise me",
    "advice on",
    "advice about",
    "can you advise",
    "guide me",
    "guidance on",
    "guidance about",
    "how do i ",
    "how can i ",
    "how does ",
    "how to ",
    "what is the process",
    "what is the procedure",
    "what documents",
    "what papers",
    "what requirements",
    "what do i need",
    "what should i know",
    "what should i ",
    "tell me about",
    "tell me how",
    "explain ",
    "explain how",
    "explain what",
    "can you explain",
    "can you tell me",
    "what are the steps",
    "steps to ",
    "is it possible to",
    "is it legal to",
    "do i need ",
    "do i have to",
    "when should i",
    "when do i",
    "why is ",
    "why does ",
    "process for ",
    "procedure for ",
    "information about",
    "info about",
    "learn about",
    "understand ",
    "overview of",
    "describe ",
    "what are the",
    "what is the difference",
    "tenant rights",
    "landlord",
    "how many",
    "types of",
    "type of",
    "what kind",
    "what kinds",
    "statistics",
    "breakdown",
    "categories of",
    "kinds of",
    "help me understand",
    "walk me through",
    "what i need to",
    "requirements ",
    "how to rent",
    "how do i rent",
    "how can i rent",
    "rent a property",
    "rent an apartment",
    "renting a property",
    "renting an apartment",
    "lease a ",
    "leasing a ",
    "como alugar",
    "como posso alugar",
    "como eu alugo",
    "orientar sobre",
    "me orientar",
    "orientação sobre",
    "pode me orientar",
    "você pode me orientar",
    "alugar um imóvel",
    "alugar um imovel",
    "alugar uma casa",
    "alugar apartamento",
    "cómo puedo",
    "qué necesito",
    "qué documentos",
    "cuál es el proceso",
    "cómo se ",
    "me explica",
    "me explique",
)

# Word-boundary / phrase patterns: avoid naive "find a" substring false positives.
_LISTING_RES = (
    re.compile(r"\bfind\s+me\s+(a|an)\b", re.I),
    re.compile(r"\bfind\s+(a|an)\s+\w", re.I),
    re.compile(r"\b(search|look)\s+for\b", re.I),
    re.compile(r"\blooking\s+for\b", re.I),
    re.compile(r"\bshow\s+me\b", re.I),
    re.compile(r"\bgive\s+me\s+a\s+list\b", re.I),
    re.compile(r"\blist\s+of\b", re.I),
    re.compile(r"\bnear\s+me\b", re.I),
    re.compile(r"\bnearby\b", re.I),
    re.compile(r"\bclosest\b", re.I),
    re.compile(r"\bin\s+my\s+area\b", re.I),
    re.compile(r"\bwhere\s+can\s+i\s+find\b", re.I),
    re.compile(r"\bwhere\s+is\s+the\s+nearest\b", re.I),
    re.compile(r"\bwhere\s+to\s+eat\b", re.I),
    re.compile(r"\brecommend\s+(a|an|some)\b", re.I),
    re.compile(r"\bsuggest\s+(a|an|some)\b", re.I),
    re.compile(r"\bhire\s+(a|an)\b", re.I),
    re.compile(r"\bbook\s+(a|an)\b", re.I),
    re.compile(r"\bneed\s+(a|an)\s+\w", re.I),
    re.compile(r"\bneed\s+to\s+hire\b", re.I),
    re.compile(r"\bI\s+need\s+a\b", re.I),
    re.compile(r"\bI\s+want\s+(a|an)\b", re.I),
    re.compile(r"\bbusco\s+un", re.I),
    re.compile(r"\bprocuro\s+um", re.I),
    re.compile(r"\bperto\s+de\s+mim", re.I),
    re.compile(r"\bcerca\s+de\s+m[ií]", re.I),
)


def _matches_hard_listing(m: str) -> bool:
    return any(rx.search(m) for rx in _LISTING_RES)


def _matches_guidance(m: str) -> bool:
    return any(p in m for p in _GUIDANCE_SUBSTRINGS)


def _matches_hybrid(m: str) -> bool:
    return any(p in m for p in _HYBRID_SUBSTRINGS)


def should_preempt_directory_for_knowledge(
    message: str,
    intent: str,
    confidence: float,
    structured: dict | None = None,
) -> bool:
    """
    True → skip directory-first (Lista + Tier 1b); run KB search and LLM answer first.
    """
    m = (message or "").lower().strip()
    if not m:
        return False

    if _matches_hybrid(m):
        logger.info("intent_classifier.preempt reason=hybrid_substring")
        return True
    if _matches_guidance(m):
        logger.info("intent_classifier.preempt reason=guidance_substring")
        return True
    if _matches_hard_listing(m):
        logger.info("intent_classifier.preempt_miss reason=listing_regex")
        return False

    conf = float(confidence or 0.5)
    gi = (intent or "").strip()

    if gi == "business_search" and conf > 0.55:
        return False

    if gi in ("information_request", "unclear") and "?" in (message or ""):
        if conf < 0.45 and gi == "unclear":
            return False
        if any(
            w in m
            for w in (
                "restaurant",
                "restaurants",
                "business",
                "businesses",
                "food scene",
                "dining",
            )
        ):
            logger.info("intent_classifier.preempt reason=informational_question")
            return True
        if gi == "information_request" and conf >= 0.55:
            if re.search(
                r"\b(rent(ing|s)?|leased?|landlord|tenants?|housing|apartment|"
                r"properties|property|mortgage|evict|alugar|imóvel|imovel|fiador)\b",
                m,
                re.I,
            ):
                logger.info("intent_classifier.preempt reason=rent_housing_info")
                return True

    return False


def classify_response_route(
    message: str,
    intent: str,
    confidence: float,
    structured: dict | None = None,
) -> dict:
    """
    Lightweight label for logging / future agents. Directory append after KB stays in chat_flow.
    """
    preempt = should_preempt_directory_for_knowledge(message, intent, confidence, structured)
    if preempt:
        rtype = RESPOND_WITH_BOTH if _matches_hybrid(message or "") else RESPOND_WITH_KNOWLEDGE
        reason = "knowledge_first"
    else:
        rtype = RESPOND_WITH_BUSINESSES
        reason = "directory_first"
    return {
        "response_type": rtype,
        "knowledge_before_directory": preempt,
        "reason": reason,
        "confidence": float(confidence or 0.5),
    }
