"""
Chat flow pipeline:
  Tier 0   : Casual talk (intents.json)
  Tier 1a  : Structured intent + merged location
  Tier 1b  : Business database FIRST for find/hire local services + location → strict then loose match;
             if empty → directory fallback (Avvo/AILA allowed there only), not generic chat
  Tier 1c  : Knowledge base hybrid search (after business routing)
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
    generate_business_directory_fallback_response,
    response_looks_like_rag_refusal,
)
from chatbot.services.knowledge_service import search_knowledge
from chatbot.services.business_matching import get_top_businesses, mongo_comparison_query
from chatbot.services.casual_intents import get_casual_response
from chatbot.services.local_search import find_nearby_places, find_nearby_pois

logger = logging.getLogger(__name__)

# Strong hybrid score → prefer exact KB answer path vs RAG (retrieval already filtered candidates)
_KB_HIGH_THRESHOLD = float(getattr(django_settings, "RAG_STRONG_MATCH_HYBRID", 0.68))


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
                for k in ("state", "city", "county", "zip_code", "latitude", "longitude", "display_name", "email", "phone"):
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
    return city


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
]


def _infer_service_category_from_text(message: str) -> tuple:
    for rx, pair in _SERVICE_INFERENCE:
        if rx.search(message or ""):
            return pair
    return (None, None)


def _heuristic_business_discovery(message: str) -> bool:
    """Hire/find local professional: service keyword + trigger (find/near me/ZIP/city phrase)."""
    t = (message or "").strip()
    if len(t) < 5:
        return False
    if _CAREER_EDUCATION_RE.search(t):
        return False
    cat, sub = _infer_service_category_from_text(t)
    if not (cat or sub):
        return False
    if _BUSINESS_TRIGGER_RE.search(t):
        return True
    if re.search(r"\b(\d{5})(?:-\d{4})?\b", t):
        return True
    if re.search(r"\b(in|near|en)\s+[A-Z][a-z]{2,}", t):
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


def _user_has_provider_location(
    state: str,
    county: str,
    zip_code: str,
    user_lat,
    user_lon,
) -> bool:
    if user_lat is not None and user_lon is not None:
        return True
    if zip_code and state:
        return True
    if county and state:
        return True
    if state:
        return True
    return False


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


def _load_openai_chat_history(session_id: str, max_documents: int = 200) -> list[dict]:
    """
    Prior turns for this session only (chronological). Used as OpenAI user/assistant messages.
    Excludes the current message (not persisted yet).
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
                    rows.append({"role": role, "content": content})
        else:
            qs = (
                ChatHistory.objects.filter(external_id=session_id)
                .order_by("created_at", "id")[:max_documents]
            )
            for row in qs:
                role = row.role
                content = (row.content or "").strip()
                if role in ("user", "assistant") and content:
                    rows.append({"role": role, "content": content})
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


def _save_history(user_id: str, message: str, reply: str, intent: str, structured: dict):
    try:
        if getattr(django_settings, "USE_MONGO", False):
            from chatbot.mongo_db import get_db
            from datetime import datetime
            db = get_db()
            col = db.chat_history
            now = datetime.utcnow()
            for role, content in [("user", message), ("assistant", reply)]:
                col.insert_one({
                    "external_id": user_id,
                    "role": role,
                    "content": content,
                    "intent": intent,
                    "entities_json": json.dumps(structured) if structured else None,
                    "created_at": now,
                })
        else:
            user = get_or_create_user(user_id)
            if hasattr(user, "id"):
                for role, content in [("user", message), ("assistant", reply)]:
                    ChatHistory.objects.create(
                        user=user,
                        external_id=user_id,
                        role=role,
                        content=content,
                        intent=intent,
                        entities_json=json.dumps(structured) if structured else None,
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
            collection_names = getattr(django_settings, "MONGO_BUSINESS_COLLECTIONS", None) or [
                "business_listings",
                "businesses",
            ]
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_message(
    message: str,
    user_id: str = None,
    session_id: str = None,
    user_location: dict = None,
    user_profile: dict = None,
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

    state = user_location.get("state") or getattr(user, "state", None)
    city = user_location.get("city") or getattr(user, "city", None)
    county = user_location.get("county") or getattr(user, "county", None)
    zip_code = user_location.get("zip_code") or getattr(user, "zip_code", None)
    location_enabled = user_location.get("location_enabled", getattr(user, "location_enabled", True))
    user_name = getattr(user, "display_name", None) or user_profile.get("name") or user_profile.get("display_name")

    _hist_cap = getattr(django_settings, "CHAT_HISTORY_MAX_DOCUMENTS", 200)
    openai_chat_history = _load_openai_chat_history(session_id, _hist_cap)
    # Short-term location memory: reuse ZIP (etc.) from earlier turns in this session.
    state, city, county, zip_code = _enrich_location_from_history(
        state, city, county, zip_code, openai_chat_history
    )

    # Prefer city/state/ZIP named in this message for retrieval (before KB + structured merge).
    state, city, county, zip_code = _apply_message_location_for_map(
        message, state, city, county, zip_code
    )
    known_facts_for_structured = _format_known_facts(state, city, county, zip_code)

    has_api_key = bool(getattr(django_settings, "OPENAI_API_KEY", None))
    logger.info("chat_flow.openai_key_configured=%s", has_api_key)

    message_detected_lang = detect_language(message)
    # user_id  → stable IP key used to persist the language preference on the user doc
    # session_id → per-tab UUID used to check whether this is a new session
    detected_lang = _resolve_conversation_language(
        user, user_id, session_id, message, message_detected_lang
    )

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

    # Merge structured extraction into location (message may mention state/ZIP not on profile)
    state = structured.get("state") or state
    city = structured.get("city") or city
    county = structured.get("county") or county
    zip_code = structured.get("zip_code") or zip_code
    state, city, county, zip_code = _apply_message_location_for_map(
        message, state, city, county, zip_code
    )
    known_facts = _format_known_facts(state, city, county, zip_code)

    if intent == "off_topic" and _looks_in_scope_topic(message):
        structured["model_intent"] = intent
        intent = "information_request"

    # ------------------------------------------------------------------
    # TIER 1b — Business database FIRST when user is finding/hiring a local service + location
    # ------------------------------------------------------------------
    inf_cat, inf_sub = _infer_service_category_from_text(message)
    biz_cat = structured.get("category") or inf_cat
    biz_sub = structured.get("subcategory") or inf_sub
    ulat = user_location.get("latitude") or getattr(user, "latitude", None)
    ulon = user_location.get("longitude") or getattr(user, "longitude", None)
    wants_biz = (intent == "business_search" or _heuristic_business_discovery(message)) and bool(
        biz_cat or biz_sub
    )

    if wants_biz:
        if not _has_business_location(state, city, county, zip_code, ulat, ulon):
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
        lim = getattr(django_settings, "MAX_BUSINESS_RESULTS", 5)
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
            external_id=user_id,
            session_id=session_id or user_id,
            strict_location=True,
            sort_mode="fairness",
        )
        businesses = r1.get("businesses") or []
        loc_note = r1.get("location_note")
        see_more = r1.get("see_more", False)
        if not businesses:
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
                external_id=user_id,
                session_id=session_id or user_id,
                strict_location=False,
                sort_mode="fairness",
            )
            businesses = r2.get("businesses") or []
            loc_note = r2.get("location_note")
            see_more = r2.get("see_more", False)

        structured = dict(structured or {})
        structured["category"] = biz_cat
        structured["subcategory"] = biz_sub

        if businesses:
            reply = _format_businesses_recommendation_engine(
                businesses,
                detected_lang,
                category=biz_cat or "",
                subcategory=biz_sub or "",
                location_note=loc_note,
            )
            structured["answer_source"] = "business_database"
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
            _save_history(session_id, message, reply, "business_search", structured)
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
            )

        structured["answer_source"] = "directory_fallback"
        if has_api_key:
            reply = generate_business_directory_fallback_response(
                message,
                biz_cat or "",
                biz_sub or "",
                state or "",
                county or "",
                city or "",
                zip_code or "",
                detected_lang,
                chat_history=openai_chat_history,
                known_facts=known_facts,
            )
        else:
            reply = {
                "en": "We did not find matching partners in our directory for your area. Try your state bar association, Avvo, or AILA for immigration attorneys — or adjust your location and search again.",
                "es": "No encontramos socios coincidentes en nuestro directorio para tu zona. Prueba el colegio de abogados de tu estado, Avvo o AILA para abogados de inmigración, o ajusta tu ubicación.",
                "pt": "Não encontramos parceiros correspondentes em nosso diretório para sua região. Tente a ordem dos advogados do seu estado, Avvo ou AILA para imigração, ou ajuste a localização.",
            }.get(detected_lang, "No matching listings in our directory.")
        _save_history(session_id, message, reply, "business_search", structured)
        logger.info("chat_flow.business_database_first user_id=%s n=0 fallback=directory", user_id)
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

        if not any([zip_code, city, county, state]):
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

        if (
            getattr(django_settings, "KB_PROVIDER_SUGGESTIONS", True)
            and intent in ("information_request", "unclear")
            and structured.get("answer_source") != "openai_general"
            and _should_suggest_providers_with_kb(structured)
            and _user_has_provider_location(
                state,
                county,
                zip_code,
                user_location.get("latitude") or getattr(user, "latitude", None),
                user_location.get("longitude") or getattr(user, "longitude", None),
            )
        ):
            ulat = user_location.get("latitude") or getattr(user, "latitude", None)
            ulon = user_location.get("longitude") or getattr(user, "longitude", None)
            lim = getattr(django_settings, "KB_PROVIDER_SUGGESTIONS_MAX", 3)
            prov = get_top_businesses(
                category=structured.get("category"),
                subcategory=structured.get("subcategory"),
                state=state,
                city=city,
                county=county,
                zip_code=zip_code,
                user_lat=ulat,
                user_lon=ulon,
                language=detected_lang,
                limit=lim,
                external_id=user_id,
                session_id=session_id,
                strict_location=False,
                sort_mode="fairness",
            )
            kb_suggest_businesses = prov.get("businesses") or []
            if kb_suggest_businesses:
                reply = reply.rstrip() + "\n\n" + _format_businesses_recommendation_engine(
                    kb_suggest_businesses,
                    detected_lang,
                    category=structured.get("category") or "",
                    subcategory=structured.get("subcategory") or "",
                    location_note=prov.get("location_note"),
                )
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

        limit = getattr(django_settings, "MAX_BUSINESS_RESULTS", 5)
        bc = structured.get("category")
        bs = structured.get("subcategory")
        result = get_top_businesses(
            category=bc,
            subcategory=bs,
            state=state,
            city=structured.get("city") or city,
            county=county,
            zip_code=zip_code,
            user_lat=user_lat,
            user_lon=user_lon,
            language=detected_lang,
            limit=limit,
            external_id=user_id,
            session_id=session_id or user_id,
            strict_location=True,
            sort_mode="fairness",
        )
        businesses = result.get("businesses") or []
        see_more = result.get("see_more", False)
        location_note = result.get("location_note")
        if not businesses:
            result = get_top_businesses(
                category=bc,
                subcategory=bs,
                state=state,
                city=structured.get("city") or city,
                county=county,
                zip_code=zip_code,
                user_lat=user_lat,
                user_lon=user_lon,
                language=detected_lang,
                limit=limit,
                external_id=user_id,
                session_id=session_id or user_id,
                strict_location=False,
                sort_mode="fairness",
            )
            businesses = result.get("businesses") or []
            see_more = result.get("see_more", False)
            location_note = result.get("location_note")
        logger.info(
            "chat_flow.business_search user_id=%s businesses=%s see_more=%s has_location_note=%s",
            user_id,
            len(businesses),
            see_more,
            bool(location_note),
        )

        if businesses:
            reply = _format_businesses_recommendation_engine(
                businesses,
                detected_lang,
                category=bc or "",
                subcategory=bs or "",
                location_note=location_note,
            )
        else:
            structured = dict(structured or {})
            structured["answer_source"] = "directory_fallback"
            if has_api_key:
                reply = generate_business_directory_fallback_response(
                    message,
                    bc or "",
                    bs or "",
                    state or "",
                    county or "",
                    city or "",
                    zip_code or "",
                    detected_lang,
                    chat_history=openai_chat_history,
                    known_facts=known_facts,
                )
            else:
                reply = {
                    "en": "We did not find matching partners in our directory for your area. Try your state bar association, Avvo, or AILA for immigration attorneys — or adjust your location and search again.",
                    "es": "No encontramos socios coincidentes en nuestro directorio para tu zona. Prueba el colegio de abogados de tu estado, Avvo o AILA, o ajusta tu ubicación.",
                    "pt": "Não encontramos parceiros em nosso diretório para sua região. Tente a OAB estadual, Avvo ou AILA, ou ajuste a localização.",
                }.get(detected_lang, "No matching listings in our directory.")

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

        _save_history(session_id, message, reply, intent, structured)
        return _build_response(
            reply, detected_lang, intent,
            businesses=businesses,
            see_more=see_more,
            location_note=location_note,
            question_analysis=structured,
            user_name=user_name,
            require_contact_details=require_contact,
            contact_details_message=contact_msg,
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
            lim = getattr(django_settings, "MAX_BUSINESS_RESULTS", 5)
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
                external_id=user_id,
                session_id=session_id or user_id,
                strict_location=False,
                sort_mode="fairness",
            )
            rescue_biz = rescue.get("businesses") or []
            if rescue_biz:
                reply = _format_businesses_recommendation_engine(
                    rescue_biz,
                    detected_lang,
                    category=rescue_cat or "",
                    subcategory=rescue_sub or "",
                    location_note=rescue.get("location_note"),
                )
                structured["category"] = rescue_cat
                structured["subcategory"] = rescue_sub
                structured["answer_source"] = "business_database"
                _save_history(session_id, message, reply, "information_request", structured)
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
                )
            if has_api_key:
                reply = generate_business_directory_fallback_response(
                    message,
                    rescue_cat or "",
                    rescue_sub or "",
                    state or "",
                    county or "",
                    city or "",
                    zip_code or "",
                    detected_lang,
                    chat_history=openai_chat_history,
                    known_facts=known_facts,
                )
            else:
                reply = {
                    "en": "We did not find matching partners in our directory for your area. Try state bar referral, Avvo, or AILA — or adjust your search.",
                    "es": "No encontramos socios en nuestro directorio. Prueba la referencia del colegio de abogados, Avvo o AILA.",
                    "pt": "Não há parceiros no diretório. Tente a OAB estadual, Avvo ou AILA.",
                }.get(detected_lang, "No directory matches.")
            structured["answer_source"] = "directory_fallback"
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
) -> dict:
    out = {
        "response": response,
        "detected_language": detected_language,
        "businesses": businesses or [],
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
    return out
