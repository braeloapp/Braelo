"""
Chat flow pipeline:
  Tier 0   : Casual talk (intents.json)
  Tier 0b  : Yes/no follow-up on last directory listings (cuisine/TAGS match vs user question)
  Tier 1a  : Structured intent + merged location
  Tier 1b  : Business database FIRST for find/hire local services + location → strict then loose match;
             if empty → directory fallback unless is_location_based_query (then defer to 2a0 / OSM / KB)
  Tier 1c  : Knowledge base hybrid search (after business routing)
  Tier 2a0 : LLM “near me” business list (trigger phrases + ZIP/GPS/state) before map OSM branch;
             skipped when KB-first routing or strong KB retrieval preempts bare “in [state]” heuristics
  Tier 2a  : Map / local office / dining overrides
  Tier 2   : KB exact answer / RAG (+ optional KB provider append)
  Tier 3   : business_search (no KB hit) — same DB + fallback rules
  Tier 4   : General US-life answer (does not push lawyer directories for hire-intent; rescue path may
             still hit DB or directory fallback)
"""
import json
import logging
import re
from django.conf import settings as django_settings
from chatbot.models import ChatHistory, User
from chatbot.services.language_detection import detect_language
from chatbot.services.gpt_service import (
    get_structured_output,
    generate_rag_response,
    generate_exact_kb_answer,
    generate_clarifying_questions,
    generate_business_comparison,
    translate_verified_answer,
    generate_kb_clarification_reply,
    generate_local_office_response,
    generate_local_dining_response,
    generate_general_braelo_response,
    handle_location_search,
    response_looks_like_rag_refusal,
)
from chatbot.services.knowledge_service import search_knowledge
from chatbot.services.business_matching import (
    _filter_mongo_docs_brazilian_vs_portuguese,
    extract_directory_attribute_terms,
    get_top_businesses,
    mongo_comparison_query,
    search_business_directory_for_discovery,
)
from chatbot.geo_constants import backfill_state_from_major_us_city as _backfill_state_from_major_us_city
from chatbot.services.business_search_service import (
    generate_business_not_found_response,
)
from chatbot.services.casual_intents import get_casual_response
from chatbot.services.local_search import find_nearby_places, find_nearby_pois
from chatbot.agents.intent_classifier import (
    classify_response_route,
    should_preempt_directory_for_knowledge,
)

logger = logging.getLogger(__name__)

# Strong hybrid score → prefer exact KB answer path vs RAG (retrieval already filtered candidates)
_KB_HIGH_THRESHOLD = float(getattr(django_settings, "RAG_STRONG_MATCH_HYBRID", 0.68))

# Phrases that indicate “nearby businesses / services” (LLM + location context) — runs before map local_search.
LOCATION_QUERY_TRIGGERS = [
    "near me",
    "near my location",
    "nearby",
    "closest to me",
    "around me",
    "in my area",
    "find me a",
    "find a",
    "restaurants near",
    "services near",
    "businesses near",
    "shops near",
    "stores near",
    "where can i find",
    "who delivers to",
    "open near",
    "cerca de mí",
    "cerca de mi",
    "cerca de mi ubicación",
    "negocios cerca",
    "restaurantes cerca",
    "servicios cerca",
    "en mi área",
    "en mi zona",
    "dónde puedo encontrar",
    "buscar cerca",
    "tiendas cerca",
    "perto de mim",
    "próximo a mim",
    "perto da minha localização",
    "restaurantes perto",
    "serviços perto",
    "negócios perto",
    "na minha área",
    "onde posso encontrar",
    "buscar perto",
    # City/state/country mentioned in message
    "in florida",
    "in texas",
    "in california",
    "in new york",
    "in arizona",
    "in illinois",
    "in georgia",
    "in nevada",
    "restaurants in",
    "food in",
    "places in",
    "businesses in",
    "services in",
    "shops in",
    "stores in",
    # Generic "find X in Y" patterns
    "find in",
    "looking for in",
    "search in",
    # Without "me" — nearby phrasing
    "food near",
    "places near",
    "near the",
    "near downtown",
    "near my hotel",
    "around the",
    "around here",
    "around downtown",
    # Question-style location queries
    "where to find",
    "where to eat",
    "where are the",
    "where is the nearest",
    "any restaurants",
    "any places",
    "any businesses",
    "good restaurants",
    "best restaurants",
]


def is_location_based_query(message: str) -> bool:
    """True when the user is asking for nearby businesses or services (general discovery, not only map POI)."""
    msg = (message or "").lower().strip()
    return any(trigger in msg for trigger in LOCATION_QUERY_TRIGGERS)


def is_pending_location_clarification_followup(message: str, chat_history: list | None) -> bool:
    """
    True when the user sends a short location answer (city/state/ZIP) after the bot asked for
    area/ZIP for a nearby-business search. Phrases like \"in miami?\" do not match
    LOCATION_QUERY_TRIGGERS, so Tier 2a0 must still run.
    """
    msg = (message or "").strip()
    if not msg or len(msg) > 180:
        return False
    hints = _extract_location_hints_from_message(message)
    loc = extract_location_from_message(message)
    has_place = bool(
        hints.get("city")
        or hints.get("zip_code")
        or hints.get("state")
        or hints.get("county")
        or loc.get("city")
        or loc.get("state")
    )
    if not has_place:
        return False
    for m in reversed(chat_history or []):
        if m.get("role") != "assistant":
            continue
        intent = (m.get("intent") or "").strip()
        if intent in ("location_search_needs_zip", "location_incomplete"):
            logger.info("chat_flow.location_followup matched intent=%s", intent)
            return True
        content = (m.get("content") or "").lower()
        if any(
            phrase in content
            for phrase in (
                "zip code",
                "zipcode",
                "código postal",
                "codigo postal",
                "cod postal",
                "postal code",
                "share your zip",
                "share your area",
                "compartir tu código",
                "most relevant options in your area",
                "opciones más relevantes",
                "opções mais relevantes",
            )
        ):
            logger.info("chat_flow.location_followup matched assistant_zip_prompt")
            return True
        break
    return False


def _skip_tier2a0_for_kb_precedence(
    message: str,
    intent: str,
    confidence: float,
    matches: list | None,
    kb_over_directory: bool,
    *,
    force_tier2a0: bool = False,
) -> bool:
    """
    LOCATION_QUERY_TRIGGERS include bare phrases like 'in florida', which match many
    information_request turns that already have KB hits. Skip Tier 2a0 so Tier 2 (exact KB / RAG) runs.
    """
    if force_tier2a0:
        return False
    if kb_over_directory:
        logger.info("chat_flow.tier2a0.skip reason=kb_over_directory")
        return True
    if not matches:
        return False
    top_sim = float((matches[0] or {}).get("similarity") or 0.0)
    min_sim = float(
        getattr(django_settings, "CHAT_TIER2A0_SKIP_MIN_KB_SIMILARITY", 0.48)
    )
    if top_sim < min_sim:
        return False
    if intent not in ("information_request", "unclear"):
        return False
    if intent == "unclear" and float(confidence or 0.0) < 0.5:
        return False
    msg = (message or "").lower()
    strong_listing = (
        "near me",
        "nearby",
        "closest",
        "find me a",
        "show me",
        "list of",
        "where can i find",
        "good restaurants",
        "best restaurants",
        "any restaurants",
        "any places",
        "where is the nearest",
        "where to eat",
        "open near",
        "services near",
        "businesses near",
        "shops near",
        "stores near",
    )
    if any(t in msg for t in strong_listing):
        return False
    # "find a ..." as a discovery phrase (word-boundary), not arbitrary substrings
    if re.search(r"\bfind\s+a\s+", msg):
        return False
    logger.info(
        "chat_flow.tier2a0.skip reason=kb_preempt_location tier top_sim=%.3f intent=%s",
        top_sim,
        intent,
    )
    return True


def extract_zip_from_message(message: str) -> str | None:
    """Extract a 5-digit US ZIP code from the message if present."""
    mo = re.search(r"\b(\d{5})\b", message or "")
    return mo.group(1) if mo else None


def extract_location_from_message(message: str) -> dict:
    """
    Extracts city, state, or country mentioned directly in the message text.

    Examples:
      "restaurants in Florida" → {"state": "Florida"}
      "food in Phoenix Arizona" → {"city": "Phoenix", "state": "Arizona"}
      "places in New York" → {"state": "New York"} (state name; not NYC)

    Returns dict with any of: city, state, country (all optional).
    Returns empty dict if nothing found.
    """
    US_STATES = {
        "alabama",
        "alaska",
        "arizona",
        "arkansas",
        "california",
        "colorado",
        "connecticut",
        "delaware",
        "florida",
        "georgia",
        "hawaii",
        "idaho",
        "illinois",
        "indiana",
        "iowa",
        "kansas",
        "kentucky",
        "louisiana",
        "maine",
        "maryland",
        "massachusetts",
        "michigan",
        "minnesota",
        "mississippi",
        "missouri",
        "montana",
        "nebraska",
        "nevada",
        "new hampshire",
        "new jersey",
        "new mexico",
        "new york",
        "north carolina",
        "north dakota",
        "ohio",
        "oklahoma",
        "oregon",
        "pennsylvania",
        "rhode island",
        "south carolina",
        "south dakota",
        "tennessee",
        "texas",
        "utah",
        "vermont",
        "virginia",
        "washington",
        "west virginia",
        "wisconsin",
        "wyoming",
    }

    US_STATE_ABBR = {
        "al",
        "ak",
        "az",
        "ar",
        "ca",
        "co",
        "ct",
        "de",
        "fl",
        "ga",
        "hi",
        "id",
        "il",
        "in",
        "ia",
        "ks",
        "ky",
        "la",
        "me",
        "md",
        "ma",
        "mi",
        "mn",
        "ms",
        "mo",
        "mt",
        "ne",
        "nv",
        "nh",
        "nj",
        "nm",
        "ny",
        "nc",
        "nd",
        "oh",
        "ok",
        "or",
        "pa",
        "ri",
        "sc",
        "sd",
        "tn",
        "tx",
        "ut",
        "vt",
        "va",
        "wa",
        "wv",
        "wi",
        "wy",
    }

    STATE_ABBR_TO_FULL = {
        "al": "Alabama",
        "ak": "Alaska",
        "az": "Arizona",
        "ar": "Arkansas",
        "ca": "California",
        "co": "Colorado",
        "ct": "Connecticut",
        "de": "Delaware",
        "fl": "Florida",
        "ga": "Georgia",
        "hi": "Hawaii",
        "id": "Idaho",
        "il": "Illinois",
        "in": "Indiana",
        "ia": "Iowa",
        "ks": "Kansas",
        "ky": "Kentucky",
        "la": "Louisiana",
        "me": "Maine",
        "md": "Maryland",
        "ma": "Massachusetts",
        "mi": "Michigan",
        "mn": "Minnesota",
        "ms": "Mississippi",
        "mo": "Missouri",
        "mt": "Montana",
        "ne": "Nebraska",
        "nv": "Nevada",
        "nh": "New Hampshire",
        "nj": "New Jersey",
        "nm": "New Mexico",
        "ny": "New York",
        "nc": "North Carolina",
        "nd": "North Dakota",
        "oh": "Ohio",
        "ok": "Oklahoma",
        "or": "Oregon",
        "pa": "Pennsylvania",
        "ri": "Rhode Island",
        "sc": "South Carolina",
        "sd": "South Dakota",
        "tn": "Tennessee",
        "tx": "Texas",
        "ut": "Utah",
        "vt": "Vermont",
        "va": "Virginia",
        "wa": "Washington",
        "wv": "West Virginia",
        "wi": "Wisconsin",
        "wy": "Wyoming",
    }

    msg_lower = (message or "").lower().strip()
    result = {}

    # Prefer longer state names first so "west virginia" beats "virginia"
    found_state = None
    for state in sorted(US_STATES, key=len, reverse=True):
        if state in msg_lower:
            found_state = state.title()
            break

    if not found_state:
        # Only treat 2-letter codes as states when BOTH letters are uppercase (e.g. "Portland, ME").
        # Lowercase "me" from "near me" must NOT map to Maine — that was clearing GPS and biasing to US.
        for m in re.finditer(r"\b([A-Z]{2})\b", message or ""):
            clean = m.group(1).lower()
            if clean in US_STATE_ABBR:
                found_state = STATE_ABBR_TO_FULL.get(clean, clean.upper())
                break

    if found_state:
        result["state"] = found_state

    city_pattern = re.search(
        r"\bin\s+([A-Za-z][a-zA-Z\s]{2,25}?)(?:\s*,|\s*\?|$|\s+[A-Z]{2}\b)",
        message or "",
        re.IGNORECASE,
    )
    if city_pattern:
        potential_city = city_pattern.group(1).strip()
        if potential_city.lower() not in US_STATES:
            result["city"] = potential_city.title() if potential_city.islower() else potential_city

    return result


def extract_category_from_message(message: str) -> str:
    """
    Extract a simple business category keyword for the location assistant, or fall back to a short query slice.
    """
    categories = [
        "restaurant",
        "restaurante",
        "food",
        "comida",
        "plumber",
        "plomero",
        "electrician",
        "electricista",
        "salon",
        "salão",
        "hair",
        "cabelo",
        "peluquería",
        "doctor",
        "médico",
        "clinic",
        "clínica",
        "grocery",
        "supermercado",
        "mercado",
        "mechanic",
        "mecánico",
        "auto repair",
        "dentist",
        "dentista",
        "lawyer",
        "abogado",
        "advogado",
        "cleaning",
        "limpieza",
        "limpeza",
        "daycare",
        "guardería",
        "childcare",
        "pharmacy",
        "farmacia",
        "farmácia",
        "bank",
        "banco",
        "credit union",
    ]
    msg = (message or "").lower()
    generic_business = (
        "local business",
        "local businesses",
        "location business",
        "location businesses",
        "businesses in",
        "business in",
        "list of business",
        "providers in",
        "services in",
        "companies in",
        "establishments in",
        "any business",
        "some business",
        "find business",
        "search business",
    )
    for g in generic_business:
        if g in msg:
            return "local businesses"
    for cat in categories:
        if cat in msg:
            return cat
    return (message or "").strip()[:500] or "local businesses"


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

class _UserLike:
    """In-memory user object — used when DB or Mongo is unavailable."""
    def __init__(self, d: dict):
        self.external_id = d.get("external_id", "")
        self.display_name = d.get("display_name") or d.get("name")
        self.email = d.get("email")
        self.phone = d.get("phone")
        self.language_preference = d.get("language_preference", "en")
        self.state = d.get("state")
        self.city = d.get("city")
        self.county = d.get("county")
        self.zip_code = d.get("zip_code")
        self.location_enabled = d.get("location_enabled", True)
        self.latitude = d.get("latitude")
        self.longitude = d.get("longitude")
        self.is_banned = d.get("is_banned", False)

    @property
    def has_complete_location(self):
        return bool(self.state and self.county and self.zip_code)

    @property
    def has_contact_details(self):
        return bool(self.email and self.phone)


def _user_from_mongo(doc: dict) -> _UserLike:
    return _UserLike(doc)


_SUPPORTED_LANGS = tuple(getattr(django_settings, "SUPPORTED_LANGUAGES", ["en", "es", "pt"]))
_LANG_SWITCH_PATTERNS = (
    (re.compile(r"\b(reply|respond|answer|speak|write)\s+(in\s+)?(english|en)\b", re.I), "en"),
    (re.compile(r"\b(reply|respond|answer|speak|write)\s+(in\s+)?(spanish|espanol|español|es)\b", re.I), "es"),
    (re.compile(r"\b(reply|respond|answer|speak|write)\s+(in\s+)?(portuguese|portugues|português|pt)\b", re.I), "pt"),
    (re.compile(r"\b(en inglés|en ingles)\b", re.I), "en"),
    (re.compile(r"\b(en español|en espanol)\b", re.I), "es"),
    (re.compile(r"\b(em português|em portugues)\b", re.I), "pt"),
)


def _normalize_language_code(value: str, default: str = "en") -> str:
    v = (value or "").strip().lower()
    if v in ("pt", "pt-br", "pt_br"):
        return "pt"
    if v == "es":
        return "es"
    if v == "en":
        return "en"
    return default


def _extract_requested_language_switch(message: str) -> str:
    t = (message or "").strip()
    if not t:
        return ""
    for rx, code in _LANG_SWITCH_PATTERNS:
        if rx.search(t):
            return code
    return ""


def _user_has_history(user_id: str) -> bool:
    try:
        if getattr(django_settings, "USE_MONGO", False):
            from chatbot.mongo_db import get_db
            db = get_db()
            return bool(db.chat_history.find_one({"external_id": user_id, "role": "user"}))
        return ChatHistory.objects.filter(external_id=user_id, role="user").exists()
    except Exception:
        logger.exception("chat_flow.user_history_check_failed user_id=%s", user_id)
        return False


def _persist_user_language_preference(user, user_id: str, language: str) -> None:
    lang = _normalize_language_code(language)
    try:
        if getattr(django_settings, "USE_MONGO", False):
            from chatbot.mongo_db import get_db
            from datetime import datetime
            get_db().users.update_one(
                {"external_id": user_id},
                {"$set": {"language_preference": lang, "updated_at": datetime.utcnow()}},
                upsert=True,
            )
        else:
            if hasattr(user, "language_preference"):
                user.language_preference = lang
                if hasattr(user, "save"):
                    user.save(update_fields=["language_preference", "updated_at"])
        logger.info("chat_flow.language_preference.saved user_id=%s lang=%s", user_id, lang)
    except Exception:
        logger.exception("chat_flow.language_preference.save_failed user_id=%s lang=%s", user_id, lang)


def _resolve_conversation_language(
    user, user_id: str, session_id: str, message: str, message_detected_lang: str
) -> str:
    """
    Language is locked per SESSION (browser tab / page refresh), not per IP.

    Policy:
    1. Explicit switch command ("reply in Spanish") → always honored immediately.
    2. No session history yet → this is the FIRST message of a NEW session.
       Detect language from the message; ignore any previously stored preference.
       This ensures a page refresh always starts fresh.
    3. Session already has history → ONGOING session.
       Use stored PT/ES preference as a hard lock; re-detect for EN (it is also
       the system default so can't be trusted as a genuine lock).
    4. Language preference is saved on the IP-based user document so it is
       available for all subsequent messages in the same session.
    """
    msg_lang = _normalize_language_code(message_detected_lang)
    stored = _normalize_language_code(getattr(user, "language_preference", "") or "")
    if stored not in _SUPPORTED_LANGS:
        stored = ""

    # "en" is indistinguishable from the DB default — never treat it as a lock.
    # Only "pt" or "es" could have been set by a real first-message detection.
    reliable_stored = stored if stored in ("es", "pt") else ""

    requested = _extract_requested_language_switch(message)
    if requested in _SUPPORTED_LANGS:
        chosen = requested
        reason = "explicit_switch"
    else:
        # session_id resets on every page-load; no history → brand-new session.
        has_session_history = _user_has_history(session_id)
        if not has_session_history:
            # New session: detect from the current message, ignore stored preference.
            chosen = msg_lang or "en"
            reason = "new_session_first_message"
        elif reliable_stored:
            # Ongoing session with a genuine PT/ES lock: honour it.
            chosen = reliable_stored
            reason = "session_lock"
        else:
            # Ongoing session, no reliable lock (English or unset): re-detect.
            chosen = msg_lang or "en"
            reason = "session_redetect"

    # Persist to the IP-based user doc (user_id), NOT the session UUID.
    if chosen != stored:
        _persist_user_language_preference(user, user_id, chosen)
        setattr(user, "language_preference", chosen)

    logger.info(
        "chat_flow.language_policy user_id=%s session_id=%s chosen=%s stored=%s "
        "detected=%s requested=%s reason=%s has_history=%s",
        user_id, session_id, chosen, stored or "none",
        msg_lang, requested or "none", reason,
        reason != "new_session_first_message",
    )
    return chosen


def get_or_create_user(external_id: str, location: dict = None, profile: dict = None) -> _UserLike:
    """Get or create user; location and profile (display_name, email, phone) are merged and persisted."""
    profile = profile or {}
    loc = location or {}
    device_only = bool(loc.get("use_device_location_only"))
    merge = {
        "state": loc.get("state"),
        "city": loc.get("city"),
        "county": loc.get("county"),
        "zip_code": loc.get("zip_code"),
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
        "location_enabled": loc.get("location_enabled", True) if "location_enabled" in loc else None,
        "display_name": profile.get("display_name") or profile.get("name"),
        "email": profile.get("email"),
        "phone": profile.get("phone"),
    }
    if device_only:
        merge["state"] = None
        merge["county"] = None
        merge["zip_code"] = None

    if getattr(django_settings, "USE_MONGO", False):
        try:
            from chatbot.mongo_db import get_db
            from datetime import datetime
            db = get_db()
            col = db.users
            doc = col.find_one({"external_id": external_id})
            now = datetime.utcnow()
            if doc is None:
                doc = {
                    "external_id": external_id,
                    "display_name": None, "email": None, "phone": None,
                    "language_preference": "en",
                    "state": None, "city": None, "county": None, "zip_code": None,
                    "location_enabled": True,
                    "latitude": None, "longitude": None,
                    "created_at": now, "updated_at": now,
                    "is_banned": False,
                }
                for k, v in merge.items():
                    if v is not None or k in ("display_name", "email", "phone"):
                        doc[k] = v
                if "location_enabled" in loc:
                    doc["location_enabled"] = bool(loc["location_enabled"])
                col.insert_one(doc)
            else:
                update = {"updated_at": now}
                if device_only:
                    for k in ("state", "county", "zip_code"):
                        update[k] = None
                for k in ("state", "city", "county", "zip_code", "latitude", "longitude", "display_name", "email", "phone"):
                    if device_only and k in ("state", "county", "zip_code"):
                        continue
                    if merge.get(k) is not None:
                        update[k] = merge[k]
                    elif k in profile and profile[k] is not None:
                        update[k] = profile[k]
                if "location_enabled" in loc:
                    update["location_enabled"] = bool(loc["location_enabled"])
                if update:
                    col.update_one({"external_id": external_id}, {"$set": update})
                    doc = col.find_one({"external_id": external_id})
            return _user_from_mongo(doc)
        except Exception:
            logger.exception("chat_flow.user.mongo_get_or_create_failed external_id=%s", external_id)
            pass

    try:
        user, _ = User.objects.get_or_create(external_id=external_id)
        updated = False
        if device_only:
            for k in ("state", "county", "zip_code"):
                setattr(user, k, None)
            updated = True
            if merge.get("city"):
                setattr(user, "city", merge["city"])
                updated = True
        else:
            for k in ("state", "city", "county", "zip_code"):
                if merge.get(k):
                    setattr(user, k, merge[k])
                    updated = True
        if "location_enabled" in loc:
            user.location_enabled = bool(loc["location_enabled"])
            updated = True
        for k in ("latitude", "longitude"):
            if merge.get(k) is not None:
                setattr(user, k, merge[k])
                updated = True
        for k in ("display_name", "email", "phone"):
            if merge.get(k) is not None:
                setattr(user, k, merge[k])
                updated = True
        if updated:
            user.save(update_fields=["state", "city", "county", "zip_code", "location_enabled",
                                     "latitude", "longitude", "display_name", "email", "phone", "updated_at"])
        return user
    except Exception:
        logger.exception("chat_flow.user.django_get_or_create_failed external_id=%s", external_id)
        return _UserLike({
            "external_id": external_id,
            **loc,
            "display_name": merge.get("display_name"),
            "email": merge.get("email"),
            "phone": merge.get("phone"),
        })


# ---------------------------------------------------------------------------
# Off-topic helpers
# ---------------------------------------------------------------------------

# Do NOT use bare substrings like "code" or "script" — they match "ZIP code", "description", etc.
_OFF_TOPIC_SUBSTRINGS = (
    "c++", "c#", "leetcode", "hackerrank",
    "python script", "javascript", "typescript", "node.js",
    "for loop", "while loop", "syntax error", "unit test",
    "programming", "coding", "tensorflow", "kubernetes",
    "weather forecast", "recipe for", "tell me a joke",
    "sport score", "movie review", "video game",
)

_OFF_TOPIC_PROGRAMMING_RE = re.compile(
    r"\b(write|fix|debug|review)\s+(my\s+)?(code|script|program)\b|"
    r"\bsource\s+code\b|"
    r"\bcode\s+review\b|"
    r"\bdebug(ging)?\s+(this|my|the)\s+(code|script|error)\b|"
    r"\bcreate\s+a\s+program\b|"
    r"\bjava\s+class\b|"
    r"\bimport\s+pandas\b|"
    r"\bimport\s+numpy\b",
    re.IGNORECASE,
)


def _looks_off_topic(message: str) -> bool:
    if not message or len(message) > 800:
        return False
    lower = message.lower().strip()
    if _OFF_TOPIC_PROGRAMMING_RE.search(lower):
        return True
    for p in _OFF_TOPIC_SUBSTRINGS:
        if p in lower:
            return True
    return False


_IN_SCOPE_TOPIC_RE = re.compile(
    r"\b("
    r"immigration|visa|uscis|green\s*card|asylum|work\s*permit|"
    r"housing|rent|lease|landlord|tenant|eviction|"
    r"tax|itin|irs|w-2|1099|"
    r"job|jobs|work|employment|resume|interview|"
    r"health|insurance|clinic|doctor|medicaid|"
    r"school|education|college|university|"
    r"bank|banking|credit|loan|"
    r"driver|drivers|license|dmv|mvd|vehicle|registration|state\s*id|"
    r"imigra|visto|residencia|residência|moradia|aluguel|arrendamento|imovel|imóvel|"
    r"credito|crédito|impuesto|impostos|empleo|trabajo|trabalho|salud|saude|"
    r"educacion|educação|banco|carteira|habilitacao|habilitação|"
    r"restaurante|restaurant|restaurants|food|comida|nearby|near\s+me"
    r")\b",
    re.IGNORECASE,
)


def _looks_in_scope_topic(message: str) -> bool:
    return bool(_IN_SCOPE_TOPIC_RE.search((message or "").strip()))


_ASSISTANT_META_RE = re.compile(
    r"\b("
    r"how\s+do\s+you\s+work|how\s+you\s+work|"
    r"tell\s+me\s+about\s+your\s+work(ing)?|"
    r"what\s+do\s+you\s+do|what\s+can\s+you\s+do|"
    r"how\s+can\s+you\s+help|what\s+is\s+your\s+job|"
    r"como\s+voces?\s+funciona(n)?|como\s+funcionas?|"
    r"que\s+puedes\s+hacer|como\s+puedes\s+ayudar|"
    r"como\s+voce\s+funciona|como\s+voces?\s+pode(m)?\s+ajudar|"
    r"o\s+que\s+voce\s+faz|o\s+que\s+voces?\s+pode(m)?\s+fazer"
    r")\b",
    re.IGNORECASE,
)


def _is_assistant_meta_question(message: str) -> bool:
    t = (message or "").strip()
    if not t:
        return False
    return bool(_ASSISTANT_META_RE.search(t))


def _assistant_capabilities_message(language: str) -> str:
    from chatbot.ellu.persona import get_phrase
    return get_phrase("capabilities", language)


_US_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}
_US_STATE_ABBR = frozenset(_US_STATE_NAMES.values())
_US_STATE_FULL_RE = "|".join(
    re.escape(n) for n in sorted(_US_STATE_NAMES.keys(), key=len, reverse=True)
)
_LOCATION_PREFIX_RE = r"(?:\b(?:in|near|around|at)\s+|cerca\s+de\s+)"
_RX_CITY_COMMA_ST = re.compile(
    _LOCATION_PREFIX_RE + r"([A-Za-z][A-Za-z\s'.-]{1,50}?)\s*,\s*([A-Za-z]{2})\b",
    re.I,
)
_RX_CITY_SPACE_ST = re.compile(
    _LOCATION_PREFIX_RE + r"([A-Za-z][A-Za-z\s'.-]{1,50}?)\s+([A-Za-z]{2})\b(?=\s|[?.!,]|$)",
    re.I,
)
_RX_CITY_FULL_STATE = re.compile(
    _LOCATION_PREFIX_RE + rf"([A-Za-z][A-Za-z\s'.-]{{1,50}}?)\s+({_US_STATE_FULL_RE})\b",
    re.I,
)
_RX_INLINE_CITY_ST = re.compile(
    r"\b([A-Za-z][A-Za-z\s'.-]{1,45}?)\s*,\s*([A-Za-z]{2})\b(?=\s|$|[?.!,])",
    re.I,
)

_LOCATION_CITY_BLOCKLIST = frozenset({
    "brazilian", "mexican", "italian", "japanese", "chinese", "thai", "indian", "peruvian",
    "colombian", "korean", "vietnamese", "french", "greek", "ethiopian", "mediterranean",
    "seafood", "steakhouse", "bbq", "barbecue", "vegan", "vegetarian",
    "my", "the", "this", "your", "our", "downtown", "area", "city", "town", "here", "usa",
    "restaurant", "restaurants", "food", "places", "place", "eating", "dining", "best", "top",
    "good", "great", "popular", "some", "any", "local", "nearby",
})


def _normalize_hint_city(raw: str) -> str:
    if not raw:
        return ""
    city = " ".join(raw.split()).strip(" ,.;:")
    if len(city) < 2:
        return ""
    low = city.lower()
    if low in _LOCATION_CITY_BLOCKLIST:
        return ""
    if low.startswith("my ") or low.startswith("the "):
        return ""
    if _implausible_hint_city_fragment(low):
        return ""
    return city


def _sanitize_pipeline_city(city: str | None) -> str | None:
    """
    Drop garbage "city" values from bad client fields or convert_query echoing full prompts.
    Real placenames are short; long sentences are never valid cities here.
    """
    if city is None:
        return None
    s = str(city).strip()
    if not s:
        return None
    if len(s) > 48:
        return None
    low = s.lower()
    padded = f" {low} "
    junk_markers = (
        " give ",
        " show ",
        " tell ",
        " looking ",
        " restaurants ",
        " want ",
        " only in ",
        " me the ",
        " the me ",
        "listings",
        "directory",
        "businesses",
    )
    if any(m in padded for m in junk_markers):
        return None
    if len(s.split()) > 4:
        return None
    return s


def _implausible_hint_city_fragment(low: str) -> bool:
    """Reject regex-captured 'city' that is clearly prose (commas with state abbr false positives)."""
    if len(low) > 46:
        return True
    if low.count(" ") >= 7:
        return True
    noise = (
        " how ",
        " many ",
        " what ",
        " which ",
        " type ",
        " types ",
        " guide ",
        " tell ",
        " explain ",
        " can you",
        " are there",
        " are in ",
        " properly",
        " proper ",
        " about ",
        " businesses ",
        " restaurants ",
    )
    return any(n in low for n in noise)


def _extract_location_hints_from_message(message: str) -> dict:
    """
    Pull ZIP / city / state from the user's text so map search targets what they typed,
    not only the saved profile (e.g. Phoenix, AZ vs a broad Arizona profile).
    """
    out = {}
    if not message:
        return out
    text = message.strip()

    z = re.search(r"\b(\d{5})(?:-(\d{4}))?\b", text)
    if z:
        out["zip_code"] = z.group(1) + (("-" + z.group(2)) if z.group(2) else "")

    city_val = None
    state_val = None

    m = _RX_CITY_COMMA_ST.search(text)
    if m:
        cn = _normalize_hint_city(m.group(1))
        ab = m.group(2).upper()
        if cn and len(ab) == 2 and ab in _US_STATE_ABBR:
            city_val, state_val = cn, ab

    if not city_val:
        m = _RX_CITY_SPACE_ST.search(text)
        if m:
            cn = _normalize_hint_city(m.group(1))
            ab = m.group(2).upper()
            if cn and len(ab) == 2 and ab in _US_STATE_ABBR:
                city_val, state_val = cn, ab

    if not city_val:
        m = _RX_INLINE_CITY_ST.search(text)
        if m:
            cn = _normalize_hint_city(m.group(1))
            ab = m.group(2).upper()
            if cn and len(ab) == 2 and ab in _US_STATE_ABBR:
                city_val, state_val = cn, ab

    if not city_val:
        m = _RX_CITY_FULL_STATE.search(text)
        if m:
            cn = _normalize_hint_city(m.group(1))
            sk = m.group(2).lower()
            if cn and sk in _US_STATE_NAMES:
                city_val, state_val = cn, _US_STATE_NAMES[sk]

    if city_val:
        out["city"] = city_val
    if state_val:
        out["state"] = state_val

    # Phrases like "restaurants in Florida" set state_en in convert_query but do not match
    # city+state regexes above; merge so cached session city (e.g. Los Angeles) is overridden.
    from chatbot.services import business_search_service as bss

    parsed = bss.convert_query_to_portuguese_fields(text)
    ps = (parsed.get("state_en") or "").strip()
    pc = _sanitize_pipeline_city(
        (_normalize_hint_city((parsed.get("city") or "").strip()) or "").strip() or None
    )
    pco = (parsed.get("county") or "").strip()
    if ps and not out.get("state"):
        out["state"] = ps
    if pc and not out.get("city"):
        out["city"] = pc
    if pco and not out.get("county"):
        out["county"] = pco
    if ps or pc or pco:
        _session_geo_log(
            "hints_from_convert_query",
            state_en=ps or None,
            city=pc or None,
            county=pco or None,
        )

    return out


def _apply_message_location_for_map(
    message: str,
    state: str,
    city: str,
    county: str,
    zip_code: str,
) -> tuple:
    """
    Override profile/structured location with any explicit place in the user message.
    When only a ZIP appears in the message, drop city/county from profile to avoid mixing areas.
    """
    hints = _extract_location_hints_from_message(message)
    if not hints:
        return state, city, county, zip_code

    z, c, co, st = zip_code, city, county, state

    if hints.get("zip_code"):
        z = hints["zip_code"]
    if hints.get("city"):
        c = hints["city"]
        if not hints.get("county"):
            co = None
    if hints.get("state"):
        st = hints["state"]
    if hints.get("county"):
        co = hints["county"]

    if hints.get("zip_code") and not hints.get("city"):
        c = None
        co = None
    # State named without a city ("in Florida") must drop prior session/profile city.
    if hints.get("state") and not hints.get("city"):
        c = None
        co = None

    out = (st, c, co, z)
    if out != (state, city, county, zip_code):
        logger.info(
            "chat_flow.map_location_from_message zip=%s city=%s county=%s state=%s parsed=%s",
            z,
            c,
            co,
            st,
            {k: hints[k] for k in ("zip_code", "city", "state", "county") if k in hints},
        )
    return out


def _off_topic_message(language: str) -> str:
    msgs = {
        "en": (
            "I'm here to help with information about living in the USA and finding local businesses "
            "in your area. I can't help with that. What would you like to know about immigration, "
            "housing, taxes, or which type of business are you looking for?"
        ),
        "es": (
            "Estoy aquí para ayudarte con información sobre vivir en EE.UU. y encontrar negocios locales "
            "en tu zona. No puedo ayudarte con eso. ¿Qué te gustaría saber sobre inmigración, vivienda, "
            "impuestos, o qué tipo de negocio buscas?"
        ),
        "pt": (
            "Estou aqui para ajudar com informações sobre viver nos EUA e encontrar negócios locais "
            "na sua região. Não posso ajudar com isso. O que você gostaria de saber sobre imigração, "
            "moradia, impostos, ou que tipo de negócio você procura?"
        ),
    }
    return msgs.get(language, msgs["en"])


def _extract_local_place_query(message: str) -> str:
    """Return a place query for local office lookup, or empty string."""
    t = (message or "").lower().strip()
    if not t:
        return ""
    local_markers = (
        "near", "nearest", "close", "closest", "around me", "in my area", "nearby", "local",
        "where is", "where can i", "where do i", "how do i find", "find the", "find a",
        "locate", "location of", "address of",
    )
    if not any(m in t for m in local_markers):
        return ""

    # Common office/provider intents we can search on maps.
    if (
        "dmv" in t
        or "mvd" in t
        or "motor vehicle" in t
        or ("driver" in t and "license" in t)
        or "driver license" in t
        or "drivers license" in t
    ):
        return "Department of Motor Vehicles"
    if "uscis" in t or "immigration office" in t:
        return "USCIS field office"
    if "social security" in t or "ssa office" in t:
        return "Social Security Administration office"
    if "post office" in t or "usps" in t:
        return "USPS post office"
    return ""


def _extract_restaurant_search_query(message: str) -> str:
    """Nominatim search phrase for dining POIs, or empty if not a local restaurant discovery ask."""
    t = (message or "").lower().strip()
    if not t:
        return ""
    if any(
        x in t
        for x in (
            "food stamp",
            "food stamps",
            "snap benefit",
            "snap benefits",
            " wic ",
            "wic program",
            "food bank",
            "food pantry",
        )
    ):
        if "restaurant" not in t and "dining" not in t and "eat out" not in t:
            return ""

    dining_keywords = (
        "restaurant",
        "restaurants",
        "restaurante",
        "restaurantes",
        "dining",
        "eatery",
        "eateries",
        "place to eat",
        "places to eat",
        "where to eat",
        "somewhere to eat",
        "go out to eat",
        "eat out",
        "food near me",
        "food truck",
        "café",
        "cafe ",
        " cafe",
        " brunch",
        "brunch ",
        "onde comer",
        "lugar para comer",
    )
    if not any(k in t for k in dining_keywords):
        return ""

    local_markers = (
        "near",
        "nearest",
        "close",
        "closest",
        "around me",
        "in my area",
        "nearby",
        "local",
        "where is",
        "where can i",
        "where do i",
        "how do i find",
        "find the",
        "find a",
        "locate",
        "in town",
        "around here",
        "my area",
        "near me",
        "best ",
        "top ",
        "popular ",
        "recommend",
        "suggestions",
        "list of",
        "in my city",
        "in my town",
        "good restaurant",
        "good restaurants",
        "good place",
        "good places",
        "great restaurant",
        "cerca de mí",
        "cerca de mi",
        "cerca de ti",
        "en mi zona",
        "en mi area",
        "por aquí",
        "por aqui",
        "perto",
        "perto de mim",
        "na minha região",
        "na minha regiao",
        "na minha área",
        "na minha area",
    )
    if not any(m in t for m in local_markers):
        return ""

    cuisines = (
        "brazilian",
        "mexican",
        "italian",
        "japanese",
        "chinese",
        "thai",
        "indian",
        "peruvian",
        "colombian",
        "korean",
        "vietnamese",
        "french",
        "greek",
        "ethiopian",
        "mediterranean",
        "seafood",
        "steakhouse",
        "bbq",
        "barbecue",
        "vegan",
        "vegetarian",
    )
    prefix = ""
    for c in cuisines:
        if c in t:
            prefix = c + " "
            break

    return (prefix + "restaurant").strip()


# ---------------------------------------------------------------------------
# Business discovery — DB must win before KB / generic web advice (see KB tier for append)
# ---------------------------------------------------------------------------

_BUSINESS_TRIGGER_RE = re.compile(
    r"\b(find|search|looking for|need a|need an|want a|want an|recommend|hire|near me|nearby|"
    r"cerca de|perto de|in my area|servicios|alguien que|alg[uú]n|any\s+\w+\s+near|nearby\s+\w+)\b",
    re.I,
)

# Listing-style questions with a place name but intent may stay "information_request" from the LLM.
_DIRECTORY_LISTING_INTENT_RE = re.compile(
    r"\b(list\s+(?:of\s+)?businesses|businesses\s+of|local\s+businesses|"
    r"find\s+(?:the\s+)?list|show\s+(?:me\s+)?(?:the\s+)?list|in\s+our\s+directory)\b",
    re.I,
)


def _directory_listing_intent(message: str) -> bool:
    t = message or ""
    if not _DIRECTORY_LISTING_INTENT_RE.search(t):
        return False
    if _BUSINESS_TRIGGER_RE.search(t):
        return True
    if re.search(r"\b(in|near|around|at)\s+[A-Za-zÀ-ÿ]", t):
        return True
    if re.search(r"\b\d{5}(?:-\d{4})?\b", t):
        return True
    return False

_CAREER_EDUCATION_RE = re.compile(
    r"\b(how to become|how do i become|becoming a|career as|law school|med school|what is a (lawyer|attorney|doctor|dentist|cpa)|"
    r"degree to be|bar exam|years? of college)\b",
    re.I,
)

_SERVICE_INFERENCE = [
    (re.compile(r"\b(attorney|lawyers?|abogad|legal services|law firm)\b", re.I), ("legal", "lawyer")),
    (re.compile(r"\b(immigration attorney|immigration lawyer|immigration consultant)\b", re.I), ("immigration", "consultant")),
    (re.compile(r"\b(doctor|physician|clinic|gp\b|general practitioner)\b", re.I), ("health", "doctor")),
    (re.compile(r"\b(dentist|dental)\b", re.I), ("health", "dentist")),
    (re.compile(r"\b(tax preparer|cpa\b|accountant|tax filing|imposto|income tax prep)\b", re.I), ("tax", "tax_preparer")),
    (re.compile(r"\b(plumber|electrician|hvac)\b", re.I), ("home", "home_services")),
    (re.compile(r"\b(real estate|realtor|realty|corretor de im[oó]veis)\b", re.I), ("housing", "real_estate_agent")),
    # Food / dining (Portuguese Lista uses "Gastronomia", "Restaurantes", etc.)
    (
        re.compile(
            r"\b(gastronomia|gastronomy|restaurants?|dining|food scene|places to eat|"
            r"churrascaria|churrasco|lanchonete|comida|where to eat|cuisine|cafes?|coffee shops?)\b",
            re.I,
        ),
        ("food", "restaurant"),
    ),
]

# "list of businesses of the Gastronomia in Los Angeles" → category "Gastronomia"
_BUSINESS_OF_PHRASE_RE = re.compile(
    r"(?:list\s+of\s+)?businesses\s+of\s+(?:the\s+)?([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\-\&\']{0,48}?)\s+in\b",
    re.I,
)


def _infer_service_category_from_text(message: str) -> tuple:
    t = message or ""
    for rx, pair in _SERVICE_INFERENCE:
        if rx.search(t):
            return pair
    mo = _BUSINESS_OF_PHRASE_RE.search(t)
    if mo:
        raw = mo.group(1).strip()
        if len(raw) >= 2:
            return (raw, None)
    return (None, None)


def _infer_category_from_prior_user_turns(chat_history: list | None) -> tuple:
    """Merge recent user messages and infer food/legal/etc. (for location-only follow-ups)."""
    if not chat_history:
        return None, None
    parts = []
    for m in chat_history[-14:]:
        if m.get("role") == "user":
            parts.append((m.get("content") or "").strip())
    blob = " ".join(x for x in parts if x)
    return _infer_service_category_from_text(blob)


def _llm_category_smells_like_location_noise(cat: str | None, message: str) -> bool:
    """Structured model sometimes puts the whole utterance (e.g. 'in Los Angeles?') in category."""
    if not cat:
        return False
    c = cat.strip()
    if len(c) > 80:
        return True
    if "?" in c:
        return True
    cl = c.lower()
    if cl.startswith(("in ", "near ", "around ", "at ")):
        return True
    msg_l = (message or "").strip().lower()
    if msg_l and cl == msg_l:
        return True
    return False


def _looks_like_location_only_followup(message: str) -> bool:
    """Short reply that names a place but does not repeat the service (e.g. 'in Los Angeles?')."""
    msg = (message or "").strip()
    if not msg or len(msg) > 120:
        return False
    ml = msg.lower()
    if any(
        x in ml
        for x in (
            "restaurant",
            "restaurants",
            "food ",
            " dining",
            "lawyer",
            "doctor",
            "plumber",
            "dentist",
            "hotel",
            "shop",
            "café",
            "cafe",
            "eat ",
        )
    ):
        return False
    if re.match(r"^\s*(in|near|around|at)\s+.+\??\s*$", msg, re.I):
        return True
    hints = _extract_location_hints_from_message(msg)
    if (hints.get("city") or hints.get("state")) and len(msg) <= 70:
        return True
    return False


def _sanitize_structured_category_for_followup(
    message: str,
    chat_history: list | None,
    st_cat: str | None,
    st_sub: str | None,
) -> tuple[str | None, str | None]:
    """
    When the user only adds a city/region after discussing restaurants (etc.), the structured
    extractor may stuff the whole message into category — strip that and inherit topic from history.
    """
    mc = (st_cat or "").strip() or None
    ms = (st_sub or "").strip() or None
    loc_only = _looks_like_location_only_followup(message)
    garbage = _llm_category_smells_like_location_noise(mc, message)
    if not (loc_only or garbage):
        return mc, ms
    ic, isub = _infer_category_from_prior_user_turns(chat_history)
    if ic:
        return ic, isub or ms
    if garbage:
        return None, ms
    return mc, ms


def _heuristic_business_discovery(message: str) -> bool:
    """Hire/find local professional: service keyword + trigger (find/near me/ZIP/city phrase)."""
    t = (message or "").strip()
    if len(t) < 5:
        return False
    if _CAREER_EDUCATION_RE.search(t):
        return False
    cat, sub = _infer_service_category_from_text(t)
    if cat or sub:
        # e.g. "restaurants in florida" — inferred food + state in text (any case)
        if extract_location_from_message(t):
            return True
    if not (cat or sub):
        return False
    if _BUSINESS_TRIGGER_RE.search(t):
        return True
    if re.search(r"\b(\d{5})(?:-\d{4})?\b", t):
        return True
    if re.search(r"\b(in|near|en)\s+[A-Z][a-z]{2,}", t):
        return True
    if re.search(r"\b(in|near|around|en)\s+[a-z]", t) and extract_location_from_message(t):
        return True
    return False


# Substrings that mean "user wants a place or local business" (paired with location-based triggers).
_DIRECTORY_BUSINESS_NEEDLES = (
    "restaurant",
    "restaurante",
    "food",
    "dining",
    "café",
    "cafe",
    "coffee shop",
    "bakery",
    "bar ",
    " pub ",
    "grocery",
    "supermarket",
    "plumber",
    "electrician",
    "lawyer",
    "attorney",
    "abogad",
    "advogad",
    "dentist",
    "doctor",
    "clinic",
    "salon",
    "hair ",
    "spa ",
    "mechanic",
    "pharmacy",
    "farmacia",
    "bank ",
    "hotel",
    "motel",
    "gym",
    "fitness",
    "shop",
    "store",
    "retail",
    "churrascaria",
    "gastronom",
    "comida",
    "lanchonete",
    "where to eat",
    "places to eat",
    "good restaurants",
    "best restaurants",
    "any restaurants",
)


def _directory_lookup_intent(
    message: str, structured: dict, intent: str, confidence: float = 0.5
) -> bool:
    """
    True when we should hit the business directory (Mongo/SQL) before KB, RAG, or other LLM tiers.

    Pipeline: user message → directory first → if empty, fall through to LLM / Places / KB as today.
    """
    conf = float((structured or {}).get("confidence") or confidence or 0.5)
    if should_preempt_directory_for_knowledge(message, intent, conf, structured):
        logger.info(
            "chat_flow.directory_intent.skip reason=knowledge_preempt intent=%s",
            intent,
        )
        return False
    if intent == "business_search":
        return True
    if _directory_listing_intent(message):
        return True
    if _heuristic_business_discovery(message):
        return True

    inf_cat, inf_sub = _infer_service_category_from_text(message or "")
    sc = (structured.get("category") or "").strip()
    ss = (structured.get("subcategory") or "").strip()
    has_cat = bool(inf_cat or inf_sub or sc or ss)
    loc_in_msg = bool(extract_location_from_message(message))
    locish = is_location_based_query(message) or loc_in_msg or bool(
        _BUSINESS_TRIGGER_RE.search(message or "")
    )

    if has_cat and locish:
        return True

    if is_location_based_query(message):
        pq = _extract_local_place_query(message)
        if pq:
            return True
        rq = _extract_restaurant_search_query(message)
        if rq:
            return True
        hint = extract_category_from_message(message or "")
        if (
            hint
            and len(hint) <= 80
            and hint.strip().lower() not in ("local businesses", "businesses", "business")
        ):
            return True
        msg_l = (message or "").lower()
        if any(n in msg_l for n in _DIRECTORY_BUSINESS_NEEDLES):
            return True

    return False


def _has_business_location(state: str, city: str, county: str, zip_code: str, user_lat, user_lon) -> bool:
    if user_lat is not None and user_lon is not None:
        return True
    if not (state or "").strip():
        return False
    return bool(zip_code or city or county)


def _service_heading_label(category: str, subcategory: str, language: str) -> str:
    c = (category or "").lower()
    s = (subcategory or "").lower()
    labels = {
        "legal": {"en": "lawyers", "es": "abogados", "pt": "advogados"},
        "immigration": {"en": "immigration professionals", "es": "profesionales de inmigración", "pt": "profissionais de imigração"},
        "tax": {"en": "tax professionals", "es": "profesionales de impuestos", "pt": "profissionais de impostos"},
        "health": {"en": "healthcare providers", "es": "proveedores de salud", "pt": "profissionais de saúde"},
        "home": {"en": "home service providers", "es": "proveedores de servicios para el hogar", "pt": "profissionais para o lar"},
        "housing": {"en": "housing professionals", "es": "profesionales de vivienda", "pt": "profissionais de moradia"},
    }
    if c in labels:
        return labels[c].get(language, labels[c]["en"])
    if s == "lawyer":
        return {"en": "lawyers", "es": "abogados", "pt": "advogados"}.get(language, "lawyers")
    return {"en": "providers", "es": "proveedores", "pt": "profissionais"}.get(language, "providers")


def _format_businesses_recommendation_engine(
    businesses: list,
    language: str,
    category: str = "",
    subcategory: str = "",
    location_note: str = None,
) -> str:
    """Concise DB-only listing (no extra marketing copy)."""
    if not businesses:
        return ""
    svc = _service_heading_label(category, subcategory, language)
    head = {
        "en": f"Here are some {svc} available in your area:",
        "es": f"Aquí hay algunos {svc} disponibles en tu zona:",
        "pt": f"Aqui estão alguns {svc} disponíveis na sua região:",
    }.get(language, f"Here are some {svc} available in your area:")
    lines = [head, ""]
    for i, b in enumerate(businesses, 1):
        name = b.get("name", "")
        cat = (b.get("category") or "").strip()
        sub = (b.get("subcategory") or "").strip()
        cat_disp = cat.title() if cat else ""
        sub_disp = sub.replace("_", " ").title() if sub else ""
        cat_line = f"{cat_disp} ({sub_disp})" if cat_disp and sub_disp else (cat_disp or sub_disp or "—")
        city = b.get("city") or ""
        st = b.get("state") or ""
        z = b.get("zip_code") or ""
        loc = ", ".join(p for p in [city, st, z] if p)
        phone = (b.get("contact_info") or "").strip()
        wa = (b.get("whatsapp_url") or "").strip()
        lines.append(f"{i}. {name}")
        lines.append(f"   - Category: {cat_line}")
        lines.append(f"   - Location: {loc or '—'}")
        lines.append(f"   - Phone: {phone or '—'}")
        lines.append(f"   - WhatsApp: {wa or '—'}")
        lines.append("")
    if location_note:
        lines.append(location_note)
    return "\n".join(lines).strip()


def _directory_ui_intro(
    language: str,
    category: str = "",
    subcategory: str = "",
    location_note: str | None = None,
) -> str:
    """Short assistant text when the client renders directory rows as structured cards."""
    svc = _service_heading_label(category, subcategory, language)
    heads = {
        "en": f"Here are some {svc} from our directory:",
        "es": f"Algunos {svc} de nuestro directorio:",
        "pt": f"Alguns {svc} do nosso diretório:",
    }
    head = heads.get(language, heads["en"])
    if location_note:
        return f"{head}\n\n{location_note}".strip()
    return head


def _directory_first_page_limit() -> int:
    """Cap directory rows on first response (client UX: avoid dumping 10+ cards at once)."""
    cap = int(getattr(django_settings, "CHATBOT_DIRECTORY_FIRST_PAGE_SIZE", 8))
    mx = int(getattr(django_settings, "MAX_BUSINESS_RESULTS", 20))
    return max(1, min(cap, mx))


def _directory_client_followup_block(
    language: str,
    *,
    zip_code: str | None,
    city: str | None,
    state: str | None,
    see_more: bool,
    n_shown: int,
) -> str:
    """Intent confirmation + refinement (after directory hits)."""
    lang = (language or "en").lower()[:2]
    loc_bits = [p for p in [city, state, zip_code] if p and str(p).strip()]
    loc_label = ", ".join(loc_bits) if loc_bits else None
    if lang == "es":
        loc_phrase = loc_label or "esa zona"
        lines = [
            f"Mostré las primeras {n_shown} opciones en {loc_phrase}.",
            "¿Quieres que sigamos solo con negocios brasileños, o ampliemos a ciudades cercanas?",
            "También puedes pedirme que acorte la lista (por ejemplo solo restaurantes) o que muestre más resultados.",
        ]
        if see_more:
            lines.append('Di “mostrar más” o usa “Ver más” en la app para el siguiente grupo.')
        return "\n".join(lines)
    if lang == "pt":
        loc_phrase = loc_label or "essa região"
        lines = [
            f"Mostrei as primeiras {n_shown} opções em {loc_phrase}.",
            "Quer que eu continue só com negócios brasileiros, ou amplie para cidades próximas?",
            "Você também pode pedir para eu enxugar a lista (por exemplo só restaurantes) ou mostrar mais resultados.",
        ]
        if see_more:
            lines.append('Diga “mostrar mais” ou use “Ver mais” no app para o próximo grupo.')
        return "\n".join(lines)
    loc_phrase = loc_label or "that area"
    lines = [
        f"Here are the first {n_shown} matches for {loc_phrase}.",
        "Would you like me to keep this to Brazilian-owned or Brazilian-style businesses only, or widen to nearby towns?",
        "You can also ask me to narrow the list (for example only sit-down restaurants) or to show more results.",
    ]
    if see_more:
        lines.append('Say “show more” or use “See more” in the app for the next batch.')
    return "\n".join(lines)


def _location_external_links_followup(language: str) -> str:
    """Explains web links after Google / LLM location fallback (client: no silent redirect)."""
    lang = (language or "en").lower()[:2]
    if lang == "es":
        return (
            "Nota: los enlaces siguientes son búsquedas web (Google) para explorar; no son filas internas "
            "del directorio de Braelo. Si quieres, dime otra categoría o un radio más amplio y vuelvo a "
            "buscar primero en nuestra base."
        )
    if lang == "pt":
        return (
            "Observação: os links abaixo são buscas na web (Google) para você explorar; não são registros "
            "internos do diretório Braelo. Se quiser, diga outra categoria ou um raio maior e eu tento "
            "de novo primeiro na nossa base."
        )
    return (
        "Note: the links below open general web searches (Google) so you can explore further; they are "
        "not Braelo directory listings. If you tell me another category or a wider area, I can search "
        "our directory again first."
    )


# ---------------------------------------------------------------------------
# KB answer + local provider suggestions (uses same Business table / Mongo collections)
# ---------------------------------------------------------------------------

def _should_suggest_providers_with_kb(structured: dict) -> bool:
    """True when classifier gave a concrete service category (not generic/other-only)."""
    if not structured:
        return False
    cat = (structured.get("category") or "").strip().lower()
    sub = (structured.get("subcategory") or "").strip().lower()
    if not cat and not sub:
        return False
    if cat in ("other", "none", "null") and not sub:
        return False
    return True


def _kb_provider_search_location(
    state: str,
    city: str,
    county: str,
    zip_code: str,
    user_location: dict | None,
    user_lat,
    user_lon,
) -> dict | None:
    """
    Build location kwargs for get_top_businesses when appending directory rows to a KB answer.
    Non-US device GPS must not widen the Mongo query (would return unrelated US listings).
    When we only have an international GPS pin and no US state/ZIP/county, skip the appendix.
    """
    loc = user_location or {}
    cc = (loc.get("country_code") or "").strip().lower()

    st = (state or "").strip()
    cy = (city or "").strip()
    co = (county or "").strip()
    z = (zip_code or "").strip()

    has_us_text_anchor = bool(st or z or co)
    us_device_ok = user_lat is not None and user_lon is not None and cc in ("us", "")
    if not has_us_text_anchor and not us_device_ok:
        logger.info(
            "chat_flow.kb_provider_suggest.skip reason=no_us_directory_anchor country_code=%s",
            cc or "unset",
        )
        return None

    p_lat, p_lon = user_lat, user_lon
    p_city, p_st, p_co, p_z = cy, st, co, z

    if cc and cc != "us":
        p_lat = None
        p_lon = None
        if not has_us_text_anchor:
            logger.info(
                "chat_flow.kb_provider_suggest.skip reason=intl_gps_only country_code=%s",
                cc,
            )
            return None
        p_city = ""
        strict = True
    else:
        strict = bool(p_st or p_z or p_co)

    return {
        "state": p_st or None,
        "city": p_city or None,
        "county": p_co or None,
        "zip_code": p_z or None,
        "user_lat": p_lat,
        "user_lon": p_lon,
        "strict_location": strict,
    }


# ---------------------------------------------------------------------------
# Business formatting helper
# ---------------------------------------------------------------------------

def _format_businesses(businesses: list, language: str, location_note: str = None,
                        see_more: bool = False, heading: str = None) -> str:
    if not businesses:
        return ""
    heading = heading or {
        "en": "Here are some options that might help you:",
        "es": "Estas son algunas opciones que podrían ayudarte:",
        "pt": "Aqui estão algumas opções que podem ajudar:",
    }.get(language, "Here are some options that might help you:")

    parts = [heading]
    for b in businesses:
        name = b.get("name", "")
        cat = b.get("category") or b.get("subcategory") or ""
        loc_parts = filter(None, [b.get("city"), b.get("county"), b.get("state"), b.get("zip_code")])
        loc_str = ", ".join(loc_parts)
        dist = b.get("distance_miles")
        dist_str = f" ({dist} miles away)" if dist is not None else ""
        line = name
        if cat:
            line += f", {cat}"
        if loc_str:
            line += f", in {loc_str}"
        line += dist_str
        if b.get("is_sponsored"):
            line += " (Sponsored)"
        parts.append(line)
        contact = (b.get("contact_info") or "").strip()
        wa = (b.get("whatsapp_url") or "").strip()
        if contact:
            parts.append(f"Contact: {contact}")
        if wa and wa not in contact:
            parts.append(f"WhatsApp: {wa}")

    brief = {
        "en": "These providers serve your area and can assist with the service you asked about.",
        "es": "Estos proveedores sirven tu zona y pueden ayudarte con el servicio que buscas.",
        "pt": "Esses provedores atendem sua região e podem ajudar com o serviço que você precisa.",
    }.get(language, "These providers serve your area and can assist with the service you asked about.")

    parts.append("")
    parts.append(brief)
    if location_note:
        parts.append("")
        parts.append(location_note)
    if see_more:
        parts.append({"en": "See more…", "es": "Ver más…", "pt": "Ver mais…"}.get(language, "See more…"))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# History helper
# ---------------------------------------------------------------------------

_ZIP_US_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")

_SESSION_LOCATION_CACHE_KEY = "braelo_session_location_{}"
_SESSION_LOCATION_CACHE_TTL = 3600
_DIRECTORY_GEO_HISTORY_INTENTS = frozenset({"business_search", "location_business_search"})
_LOCATION_REFERENCE_PHRASES_EN = (
    "in that",
    "in there",
    "over there",
    "that area",
    "same place",
    "same city",
    "same area",
    "same town",
    "that city",
    "that town",
    "that place",
    "those ones",
    "those places",
    "the same area",
    "around there",
)
_LOCATION_REFERENCE_PHRASES_ES = (
    "en eso",
    "ahí",
    "allí",
    "misma ciudad",
    "mismo lugar",
    "esa área",
    "esa zona",
)
_LOCATION_REFERENCE_PHRASES_PT = (
    "no mesmo lugar",
    "mesma cidade",
    "mesma área",
    "mesma area",
    "lá",
    "ali",
    "nesse lugar",
    "nessa cidade",
    "nessa área",
    "nessa area",
)
_THERE_REFERENCE_RE = re.compile(r"\bthere\?|\bthere\s*$", re.I)

_DEVICE_PROXIMITY_PHRASES_EN = (
    "near me",
    "near my location",
    "near my area",
    "around me",
    "close to me",
    "next to me",
    "where i am",
    "where i'm",
    "current location",
    "my gps",
    "locate me",
    "closest to me",
    "around here",
    "in my area",
    "in my town",
    "in my city",
)
_DEVICE_PROXIMITY_PHRASES_ES = (
    "cerca de mí",
    "cerca de mi",
    "cerca de mi ubicación",
    "cerca de mi ubicacion",
    "en mi área",
    "en mi area",
    "donde estoy",
    "mi ubicación",
    "mi ubicacion",
)
_DEVICE_PROXIMITY_PHRASES_PT = (
    "perto de mim",
    "perto da minha localização",
    "perto da minha localizacao",
    "na minha área",
    "na minha area",
    "onde estou",
    "minha localização",
    "minha localizacao",
)


def _session_geo_debug_enabled() -> bool:
    return getattr(django_settings, "BRAELO_SESSION_GEO_DEBUG", True)


def _session_geo_log(event: str, **fields) -> None:
    if not _session_geo_debug_enabled():
        return
    parts = " ".join(f"{k}={fields[k]!r}" for k in sorted(fields))
    logger.info("[SessionGeo] %s | %s", event, parts)


def _parse_history_entities(raw) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _compact_directory_listings_for_history(businesses: list | None) -> list[dict]:
    out: list[dict] = []
    for b in businesses or []:
        if not isinstance(b, dict):
            continue
        out.append(
            {
                "id": b.get("id"),
                "name": (b.get("name") or "")[:200],
                "category": (b.get("category") or "")[:120],
                "subcategory": (b.get("subcategory") or "")[:120],
                "tag_match_text": ((b.get("tag_match_text") or "")[:2000]),
            }
        )
    return out[:16]


def _last_directory_listings_snapshot_from_history(chat_history: list | None) -> list[dict] | None:
    for item in reversed(chat_history or []):
        if item.get("role") != "assistant":
            continue
        ent = item.get("entities")
        if not isinstance(ent, dict):
            continue
        snap = ent.get("directory_listings_snapshot")
        if isinstance(snap, list) and len(snap) > 0:
            return snap
    return None


def _is_directory_attribute_yes_no_followup(message: str | None) -> bool:
    t = (message or "").strip().lower()
    if len(t) < 10:
        return False
    wants_yn = bool(
        re.search(
            r"\b(yes\s+or\s+no|tell\s+me\s+(yes|no)\b|\b(?:answer|reply)\s+with\s+(yes|no))",
            t,
        )
        or ("?" in t and re.search(r"\b(yes|no)\b", t))
    )
    refers_back = bool(
        re.search(
            r"\b(these|those|that|they|them|above|previous|last|same)\b",
            t,
        )
    )
    has_cuisine = bool(
        re.search(
            r"\b(bbq|barbecue|barbeque|brazil|brazilian|churras|steakhouse|sushi|pizza|vegan|"
            r"halal|kosher|mexican|italian|chinese|thai|korean|japanese|indian|restaurant)\b",
            t,
        )
    )
    return (wants_yn or refers_back) and has_cuisine


def _merge_terms_for_directory_confirmation(message: str) -> list[str]:
    from chatbot.services.business_search_service import extract_listing_name_filter_terms

    t1 = extract_listing_name_filter_terms(message) or []
    t2 = extract_directory_attribute_terms(message) or []
    seen: set[str] = set()
    out: list[str] = []
    for x in list(t1) + list(t2):
        s = (x or "").strip().lower()
        if len(s) >= 2 and s not in seen:
            seen.add(s)
            out.append(s)
    if out:
        return out[:32]
    m = (message or "").lower()
    fb: list[str] = []
    if re.search(r"\b(bbq|barbecue|barbeque)\b", m):
        fb.extend(
            ["bbq", "barbecue", "churrasco", "churrasqueiro", "churrasqueiros", "churrascaria"]
        )
    if re.search(r"\b(brazil|brazilian|brasileir)\b", m):
        fb.extend(["brazil", "brazilian", "brasileir", "brasil"])
    dedup: list[str] = []
    seen2: set[str] = set()
    for x in fb:
        if x not in seen2:
            seen2.add(x)
            dedup.append(x)
    return dedup[:32]


def _listing_snapshot_matches_terms(snap: dict, terms: list[str]) -> bool:
    if not terms:
        return False
    hay = " ".join(
        [
            str(snap.get("name") or ""),
            str(snap.get("tag_match_text") or ""),
            str(snap.get("category") or ""),
            str(snap.get("subcategory") or ""),
        ]
    ).lower()
    for term in terms:
        te = (term or "").strip().lower()
        if len(te) < 2:
            continue
        if len(te) <= 3:
            if re.search(r"(?<![a-z0-9])" + re.escape(te) + r"(?![a-z0-9])", hay):
                return True
        elif te in hay:
            return True
    return False


def _compose_directory_confirmation_reply(
    *,
    snapshot: list[dict],
    terms: list[str],
    detected_lang: str,
) -> str:
    flags = [_listing_snapshot_matches_terms(s, terms) for s in snapshot]
    n_ok = sum(1 for x in flags if x)
    n = len(flags)
    labels = [str(s.get("name") or "?")[:80] for s in snapshot]

    def label_join(names: list[str]) -> str:
        if len(names) <= 2:
            return " and ".join(names)
        return ", ".join(names[:-1]) + f", and {names[-1]}"

    if detected_lang == "pt":
        if n == 0:
            return ""
        if n_ok == n:
            return "**Sim** — esses anúncios combinam com o que você perguntou."
        if n_ok == 0:
            return "**Não** — nenhum desses anúncios combinou bem com a sua pergunta."
        yes_ix = [labels[i] for i in range(n) if flags[i]]
        no_ix = [labels[i] for i in range(n) if not flags[i]]
        return (
            "**Parcialmente** — "
            + (f"combinam: {label_join(yes_ix)}. " if yes_ix else "")
            + (f"não combinam: {label_join(no_ix)}." if no_ix else "")
        )

    if detected_lang == "es":
        if n == 0:
            return ""
        if n_ok == n:
            return "**Sí** — estos listados encajan con lo que preguntaste."
        if n_ok == 0:
            return "**No** — ninguno de estos listados encajó del todo con tu pregunta."
        yes_ix = [labels[i] for i in range(n) if flags[i]]
        no_ix = [labels[i] for i in range(n) if not flags[i]]
        return (
            "**Parcialmente** — "
            + (f"sí: {label_join(yes_ix)}. " if yes_ix else "")
            + (f"no: {label_join(no_ix)}." if no_ix else "")
        )

    if n == 0:
        return ""
    if n_ok == n:
        return "**Yes** — these listings match what you asked for."
    if n_ok == 0:
        return "**No** — none of these listings lined up well with your question."
    yes_ix = [labels[i] for i in range(n) if flags[i]]
    no_ix = [labels[i] for i in range(n) if not flags[i]]
    return (
        "**Partially** — "
        + (f"matches: {label_join(yes_ix)}. " if yes_ix else "")
        + (f"does not match: {label_join(no_ix)}." if no_ix else "")
    )


def _reload_businesses_for_snapshot(
    snapshot: list[dict],
    user_id: str,
    session_id: str | None,
) -> list[dict]:
    from chatbot.services import business_search_service as bss

    ids = [str(s.get("id")) for s in (snapshot or []) if s.get("id")]
    if not ids:
        return []
    try:
        from bson import ObjectId
        from bson.errors import InvalidId
        from chatbot.mongo_db import get_db

        oids: list = []
        for i in ids:
            try:
                oids.append(ObjectId(i))
            except (InvalidId, TypeError):
                continue
        if not oids:
            return []
        db = get_db()
        names = getattr(django_settings, "MONGO_BUSINESS_COLLECTIONS", None) or ["businesses"]
        if isinstance(names, str):
            names = [x.strip() for x in names.split(",") if x.strip()]
        docs: list = []
        for coll_name in names:
            docs.extend(list(db[coll_name].find({"_id": {"$in": oids}})))
        if not docs:
            return []
        by_id = {str(d.get("_id")): d for d in docs}
        ordered_docs = [by_id[i] for i in ids if i in by_id]
        return bss.mongo_docs_to_api_businesses(ordered_docs, user_id, session_id or user_id)
    except Exception:
        logger.exception("chat_flow.reload_businesses_for_snapshot_failed")
        return []


def _store_session_location(
    session_id: str,
    *,
    city: str | None = None,
    state: str | None = None,
    county: str | None = None,
    zip_code: str | None = None,
) -> None:
    if not session_id:
        return
    payload: dict = {}
    if city and str(city).strip():
        payload["city"] = str(city).strip()
    if state and str(state).strip():
        payload["state"] = str(state).strip()
    if county and str(county).strip():
        payload["county"] = str(county).strip()
    if zip_code and str(zip_code).strip():
        payload["zip_code"] = str(zip_code).strip()
    if not payload:
        return
    try:
        from django.core.cache import cache

        cache.set(
            _SESSION_LOCATION_CACHE_KEY.format(session_id),
            payload,
            timeout=_SESSION_LOCATION_CACHE_TTL,
        )
        _session_geo_log("cache_store", session_id=session_id, **payload)
    except Exception:
        logger.debug("chat_flow.session_location_store_failed session_id=%s", session_id, exc_info=True)


def _get_session_location(session_id: str) -> dict:
    if not session_id:
        return {}
    try:
        from django.core.cache import cache

        data = cache.get(_SESSION_LOCATION_CACHE_KEY.format(session_id))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _is_location_reference(message: str) -> bool:
    t = (message or "").lower()
    if not t.strip():
        return False
    if any(p in t for p in _LOCATION_REFERENCE_PHRASES_EN):
        return True
    if any(p in t for p in _LOCATION_REFERENCE_PHRASES_ES):
        return True
    if any(p in t for p in _LOCATION_REFERENCE_PHRASES_PT):
        return True
    if _THERE_REFERENCE_RE.search(message or ""):
        return True
    return False


def _message_prefers_device_gps_for_geo(message: str | None, user_location: dict | None) -> bool:
    loc = user_location or {}
    if loc.get("latitude") is None or loc.get("longitude") is None:
        return False
    if _is_location_reference(message or ""):
        return False
    t = (message or "").lower()
    if not t.strip():
        return False
    if any(p in t for p in _DEVICE_PROXIMITY_PHRASES_EN):
        return True
    if any(p in t for p in _DEVICE_PROXIMITY_PHRASES_ES):
        return True
    if any(p in t for p in _DEVICE_PROXIMITY_PHRASES_PT):
        return True
    return False


def _extract_location_from_chat_history(
    chat_history: list | None,
    *,
    limit: int = 8,
) -> dict:
    from chatbot.services import business_search_service as bss

    n = 0
    for m in reversed(chat_history or []):
        if m.get("role") != "user":
            continue
        if n >= limit:
            break
        content = (m.get("content") or "").strip()
        if not content:
            continue
        n += 1
        parsed = bss.convert_query_to_portuguese_fields(content)
        ci = _sanitize_pipeline_city((parsed.get("city") or "").strip() or None)
        st = (parsed.get("state_en") or "").strip() or None
        if ci or st:
            return {"city": ci, "state": st}
    return {}


def _geo_from_last_directory_turn(chat_history: list | None) -> dict:
    for m in reversed(chat_history or []):
        if m.get("intent") not in _DIRECTORY_GEO_HISTORY_INTENTS:
            continue
        ent = m.get("entities")
        if not isinstance(ent, dict):
            continue
        st = (ent.get("state") or ent.get("state_en") or "").strip() or None
        ci = _sanitize_pipeline_city((ent.get("city") or "").strip() or None)
        co = (ent.get("county") or "").strip() or None
        z = (ent.get("zip_code") or "").strip() or None
        if st or ci or co or z:
            return {"state": st, "city": ci, "county": co, "zip_code": z}
    return {}


def _initial_location_with_priority(
    user_location: dict,
    user,
    session_id: str,
    chat_history: list | None,
    *,
    message: str | None = None,
) -> tuple:
    def nz(x):
        return (str(x).strip() if x is not None else "") or None

    state = nz(getattr(user, "state", None))
    city = nz(getattr(user, "city", None))
    county = nz(getattr(user, "county", None))
    zip_code = nz(getattr(user, "zip_code", None))

    if nz(user_location.get("state")):
        state = nz(user_location.get("state"))
    if nz(user_location.get("city")):
        city = nz(user_location.get("city"))
    if nz(user_location.get("county")):
        county = nz(user_location.get("county"))
    if nz(user_location.get("zip_code")):
        zip_code = nz(user_location.get("zip_code"))

    if not zip_code:
        for m in reversed(chat_history or []):
            if m.get("role") != "user":
                continue
            mo = _ZIP_US_RE.search(m.get("content") or "")
            if mo:
                zip_code = mo.group(1)
                break

    if not _message_prefers_device_gps_for_geo(message, user_location):
        for layer in (
            _extract_location_from_chat_history(chat_history, limit=8),
            _get_session_location(session_id),
            _geo_from_last_directory_turn(chat_history),
        ):
            if not layer:
                continue
            st = nz(layer.get("state") or layer.get("state_en"))
            ci = nz(layer.get("city"))
            co = nz(layer.get("county"))
            z = nz(layer.get("zip_code") or layer.get("zip"))
            if ci:
                city = ci
            if st:
                state = st
            if co:
                county = co
            if z:
                zip_code = z

    city = _sanitize_pipeline_city(city)
    _session_geo_log(
        "initial_location_result",
        session_id=session_id or "",
        state=state,
        city=city,
        county=county,
        zip_code=zip_code,
        skipped_session_layers=_message_prefers_device_gps_for_geo(message, user_location),
    )
    return state, city, county, zip_code


def _apply_directory_session_geo_overrides(
    message: str,
    state: str,
    city: str,
    county: str,
    zip_code: str,
    chat_history: list,
    intent: str,
    *,
    session_id: str = "",
    use_device_location_only: bool = False,
    user_location: dict | None = None,
) -> tuple:
    from chatbot.services import business_search_service as bss

    if use_device_location_only and _message_prefers_device_gps_for_geo(message, user_location):
        _session_geo_log(
            "overrides_skip_device_gps_preferred",
            session_id=session_id or "",
            state=state,
            city=city,
        )
        return state, city, county, zip_code

    hints = _extract_location_hints_from_message(message)
    if hints:
        _session_geo_log("overrides_skip_explicit_message_hints", hints=dict(hints))
        return state, city, county, zip_code

    if intent not in _DIRECTORY_GEO_HISTORY_INTENTS and not bss.is_business_search_query(message):
        return state, city, county, zip_code

    hist = _geo_from_last_directory_turn(chat_history)
    sl = _get_session_location(session_id) if session_id else {}
    mem_st = ((hist.get("state") or "").strip() or (sl.get("state") or "").strip() or None)
    mem_ci = ((hist.get("city") or "").strip() or (sl.get("city") or "").strip() or None)
    mem_co = ((hist.get("county") or "").strip() or (sl.get("county") or "").strip() or None)
    mem_z = ((hist.get("zip_code") or "").strip() or (sl.get("zip_code") or "").strip() or None)
    if not (mem_st or mem_ci or mem_co or mem_z):
        return state, city, county, zip_code

    new_state = mem_st or state
    new_city = mem_ci or city
    new_county = mem_co or county
    new_zip = mem_z or zip_code
    _session_geo_log(
        "overrides_applied",
        session_id=session_id or "",
        from_history=hist,
        from_cache=sl,
        out_state=new_state,
        out_city=new_city,
        out_county=new_county,
        out_zip=new_zip,
    )
    return new_state, new_city, new_county, new_zip


def _load_openai_chat_history(session_id: str, max_documents: int = 200) -> list[dict]:
    """
    Prior turns for this session only (chronological). Used as OpenAI user/assistant messages.
    Rows may include intent + entities (entities_json) for session geo; gpt_service keeps role/content only.
    """
    if not session_id:
        return []
    rows: list[dict] = []
    try:
        if getattr(django_settings, "USE_MONGO", False):
            from chatbot.mongo_db import get_db
            db = get_db()
            col = db.chat_history
            cur = (
                col.find({"external_id": session_id})
                .sort("created_at", 1)
                .limit(max_documents)
            )
            for doc in cur:
                role = doc.get("role")
                content = (doc.get("content") or "").strip()
                if role in ("user", "assistant") and content:
                    item: dict = {"role": role, "content": content}
                    if doc.get("intent"):
                        item["intent"] = doc.get("intent")
                    ent = _parse_history_entities(doc.get("entities_json"))
                    if ent:
                        item["entities"] = ent
                    rows.append(item)
        else:
            qs = (
                ChatHistory.objects.filter(external_id=session_id)
                .order_by("created_at", "id")[:max_documents]
            )
            for row in qs:
                role = row.role
                content = (row.content or "").strip()
                if role in ("user", "assistant") and content:
                    item = {"role": role, "content": content}
                    if row.intent:
                        item["intent"] = row.intent
                    ent = _parse_history_entities(row.entities_json)
                    if ent:
                        item["entities"] = ent
                    rows.append(item)
    except Exception:
        logger.exception("chat_flow.load_history_failed session_id=%s", session_id)
        return []
    return rows


def _enrich_location_from_history(
    state: str,
    city: str,
    county: str,
    zip_code: str,
    chat_history: list,
) -> tuple:
    """Fill missing ZIP from recent user turns (e.g. follow-up only refers to restaurants)."""
    if zip_code:
        return state, city, county, zip_code
    for m in reversed(chat_history or []):
        if m.get("role") != "user":
            continue
        mo = _ZIP_US_RE.search(m.get("content") or "")
        if mo:
            return state, city, county, mo.group(1)
    return state, city, county, zip_code


def _format_known_facts(state: str, city: str, county: str, zip_code: str) -> str:
    """Compact block for LLM system/user injection."""
    parts = []
    if city:
        parts.append(f"City: {city}")
    if state:
        parts.append(f"State: {state}")
    if county:
        parts.append(f"County: {county}")
    if zip_code:
        parts.append(f"ZIP: {zip_code}")
    return "\n".join(parts) if parts else ""


def _save_history(
    user_id: str,
    message: str,
    reply: str,
    intent: str,
    structured: dict,
    businesses: list | None = None,
):
    try:
        if getattr(django_settings, "USE_MONGO", False):
            from chatbot.mongo_db import get_db
            from datetime import datetime
            db = get_db()
            col = db.chat_history
            now = datetime.utcnow()
            for role, content in [("user", message), ("assistant", reply)]:
                st = dict(structured or {})
                if role == "assistant" and businesses:
                    st["directory_listings_snapshot"] = _compact_directory_listings_for_history(businesses)
                col.insert_one({
                    "external_id": user_id,
                    "role": role,
                    "content": content,
                    "intent": intent,
                    "entities_json": json.dumps(st) if st else None,
                    "created_at": now,
                })
        else:
            user = get_or_create_user(user_id)
            if hasattr(user, "id"):
                for role, content in [("user", message), ("assistant", reply)]:
                    st = dict(structured or {})
                    if role == "assistant" and businesses:
                        st["directory_listings_snapshot"] = _compact_directory_listings_for_history(businesses)
                    ChatHistory.objects.create(
                        user=user,
                        external_id=user_id,
                        role=role,
                        content=content,
                        intent=intent,
                        entities_json=json.dumps(st) if st else None,
                    )
    except Exception:
        logger.exception("chat_flow.save_history_failed user_id=%s intent=%s", user_id, intent)


# ---------------------------------------------------------------------------
# Business comparison helper
# ---------------------------------------------------------------------------

def _fetch_business_context(structured: dict, state: str) -> str:
    context = ""
    try:
        if getattr(django_settings, "USE_MONGO", False):
            from chatbot.mongo_db import get_db
            db = get_db()
            q = mongo_comparison_query(structured or {})
            collection_names = getattr(django_settings, "MONGO_BUSINESS_COLLECTIONS", None) or ["businesses"]
            if isinstance(collection_names, str):
                collection_names = [x.strip() for x in collection_names.split(",") if x.strip()]
            seen = set()
            for coll_name in collection_names:
                for b in db[coll_name].find(q).limit(8):
                    sid = str(b.get("_id"))
                    if sid in seen:
                        continue
                    seen.add(sid)
                    name = b.get("name") or b.get("business_name") or ""
                    cat = b.get("category") or b.get("business_category") or ""
                    sub = b.get("subcategory") or b.get("business_subcategory") or ""
                    city = b.get("city") or ""
                    st = b.get("state") or ""
                    contact = (b.get("contact_info") or "").strip()
                    if not contact:
                        contact = " ".join(
                            filter(None, [b.get("business_number"), b.get("business_email")])
                        )
                    context += f"{name}: {cat} {sub}, {city} {st}. {contact}\n".strip() + "\n"
                    if len(seen) >= 5:
                        break
                if len(seen) >= 5:
                    break
        else:
            from chatbot.models import Business
            from django.db.models import Q
            category = (structured or {}).get("category") or (structured or {}).get("subcategory")
            qs = Business.objects.filter(is_active=True, is_banned=False)
            if state:
                qs = qs.filter(state__icontains=state)
            if category:
                qs = qs.filter(Q(category__icontains=category) | Q(subcategory__icontains=category))
            for b in qs[:5]:
                context += f"{b.name}: {b.category or ''} {b.subcategory or ''}, {b.city or ''} {b.state or ''}. {b.contact_info or ''}\n"
    except Exception:
        logger.exception("chat_flow.fetch_business_context_failed state=%s", state)
    return context.strip()


def _lista_mongo_directory_response(
    message: str,
    *,
    state,
    city,
    county,
    zip_code,
    ulat,
    ulon,
    detected_lang: str,
    user_id: str,
    session_id: str,
    user_name,
    structured: dict,
    user,
    category_pt: str | None = None,
    subcategory_pt: str | None = None,
) -> dict | None:
    """
    Lista-shaped Mongo probe (PT category/subcategory + English geo). Used when get_top_businesses
    returns no rows or before deferring to Places/LLM.
    """
    if not getattr(django_settings, "USE_MONGO", False):
        return None
    from chatbot.services import business_search_service as bss

    if not bss.is_business_search_query(message):
        return None
    parsed = bss.convert_query_to_portuguese_fields(message)
    cat_pt = category_pt or parsed.get("category_pt")
    sub_pt = subcategory_pt or parsed.get("subcategory_pt")
    cat_en = parsed.get("category_en")
    sub_en = parsed.get("subcategory_en")
    if not any([cat_pt, sub_pt, cat_en, sub_en]):
        return None
    has_regex_hints = bool(_extract_location_hints_from_message(message))
    has_parse_geo = bool(
        (parsed.get("city") or "").strip() or (parsed.get("state_en") or "").strip()
    )
    if has_parse_geo and _is_location_reference(message) and not has_regex_hints:
        has_parse_geo = False
    caller_geo_only = not has_regex_hints and not has_parse_geo
    if caller_geo_only:
        s_state = (state or "").strip() or None
        s_city = (city or "").strip() or None
        s_county = (county or "").strip() or None
    else:
        s_state = (state or parsed.get("state_en") or "").strip() or None
        s_city = (city or parsed.get("city") or "").strip() or None
        s_county = (county or parsed.get("county") or "").strip() or None
    s_state = _backfill_state_from_major_us_city(s_state, s_city)
    _session_geo_log(
        "lista_geo_resolve",
        session_id=session_id,
        caller_geo_only=caller_geo_only,
        has_parse_geo=has_parse_geo,
        has_regex_hints=has_regex_hints,
        pipeline_state=state,
        pipeline_city=city,
        s_state=s_state,
        s_city=s_city,
    )
    if not _has_business_location(s_state, s_city, s_county, zip_code, ulat, ulon):
        logger.info("chat_flow.lista_probe.skip_no_location user_id=%s", user_id)
        return None
    lim = _directory_first_page_limit()
    logger.info(
        "chat_flow.lista_probe.search user_id=%s cat_pt=%s sub_pt=%s state=%s city=%s county=%s",
        user_id,
        cat_pt,
        sub_pt,
        s_state,
        s_city,
        s_county,
    )
    search_res = bss.search_businesses_in_mongodb(
        query=message,
        state=s_state,
        city=s_city,
        county=s_county,
        zip_code=zip_code,
        category_pt=cat_pt,
        subcategory_pt=sub_pt,
        category_en=cat_en,
        subcategory_en=sub_en,
        limit=lim,
        offset=0,
        caller_geo_only=caller_geo_only,
    )
    docs = search_res.get("businesses") or []
    docs = _filter_mongo_docs_brazilian_vs_portuguese(
        message, extract_directory_attribute_terms(message), docs
    )
    lista_see_more = bool(search_res.get("see_more"))
    if not docs:
        logger.info("chat_flow.lista_probe.empty user_id=%s", user_id)
        return None
    businesses = bss.mongo_docs_to_api_businesses(docs, user_id, session_id or user_id)
    if not businesses:
        return None
    merged = dict(structured or {})
    merged["category"] = cat_pt or cat_en
    merged["subcategory"] = sub_pt or sub_en
    merged["answer_source"] = "lista_mongo_directory"
    merged["detected_language"] = detected_lang
    merged["state"] = s_state or merged.get("state")
    merged["city"] = s_city or merged.get("city")
    merged["county"] = s_county or merged.get("county")
    if zip_code:
        merged["zip_code"] = zip_code
    _store_session_location(
        session_id,
        city=s_city,
        state=s_state,
        county=s_county,
        zip_code=zip_code,
    )
    _session_geo_log(
        "lista_hit_store_session",
        session_id=session_id,
        stored_city=s_city,
        stored_state=s_state,
        n_businesses=len(businesses),
    )
    reply = _directory_ui_intro(
        detected_lang,
        category=(cat_pt or cat_en or ""),
        subcategory=(sub_pt or sub_en or ""),
        location_note=None,
    )
    reply = (
        reply.rstrip()
        + "\n\n"
        + _directory_client_followup_block(
            detected_lang,
            zip_code=zip_code,
            city=s_city,
            state=s_state,
            see_more=lista_see_more,
            n_shown=len(businesses),
        )
    )
    require_contact = False
    contact_msg = None
    if businesses and hasattr(user, "has_contact_details") and not getattr(user, "has_contact_details", True):
        require_contact = True
        contact_msg = {
            "en": "I'll save this and your chat history. Please add your details so I can continue:",
            "es": "Guardaré esto y tu historial. Por favor agrega tus datos para continuar:",
            "pt": "Vou salvar isso e seu histórico. Por favor adicione seus dados para continuar:",
        }.get(detected_lang, "Please add your email and phone so we can connect you and save your history:")
    lista_snap = {
        "v": 1,
        "kind": "lista_mongo",
        "intent": "business_search",
        "language": detected_lang,
        "message": message,
        "state": s_state,
        "city": s_city,
        "county": s_county,
        "zip_code": zip_code,
        "category_pt": cat_pt,
        "subcategory_pt": sub_pt,
        "category_en": cat_en,
        "subcategory_en": sub_en,
    }
    lista_pag = _business_pagination_dict(lista_snap, lim, 0, businesses, lista_see_more)
    _save_history(session_id, message, reply, "business_search", merged, businesses=businesses)
    logger.info("chat_flow.lista_probe.hit user_id=%s n=%s", user_id, len(businesses))
    return _build_response(
        reply,
        detected_lang,
        "business_search",
        businesses=businesses,
        see_more=lista_see_more,
        location_note=None,
        question_analysis=merged,
        user_name=user_name,
        require_contact_details=require_contact,
        contact_details_message=contact_msg,
        business_pagination=lista_pag,
    )


# ---------------------------------------------------------------------------
# Business list pagination (Show more)
# ---------------------------------------------------------------------------

def _business_pagination_dict(
    snapshot: dict,
    page_size: int,
    page_offset: int,
    businesses: list,
    see_more: bool,
) -> dict:
    return {
        "page_size": page_size,
        "next_offset": page_offset + len(businesses or []),
        "has_more": bool(see_more),
        "snapshot": snapshot,
    }


def _handle_business_load_more(
    *,
    business_snapshot: dict | None,
    business_offset: int,
    business_page_size: int | None,
    user_id: str,
    session_id: str,
) -> dict:
    from chatbot.services import business_search_service as bss

    snap = business_snapshot if isinstance(business_snapshot, dict) else None
    if not snap or snap.get("v") != 1:
        return _build_response(
            "Could not load more listings. Please search again.",
            "en",
            "business_search",
            businesses=[],
            see_more=False,
        )

    page_size = int(business_page_size or _directory_first_page_limit())
    page_size = max(1, min(page_size, 100))
    off = max(0, int(business_offset or 0))
    lang = (snap.get("language") or "en").strip()[:2] or "en"
    kind = snap.get("kind")
    intent_out = snap.get("intent") or "business_search"

    if kind == "get_top":
        result = get_top_businesses(
            category=snap.get("category"),
            subcategory=snap.get("subcategory"),
            state=snap.get("state"),
            city=snap.get("city"),
            county=snap.get("county"),
            zip_code=snap.get("zip_code"),
            user_lat=snap.get("user_lat"),
            user_lon=snap.get("user_lon"),
            language=snap.get("language") or "en",
            limit=page_size,
            offset=off,
            external_id=user_id,
            session_id=session_id or user_id,
            strict_location=bool(snap.get("strict_location")),
            sort_mode=snap.get("sort_mode") or "fairness",
            extra_match_terms=snap.get("extra_match_terms") or None,
            apply_gps_radius=bool(snap.get("apply_gps_radius", True)),
            anchor_results_to_message_city=bool(snap.get("anchor_results_to_message_city", False)),
            source_message=snap.get("source_message"),
        )
    elif kind == "directory_discovery":
        result = search_business_directory_for_discovery(
            message=snap.get("message") or "",
            category=snap.get("category"),
            subcategory=snap.get("subcategory"),
            category_hint=snap.get("category_hint"),
            state=snap.get("state"),
            city=snap.get("city"),
            county=snap.get("county"),
            zip_code=snap.get("zip_code"),
            user_lat=snap.get("user_lat"),
            user_lon=snap.get("user_lon"),
            language=snap.get("language"),
            limit=page_size,
            offset=off,
            external_id=user_id,
            session_id=session_id or user_id,
        )
    elif kind == "lista_mongo":
        res = bss.search_businesses_in_mongodb(
            query=snap.get("message") or "",
            state=snap.get("state"),
            city=snap.get("city"),
            county=snap.get("county"),
            zip_code=snap.get("zip_code"),
            category_pt=snap.get("category_pt"),
            subcategory_pt=snap.get("subcategory_pt"),
            category_en=snap.get("category_en"),
            subcategory_en=snap.get("subcategory_en"),
            limit=page_size,
            offset=off,
        )
        docs = res.get("businesses") or []
        businesses = bss.mongo_docs_to_api_businesses(docs, user_id, session_id or user_id)
        see_more = bool(res.get("see_more"))
        result = {"businesses": businesses, "see_more": see_more, "location_note": None}
    else:
        return _build_response(
            "Could not load more listings. Please search again.",
            lang,
            intent_out,
            businesses=[],
            see_more=False,
        )

    businesses = result.get("businesses") or []
    see_more = result.get("see_more", False)
    pag = _business_pagination_dict(snap, page_size, off, businesses, see_more)
    return _build_response(
        "",
        lang,
        intent_out,
        businesses=businesses,
        see_more=see_more,
        location_note=result.get("location_note"),
        business_pagination=pag,
        question_analysis={"intent": intent_out, "detected_language": lang, "business_load_more": True},
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_message(
    message: str,
    user_id: str = None,
    session_id: str = None,
    user_location: dict = None,
    user_profile: dict = None,
    *,
    business_load_more: bool = False,
    business_snapshot: dict | None = None,
    business_offset: int = 0,
    business_page_size: int | None = None,
) -> dict:
    # user_id  = stable identifier (IP or permanent ID) used for location / profile persistence.
    # session_id = per-tab UUID that resets on every page refresh, used for language locking and
    #              chat history so each new conversation independently detects its own language.
    user_id = user_id or session_id or "anonymous"
    session_id = session_id or user_id          # fall back to user_id when not sent by frontend
    user_location = user_location or {}
    user_profile = user_profile or {}
    logger.info(
        "chat_flow.process_message.start user_id=%s session_id=%s message_len=%s",
        user_id,
        session_id,
        len(message or ""),
    )
    # Profile and location are looked up / persisted against the STABLE user_id (IP).
    user = get_or_create_user(user_id, user_location, profile=user_profile)

    if business_load_more:
        return _handle_business_load_more(
            business_snapshot=business_snapshot,
            business_offset=business_offset,
            business_page_size=business_page_size,
            user_id=user_id,
            session_id=session_id,
        )

    use_device_only = bool(user_location.get("use_device_location_only"))
    location_enabled = user_location.get("location_enabled", getattr(user, "location_enabled", True))
    user_name = getattr(user, "display_name", None) or user_profile.get("name") or user_profile.get("display_name")

    _hist_cap = getattr(django_settings, "CHAT_HISTORY_MAX_DOCUMENTS", 200)
    openai_chat_history = _load_openai_chat_history(session_id, _hist_cap)
    _session_geo_log(
        "turn_start",
        session_id=session_id,
        message_preview=(message or "")[:120],
        use_device_location_only=use_device_only,
        history_turns=len(openai_chat_history),
        cache_snapshot=_get_session_location(session_id),
    )
    state, city, county, zip_code = _initial_location_with_priority(
        user_location,
        user,
        session_id,
        openai_chat_history,
        message=message,
    )
    state, city, county, zip_code = _enrich_location_from_history(
        state, city, county, zip_code, openai_chat_history
    )

    # Prefer city/state/ZIP named in this message for retrieval (before KB + structured merge).
    state, city, county, zip_code = _apply_message_location_for_map(
        message, state, city, county, zip_code
    )
    state = _backfill_state_from_major_us_city(state, city)
    _session_geo_log(
        "after_message_location_pass1",
        session_id=session_id,
        state=state,
        city=city,
        county=county,
        zip_code=zip_code,
    )
    _msg_place_hints = _extract_location_hints_from_message(message)
    _explicit_place_in_message = bool(
        (_msg_place_hints.get("city") or "").strip() or (_msg_place_hints.get("zip_code") or "").strip()
    )
    _anchor_msg_city = bool((_msg_place_hints.get("city") or "").strip())
    _apply_gps_radius = not _explicit_place_in_message
    known_facts_for_structured = _format_known_facts(state, city, county, zip_code)

    has_api_key = bool(getattr(django_settings, "OPENAI_API_KEY", None))
    logger.info("chat_flow.openai_key_configured=%s", has_api_key)

    message_detected_lang = detect_language(message)
    # user_id  → stable IP key used to persist the language preference on the user doc
    # session_id → per-tab UUID used to check whether this is a new session
    detected_lang = _resolve_conversation_language(
        user, user_id, session_id, message, message_detected_lang
    )

    from chatbot.ellu.privacy_guard import PrivacyGuard
    guard_action, guard_response = PrivacyGuard().check_incoming_message(message, detected_lang)
    if guard_action == "BLOCK":
        _save_history(
            session_id,
            message,
            guard_response,
            "privacy_block",
            {"intent": "privacy_block", "detected_language": detected_lang},
        )
        return _build_response(guard_response, detected_lang, "privacy_block")

    # ------------------------------------------------------------------
    # TIER 0 — Casual intents  (intents.json, no OpenAI call needed)
    # get_casual_response() only fires for short, non-FAQ messages; see casual_intents.
    # ------------------------------------------------------------------
    casual_text, casual_tag = get_casual_response(message)
    if casual_text:
        reply = (
            translate_verified_answer(casual_text, detected_lang)
            if has_api_key and detected_lang != "en"
            else casual_text
        )
        from chatbot.ellu.persona import get_phrase
        _is_first_turn = len(openai_chat_history) == 0
        if _is_first_turn:
            reply = f"{reply}\n\n{get_phrase('welcome_new', detected_lang)}"

        _save_history(session_id, message, reply, "casual", {"intent": "casual", "detected_language": detected_lang})
        logger.info("chat_flow.tier0.casual user_id=%s lang=%s tag=%s", user_id, detected_lang, casual_tag)
        return _build_response(reply, detected_lang, "casual", user_name=user_name)

    # Meta assistant question (e.g., "how do you work?") should not route to job/work KB content.
    if _is_assistant_meta_question(message):
        reply = _assistant_capabilities_message(detected_lang)
        meta_struct = {
            "intent": "casual",
            "detected_language": detected_lang,
            "meta_question": "assistant_capabilities",
        }
        _save_history(session_id, message, reply, "casual", meta_struct)
        logger.info("chat_flow.meta_capabilities user_id=%s lang=%s", user_id, detected_lang)
        return _build_response(reply, detected_lang, "casual", question_analysis=meta_struct, user_name=user_name)

    # ------------------------------------------------------------------
    # TIER 0b — Yes/no follow-up about the last directory rows (BBQ, Brazilian, …)
    # ------------------------------------------------------------------
    if getattr(django_settings, "USE_MONGO", False) and _is_directory_attribute_yes_no_followup(message):
        snap = _last_directory_listings_snapshot_from_history(openai_chat_history)
        if snap:
            terms = _merge_terms_for_directory_confirmation(message)
            if terms:
                lead = _compose_directory_confirmation_reply(
                    snapshot=snap,
                    terms=terms,
                    detected_lang=detected_lang,
                )
                reply = lead.strip()
                merged_bs = _reload_businesses_for_snapshot(snap, user_id, session_id)
                persist_bs = merged_bs if merged_bs else [
                    {
                        "id": s.get("id"),
                        "name": s.get("name") or "?",
                        "tag_match_text": s.get("tag_match_text") or "",
                        "category": s.get("category") or "",
                        "subcategory": s.get("subcategory") or "",
                        "state": "",
                        "city": "",
                        "county": "",
                        "contact_info": None,
                        "whatsapp_url": "",
                    }
                    for s in snap
                ]
                q_struct = {
                    "intent": "business_search",
                    "detected_language": detected_lang,
                    "answer_source": "directory_attribute_confirmation",
                }
                _save_history(
                    session_id,
                    message,
                    reply,
                    "business_search",
                    q_struct,
                    businesses=persist_bs,
                )
                logger.info(
                    "chat_flow.tier0b.directory_confirmation user_id=%s n_snap=%s n_reload=%s",
                    user_id,
                    len(snap),
                    len(merged_bs or []),
                )
                return _build_response(
                    reply,
                    detected_lang,
                    "business_search",
                    businesses=persist_bs,
                    see_more=False,
                    question_analysis=q_struct,
                    user_name=user_name,
                )

    # ------------------------------------------------------------------
    # TIER 1a — Structured intent + location (before business DB and KB)
    # ------------------------------------------------------------------
    if has_api_key:
        structured = get_structured_output(
            message,
            chat_history=openai_chat_history,
            known_facts=known_facts_for_structured,
        )
    else:
        structured = {
            "intent": "information_request",
            "category": None, "subcategory": None,
            "state": state, "city": city, "county": county, "zip_code": zip_code,
            "detected_language": detected_lang,
            "confidence": 0.5,
        }

    if structured.get("detected_language") and structured.get("detected_language") != detected_lang:
        structured["model_detected_language"] = structured.get("detected_language")
        structured["detected_language"] = detected_lang

    intent = structured.get("intent") or "information_request"
    confidence = float(structured.get("confidence") or 0.5)
    logger.info(
        "chat_flow.intent user_id=%s intent=%s confidence=%.2f detected_lang=%s",
        user_id,
        intent,
        confidence,
        detected_lang,
    )

    kb_over_directory = should_preempt_directory_for_knowledge(
        message, intent, confidence, structured
    )
    if kb_over_directory:
        logger.info("chat_flow.route_kb_first user_id=%s intent=%s", user_id, intent)
    _route = classify_response_route(message, intent, confidence, structured)
    logger.info(
        "chat_flow.intent_classifier route=%s knowledge_first=%s",
        _route.get("response_type"),
        _route.get("knowledge_before_directory"),
    )

    _pg = PrivacyGuard()
    if _pg.is_sensitive_topic(message):
        from chatbot.ellu.persona import get_phrase as _ellu_phrase

        sens_reply = _ellu_phrase("sensitive_topic", detected_lang)
        sens_struct = {
            "intent": "sensitive_topic_redirect",
            "detected_language": detected_lang,
            "model_intent": intent,
        }
        _save_history(session_id, message, sens_reply, "sensitive_topic_redirect", sens_struct)
        logger.info("chat_flow.sensitive_topic_redirect user_id=%s", user_id)
        return _build_response(
            sens_reply,
            detected_lang,
            "sensitive_topic_redirect",
            question_analysis=sens_struct,
            user_name=user_name,
        )

    # Merge structured extraction into location (message may mention state/ZIP not on profile)
    state = structured.get("state") or state
    city = structured.get("city") or city
    county = structured.get("county") or county
    zip_code = structured.get("zip_code") or zip_code
    state, city, county, zip_code = _apply_message_location_for_map(
        message, state, city, county, zip_code
    )
    state = _backfill_state_from_major_us_city(state, city)
    state, city, county, zip_code = _apply_directory_session_geo_overrides(
        message,
        state,
        city,
        county,
        zip_code,
        openai_chat_history,
        intent,
        session_id=session_id,
        use_device_location_only=use_device_only,
        user_location=user_location,
    )
    state = _backfill_state_from_major_us_city(state, city)
    _session_geo_log(
        "pipeline_before_lista",
        session_id=session_id,
        intent=intent,
        state=state,
        city=city,
        county=county,
        zip_code=zip_code,
        location_reference=_is_location_reference(message or ""),
    )
    known_facts = _format_known_facts(state, city, county, zip_code)

    ulat = user_location.get("latitude") or getattr(user, "latitude", None)
    ulon = user_location.get("longitude") or getattr(user, "longitude", None)

    _lista_early = None
    if not kb_over_directory:
        _lista_early = _lista_mongo_directory_response(
            message,
            state=state,
            city=city,
            county=county,
            zip_code=zip_code,
            ulat=ulat,
            ulon=ulon,
            detected_lang=detected_lang,
            user_id=user_id,
            session_id=session_id,
            user_name=user_name,
            structured=dict(structured or {}),
            user=user,
        )
    if _lista_early:
        return _lista_early

    if intent == "off_topic" and _looks_in_scope_topic(message):
        structured["model_intent"] = intent
        intent = "information_request"

    # ------------------------------------------------------------------
    # TIER 1b — Business directory first (Mongo when USE_MONGO, else SQL)
    # Eligibility is _directory_lookup_intent: resolve category, query DB, return listings if any.
    # If empty: defer to Tier 2a0 (directory discovery + Places/LLM) when location-style query;
    # otherwise directory LLM fallback here. Later tiers (KB/RAG) run only after this gate.
    # ------------------------------------------------------------------
    inf_cat, inf_sub = _infer_service_category_from_text(message)
    # Prefer regex/heuristic inference from the user text over the LLM's category labels. Lista and
    # Mongo often use Portuguese bucket names (Gastronomia, Restaurantes); the LLM may return
    # English phrases that do not match those fields, which skipped the directory and fell through
    # to Google Places / generic LLM answers.
    _st_cat = (structured.get("category") or "").strip() or None
    _st_sub = (structured.get("subcategory") or "").strip() or None
    _st_cat, _st_sub = _sanitize_structured_category_for_followup(
        message, openai_chat_history, _st_cat, _st_sub
    )
    if isinstance(structured, dict):
        structured["category"] = _st_cat
        structured["subcategory"] = _st_sub
    biz_cat = inf_cat or _st_cat
    biz_sub = inf_sub or _st_sub
    directory_intent = _directory_lookup_intent(
        message, structured or {}, intent, confidence
    ) and not kb_over_directory

    if directory_intent:
        if not (biz_cat or biz_sub):
            biz_cat = biz_cat or inf_cat
            biz_sub = biz_sub or inf_sub
        if not (biz_cat or biz_sub):
            hint = extract_category_from_message(message or "")
            gl = (hint or "").strip().lower()
            if hint and len(hint) <= 80 and gl not in ("local businesses", "businesses", "business"):
                biz_cat = hint
        if not (biz_cat or biz_sub) and _extract_restaurant_search_query(message):
            biz_cat, biz_sub = "food", "restaurant"
        if not (biz_cat or biz_sub):
            msg_l = (message or "").lower()
            if any(
                n in msg_l
                for n in (
                    "restaurant",
                    "restaurante",
                    "food",
                    "dining",
                    "eat",
                    "café",
                    "cafe",
                    "bakery",
                    "churrascaria",
                    "gastronom",
                    "comida",
                    "lanchonete",
                )
            ):
                biz_cat, biz_sub = "food", "restaurant"
        if not (biz_cat or biz_sub):
            directory_intent = False
            logger.info(
                "chat_flow.directory_intent.skip_no_category user_id=%s (fall_through_to_later_tiers)",
                user_id,
            )

    if directory_intent:
        from chatbot.ellu.what_where_gate import WhatWhereGate
        gate = WhatWhereGate()
        gate_res = gate.check(
            message=message,
            category=biz_cat or "",
            subcategory=biz_sub or "",
            city=city or "",
            state=state or "",
            zip_code=zip_code or "",
            latitude=ulat,
            longitude=ulon,
            session_city=user_location.get("city", "") if user_location else "",
            session_state=user_location.get("state", "") if user_location else "",
            detected_language=detected_lang,
            is_business_search=True,
        )
        if not gate_res.can_search:
            reply = gate_res.clarification_needed
            _save_history(session_id, message, reply, "location_incomplete", structured)
            return _build_response(
                reply, detected_lang, "location_incomplete", question_analysis=structured, user_name=user_name
            )
        lim = _directory_first_page_limit()
        _attr_terms = extract_directory_attribute_terms(message)
        snap_strict = True
        snap_extra = _attr_terms or None
        r1 = get_top_businesses(
            category=biz_cat,
            subcategory=biz_sub,
            state=state,
            city=city,
            county=county,
            zip_code=zip_code,
            user_lat=ulat,
            user_lon=ulon,
            language=detected_lang,
            limit=lim,
            offset=0,
            external_id=user_id,
            session_id=session_id or user_id,
            strict_location=True,
            sort_mode="fairness",
            extra_match_terms=_attr_terms or None,
            apply_gps_radius=_apply_gps_radius,
            anchor_results_to_message_city=_anchor_msg_city,
            source_message=message,
        )
        businesses = r1.get("businesses") or []
        loc_note = r1.get("location_note")
        see_more = r1.get("see_more", False)
        if not businesses:
            snap_strict = False
            snap_extra = _attr_terms or None
            r2 = get_top_businesses(
                category=biz_cat,
                subcategory=biz_sub,
                state=state,
                city=city,
                county=county,
                zip_code=zip_code,
                user_lat=ulat,
                user_lon=ulon,
                language=detected_lang,
                limit=lim,
                offset=0,
                external_id=user_id,
                session_id=session_id or user_id,
                strict_location=False,
                sort_mode="fairness",
                extra_match_terms=_attr_terms or None,
                apply_gps_radius=_apply_gps_radius,
                anchor_results_to_message_city=_anchor_msg_city,
                source_message=message,
            )
            businesses = r2.get("businesses") or []
            loc_note = r2.get("location_note")
            see_more = r2.get("see_more", False)
        if not businesses and _attr_terms:
            snap_strict = False
            snap_extra = None
            r3 = get_top_businesses(
                category=biz_cat,
                subcategory=biz_sub,
                state=state,
                city=city,
                county=county,
                zip_code=zip_code,
                user_lat=ulat,
                user_lon=ulon,
                language=detected_lang,
                limit=lim,
                offset=0,
                external_id=user_id,
                session_id=session_id or user_id,
                strict_location=False,
                sort_mode="fairness",
                extra_match_terms=None,
                apply_gps_radius=_apply_gps_radius,
                anchor_results_to_message_city=_anchor_msg_city,
                source_message=message,
            )
            businesses = r3.get("businesses") or []
            loc_note = r3.get("location_note")
            see_more = r3.get("see_more", False)
            logger.info(
                "chat_flow.business_database_first user_id=%s name_hint_fallback_no_match n=%s",
                user_id,
                len(businesses),
            )

        structured = dict(structured or {})
        structured["category"] = biz_cat
        structured["subcategory"] = biz_sub

        if businesses:
            reply = _directory_ui_intro(
                detected_lang,
                category=biz_cat or "",
                subcategory=biz_sub or "",
                location_note=loc_note,
            )
            reply = (
                reply.rstrip()
                + "\n\n"
                + _directory_client_followup_block(
                    detected_lang,
                    zip_code=zip_code,
                    city=city,
                    state=state,
                    see_more=see_more,
                    n_shown=len(businesses),
                )
            )
            structured["answer_source"] = "business_database"
            structured["state"] = state or structured.get("state")
            structured["city"] = city or structured.get("city")
            structured["county"] = county or structured.get("county")
            structured["zip_code"] = zip_code or structured.get("zip_code")
            _store_session_location(
                session_id,
                city=city,
                state=state,
                county=county,
                zip_code=zip_code,
            )
            _session_geo_log(
                "get_top_hit_store_session",
                session_id=session_id,
                city=city,
                state=state,
                county=county,
                zip_code=zip_code,
                n_businesses=len(businesses),
            )
            logger.info(
                "chat_flow.business_database_first user_id=%s n=%s strict_then_loose=%s",
                user_id,
                len(businesses),
                True,
            )
            require_contact = False
            contact_msg = None
            if not getattr(user, "has_contact_details", True):
                require_contact = True
                contact_msg = {
                    "en": "I'll save this and your chat history. Please add your details so I can continue:",
                    "es": "Guardaré esto y tu historial. Por favor agrega tus datos para continuar:",
                    "pt": "Vou salvar isso e seu histórico. Por favor adicione seus dados para continuar:",
                }.get(detected_lang, "Please add your email and phone so we can connect you and save your history:")
            biz_snap = {
                "v": 1,
                "kind": "get_top",
                "intent": "business_search",
                "language": detected_lang,
                "category": biz_cat,
                "subcategory": biz_sub,
                "state": state,
                "city": city,
                "county": county,
                "zip_code": zip_code,
                "user_lat": ulat,
                "user_lon": ulon,
                "strict_location": snap_strict,
                "sort_mode": "fairness",
                "extra_match_terms": snap_extra,
                "apply_gps_radius": _apply_gps_radius,
                "anchor_results_to_message_city": _anchor_msg_city,
                "source_message": message,
            }
            biz_pag = _business_pagination_dict(biz_snap, lim, 0, businesses, see_more)
            _save_history(session_id, message, reply, "business_search", structured, businesses=businesses)
            return _build_response(
                reply,
                detected_lang,
                "business_search",
                businesses=businesses,
                see_more=see_more,
                location_note=loc_note,
                question_analysis=structured,
                user_name=user_name,
                require_contact_details=require_contact,
                contact_details_message=contact_msg,
                business_pagination=biz_pag,
            )

        # "Near me" / local discovery: empty Mongo should not short-circuit with directory fallback;
        # continue to KB → Tier 2a0 (LLM) / 2a (OSM dining).
        if is_location_based_query(message) and not kb_over_directory:
            structured["answer_source"] = "deferred_location_discovery"
            logger.info(
                "chat_flow.business_database_first user_id=%s n=0 skip_fallback=location_query",
                user_id,
            )
            _lista_defer = _lista_mongo_directory_response(
                message,
                state=state,
                city=city,
                county=county,
                zip_code=zip_code,
                ulat=ulat,
                ulon=ulon,
                detected_lang=detected_lang,
                user_id=user_id,
                session_id=session_id,
                user_name=user_name,
                structured=dict(structured or {}),
                user=user,
            )
            if _lista_defer:
                return _lista_defer
        else:
            structured = dict(structured or {})
            structured["answer_source"] = "directory_llm_fallback"
            reply = generate_business_not_found_response(
                message,
                city=city or "",
                state=state or "",
                county=county or "",
                zip_code=zip_code or "",
                category_en=biz_cat,
                subcategory_en=biz_sub,
                detected_language=detected_lang,
            )
            _save_history(session_id, message, reply, "business_search", structured)
            logger.info("chat_flow.business_database_first user_id=%s n=0 fallback=helpful_llm", user_id)
            return _build_response(
                reply,
                detected_lang,
                "business_search",
                businesses=[],
                question_analysis=structured,
                user_name=user_name,
            )

    # ------------------------------------------------------------------
    # TIER 1c — Knowledge base search (after business routing)
    # ------------------------------------------------------------------
    matches = search_knowledge(message, state=state, county=county, user_language=detected_lang)
    if not matches and state:
        matches = search_knowledge(message, state=None, county=None, user_language=detected_lang)
    logger.info(
        "chat_flow.kb_search user_id=%s lang=%s state=%s county=%s matches=%s top_similarity=%s",
        user_id,
        detected_lang,
        state,
        county,
        len(matches or []),
        (matches[0].get("similarity") if matches else None),
    )

    if intent == "unclear" and matches:
        intent = "information_request"

    if not matches and (intent == "off_topic" or _looks_off_topic(message)):
        reply = _off_topic_message(detected_lang)
        _save_history(session_id, message, reply, "off_topic", structured)
        logger.info(
            "chat_flow.off_topic.fallback user_id=%s lang=%s model_intent=%s hard_filter=%s",
            user_id,
            detected_lang,
            structured.get("intent"),
            _looks_off_topic(message),
        )
        return _build_response(reply, detected_lang, "off_topic", user_name=user_name)

    if intent == "off_topic" and matches:
        intent = "information_request"

    # ------------------------------------------------------------------
    # TIER 2a0 — Location-based business search (OpenAI + GPS/ZIP/state), Google Maps–style list
    # Runs before OSM local_search; on failure or no API key, falls through to existing branches.
    # ------------------------------------------------------------------
    _tier2a0_location_followup = is_pending_location_clarification_followup(
        message, openai_chat_history
    )
    if (
        is_location_based_query(message) or _tier2a0_location_followup
    ) and not _skip_tier2a0_for_kb_precedence(
        message,
        intent,
        confidence,
        matches,
        kb_over_directory,
        force_tier2a0=_tier2a0_location_followup,
    ):
        def _safe_coord(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        explicit_profile_location = user_location.get("explicit_profile_location", False)
        pipeline_city = (city or "").strip()
        pipeline_state = (state or "").strip() if state else ""

        if explicit_profile_location:
            search_lat = None
            search_lng = None
            if pipeline_city:
                search_city = pipeline_city or (user_location.get("city") or "").strip()
            elif pipeline_state:
                # State named (e.g. Florida) without city — do not pin to GPS city abroad
                search_city = ""
            else:
                search_city = (pipeline_city or user_location.get("city") or "").strip()
            search_state = pipeline_state
            search_zip = zip_code
            search_country = "US"
        else:
            llat = user_location.get("latitude")
            llon = user_location.get("longitude")
            if llat is None:
                llat = getattr(user, "latitude", None)
            if llon is None:
                llon = getattr(user, "longitude", None)
            search_lat = _safe_coord(llat)
            search_lng = _safe_coord(llon)
            if pipeline_city:
                search_city = pipeline_city or (user_location.get("city") or "").strip()
            elif pipeline_state:
                search_city = ""
                search_lat, search_lng = None, None
            else:
                search_city = (pipeline_city or user_location.get("city") or "").strip()
            search_state = pipeline_state
            search_zip = zip_code or extract_zip_from_message(message)
            search_country = (user_location.get("country") or "").strip()

        message_location = extract_location_from_message(message)
        if message_location:
            msg_city = (message_location.get("city") or "").strip()
            msg_state = (message_location.get("state") or search_state or "").strip()
            resolved_state = msg_state
            resolved_city = msg_city
            if not resolved_city:
                resolved_city = ""
            _rc = message_location.get("country") or search_country or (
                "US" if pipeline_state else ""
            )
            resolved_country = str(_rc).strip() or ("US" if pipeline_state else "")
            resolved_lat = None
            resolved_lng = None
            resolved_zip = search_zip
        else:
            resolved_city = search_city
            resolved_state = search_state
            resolved_country = (
                search_country or ("US" if explicit_profile_location else "")
            ).strip()
            if pipeline_state and not pipeline_city:
                resolved_lat, resolved_lng = None, None
                resolved_country = resolved_country or "US"
            else:
                resolved_lat = search_lat
                resolved_lng = search_lng
            resolved_zip = search_zip or extract_zip_from_message(message)

        _rs_fill = _backfill_state_from_major_us_city(resolved_state, resolved_city)
        if _rs_fill:
            resolved_state = _rs_fill
        if pipeline_state and not pipeline_city and (resolved_state or "").strip():
            resolved_country = "US"

        if (
            resolved_lat is None
            and resolved_lng is None
            and not resolved_zip
            and not (resolved_state or "").strip()
        ):
            missing_location_response = {
                "en": "To find businesses near you, could you share your ZIP code? That way I can show you the most relevant options in your area.",
                "es": "Para encontrar negocios cerca de ti, ¿podrías compartir tu código postal? Así puedo mostrarte las opciones más relevantes en tu área.",
                "pt": "Para encontrar negócios perto de você, pode compartilhar seu CEP? Assim posso mostrar as opções mais relevantes na sua área.",
            }
            reply = missing_location_response.get(detected_lang, missing_location_response["en"])
            loc_struct = dict(structured or {})
            loc_struct["intent"] = "location_search_needs_zip"
            loc_struct["detected_language"] = detected_lang
            _save_history(session_id, message, reply, "location_search_needs_zip", loc_struct)
            logger.info("chat_flow.location_llm.needs_zip user_id=%s", user_id)
            return _build_response(
                reply,
                detected_lang,
                "location_search_needs_zip",
                question_analysis=loc_struct,
                user_name=user_name,
            )

        hist = openai_chat_history or []
        recent_hist = hist[-4:] if len(hist) > 4 else list(hist)
        category_hint = extract_category_from_message(message)
        reply = ""

        from chatbot.agents.decision_agent import DecisionAgent
        from chatbot.agents.intent_agent import IntentAgent
        from chatbot.agents.location_agent import LocationAgent
        from chatbot.agents.service_search_agent import ServiceSearchAgent
        from chatbot.agents.ranking_agent import RankingAgent
        from chatbot.agents.response_agent import ResponseAgent
        from chatbot.agents.validation_agent import ValidationAgent
        from chatbot.agents.learning_agent import LearningAgent

        _session_ctx = {"history_turns": len(openai_chat_history or [])}
        _decision = DecisionAgent().run(
            message=message,
            detected_language=detected_lang,
            session_id=session_id,
            session_context=_session_ctx,
            structured_output=dict(structured or {}),
        )
        _intent_ag = IntentAgent().run(message, structured_output=dict(structured or {}))
        _loc_ag = LocationAgent().run_from_pipeline(
            resolved_city=resolved_city or "",
            resolved_state=resolved_state or "",
            county=county or "",
            zip_code=resolved_zip or "",
            latitude=resolved_lat,
            longitude=resolved_lng,
            country=resolved_country or "",
            user_location=user_location,
            explicit_profile_location=explicit_profile_location,
            message=message,
            session_id=session_id,
        )
        logger.info(
            "chat_flow.tier2a0.agent_bridge decision=%s intent=%s loc=%s",
            _decision.route,
            _intent_ag.primary_intent,
            _loc_ag.source,
        )

        _t2_cat, _t2_sub = biz_cat, biz_sub
        _bad_cat = (_t2_cat or "").strip()
        _msg_l = (message or "").strip().lower()
        if (
            len(_bad_cat) > 80
            or "please tell" in _bad_cat.lower()
            or "can you " in _bad_cat.lower()
            or (
                len(_bad_cat) > 32
                and _msg_l.startswith(_bad_cat.lower()[: min(48, len(_bad_cat))])
            )
        ):
            _t2_cat, _t2_sub = None, None
            logger.info("chat_flow.tier2a0.sanitize_category dropped garbage biz_cat")

        lim_db = _directory_first_page_limit()
        _search_ag = ServiceSearchAgent().run(
            message=message,
            category=_t2_cat,
            subcategory=_t2_sub,
            category_hint=category_hint,
            state=resolved_state,
            city=resolved_city,
            county=county,
            zip_code=resolved_zip,
            user_lat=resolved_lat,
            user_lon=resolved_lng,
            language=detected_lang,
            limit=lim_db,
            offset=0,
            external_id=user_id,
            session_id=session_id or user_id,
        )
        _rank_ag = RankingAgent().run(
            _search_ag.businesses,
            message=message,
            user_lat=resolved_lat,
            user_lon=resolved_lng,
        )
        db_discovery = {
            "businesses": _rank_ag.businesses,
            "see_more": _search_ag.see_more,
            "location_note": _search_ag.location_note,
        }
        if db_discovery.get("businesses"):
            _resp_ag = ResponseAgent().build_directory_intro(
                language=detected_lang,
                category=biz_cat or category_hint or "",
                subcategory=biz_sub or "",
                location_note=db_discovery.get("location_note"),
                route_label=_decision.route,
            )
            reply = _resp_ag.response_text
            reply = (
                reply.rstrip()
                + "\n\n"
                + _directory_client_followup_block(
                    detected_lang,
                    zip_code=resolved_zip,
                    city=resolved_city,
                    state=resolved_state,
                    see_more=db_discovery.get("see_more", False),
                    n_shown=len(db_discovery["businesses"]),
                )
            )
            _val_ag = ValidationAgent().run(
                response_text=reply,
                source=_resp_ag.source,
                detected_language=detected_lang,
                original_message=message,
                businesses_count=len(db_discovery["businesses"]),
            )
            LearningAgent().log_interaction(
                session_id=session_id,
                user_id=user_id,
                message=message,
                route=_decision.route,
                source=_search_ag.source,
                gap_detected=False,
                location_source=_loc_ag.source,
                search_params=_search_ag.search_params,
                response_valid=_val_ag.is_valid,
                detected_language=detected_lang,
                meta={
                    "intent_primary": _intent_ag.primary_intent,
                    "validation_issues": list(_val_ag.issues),
                },
            )
            loc_struct = dict(structured or {})
            loc_struct["intent"] = "location_business_search"
            loc_struct["detected_language"] = detected_lang
            loc_struct["location_llm_category"] = category_hint
            loc_struct["answer_source"] = (
                "directory_discovery_mongo"
                if getattr(django_settings, "USE_MONGO", False)
                else "directory_discovery_sql"
            )
            loc_struct["agent_decision_route"] = _decision.route
            loc_struct["agent_validation_ok"] = _val_ag.is_valid
            loc_struct["agent_validation_issues"] = list(_val_ag.issues)
            _save_history(
                session_id,
                message,
                reply,
                "location_business_search",
                loc_struct,
                businesses=db_discovery["businesses"],
            )
            logger.info(
                "chat_flow.location_llm.directory_first user_id=%s n=%s",
                user_id,
                len(db_discovery["businesses"]),
            )
            disc_snap = {
                "v": 1,
                "kind": "directory_discovery",
                "intent": "location_business_search",
                "language": detected_lang,
                "message": message,
                "source_message": message,
                "category": biz_cat,
                "subcategory": biz_sub,
                "category_hint": category_hint,
                "state": resolved_state,
                "city": resolved_city,
                "county": county,
                "zip_code": resolved_zip,
                "user_lat": resolved_lat,
                "user_lon": resolved_lng,
            }
            disc_pag = _business_pagination_dict(
                disc_snap,
                lim_db,
                0,
                db_discovery["businesses"],
                db_discovery.get("see_more", False),
            )
            return _build_response(
                reply,
                detected_lang,
                "location_business_search",
                businesses=db_discovery["businesses"],
                see_more=db_discovery.get("see_more", False),
                location_note=db_discovery.get("location_note"),
                question_analysis=loc_struct,
                user_name=user_name,
                business_pagination=disc_pag,
            )

        if not db_discovery.get("businesses"):
            LearningAgent().log_interaction(
                session_id=session_id,
                user_id=user_id,
                message=message,
                route=_decision.route,
                source=_search_ag.source,
                gap_detected=True,
                location_source=_loc_ag.source,
                search_params=_search_ag.search_params,
                response_valid=False,
                detected_language=detected_lang,
                meta={"stage": "tier2a0_directory_empty_before_llm"},
            )

        if has_api_key:
            try:
                reply = handle_location_search(
                    query=message,
                    detected_language=detected_lang,
                    zip_code=resolved_zip,
                    latitude=resolved_lat,
                    longitude=resolved_lng,
                    state=resolved_state or None,
                    county=county,
                    city=resolved_city or None,
                    country=resolved_country or None,
                    neighbourhood=(user_location.get("neighbourhood") or ""),
                    category=category_hint,
                    chat_history=recent_hist or None,
                )
            except Exception:
                logger.exception("chat_flow.location_llm.openai_failed user_id=%s", user_id)
                reply = ""

        if reply:
            reply = _location_external_links_followup(detected_lang).strip() + "\n\n" + reply.strip()
            loc_struct = dict(structured or {})
            loc_struct["intent"] = "location_business_search"
            loc_struct["detected_language"] = detected_lang
            loc_struct["location_llm_category"] = category_hint
            _save_history(session_id, message, reply, "location_business_search", loc_struct)
            logger.info("chat_flow.location_llm.success user_id=%s len=%s", user_id, len(reply))
            return _build_response(
                reply,
                detected_lang,
                "location_business_search",
                question_analysis=loc_struct,
                user_name=user_name,
            )

    # ------------------------------------------------------------------
    # TIER 2a — Nearest office / restaurants (map lookup) BEFORE generic KB+RAG
    # (KB often has prose but not live listings; RAG was giving generic "use apps" answers.)
    # ------------------------------------------------------------------
    place_query = _extract_local_place_query(message)
    restaurant_query = _extract_restaurant_search_query(message)
    needs_map_lookup = bool(place_query or restaurant_query)
    local_places = []
    restaurant_places = []

    if needs_map_lookup:
        if not location_enabled:
            reply = {
                "en": "To find nearby offices or restaurants on the map, I need your location access or your state/city/ZIP code.",
                "es": "Para buscar oficinas o restaurantes cercanos en el mapa, necesito acceso a tu ubicación o tu estado/ciudad/código postal.",
                "pt": "Para buscar escritórios ou restaurantes próximos no mapa, preciso do acesso à sua localização ou do seu estado/cidade/CEP.",
            }.get(detected_lang, "To find nearby places on the map, I need your state/city/ZIP code.")
            _save_history(session_id, message, reply, "location_required", structured)
            return _build_response(reply, detected_lang, "location_required", question_analysis=structured, user_name=user_name)

        map_lat = user_location.get("latitude")
        map_lon = user_location.get("longitude")
        if map_lat is None:
            map_lat = getattr(user, "latitude", None)
        if map_lon is None:
            map_lon = getattr(user, "longitude", None)
        has_text_location = bool(
            (zip_code and str(zip_code).strip())
            or (city and str(city).strip())
            or (county and str(county).strip())
            or (state and str(state).strip())
        )
        try:
            if map_lat is None or map_lon is None:
                has_gps_location = False
            else:
                float(map_lat)
                float(map_lon)
                has_gps_location = True
        except (TypeError, ValueError):
            has_gps_location = False

        if not has_text_location and not has_gps_location:
            reply = {
                "en": "I can search the map for you. Please share at least your ZIP code or your city/state.",
                "es": "Puedo buscar en el mapa. Comparte al menos tu código postal o tu ciudad/estado.",
                "pt": "Posso buscar no mapa. Compartilhe pelo menos seu CEP ou sua cidade/estado.",
            }.get(detected_lang, "Please share your ZIP code or city/state so I can search the map.")
            _save_history(session_id, message, reply, "location_incomplete", structured)
            return _build_response(reply, detected_lang, "location_incomplete", question_analysis=structured, user_name=user_name)

        if place_query:
            local_places = find_nearby_places(
                place_query, state=state, county=county, city=city, zip_code=zip_code, limit=5
            )
        if restaurant_query:
            restaurant_places = find_nearby_pois(
                restaurant_query, state=state, county=county, city=city, zip_code=zip_code, limit=8
            )

    if place_query and local_places:
        kb_context = ""
        if matches:
            kb_context = "\n\n".join(
                f"Q: {m.get('question', '')}\nA: {m.get('answer', '')}" for m in matches[:4]
            )
        reply = generate_local_office_response(
            user_message=message,
            places=local_places,
            kb_context=kb_context,
            state=state or "",
            county=county or "",
            zip_code=zip_code or "",
            language=detected_lang,
            place_label=place_query,
            chat_history=openai_chat_history,
            known_facts=known_facts,
        )
        _save_history(session_id, message, reply, "local_search", structured)
        logger.info(
            "chat_flow.local_search user_id=%s place=%s places=%s kb_snippets=%s",
            user_id,
            place_query,
            len(local_places),
            bool(matches),
        )
        return _build_response(reply, detected_lang, "local_search", question_analysis=structured, user_name=user_name)

    if restaurant_query and restaurant_places:
        kb_context = ""
        if matches:
            kb_context = "\n\n".join(
                f"Q: {m.get('question', '')}\nA: {m.get('answer', '')}" for m in matches[:4]
            )
        reply = generate_local_dining_response(
            user_message=message,
            places=restaurant_places,
            kb_context=kb_context,
            state=state or "",
            county=county or "",
            zip_code=zip_code or "",
            language=detected_lang,
            search_label=restaurant_query,
            chat_history=openai_chat_history,
            known_facts=known_facts,
        )
        _save_history(session_id, message, reply, "local_search", structured)
        logger.info(
            "chat_flow.local_dining user_id=%s query=%s places=%s kb_snippets=%s",
            user_id,
            restaurant_query,
            len(restaurant_places),
            bool(matches),
        )
        return _build_response(reply, detected_lang, "local_search", question_analysis=structured, user_name=user_name)

    if place_query and not local_places and location_enabled and any([zip_code, city, county, state]):
        logger.info(
            "chat_flow.local_search.skip_no_results user_id=%s place=%s (falling_through_to_kb)",
            user_id,
            place_query,
        )
    if restaurant_query and not restaurant_places and location_enabled and any([zip_code, city, county, state]):
        logger.info(
            "chat_flow.local_dining.skip_no_results user_id=%s query=%s (falling_through_to_kb)",
            user_id,
            restaurant_query,
        )

    # ------------------------------------------------------------------
    # TIER 2 — KB-based response (non-empty matches already passed retrieval thresholds)
    # ------------------------------------------------------------------
    if matches:
        kb_suggest_businesses = []
        top_sim = float(matches[0].get("similarity") or 0.0)
        context_parts = [f"Q: {m.get('question', '')}\nA: {m.get('answer', '')}" for m in matches]
        retrieved_context = "\n\n".join(context_parts)

        if top_sim >= _KB_HIGH_THRESHOLD:
            reply = generate_exact_kb_answer(
                user_message=message,
                kb_entry=matches[0],
                language=detected_lang,
                chat_history=openai_chat_history,
                known_facts=known_facts,
            )
            logger.info(
                "chat_flow.kb_response user_id=%s mode=exact_kb top_similarity=%.4f",
                user_id,
                top_sim,
            )
        else:
            reply = generate_rag_response(
                user_message=message,
                retrieved_context=retrieved_context,
                state=state or "",
                county=county or "",
                zip_code=zip_code or "",
                language=detected_lang,
                chat_history=openai_chat_history,
                known_facts=known_facts,
            )
            logger.info(
                "chat_flow.kb_response user_id=%s mode=rag top_similarity=%.4f context_items=%s",
                user_id,
                top_sim,
                len(matches),
            )
            if has_api_key and response_looks_like_rag_refusal(reply):
                reply = generate_general_braelo_response(
                    message,
                    state or "",
                    county or "",
                    city or "",
                    zip_code or "",
                    detected_lang,
                    chat_history=openai_chat_history,
                    known_facts=known_facts,
                )
                structured = dict(structured or {})
                structured["answer_source"] = "openai_general"
                logger.info(
                    "chat_flow.kb_response user_id=%s mode=openai_general_after_rag_refusal top_similarity=%.4f",
                    user_id,
                    top_sim,
                )

        if (
            structured.get("answer_source") != "openai_general"
            and (not state or not county or not zip_code)
        ):
            loc_hint = {
                "en": " For location-specific results or to find businesses near you, share your state, county, and ZIP code.",
                "es": " Para información específica de tu zona o para encontrar negocios cerca, comparte tu estado, condado y código postal.",
                "pt": " Para informações específicas da sua região ou para encontrar negócios perto de você, compartilhe seu estado, condado e CEP.",
            }
            reply = reply.rstrip() + loc_hint.get(detected_lang, loc_hint["en"])

        _kb_loc = None
        if (
            getattr(django_settings, "KB_PROVIDER_SUGGESTIONS", True)
            and intent in ("information_request", "unclear")
            and structured.get("answer_source") != "openai_general"
            and _should_suggest_providers_with_kb(structured)
        ):
            _kb_loc = _kb_provider_search_location(
                state,
                city,
                county,
                zip_code,
                user_location,
                user_location.get("latitude") or getattr(user, "latitude", None),
                user_location.get("longitude") or getattr(user, "longitude", None),
            )
        if _kb_loc:
            lim = getattr(django_settings, "KB_PROVIDER_SUGGESTIONS_MAX", 3)
            prov = get_top_businesses(
                category=structured.get("category"),
                subcategory=structured.get("subcategory"),
                state=_kb_loc["state"],
                city=_kb_loc["city"],
                county=_kb_loc["county"],
                zip_code=_kb_loc["zip_code"],
                user_lat=_kb_loc["user_lat"],
                user_lon=_kb_loc["user_lon"],
                language=detected_lang,
                limit=lim,
                external_id=user_id,
                session_id=session_id,
                strict_location=bool(_kb_loc["strict_location"]),
                sort_mode="fairness",
                extra_match_terms=extract_directory_attribute_terms(message) or None,
                source_message=message,
            )
            kb_suggest_businesses = prov.get("businesses") or []
            if kb_suggest_businesses:
                logger.info(
                    "chat_flow.kb_provider_suggest user_id=%s category=%s subcategory=%s n=%s",
                    user_id,
                    structured.get("category"),
                    structured.get("subcategory"),
                    len(kb_suggest_businesses),
                )

        _save_history(session_id, message, reply, intent, structured)
        return _build_response(
            reply,
            detected_lang,
            intent,
            question_analysis=structured,
            user_name=user_name,
            businesses=kb_suggest_businesses,
        )

    # ------------------------------------------------------------------
    # TIER 3 — Business search  (only when KB has no match)
    # ------------------------------------------------------------------
    if intent == "business_search":
        user_lat = user_location.get("latitude") or getattr(user, "latitude", None)
        user_lon = user_location.get("longitude") or getattr(user, "longitude", None)
        if not _has_business_location(state, city, county, zip_code, user_lat, user_lon):
            reply = generate_clarifying_questions(
                message,
                detected_lang,
                missing_location=True,
                chat_history=openai_chat_history,
                known_facts=known_facts,
            )
            _save_history(session_id, message, reply, "location_incomplete", structured)
            return _build_response(
                reply, detected_lang, "location_incomplete", question_analysis=structured, user_name=user_name
            )

        limit = _directory_first_page_limit()
        bc = inf_cat or _st_cat
        bs = inf_sub or _st_sub
        _city_for_biz = structured.get("city") or city
        _attr_biz = extract_directory_attribute_terms(message)
        snap_strict = True
        snap_extra = _attr_biz or None
        result = get_top_businesses(
            category=bc,
            subcategory=bs,
            state=state,
            city=_city_for_biz,
            county=county,
            zip_code=zip_code,
            user_lat=user_lat,
            user_lon=user_lon,
            language=detected_lang,
            limit=limit,
            offset=0,
            external_id=user_id,
            session_id=session_id or user_id,
            strict_location=True,
            sort_mode="fairness",
            extra_match_terms=_attr_biz or None,
            apply_gps_radius=_apply_gps_radius,
            anchor_results_to_message_city=_anchor_msg_city,
            source_message=message,
        )
        businesses = result.get("businesses") or []
        see_more = result.get("see_more", False)
        location_note = result.get("location_note")
        if not businesses:
            snap_strict = False
            snap_extra = _attr_biz or None
            result = get_top_businesses(
                category=bc,
                subcategory=bs,
                state=state,
                city=_city_for_biz,
                county=county,
                zip_code=zip_code,
                user_lat=user_lat,
                user_lon=user_lon,
                language=detected_lang,
                limit=limit,
                offset=0,
                external_id=user_id,
                session_id=session_id or user_id,
                strict_location=False,
                sort_mode="fairness",
                extra_match_terms=_attr_biz or None,
                apply_gps_radius=_apply_gps_radius,
                anchor_results_to_message_city=_anchor_msg_city,
                source_message=message,
            )
            businesses = result.get("businesses") or []
            see_more = result.get("see_more", False)
            location_note = result.get("location_note")
        if not businesses and _attr_biz:
            snap_strict = False
            snap_extra = None
            result = get_top_businesses(
                category=bc,
                subcategory=bs,
                state=state,
                city=_city_for_biz,
                county=county,
                zip_code=zip_code,
                user_lat=user_lat,
                user_lon=user_lon,
                language=detected_lang,
                limit=limit,
                offset=0,
                external_id=user_id,
                session_id=session_id or user_id,
                strict_location=False,
                sort_mode="fairness",
                extra_match_terms=None,
                apply_gps_radius=_apply_gps_radius,
                anchor_results_to_message_city=_anchor_msg_city,
                source_message=message,
            )
            businesses = result.get("businesses") or []
            see_more = result.get("see_more", False)
            location_note = result.get("location_note")
            logger.info(
                "chat_flow.business_search user_id=%s name_hint_fallback_no_match n=%s",
                user_id,
                len(businesses),
            )
        logger.info(
            "chat_flow.business_search user_id=%s businesses=%s see_more=%s has_location_note=%s",
            user_id,
            len(businesses),
            see_more,
            bool(location_note),
        )

        if businesses:
            reply = _directory_ui_intro(
                detected_lang,
                category=bc or "",
                subcategory=bs or "",
                location_note=location_note,
            )
            reply = (
                reply.rstrip()
                + "\n\n"
                + _directory_client_followup_block(
                    detected_lang,
                    zip_code=zip_code,
                    city=_city_for_biz,
                    state=state,
                    see_more=see_more,
                    n_shown=len(businesses),
                )
            )
        else:
            structured = dict(structured or {})
            structured["answer_source"] = "directory_llm_fallback"
            reply = generate_business_not_found_response(
                message,
                city=structured.get("city") or city or "",
                state=state or "",
                county=county or "",
                zip_code=zip_code or "",
                category_en=bc,
                subcategory_en=bs,
                detected_language=detected_lang,
            )

        # When we show business results (connecting user with providers), ask for email/phone if missing
        require_contact = False
        contact_msg = None
        if businesses and not getattr(user, "has_contact_details", True):
            require_contact = True
            contact_msg = {
                "en": "I'll save this and your chat history. Please add your details so I can continue:",
                "es": "Guardaré esto y tu historial. Por favor agrega tus datos para continuar:",
                "pt": "Vou salvar isso e seu histórico. Por favor adicione seus dados para continuar:",
            }.get(detected_lang, "Please add your email and phone so we can connect you and save your history:")

        biz_pag = None
        if businesses:
            biz_snap = {
                "v": 1,
                "kind": "get_top",
                "intent": intent,
                "language": detected_lang,
                "category": bc,
                "subcategory": bs,
                "state": state,
                "city": _city_for_biz,
                "county": county,
                "zip_code": zip_code,
                "user_lat": user_lat,
                "user_lon": user_lon,
                "strict_location": snap_strict,
                "sort_mode": "fairness",
                "extra_match_terms": snap_extra,
                "apply_gps_radius": _apply_gps_radius,
                "anchor_results_to_message_city": _anchor_msg_city,
                "source_message": message,
            }
            biz_pag = _business_pagination_dict(biz_snap, limit, 0, businesses, see_more)

        _save_history(
            session_id,
            message,
            reply,
            intent,
            structured,
            businesses=businesses if businesses else None,
        )
        return _build_response(
            reply, detected_lang, intent,
            businesses=businesses,
            see_more=see_more,
            location_note=location_note,
            question_analysis=structured,
            user_name=user_name,
            require_contact_details=require_contact,
            contact_details_message=contact_msg,
            business_pagination=biz_pag,
        )

    # ------------------------------------------------------------------
    # TIER 3b — Business comparison
    # ------------------------------------------------------------------
    if intent == "business_comparison":
        biz_ctx = _fetch_business_context(structured, state)
        logger.info(
            "chat_flow.business_comparison user_id=%s context_len=%s",
            user_id,
            len(biz_ctx or ""),
        )
        reply = generate_business_comparison(
            message,
            biz_ctx or "No business data available.",
            detected_lang,
            chat_history=openai_chat_history,
        )
        _save_history(session_id, message, reply, intent, structured)
        return _build_response(reply, detected_lang, intent, question_analysis=structured, user_name=user_name)

    # ------------------------------------------------------------------
    # TIER 4 — No KB match: OpenAI general answer (in-scope) vs clarification / off-topic
    # ------------------------------------------------------------------
    if intent in ("information_request", "unclear"):
        structured = dict(structured or {})
        structured["retrieval_confidence"] = "none"
        ulat = user_location.get("latitude") or getattr(user, "latitude", None)
        ulon = user_location.get("longitude") or getattr(user, "longitude", None)
        ic, isub = _infer_service_category_from_text(message)
        rescue_cat = structured.get("category") or ic
        rescue_sub = structured.get("subcategory") or isub
        if (
            _heuristic_business_discovery(message)
            and (rescue_cat or rescue_sub)
            and _has_business_location(state, city, county, zip_code, ulat, ulon)
        ):
            lim = _directory_first_page_limit()
            _rescue_attr = extract_directory_attribute_terms(message)
            rescue_snap_extra = _rescue_attr or None
            rescue = get_top_businesses(
                category=rescue_cat,
                subcategory=rescue_sub,
                state=state,
                city=city,
                county=county,
                zip_code=zip_code,
                user_lat=ulat,
                user_lon=ulon,
                language=detected_lang,
                limit=lim,
                offset=0,
                external_id=user_id,
                session_id=session_id or user_id,
                strict_location=False,
                sort_mode="fairness",
                extra_match_terms=_rescue_attr or None,
                apply_gps_radius=_apply_gps_radius,
                anchor_results_to_message_city=_anchor_msg_city,
                source_message=message,
            )
            rescue_biz = rescue.get("businesses") or []
            if not rescue_biz and _rescue_attr:
                rescue_snap_extra = None
                rescue = get_top_businesses(
                    category=rescue_cat,
                    subcategory=rescue_sub,
                    state=state,
                    city=city,
                    county=county,
                    zip_code=zip_code,
                    user_lat=ulat,
                    user_lon=ulon,
                    language=detected_lang,
                    limit=lim,
                    offset=0,
                    external_id=user_id,
                    session_id=session_id or user_id,
                    strict_location=False,
                    sort_mode="fairness",
                    extra_match_terms=None,
                    apply_gps_radius=_apply_gps_radius,
                    anchor_results_to_message_city=_anchor_msg_city,
                    source_message=message,
                )
                rescue_biz = rescue.get("businesses") or []
            if rescue_biz:
                reply = _directory_ui_intro(
                    detected_lang,
                    category=rescue_cat or "",
                    subcategory=rescue_sub or "",
                    location_note=rescue.get("location_note"),
                )
                reply = (
                    reply.rstrip()
                    + "\n\n"
                    + _directory_client_followup_block(
                        detected_lang,
                        zip_code=zip_code,
                        city=city,
                        state=state,
                        see_more=rescue.get("see_more", False),
                        n_shown=len(rescue_biz),
                    )
                )
                structured["category"] = rescue_cat
                structured["subcategory"] = rescue_sub
                structured["answer_source"] = "business_database"
                rescue_snap = {
                    "v": 1,
                    "kind": "get_top",
                    "intent": "information_request",
                    "language": detected_lang,
                    "category": rescue_cat,
                    "subcategory": rescue_sub,
                    "state": state,
                    "city": city,
                    "county": county,
                    "zip_code": zip_code,
                    "user_lat": ulat,
                    "user_lon": ulon,
                    "strict_location": False,
                    "sort_mode": "fairness",
                    "extra_match_terms": rescue_snap_extra,
                    "apply_gps_radius": _apply_gps_radius,
                    "anchor_results_to_message_city": _anchor_msg_city,
                    "source_message": message,
                }
                rescue_pag = _business_pagination_dict(
                    rescue_snap,
                    lim,
                    0,
                    rescue_biz,
                    rescue.get("see_more", False),
                )
                _save_history(
                    session_id,
                    message,
                    reply,
                    "information_request",
                    structured,
                    businesses=rescue_biz,
                )
                logger.info("chat_flow.tier4.business_rescue user_id=%s n=%s", user_id, len(rescue_biz))
                return _build_response(
                    reply,
                    detected_lang,
                    "information_request",
                    businesses=rescue_biz,
                    see_more=rescue.get("see_more", False),
                    location_note=rescue.get("location_note"),
                    question_analysis=structured,
                    user_name=user_name,
                    business_pagination=rescue_pag,
                )
            reply = generate_business_not_found_response(
                message,
                city=city or "",
                state=state or "",
                county=county or "",
                zip_code=zip_code or "",
                category_en=rescue_cat,
                subcategory_en=rescue_sub,
                detected_language=detected_lang,
            )
            structured["answer_source"] = "directory_llm_fallback"
            _save_history(session_id, message, reply, "information_request", structured)
            return _build_response(
                reply, detected_lang, "information_request", question_analysis=structured, user_name=user_name
            )

        if has_api_key:
            reply = generate_general_braelo_response(
                message,
                state or "",
                county or "",
                city or "",
                zip_code or "",
                detected_lang,
                chat_history=openai_chat_history,
                known_facts=known_facts,
            )
            structured["answer_source"] = "openai_general"
            out_intent = "information_request"
            _save_history(session_id, message, reply, out_intent, structured)
            logger.info(
                "chat_flow.general_knowledge user_id=%s reason=no_kb_matches prior_intent=%s",
                user_id,
                intent,
            )
            return _build_response(
                reply, detected_lang, out_intent, question_analysis=structured, user_name=user_name
            )
        reply = generate_kb_clarification_reply(
            message,
            detected_lang,
            chat_history=openai_chat_history,
            known_facts=known_facts,
        )
        _save_history(session_id, message, reply, "kb_clarification", structured)
        logger.info("chat_flow.kb_clarification user_id=%s reason=no_matches_no_openai intent=%s", user_id, intent)
        return _build_response(
            reply, detected_lang, "kb_clarification", question_analysis=structured, user_name=user_name
        )

    reply = _off_topic_message(detected_lang)
    _save_history(session_id, message, reply, "off_topic", structured)
    return _build_response(reply, detected_lang, "off_topic", question_analysis=structured, user_name=user_name)


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------

def _build_response(
    response: str,
    detected_language: str,
    intent: str,
    businesses: list = None,
    see_more: bool = False,
    location_note: str = None,
    question_analysis: dict = None,
    user_name: str = None,
    require_contact_details: bool = False,
    contact_details_message: str = None,
    business_pagination: dict | None = None,
) -> dict:
    from chatbot.ellu.response_formatter import tag_businesses_as_braelo_directory
    from chatbot.ellu.privacy_guard import PrivacyGuard
    from chatbot.ellu.persona import get_phrase

    b_list = tag_businesses_as_braelo_directory(businesses or [])
    # When businesses are returned for structured cards, do not duplicate them in `response`
    # (numbered list + WhatsApp lines); the client renders the same data as cards.
    final_resp = (response or "").strip()

    if not PrivacyGuard().check_outgoing_response(final_resp):
        final_resp = get_phrase("ask_next", detected_language)

    out = {
        "response": final_resp,
        "detected_language": detected_language,
        "businesses": b_list,
        "intent": intent,
        "see_more": see_more,
        "location_note": location_note,
        "question_analysis": question_analysis or {"intent": intent, "detected_language": detected_language},
    }
    if user_name is not None:
        out["user_name"] = user_name
    if require_contact_details:
        out["require_contact_details"] = True
        out["contact_details_message"] = contact_details_message or "Please add your email and phone so we can continue."
    if business_pagination:
        out["business_pagination"] = business_pagination
    return out
