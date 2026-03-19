"""
RAG chat flow — 3-tier pipeline:
  Tier 0  : Casual talk  → intents.json  (no API call)
  Tier 1  : Hard off-topic filter
  Tier 2  : Knowledge base search (always runs before intent routing)
             - Strong match  (similarity >= HIGH_THRESHOLD) → OpenAI returns exact KB answer
             - Partial match (similarity >= FALLBACK_THRESHOLD) → OpenAI generates RAG response
  Tier 3  : Business search  (location-gated)
  Tier 4  : No KB match, not a business search → friendly off-topic message
"""
import json
import logging
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
)
from chatbot.services.knowledge_service import search_knowledge
from chatbot.services.business_matching import get_top_businesses
from chatbot.services.casual_intents import get_casual_response

logger = logging.getLogger(__name__)

# Similarity thresholds for the 3-tier KB response
_KB_HIGH_THRESHOLD = 0.72   # strong / exact match → give the defined KB answer
_KB_FALLBACK_THRESHOLD = 0.38  # partial match → RAG context response


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


def get_or_create_user(external_id: str, location: dict = None, profile: dict = None) -> _UserLike:
    """Get or create user; location and profile (display_name, email, phone) are merged and persisted."""
    profile = profile or {}
    loc = location or {}
    merge = {
        "state": loc.get("state"),
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
                for k in ("state", "county", "zip_code", "latitude", "longitude", "display_name", "email", "phone"):
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
        for k in ("state", "county", "zip_code"):
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
            user.save(update_fields=["state", "county", "zip_code", "location_enabled",
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

_OFF_TOPIC_HARD_PATTERNS = (
    "code", "program", "c++", "c#", "python script", "javascript", "java ",
    "for loop", "while loop", "algorithm", "script", "coding", "programming",
    "write me a", "create a program", "debug", "syntax", "compile", "variable",
    "weather", "recipe", "tell me a joke", "sport score", "movie review", "video game",
)


def _looks_off_topic(message: str) -> bool:
    if not message or len(message) > 600:
        return False
    lower = message.lower().strip()
    for p in _OFF_TOPIC_HARD_PATTERNS:
        if p in lower:
            return True
    return False


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


# ---------------------------------------------------------------------------
# Business formatting helper
# ---------------------------------------------------------------------------

def _format_businesses(businesses: list, language: str, location_note: str = None,
                        see_more: bool = False) -> str:
    if not businesses:
        return ""
    heading = {
        "en": "Here are some options that might help you:",
        "es": "Estas son algunas opciones que podrían ayudarte:",
        "pt": "Aqui estão algumas opções que podem ajudar:",
    }.get(language, "Here are some options that might help you:")

    parts = [heading]
    for b in businesses:
        name = b.get("name", "")
        cat = b.get("category") or b.get("subcategory") or ""
        loc_parts = filter(None, [b.get("city"), b.get("county"), b.get("state")])
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
        contact = b.get("contact_info") or b.get("whatsapp_url") or ""
        if contact:
            parts.append(f"Contact: {contact}")

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
    category = structured.get("category") or structured.get("subcategory")
    try:
        if getattr(django_settings, "USE_MONGO", False):
            from chatbot.mongo_db import get_db
            db = get_db()
            q = {"is_active": True}
            if category:
                q["$or"] = [
                    {"business_category": {"$regex": category, "$options": "i"}},
                    {"business_subcategory": {"$regex": category, "$options": "i"}},
                ]
            for b in db.business_listings.find(q).limit(5):
                contact = " ".join(filter(None, [b.get("business_number"), b.get("business_email")]))
                context += f"{b.get('business_name','')}: {b.get('business_category') or ''} {b.get('business_subcategory') or ''}. {contact}\n"
        else:
            from chatbot.models import Business
            from django.db.models import Q
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
    user_id = user_id or session_id or "anonymous"
    user_location = user_location or {}
    user_profile = user_profile or {}
    logger.info(
        "chat_flow.process_message.start user_id=%s session_id=%s message_len=%s",
        user_id,
        session_id or user_id,
        len(message or ""),
    )
    user = get_or_create_user(user_id, user_location, profile=user_profile)

    state = user_location.get("state") or getattr(user, "state", None)
    county = user_location.get("county") or getattr(user, "county", None)
    zip_code = user_location.get("zip_code") or getattr(user, "zip_code", None)
    location_enabled = user_location.get("location_enabled", getattr(user, "location_enabled", True))
    user_name = getattr(user, "display_name", None) or user_profile.get("name") or user_profile.get("display_name")

    has_api_key = bool(getattr(django_settings, "OPENAI_API_KEY", None))
    logger.info("chat_flow.openai_key_configured=%s", has_api_key)

    # ------------------------------------------------------------------
    # TIER 0 — Casual intents  (intents.json, no OpenAI call needed)
    # ------------------------------------------------------------------
    casual_text, casual_tag = get_casual_response(message)
    if casual_text:
        detected_lang = detect_language(message)
        reply = (
            translate_verified_answer(casual_text, detected_lang)
            if has_api_key and detected_lang != "en"
            else casual_text
        )
        _save_history(user_id, message, reply, "casual", {"intent": "casual", "detected_language": detected_lang})
        logger.info("chat_flow.tier0.casual user_id=%s lang=%s tag=%s", user_id, detected_lang, casual_tag)
        return _build_response(reply, detected_lang, "casual", user_name=user_name)

    # ------------------------------------------------------------------
    # Language detection + hard off-topic filter
    # ------------------------------------------------------------------
    detected_lang = detect_language(message)

    if _looks_off_topic(message):
        reply = _off_topic_message(detected_lang)
        _save_history(user_id, message, reply, "off_topic", {"intent": "off_topic"})
        logger.info("chat_flow.off_topic.hard_filter user_id=%s lang=%s", user_id, detected_lang)
        return _build_response(reply, detected_lang, "off_topic", user_name=user_name)

    # ------------------------------------------------------------------
    # TIER 1 — Knowledge base search  (ALWAYS runs first, before intent)
    # ------------------------------------------------------------------
    matches = search_knowledge(message, state=state, county=county, user_language=detected_lang)

    # Broaden to global KB if no state-specific match
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

    # ------------------------------------------------------------------
    # Structured intent extraction  (happens in parallel with KB search)
    # ------------------------------------------------------------------
    if has_api_key:
        structured = get_structured_output(message)
    else:
        structured = {
            "intent": "information_request",
            "category": None, "subcategory": None,
            "state": state, "city": None, "county": county, "zip_code": zip_code,
            "detected_language": detected_lang,
            "confidence": 0.5,
        }

    if structured.get("detected_language"):
        detected_lang = structured["detected_language"]

    intent = structured.get("intent") or "information_request"
    confidence = float(structured.get("confidence") or 0.5)
    logger.info(
        "chat_flow.intent user_id=%s intent=%s confidence=%.2f detected_lang=%s",
        user_id,
        intent,
        confidence,
        detected_lang,
    )

    # If GPT says "unclear" but KB has something useful, treat as information_request
    if intent == "unclear" and matches:
        intent = "information_request"

    # If GPT says "off_topic" and KB also has nothing → firm off-topic response
    if intent == "off_topic" and not matches:
        reply = _off_topic_message(detected_lang)
        _save_history(user_id, message, reply, "off_topic", structured)
        return _build_response(reply, detected_lang, "off_topic", user_name=user_name)

    # If intent is off_topic but KB actually found something, override intent so we use the KB
    if intent == "off_topic" and matches:
        intent = "information_request"

    # ------------------------------------------------------------------
    # TIER 2 — KB-based response  (strongest tier, fires whenever KB has hits)
    # ------------------------------------------------------------------
    if matches:
        top_sim = matches[0].get("similarity", 0.0)
        context_parts = [f"Q: {m.get('question', '')}\nA: {m.get('answer', '')}" for m in matches]
        retrieved_context = "\n\n".join(context_parts)

        if top_sim >= _KB_HIGH_THRESHOLD:
            # Strong / exact match — give the pre-defined KB answer, enhanced naturally
            reply = generate_exact_kb_answer(
                user_message=message,
                kb_entry=matches[0],
                language=detected_lang,
            )
            logger.info(
                "chat_flow.kb_response user_id=%s mode=exact_kb top_similarity=%.4f",
                user_id,
                top_sim,
            )
        else:
            # Partial / fallback match — RAG: OpenAI uses KB as context
            reply = generate_rag_response(
                user_message=message,
                retrieved_context=retrieved_context,
                state=state or "",
                county=county or "",
                zip_code=zip_code or "",
                language=detected_lang,
            )
            logger.info(
                "chat_flow.kb_response user_id=%s mode=rag top_similarity=%.4f context_items=%s",
                user_id,
                top_sim,
                len(matches),
            )

        # Append subtle location hint if location is missing (don't block the answer)
        if not state or not county or not zip_code:
            loc_hint = {
                "en": " For location-specific results or to find businesses near you, share your state, county, and ZIP code.",
                "es": " Para información específica de tu zona o para encontrar negocios cerca, comparte tu estado, condado y código postal.",
                "pt": " Para informações específicas da sua região ou para encontrar negócios perto de você, compartilhe seu estado, condado e CEP.",
            }
            reply = reply.rstrip() + loc_hint.get(detected_lang, loc_hint["en"])

        _save_history(user_id, message, reply, intent, structured)
        return _build_response(reply, detected_lang, intent, question_analysis=structured, user_name=user_name)

    # ------------------------------------------------------------------
    # TIER 3 — Business search  (only when KB has no match)
    # ------------------------------------------------------------------
    if intent == "business_search":
        if not location_enabled:
            reply = "To give you the most accurate business recommendations, I need access to your location. Please enable location sharing."
            if has_api_key and detected_lang != "en":
                reply = translate_verified_answer(reply, detected_lang)
            _save_history(user_id, message, reply, "location_required", structured)
            return _build_response(reply, detected_lang, "location_required", user_name=user_name)

        if not state or not county or not zip_code:
            reply = generate_clarifying_questions(message, detected_lang, missing_location=True)
            _save_history(user_id, message, reply, "location_incomplete", structured)
            return _build_response(reply, detected_lang, "location_incomplete", user_name=user_name)

        limit = getattr(django_settings, "MAX_BUSINESS_RESULTS", 5)
        user_lat = user_location.get("latitude") or getattr(user, "latitude", None)
        user_lon = user_location.get("longitude") or getattr(user, "longitude", None)
        result = get_top_businesses(
            category=structured.get("category"),
            subcategory=structured.get("subcategory"),
            state=state,
            city=structured.get("city"),
            county=county,
            zip_code=zip_code,
            user_lat=user_lat,
            user_lon=user_lon,
            language=detected_lang,
            limit=limit,
            external_id=user_id,
            session_id=session_id or user_id,
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
            reply = _format_businesses(businesses, detected_lang, location_note=location_note, see_more=see_more)
        else:
            no_biz = {
                "en": "I couldn't find businesses matching your request in your area. Try adjusting your search or location.",
                "es": "No encontré negocios que coincidan con tu solicitud en tu zona. Intenta ajustar tu búsqueda o ubicación.",
                "pt": "Não encontrei negócios que correspondam ao seu pedido na sua área. Tente ajustar sua pesquisa ou localização.",
            }
            reply = no_biz.get(detected_lang, no_biz["en"])

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

        _save_history(user_id, message, reply, intent, structured)
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
        reply = generate_business_comparison(message, biz_ctx or "No business data available.", detected_lang)
        _save_history(user_id, message, reply, intent, structured)
        return _build_response(reply, detected_lang, intent, question_analysis=structured, user_name=user_name)

    # ------------------------------------------------------------------
    # TIER 4 — No KB match, not a known intent → helpful off-topic message
    # ------------------------------------------------------------------
    reply = _off_topic_message(detected_lang)
    _save_history(user_id, message, reply, "off_topic", structured)
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
