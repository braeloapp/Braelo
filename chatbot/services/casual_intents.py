"""
Match user messages against intents.json for casual conversation (greetings, goodbye, thanks, etc.).

Tier-0 casual matching is conservative: substantive or FAQ-style input is rejected here so the main
chat pipeline (KB search, OpenAI, business search) always runs for real user questions.
"""
import json
import logging
import random
import re
from pathlib import Path

_log = logging.getLogger(__name__)

# Messages outside these bounds are never treated as casual-only (any language).
_CASUAL_MAX_CHARS = 64
_CASUAL_MAX_WORDS = 12
_CASUAL_QUESTION_MARK_STRICT_LEN = 28  # "?" + longer than this → not casual
_SHORT_PATTERN_MAX_LEN = 6  # hi, hey, thanks, wassup, …
_SHORT_PATTERN_MAX_MESSAGE_CHARS = 56
_LONG_MESSAGE_FOR_PHRASE = 72
_MIN_PATTERN_CHARS_IN_LONG_MSG = 14

CASUAL_TAGS = frozenset({
    "greetings", "goodbye", "thanks", "name1", "name", "fav", "need", "do",
    "noanswer", "date", "AI", "sentiment", "sapient", "abbr", "lang", "sound",
    "artificial", "imortal", "sense", "clone", "move",
})

_INTENTS_CACHE = None


def _normalize(text: str) -> str:
    if not text:
        return ""
    return text.lower().strip()


def _load_intents() -> list:
    global _INTENTS_CACHE
    if _INTENTS_CACHE is not None:
        return _INTENTS_CACHE
    # Look for intents.json in braelo project root (parent of chatbot app)
    app_dir = Path(__file__).resolve().parent.parent
    backend_dir = app_dir.parent
    path = backend_dir / "intents.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _INTENTS_CACHE = data.get("intents", [])
        return _INTENTS_CACHE
    except Exception:
        _INTENTS_CACHE = []
        return []


def is_casual_candidate_message(message: str) -> bool:
    """
    Return True only if the message may be a greeting, thanks, or other small-talk blip.

    Anything that looks like a real question, pasted text, a list, or a URL is excluded so
    retrieval + LLM paths run instead of tier-0 intents.json.
    """
    t = (message or "").strip()
    if not t:
        return False
    if "\n" in t or "\r" in t:
        return False
    low = t.lower()
    if "http://" in low or "https://" in low or re.search(r"\bwww\.", low):
        return False
    if len(t) > _CASUAL_MAX_CHARS:
        return False
    words = t.split()
    nw = len(words)
    if nw > _CASUAL_MAX_WORDS:
        return False
    if t.count("?") >= 2:
        return False
    if "?" in t and len(t) > _CASUAL_QUESTION_MARK_STRICT_LEN:
        return False
    # Dense prose without a question mark (typical FAQ / explanation)
    if nw >= 8 and len(t) > 52:
        return False
    return True


def _whole_phrase_in_message(message_norm: str, phrase: str) -> bool:
    """Phrase appears as a contiguous token run, not as arbitrary substring inside a longer word."""
    if not phrase or not message_norm:
        return False
    p = phrase.strip().lower()
    if not p:
        return False
    if p == message_norm:
        return True
    padded = f" {message_norm} "
    return f" {p} " in padded


def _matches_pattern(message_norm: str, pattern: str) -> bool:
    if not pattern or not message_norm:
        return False
    p = _normalize(pattern)
    if not p:
        return False
    if p == message_norm:
        return True

    # Short patterns ("hi", "hey", "thanks", "wassup", …): no substring matches in long text.
    short_p = len(p) <= _SHORT_PATTERN_MAX_LEN
    if short_p:
        if len(message_norm) > _SHORT_PATTERN_MAX_MESSAGE_CHARS:
            return False
        return (
            message_norm.startswith(p + " ")
            or message_norm.startswith(p + ",")
            or message_norm.startswith(p + "!")
            or message_norm.startswith(p + "?")
            or message_norm.startswith(p + ".")
            or message_norm.startswith(p + ":")
        )

    long_msg = len(message_norm) > _LONG_MESSAGE_FOR_PHRASE
    if long_msg and len(p) < _MIN_PATTERN_CHARS_IN_LONG_MSG:
        return False

    if long_msg:
        return (
            _whole_phrase_in_message(message_norm, p)
            or message_norm.startswith(p)
            or (len(p) <= len(message_norm) and message_norm.endswith(p))
        )

    return (
        p in message_norm
        or message_norm in p
        or message_norm.startswith(p)
        or p.startswith(message_norm)
    )


def _extract_name(message: str) -> str:
    msg = message.strip()
    for prefix in ("my name is", "i'm", "i am", "me chamo", "me llamo", "mi nombre es"):
        if msg.lower().startswith(prefix):
            name = msg[len(prefix):].strip(" ,.")
            if name:
                return name
    return ""


def get_casual_response(message: str) -> tuple:
    if not message or not message.strip():
        return None, None
    if not is_casual_candidate_message(message):
        _log.info(
            "casual_intents.skip_tier0 reason=not_casual_candidate len=%s words=%s",
            len(message.strip()),
            len(message.split()),
        )
        return None, None
    message_norm = _normalize(message)
    intents = _load_intents()
    for intent in intents:
        tag = intent.get("tag", "")
        if tag not in CASUAL_TAGS:
            continue
        patterns = intent.get("patterns") or []
        for pattern in patterns:
            if not pattern and tag != "noanswer":
                continue
            if _matches_pattern(message_norm, pattern):
                responses = intent.get("responses") or []
                if not responses:
                    continue
                response = random.choice(responses)
                if tag == "name":
                    name = _extract_name(message)
                    response = response.replace("{n}", name if name else "there")
                return response.strip(), tag
    return None, None
