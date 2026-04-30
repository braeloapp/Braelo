"""
GPT service: structured intent/entity extraction and conversational response. Uses config.settings.
"""
import json
import logging
import re
from urllib.parse import quote_plus

from django.conf import settings

from chatbot.services.google_places_service import (
    format_places_for_response,
    search_nearby_places,
    search_places_text,
)

logger = logging.getLogger(__name__)
client = None
if getattr(settings, "OPENAI_API_KEY", None):
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info(
            "gpt_service.init openai_client_ready=True model=%s",
            getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
        )
    except Exception:
        client = None
        logger.exception("gpt_service.init openai_client_init_failed")
else:
    logger.info("gpt_service.init openai_client_ready=False reason=missing_openai_api_key")

def _trim_openai_chat_history(
    history: list | None,
    max_messages: int = 24,
    max_content_len: int = 3500,
) -> list[dict]:
    """Keep recent user/assistant turns for OpenAI; drop empty or invalid entries."""
    if not history:
        return []
    out = []
    for m in history:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        out.append({"role": role, "content": content[:max_content_len]})
    if len(out) > max_messages:
        out = out[-max_messages:]
    while out and out[0]["role"] == "assistant":
        out = out[1:]
    return out


def _conversation_memory_system_note() -> str:
    return (
        "CONVERSATION MEMORY: Prior user/assistant messages in this request are real chat history. "
        "Use them to resolve follow-ups (\"that\", \"it\", \"the cheapest\", \"the first one\"). "
        "Stay consistent with earlier answers. Do not contradict yourself without explaining a correction. "
        "Do not ask again for ZIP, city, state, or other details the user already gave in a previous turn. "
        "Never claim you cannot remember the conversation when history is present."
    )


def openai_messages_with_history(
    system_blocks: list,
    chat_history: list | None,
    final_user_content: str,
    *,
    max_messages: int = 24,
    max_final_len: int = 4000,
) -> list[dict]:
    """
    Build [system*, ...history user/assistant..., user] for chat.completions.
    system_blocks: list of non-empty strings (each becomes one system message).
    """
    messages = []
    for block in system_blocks:
        text = (block or "").strip()
        if text:
            messages.append({"role": "system", "content": text[:14000]})
    hist = _trim_openai_chat_history(chat_history, max_messages=max_messages)
    if hist:
        messages.append({"role": "system", "content": _conversation_memory_system_note()})
    messages.extend(hist)
    messages.append({"role": "user", "content": (final_user_content or "").strip()[:max_final_len]})
    return messages


def _lang_system_prefix(language: str) -> str:
    """
    Returns a strict language-enforcement line to prepend to any system prompt.
    This is the single source of truth for forcing output language across all LLM calls.
    """
    names = getattr(settings, "LANGUAGE_NAMES", {"en": "English", "es": "Spanish", "pt": "Portuguese"})
    lang_name = names.get(language, "English")
    if language == "en":
        return ""
    return (
        f"LANGUAGE RULE (ABSOLUTE, HIGHEST PRIORITY): "
        f"You MUST write your ENTIRE response in {lang_name} only. "
        f"Every single word must be in {lang_name}. "
        f"Do NOT use English or any other language anywhere in your response, "
        f"even if the source context or knowledge base is in English. "
        f"Translate all content naturally into {lang_name}.\n\n"
    )


STRUCTURED_SCHEMA = {
    "intent": "casual | information_request | business_search | business_comparison | unclear",
    "category": "e.g. legal, tax, housing",
    "subcategory": "e.g. lawyer, tax_preparer",
    "state": "US state or null",
    "city": "city or null",
    "county": "county or null",
    "zip_code": "ZIP or null",
    "detected_language": "en | es | pt",
    "confidence": "0.0 to 1.0",
}


def get_structured_output(
    message: str,
    conversation_summary: str = "",
    chat_history: list | None = None,
    known_facts: str = "",
) -> dict:
    if not client:
        logger.info("gpt_service.structured.skip reason=no_openai_client")
        return _fallback_structured(message)
    from chatbot.ellu.persona import ELLU_NAME

    system = f"""You are a message classifier for Éllu ({ELLU_NAME} by Braelo), serving immigrant communities in the USA (Hispanic and Brazilian).
Output must be a single JSON object only — no markdown, no explanation, no extra text before or after.

Classify the user message and extract structured data. Respond with a JSON object only, no markdown.

SCOPE: This chatbot helps with (1) practical life in the USA from the knowledge base: immigration paperwork, housing and renting, taxes and ITIN, jobs and work authorization, health and insurance, education, banking, driver's license and DMV/MVD processes (including converting or transferring a foreign license), vehicle registration, state ID, and similar day-to-day topics, (2) finding local businesses (lawyer, tax preparer, doctor, real estate, etc.), (3) comparing businesses, (4) casual conversation (greetings, thanks, goodbye).

Set intent to "information_request" for questions about driver's licenses, permits, DMV visits, tests, documents for driving, or any state-specific procedure that immigrants commonly need — these are IN SCOPE.

Set intent to **"business_search"** (not "information_request") when the user wants to **find, hire, or get a recommendation** for a local professional or service provider — including phrases like "find a lawyer", "need a doctor near me", "any tax person in Phoenix", "immigration attorney in 85001", "plumber nearby", "recommend a realtor", "servicios legales cerca". Extract category, subcategory, and location fields precisely.

Set intent to "information_request" (not business_search) for **career or education** questions about a profession — e.g. "how to become a lawyer", "law school", "what does a CPA do" — with no request to find someone to hire.

For "information_request", when the topic clearly involves a type of professional (e.g. immigration lawyer, tax preparer, real estate agent, doctor), set category and subcategory accordingly (e.g. category "legal", subcategory "lawyer") so the app can suggest local providers — even if the user did not explicitly say "find me a business".

If the user asks for anything OUTSIDE this scope, set intent to "off_topic". Examples of off_topic: writing or debugging software code, programming tutorials, pure math homework, weather, jokes, unrelated trivia, recipes, sports scores, movies, games, or topics with no connection to living in the USA or local services.

Keys:
- intent: One of "casual", "information_request", "business_search", "business_comparison", "unclear", "off_topic".
- category: legal, tax, housing, immigration, health, job, education, other (or null).
- subcategory: lawyer, tax_preparer, real_estate_agent, doctor, etc. (or null).
- state: US state name or 2-letter code if mentioned or null.
- city: city if mentioned or null.
- county: county if mentioned or null.
- zip_code: ZIP code if mentioned or null.
- detected_language: "en", "es", or "pt".
- confidence: number from 0.0 to 1.0. Use low for unclear; use off_topic for out-of-scope requests.

If the user names a specific place for a local question (e.g. "restaurants in Phoenix, AZ", "DMV near ZIP 85004", "Mesa Arizona"), extract city, state, county, and zip_code exactly from their words so map search uses that location, not a vague region.

When the LATEST message is a short follow-up (e.g. only a ZIP code, "the cheapest one", "yes", "that one"), use prior turns in the conversation to infer intent, location, and entities. Carry forward zip_code/state/city from earlier user messages if still relevant.

Use null for any field not clearly stated."""

    facts_block = ""
    if (known_facts or "").strip():
        facts_block = f"\nKnown session facts (trust these; extract into JSON fields when applicable):\n{known_facts.strip()[:2000]}"

    user_tail = f"""Latest user message to classify (this is the current turn):
{message.strip()[:2000]}"""
    if conversation_summary:
        user_tail += f"\n\n(Additional summary: {conversation_summary.strip()[:1500]})"
    if facts_block:
        user_tail += facts_block

    hist = _trim_openai_chat_history(chat_history, max_messages=20)
    msg_list = [{"role": "system", "content": system}]
    if hist:
        msg_list.append({"role": "system", "content": _conversation_memory_system_note()})
        msg_list.extend(hist)
    msg_list.append({"role": "user", "content": user_tail})

    try:
        logger.info(
            "gpt_service.structured.request message_len=%s history_turns=%s",
            len(message or ""),
            len(hist),
        )
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=msg_list,
            temperature=0.1,
        )
        content = (resp.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
        data = json.loads(content)
        for key in ("intent", "category", "subcategory", "state", "city", "county", "zip_code", "detected_language", "confidence"):
            if key not in data:
                data[key] = None
        if data.get("detected_language") not in getattr(settings, "SUPPORTED_LANGUAGES", ["en", "es", "pt"]):
            data["detected_language"] = "en"
        if data.get("intent") not in ("casual", "information_request", "business_search", "business_comparison", "unclear", "off_topic"):
            data["intent"] = "information_request"
        logger.info(
            "gpt_service.structured.response intent=%s confidence=%s lang=%s",
            data.get("intent"),
            data.get("confidence"),
            data.get("detected_language"),
        )
        return data
    except Exception:
        logger.exception("gpt_service.structured.error")
        return _fallback_structured(message)


def _fallback_structured(message: str) -> dict:
    return {
        "intent": "information_request",
        "category": None,
        "subcategory": None,
        "state": None,
        "city": None,
        "county": None,
        "zip_code": None,
        "detected_language": "en",
        "confidence": 0.5,
    }


def translate_query_to_portuguese_for_search(query: str) -> str:
    if not client or not query or not query.strip():
        if not client:
            logger.info("gpt_service.translate_query.skip reason=no_openai_client")
        return query or ""
    try:
        logger.info("gpt_service.translate_query.request query_len=%s", len(query or ""))
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": "Translate the following user question to Portuguese (Brazil). Output ONLY the Portuguese translation, no explanation or quotes. Keep the meaning exact for search.",
                },
                {"role": "user", "content": query.strip()[:2000]},
            ],
            temperature=0,
        )
        out = (resp.choices[0].message.content or "").strip()
        logger.info("gpt_service.translate_query.response translated_len=%s", len(out or ""))
        return out if out else query
    except Exception as e:
        logger.warning("translate_query_to_portuguese_for_search failed: %s", e)
        logger.exception("gpt_service.translate_query.error")
        return query


def rewrite_query_for_kb_retrieval(query: str, user_language: str = "en") -> str:
    """
    Produce a compact Portuguese-oriented search line for retrieval against a PT-structured FAQ.
    No facts or answers — paraphrase and key entities only (for embeddings + token overlap).
    """
    if not client or not query or not query.strip():
        return ""
    lang = (user_language or "en").lower()
    lang_note = {
        "en": "The user wrote in English.",
        "es": "The user wrote in Spanish.",
        "pt": "The user wrote in Portuguese (Brazil).",
    }.get(lang, "The user may write in English, Spanish, or Portuguese.")
    try:
        logger.info("gpt_service.rewrite_query_for_kb.request lang=%s len=%s", lang, len(query))
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You help retrieve FAQ rows from a knowledge base about living in the USA "
                        "(immigration, housing, driver's license, taxes, health, work, etc.). "
                        f"{lang_note} "
                        "Output exactly ONE line in Portuguese (Brazil): a short search query that could appear "
                        "in a FAQ title or answer — synonyms and key nouns only. "
                        "Do NOT answer the question. Do NOT add facts. No quotes, bullets, or JSON."
                    ),
                },
                {"role": "user", "content": query.strip()[:2000]},
            ],
            temperature=0,
        )
        out = (resp.choices[0].message.content or "").strip().split("\n")[0].strip()
        out = out.strip('"').strip("'")[:500]
        logger.info("gpt_service.rewrite_query_for_kb.response len=%s", len(out or ""))
        return out
    except Exception:
        logger.exception("gpt_service.rewrite_query_for_kb.error")
        return ""


def generate_kb_clarification_reply(
    user_message: str,
    language: str,
    chat_history: list | None = None,
    known_facts: str = "",
) -> str:
    """
    When retrieval is uncertain or empty: ask the user to rephrase or give location.
    Must not use external knowledge; stay within Braelo's scope (USA life / local help).
    """
    if not client or not (user_message or "").strip():
        return _kb_clarification_fallback(language)

    lang_name = getattr(settings, "LANGUAGE_NAMES", {"en": "English", "es": "Spanish", "pt": "Portuguese"}).get(language, "English")
    from chatbot.ellu.persona import get_system_prompt

    ellu_base = get_system_prompt(language or "pt")
    system = f"""{ellu_base}

YOUR TASK FOR THIS RESPONSE:
{_lang_system_prefix(language)}The user's message did not match any FAQ entry clearly enough to answer safely.

Write 1–2 short sentences in {lang_name} that:
- Ask them to rephrase using different words, or name the topic (housing, driver's license, taxes, etc.).
- Optionally ask for their US state and ZIP code ONLY if those are not already in the known session facts or prior user messages.
- Do NOT answer their substantive question. Do NOT use outside facts. Do NOT use bullet points or dashes.
- Sound warm and helpful. No closing fluff like "Let me know if you need anything else."
"""

    user_parts = []
    if (known_facts or "").strip():
        user_parts.append(f"Known session facts (do not ask for these again):\n{known_facts.strip()[:2000]}")
    user_parts.append(f"User message:\n{user_message.strip()[:2000]}")
    user = "\n\n".join(user_parts)

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=openai_messages_with_history([system], chat_history, user, max_messages=20),
            temperature=0.35,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else _kb_clarification_fallback(language)
    except Exception:
        logger.exception("gpt_service.kb_clarification.error")
        return _kb_clarification_fallback(language)


def _kb_clarification_fallback(language: str) -> str:
    msgs = {
        "en": "I don't have a close match in my knowledge base for that yet. Could you rephrase your question or tell me your US state and ZIP code so I can look for the right information?",
        "es": "No tengo una coincidencia clara en mi base de conocimiento. ¿Podrías reformular tu pregunta o indicarme tu estado y código postal en EE. UU.?",
        "pt": "Ainda não encontrei uma correspondência clara na minha base de conhecimento. Pode reformular a pergunta ou informar seu estado e CEP nos EUA?",
    }
    return msgs.get(language, msgs["en"])


def response_looks_like_rag_refusal(text: str) -> bool:
    """True when the model answered with the KB-only refusal instead of useful content."""
    if not (text or "").strip():
        return True
    t = text.lower()
    needles = (
        "don't have specific information",
        "do not have specific information",
        "i don't have specific information",
        "no tengo información específica",
        "no tengo informacion especifica",
        "não tenho informações específicas",
        "nao tenho informacoes especificas",
        "tell me your state, county, and zip code",
        "tu estado, condado y código postal",
        "seu estado, condado e cep",
        "could you rephrase your question or tell me your state",
    )
    return any(n in t for n in needles)


GENERAL_BRAELO_SYSTEM = """You are Braelo, a warm assistant for immigrants and newcomers in the United States.

The user's question did not match a verified FAQ article closely enough, or no article covered their situation. Answer using general, widely known information about life in the USA.

Rules:
1. Use the user's wording: if they name a US state, city, or region (e.g. Alaska, Phoenix), tailor your answer to that place. Do NOT ask them to repeat state or ZIP if they already gave a location in the question.
2. Give practical, actionable guidance (where to look, what steps exist, what to watch for). Prefer well-known resource categories: official state websites, federal agencies, workforce or state job boards, USAJOBS for federal jobs, CareerOneStop, local government and library pages, community organizations, networking, training or volunteer programs — as appropriate to their question.
3. If the user is trying to **find or hire** a local professional (lawyer, doctor, tax preparer, etc.) in a specific area, do NOT list third-party directories (Avvo, AILA, FindLaw, Yelp, etc.). Say briefly that no matching partners were found in Braelo's directory for their area and invite them to adjust location or category — unless you are explicitly told this is a "directory fallback" turn (separate instructions).
4. When the topic is work or a job search, briefly remind them that work authorization depends on their immigration status and they should confirm with a qualified professional or official USCIS information; do not assert that someone is or is not allowed to work.
5. Do not invent private phone numbers, office addresses, or legal citations. If details vary by location or year, say they should check current official sources.
6. Focus on the United States (any state or territory). If they ask about another country, answer briefly only if helpful and steer back to US-focused guidance when relevant.
7. Write in the user's language. Short paragraphs or a few bullet points are fine when listing options. Avoid salesy sign-offs; you MAY end with exactly one short, concrete follow-up question so the user can continue (for example which step they are on, or whether they want city-wide vs statewide detail).

TONE: Supportive, clear, and honest."""


BUSINESS_DIRECTORY_FALLBACK_SYSTEM = """You are Braelo. The app's local business database returned NO matches for this user's request (category + location).

Write a SHORT reply in the user's language (under 140 words):
1. Say clearly first that Braelo's internal directory did not return matches for that category and location (so the user understands why you are moving to general web guidance).
2. Offer one refinement before external links: ask if they want you to widen the area (nearby ZIP/city) or change the category wording — they can answer in the next message.
3. Only then give 2–3 practical next steps (Google Maps search, state licensing or bar referral pages, professional associations, etc.). Do NOT invent phone numbers or office addresses.
4. Avoid salesy sign-offs; do not imply any third-party site is a Braelo partner."""


def generate_general_braelo_response(
    user_message: str,
    state: str,
    county: str,
    city: str,
    zip_code: str,
    language: str,
    chat_history: list | None = None,
    known_facts: str = "",
) -> str:
    """
    OpenAI answer when KB retrieval is empty or RAG refuses — use any US location the user names.
    """
    if not client:
        logger.info("gpt_service.general_braelo.skip reason=no_openai_client")
        return _kb_clarification_fallback(language)

    lang_name = getattr(settings, "LANGUAGE_NAMES", {"en": "English", "es": "Spanish", "pt": "Portuguese"}).get(language, "English")
    loc_parts = [p for p in [city, county, state, zip_code] if p]
    location_hint = ", ".join(loc_parts) if loc_parts else "(none—rely on the question text)"

    user = f"""User question:
{user_message.strip()[:2000]}

Optional profile hints: {location_hint}"""
    if (known_facts or "").strip():
        user += f"\n\nKnown session facts (use for continuity; do not re-ask):\n{known_facts.strip()[:2000]}"
    user += f"\n\nRespond in {lang_name}. Every word must be in {lang_name}."

    try:
        logger.info("gpt_service.general_braelo.request lang=%s msg_len=%s", language, len(user_message or ""))
        from chatbot.ellu.persona import get_system_prompt
        ellu_base = get_system_prompt(language or "pt")
        system_prompt = f"{ellu_base}\n\nYOUR TASK FOR THIS RESPONSE:\n{GENERAL_BRAELO_SYSTEM}"

        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=openai_messages_with_history(
                [system_prompt],
                chat_history,
                user,
                max_messages=24,
            ),
            temperature=0.45,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else _kb_clarification_fallback(language)
    except Exception:
        logger.exception("gpt_service.general_braelo.error")
        return _kb_clarification_fallback(language)


def generate_business_directory_fallback_response(
    user_message: str,
    category: str,
    subcategory: str,
    state: str,
    county: str,
    city: str,
    zip_code: str,
    language: str,
    chat_history: list | None = None,
    known_facts: str = "",
) -> str:
    """
    Only after the business DB returned zero rows: suggest external directories (Avvo, AILA, etc.).
    """
    if not client:
        return _kb_clarification_fallback(language)
    lang_name = getattr(settings, "LANGUAGE_NAMES", {"en": "English", "es": "Spanish", "pt": "Portuguese"}).get(language, "English")
    loc = ", ".join(filter(None, [city, county, state, zip_code])) or "(from message)"
    facts = (known_facts or "").strip()
    user = (
        f"User message:\n{(user_message or '').strip()[:2000]}\n\n"
        f"Inferred category: {category or 'unknown'}\n"
        f"Inferred subcategory: {subcategory or 'unknown'}\n"
        f"Location context: {loc}"
    )
    if facts:
        user += f"\n\nKnown session facts:\n{facts[:2000]}"
    user += f"\n\nRespond entirely in {lang_name}."
    try:
        from chatbot.ellu.persona import get_system_prompt
        ellu_base = get_system_prompt(language or "pt")
        system_prompt = f"{ellu_base}\n\nYOUR TASK FOR THIS RESPONSE:\n{BUSINESS_DIRECTORY_FALLBACK_SYSTEM}"

        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=openai_messages_with_history(
                [system_prompt],
                chat_history,
                user,
                max_messages=20,
            ),
            temperature=0.35,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else _kb_clarification_fallback(language)
    except Exception:
        logger.exception("gpt_service.business_directory_fallback.error")
        return _kb_clarification_fallback(language)


LOCATION_SEARCH_SYSTEM = """You are Braelo, a helpful local business assistant for the US Latino and immigrant community.

LOCATION CONTEXT:
{location_context}

YOUR JOB:
The user is asking to find businesses or services nearby. Respond like a knowledgeable local guide — give a clear,
numbered list of relevant businesses or service types in the user's area.

FORMAT (IMPORTANT — one line per item, use an em dash between parts):
1. [Business Name or Type] — [Brief description, 1 sentence] — [Neighborhood or city area if known]
2. ...
(List 5 to 8 options; keep each numbered item on a SINGLE line so links can be added after it.)

After the list, add one short sentence suggesting they call ahead to confirm hours/availability.

RULES:
- {lang_instruction}
- When GPS coordinates are given, derive the city and neighborhood from those coordinates only. Do not use a separate city/ZIP line from the user profile if it could disagree with the coordinates.
- Be specific to the user's location. If you know the area from their ZIP/GPS, name real neighborhoods or nearby cities when reasonable.
- If you don't know specific business names for that exact area, list the types of businesses they should search for.
- Never make up phone numbers or street addresses or website URLs (links will be added automatically).
- Keep the tone friendly and helpful, like a knowledgeable neighbor.
- If the category is very specific (e.g., "Brazilian bakery"), acknowledge it and give the closest useful match.
- Do not start by saying you are an AI or listing your limitations — begin helping directly.
"""


def _split_business_name_from_list_item(rest: str) -> str:
    """Take the segment after 'N. ' up to the first em/en dash (description separator)."""
    rest = (rest or "").strip()
    for sep in (" — ", " – ", " - "):
        if sep in rest:
            return rest.split(sep, 1)[0].strip()
    for ch in ("—", "–"):
        if ch in rest:
            return rest.split(ch, 1)[0].strip()
    return rest[:160].strip()


def _enrich_location_search_with_links(
    text: str,
    *,
    city: str = None,
    state: str = None,
    zip_code: str = None,
    country: str = None,
    latitude: float = None,
    longitude: float = None,
    language: str = "en",
) -> str:
    """
    After the model lists businesses, append a real Google Maps search URL and a Google search URL
    per item (no invented domains).
    """
    if not (text or "").strip():
        return text
    lang = (language or "en").lower()[:2]
    labels = {
        "en": ("Google Maps", "Website & reviews (Google)"),
        "es": ("Google Maps", "Web y reseñas (Google)"),
        "pt": ("Google Maps", "Site e avaliações (Google)"),
    }
    lm, lw = labels.get(lang, labels["en"])
    loc = " ".join(
        x.strip()
        for x in (city or "", state or "", zip_code or "", country or "")
        if x and str(x).strip()
    ).strip()
    geo_hint = ""
    if not loc and latitude is not None and longitude is not None:
        try:
            geo_hint = f"{float(latitude):.5f},{float(longitude):.5f}"
        except (TypeError, ValueError):
            geo_hint = ""

    lines = text.splitlines()
    out = []
    item_line = re.compile(r"^(\d+)\.\s+(.+)$")
    for line in lines:
        out.append(line)
        m = item_line.match(line.strip())
        if not m:
            continue
        name = _split_business_name_from_list_item(m.group(2))
        if len(name) < 2:
            continue
        if loc:
            q_maps = f"{name} {loc}".strip()
        elif geo_hint:
            q_maps = f"{name} near {geo_hint}"
        else:
            q_maps = name
        maps_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(q_maps)}"
        q_web = (
            f"{name} {loc} official website".strip()
            if loc
            else (f"{name} near {geo_hint} official website" if geo_hint else f"{name} official website")
        )
        web_url = f"https://www.google.com/search?q={quote_plus(q_web)}"
        out.append(f"   - {lm}: {maps_url}")
        out.append(f"   - {lw}: {web_url}")
    return "\n".join(out)


def _places_search_keyword(category: str, query: str) -> str:
    """Keyword for Google Places Nearby/Text search; avoid useless generic categories."""
    generic = frozenset(
        {
            "local businesses",
            "businesses",
            "business",
            "nearby",
            "services",
            "shops",
            "stores",
            "",
        }
    )
    c = (category or "").strip()
    if c and c.lower() not in generic and len(c) < 300:
        return c[:100]
    q = (query or "").strip()
    return q[:120] if q else ""


def handle_location_search(
    query: str,
    detected_language: str = "en",
    zip_code: str = None,
    latitude: float = None,
    longitude: float = None,
    state: str = None,
    county: str = None,
    city: str = None,
    country: str = None,
    neighbourhood: str = None,
    category: str = None,
    chat_history: list = None,
) -> str:
    """
    Location-based business search: Google Places first (real listings), then GPT fallback.
    """
    logger.info(
        "[LocationSearch] lat=%s, lng=%s, zip=%s, state=%s, city=%s, country=%s, "
        "category=%s, neighbourhood=%s, lang=%s",
        latitude,
        longitude,
        zip_code,
        state,
        city,
        country,
        category,
        neighbourhood,
        detected_language,
    )

    radius_m = int(getattr(settings, "GOOGLE_PLACES_RADIUS_M", 6000))
    max_places = int(getattr(settings, "GOOGLE_PLACES_MAX_RESULTS", 7))
    kw = _places_search_keyword(category, query)

    try:
        if latitude is not None and longitude is not None:
            latf, lonf = float(latitude), float(longitude)
        else:
            latf, lonf = None, None
    except (TypeError, ValueError):
        latf, lonf = None, None

    places = []
    effective_kw = (kw or "").strip()
    if not effective_kw:
        effective_kw = ((query or "").strip()[:120] or "restaurant")

    if latf is not None and lonf is not None:
        places = search_nearby_places(
            latitude=latf,
            longitude=lonf,
            keyword=effective_kw,
            radius_meters=radius_m,
            max_results=max_places,
        )
        if not places:
            city_s_q = (city or "").strip()
            full_query = f"{effective_kw} near {city_s_q}" if city_s_q else effective_kw
            places = search_places_text(
                query=full_query,
                latitude=latf,
                longitude=lonf,
                radius_meters=radius_m,
                max_results=max_places,
            )
    elif zip_code or city or state:
        location_parts = []
        if city:
            location_parts.append(str(city).strip())
        if state:
            location_parts.append(str(state).strip())
        if zip_code:
            location_parts.append(str(zip_code).strip())
        location_text = " ".join(p for p in location_parts if p)
        q_clean = (query or "").strip()
        if location_text and location_text.lower() not in q_clean.lower():
            text_q = f"{effective_kw} in {location_text}".strip()
        else:
            text_q = (q_clean[:200] if q_clean else f"{effective_kw} in {location_text}".strip())
        places = search_places_text(
            query=text_q,
            latitude=None,
            longitude=None,
            radius_meters=None,
            max_results=max_places,
        )

    if places:
        logger.info(
            "[LocationSearch] Returning %s Google Places results",
            len(places),
        )
        return format_places_for_response(places, detected_language)

    logger.info("[LocationSearch] Google Places empty or skipped, falling back to GPT")

    if not client:
        logger.info("gpt_service.location_search.skip reason=no_openai_client")
        return ""

    city_s = (city or "").strip()
    country_s = (country or "").strip()

    if latitude is not None and longitude is not None:
        try:
            latf, lonf = float(latitude), float(longitude)
            if city_s and country_s:
                location_context = (
                    f"The user is located in {city_s}, {country_s}. "
                    f"Exact GPS coordinates: latitude {latf}, longitude {lonf}. "
                    f"This city was verified by reverse geocoding — use '{city_s}' "
                    f"as the city name in your response. Do NOT use any other city."
                )
            elif city_s:
                location_context = (
                    f"The user is in {city_s}. "
                    f"GPS coordinates: latitude {latf}, longitude {lonf}. "
                    f"Use '{city_s}' as the city — do not guess a different city."
                )
            else:
                location_context = (
                    f"GPS coordinates: latitude {latf}, longitude {lonf}. "
                    f"Determine the city from these exact coordinates. "
                    f"Examples for reference: "
                    f"lat 31.52 lng 74.36 = Lahore Pakistan, "
                    f"lat 31.41 lng 73.08 = Faisalabad Pakistan, "
                    f"lat 33.72 lng 73.09 = Islamabad Pakistan, "
                    f"lat 24.86 lng 67.00 = Karachi Pakistan, "
                    f"lat 40.71 lng -74.01 = New York USA, "
                    f"lat 34.05 lng -118.24 = Los Angeles USA, "
                    f"lat 25.76 lng -80.19 = Miami USA. "
                    f"Use ONLY these coordinates to name the city. "
                    f"Never guess or use a different location."
                )
        except (TypeError, ValueError):
            location_context = "The user's GPS coordinates were invalid."
    elif zip_code:
        location_context = f"ZIP code: {zip_code}. Use ONLY this ZIP."
    elif city_s and state:
        location_context = f"City: {city_s}, State: {state}. Use ONLY this location."
    elif city_s:
        location_context = f"City: {city_s}. Use ONLY this location."
    elif state:
        location_context = f"State: {state}. Use ONLY this location."
    else:
        location_context = "Location unknown."

    lang_map = {
        "es": "Respond entirely in Spanish.",
        "pt": "Respond entirely in Portuguese (Brazilian).",
        "en": "Respond entirely in English.",
    }
    lang_instruction = lang_map.get((detected_language or "en").lower()[:2], lang_map["en"])

    system_body = LOCATION_SEARCH_SYSTEM.format(
        location_context=location_context,
        lang_instruction=lang_instruction,
    )
    from chatbot.ellu.persona import get_system_prompt
    ellu_base = get_system_prompt(detected_language or "pt")
    system_full = f"{ellu_base}\n\nYOUR TASK FOR THIS RESPONSE:\n{system_body}"

    q = (query or "").strip()[:2000]
    cat = (category or "").strip()[:300]
    if cat and cat != q:
        user_content = f"Business or service category focus: {cat}\n\nUser message:\n{q}"
    else:
        user_content = q

    model = getattr(settings, "GPT_MODEL", "gpt-4o-mini")
    try:
        logger.info(
            "gpt_service.location_search.request lang=%s has_gps=%s has_zip=%s",
            detected_language,
            latitude is not None and longitude is not None,
            bool(zip_code),
        )
        resp = client.chat.completions.create(
            model=model,
            messages=openai_messages_with_history(
                [system_full],
                chat_history,
                user_content,
                max_messages=12,
            ),
            max_tokens=900,
            temperature=0.4,
        )
        out = (resp.choices[0].message.content or "").strip()
        out = _enrich_location_search_with_links(
            out,
            city=city,
            state=state,
            zip_code=zip_code,
            country=country,
            latitude=latitude,
            longitude=longitude,
            language=detected_language,
        )
        logger.info("gpt_service.location_search.response len=%s", len(out or ""))
        return out
    except Exception:
        logger.exception("gpt_service.location_search.error")
        return ""


BRAELO_RAG_SYSTEM = """You are Braelo, a warm, empathetic, and professional assistant helping immigrants navigate life in the United States. You provide accurate, helpful information based ONLY on the provided knowledge base.

CORE RULES (NEVER VIOLATE):
1. ONLY use information from the provided context. NEVER use external knowledge or guess.
2. When the context CONTAINS information about the SAME topic as the user's question (driver's license, DMV, documents, tests, housing, taxes, immigration steps, etc.) — even if phrased differently or partially — you MUST synthesize a helpful answer from that context. Treat synonyms and related phrases as a match.
3. Do NOT say "I don't have specific information" when the context mentions the same process, agency, documents, or requirements the user is asking about. Use what is there; if something is missing in the context, say only that part is not in your materials — do not refuse the whole answer.
4. ONLY when the context is empty or is clearly about a completely different subject than the question, say in the user's language: "I don't have specific information about that for your area. Could you rephrase your question or tell me your state, county, and ZIP code so I can give you the most accurate answer?" — but NEVER use that refusal if the user's state, county, or ZIP already appears in "Known user / session facts" or in prior conversation turns; answer with what you have.
5. Prefer natural flowing paragraphs. If the user explicitly asks for steps or a procedure AND the context lists steps or requirements, you MAY present those as a short numbered list (1, 2, 3) taken only from the context.
6. NEVER guess or invent facts beyond the context. If the context is relevant, use it; if only partly relevant, answer the part you can and note what is not covered.
7. Avoid salesy closings like "Let me know if you need anything else." You SHOULD end with exactly one short, helpful follow-up question tied to their topic (for example which step they are on, or whether they need the process for a different visa type) so the chat can continue naturally.
8. Acknowledge the user's state or ZIP when they provided it.
9. LANGUAGE: Respond EXCLUSIVELY in the language stated in "Response language". If the context is in a different language, translate it naturally. Never default to English unless English is the stated response language.

TONE: Warm and clear. Concise but complete."""


def generate_rag_response(
    user_message: str,
    retrieved_context: str,
    state: str,
    county: str,
    zip_code: str,
    language: str,
    chat_history: list | None = None,
    known_facts: str = "",
) -> str:
    if not client:
        logger.info("gpt_service.rag.skip reason=no_openai_client")
        return "I don't have enough information to answer that right now. Please try again or share your state, county, and ZIP code."

    lang_names = getattr(settings, "LANGUAGE_NAMES", {"en": "English", "es": "Spanish", "pt": "Portuguese"})
    lang_name = lang_names.get(language, "English")
    location_line = f"Location: {state or 'not provided'}, {county or 'not provided'}, ZIP: {zip_code or 'not provided'}"

    if language == "en":
        lang_instruction = (
            "Provide your response in clear, natural English. "
            "If the context is in Portuguese or Spanish, translate it into natural English."
        )
    else:
        lang_instruction = (
            f"Provide your response in {lang_name}. "
            f"If the context is in another language, translate it naturally into {lang_name}. "
            f"Every word of your response must be in {lang_name}."
        )

    kb_block = (
        "Retrieved knowledge base context (use ONLY this for factual claims from the FAQ):\n"
        f"{retrieved_context or '(No matching content found.)'}"
    )
    facts_block = ""
    if (known_facts or "").strip():
        facts_block = (
            "Known user / session facts (short-term memory; honor these; do not ask again):\n"
            f"{known_facts.strip()[:2500]}"
        )

    user = f"""User Information:
{location_line}
Response language: {language} ({lang_name})

Current user message:
{user_message.strip()[:2000]}

{lang_instruction} Prefer flowing prose; use a short numbered list only if the user asked for steps and the context lists steps. End with exactly one short follow-up question (not a salesy sign-off) so the user can continue."""

    from chatbot.ellu.persona import get_system_prompt
    ellu_base = get_system_prompt(language or "pt")
    system_prompt = f"{ellu_base}\n\nYOUR TASK FOR THIS RESPONSE:\n{BRAELO_RAG_SYSTEM}"

    system_blocks = [system_prompt, kb_block]
    if facts_block:
        system_blocks.append(facts_block)

    try:
        logger.info(
            "gpt_service.rag.request language=%s context_len=%s history_turns=%s",
            language,
            len(retrieved_context or ""),
            len(_trim_openai_chat_history(chat_history)),
        )
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=openai_messages_with_history(system_blocks, chat_history, user, max_messages=24),
            temperature=0.3,
        )
        out = (resp.choices[0].message.content or "").strip()
        logger.info("gpt_service.rag.response output_len=%s", len(out or ""))
        return out if out else "I don't have specific information about that in my knowledge base. Could you rephrase or provide your state, county, and ZIP code?"
    except Exception as e:
        logger.warning("GPT generate_rag_response failed: %s", e)
        logger.exception("gpt_service.rag.error")
        return "Something went wrong. Please try again."


def _format_map_places_bullets(places: list, max_items: int, name_fallback: str) -> str:
    """Build a markdown bullet list for map POIs (one `- ` per place; sub-line for map URL)."""
    lines = []
    for p in (places or [])[:max_items]:
        disp = (p or {}).get("display_name") or (p or {}).get("name") or name_fallback
        mu = (p or {}).get("map_url")
        if mu:
            lines.append(f"- {disp}\n  - Map: {mu}")
        else:
            lines.append(f"- {disp}")
    return "\n".join(lines)


def generate_local_office_response(
    user_message: str,
    places: list,
    kb_context: str,
    state: str,
    county: str,
    zip_code: str,
    language: str,
    place_label: str,
    chat_history: list | None = None,
    known_facts: str = "",
) -> str:
    """
    Combine OpenStreetMap/Nominatim results with optional KB snippets.
    Must not claim missing office info when places is non-empty.
    """
    if not places:
        return ""

    lang_name = getattr(settings, "LANGUAGE_NAMES", {}).get(language, "English")
    places_block = _format_map_places_bullets(places, 5, place_label)

    if not client:
        header = {
            "en": f"Here are nearby {place_label} options for your area:",
            "es": f"Aquí hay opciones cercanas de {place_label} en tu zona:",
            "pt": f"Aqui estão opções próximas de {place_label} na sua região:",
        }.get(language, f"Here are nearby {place_label} options:")
        return header + "\n\n" + places_block

    from chatbot.ellu.persona import get_system_prompt

    ellu_base = get_system_prompt(language or "pt")
    system = f"""{ellu_base}

YOUR TASK FOR THIS RESPONSE:
{_lang_system_prefix(language)}The user asked for nearby offices or locations (e.g. DMV). Below are REAL map search results with addresses and map links. You MUST use them.

Rules:
1. Write in {lang_name}. Start with one short friendly intro sentence (no bullets in the intro).
2. After the intro, list EVERY map result as markdown bullet points: each main item MUST start with "- " (hyphen + space). For each place, use the exact text from the data (name/address); keep the nested "- Map: …" line under that bullet when a link is provided. Do not use numbered lists (1. 2.) for the locations.
3. Do NOT add offices or addresses that are not in the Map results block.
4. Do NOT say you lack information about office locations when the map results are present.
5. If "Knowledge base context" below is non-empty, add one short paragraph of tips (documents, tests, appointments) using ONLY that context — no invented facts.
6. If knowledge base context is empty, omit procedural detail beyond confirming they should verify hours and required documents on the official state DMV/MVD site.
7. Use prior conversation turns when the user refers to "that", "it", or a follow-up question.
8. No closing fluff like "Let me know if you need anything else."
"""

    user = f"""User question:
{user_message.strip()[:2000]}

User location hint: state={state or 'n/a'}, county={county or 'n/a'}, ZIP={zip_code or 'n/a'}"""
    if (known_facts or "").strip():
        user += f"\n\nKnown session facts:\n{known_facts.strip()[:2000]}"
    user += f"""

Map results (use all of these):
{places_block}

Knowledge base context (may be empty):
{kb_context.strip()[:6000] if kb_context else '(none)'}
"""

    try:
        logger.info(
            "gpt_service.local_office.request lang=%s places=%s kb_len=%s",
            language,
            len(places),
            len(kb_context or ""),
        )
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=openai_messages_with_history([system], chat_history, user, max_messages=20),
            temperature=0.25,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else places_block
    except Exception:
        logger.exception("gpt_service.local_office.error")
        header = {
            "en": f"Here are nearby {place_label} options:",
            "es": f"Opciones cercanas de {place_label}:",
            "pt": f"Opções próximas de {place_label}:",
        }.get(language, f"Here are nearby {place_label} options:")
        return header + "\n\n" + places_block


def generate_local_dining_response(
    user_message: str,
    places: list,
    kb_context: str,
    state: str,
    county: str,
    zip_code: str,
    language: str,
    search_label: str,
    chat_history: list | None = None,
    known_facts: str = "",
) -> str:
    """
    Format OpenStreetMap/Nominatim restaurant (or dining) results.
    Same shape as office lookup; tuned so the model lists real names/links, not generic app advice.
    """
    if not places:
        return ""

    lang_name = getattr(settings, "LANGUAGE_NAMES", {}).get(language, "English")
    places_block = _format_map_places_bullets(places, 10, search_label)

    if not client:
        header = {
            "en": f"Here are map results for {search_label} in your area:",
            "es": f"Resultados del mapa para {search_label} en tu zona:",
            "pt": f"Resultados do mapa para {search_label} na sua região:",
        }.get(language, f"Here are map results for {search_label}:")
        return header + "\n\n" + places_block

    from chatbot.ellu.persona import get_system_prompt

    ellu_base = get_system_prompt(language or "pt")
    system = f"""{ellu_base}

YOUR TASK FOR THIS RESPONSE:
{_lang_system_prefix(language)}The user asked for nearby restaurants or places to eat. Below are REAL OpenStreetMap/Nominatim map search results (names, addresses, map links). You MUST use them as the ONLY source for restaurant names and locations.

Rules:
1. Write in {lang_name}. Start with one short friendly intro sentence (no bullets in the intro).
2. After the intro, list EVERY map result as markdown bullet points: each main item MUST start with "- " (hyphen + space). Copy the place line from the data exactly; keep the nested "- Map: …" line under that bullet when a link is provided. Do not use numbered lists (1. 2.) for the places.
3. Add one short sentence (after the list or woven into the intro) that map data can be incomplete or outdated — they should confirm hours and that the place is still open before going.
4. Do NOT name any restaurant, chain, or neighborhood spot that does NOT appear in the Map results block (no examples like "typically you might try X" — only the given rows).
5. Do NOT say you have no specific restaurant information when the map results are present. Do NOT replace the bullet list with generic advice like "use Google Maps or Yelp" as the main answer.
6. If "Knowledge base context" below is non-empty, add one short paragraph of general tips using ONLY that context — no invented facts.
7. If knowledge base context is empty, do not add procedural filler beyond the accuracy note in rule 3.
8. Use prior conversation turns for follow-ups (e.g. "which is cheapest" refers to the listed places).
9. No closing fluff like "Let me know if you need anything else."
"""

    user = f"""User question:
{user_message.strip()[:2000]}

User location hint: state={state or 'n/a'}, county={county or 'n/a'}, ZIP={zip_code or 'n/a'}"""
    if (known_facts or "").strip():
        user += f"\n\nKnown session facts:\n{known_facts.strip()[:2000]}"
    user += f"""

Map results (use all of these):
{places_block}

Knowledge base context (may be empty):
{kb_context.strip()[:6000] if kb_context else '(none)'}
"""

    try:
        logger.info(
            "gpt_service.local_dining.request lang=%s places=%s kb_len=%s",
            language,
            len(places),
            len(kb_context or ""),
        )
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=openai_messages_with_history([system], chat_history, user, max_messages=20),
            temperature=0.2,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else places_block
    except Exception:
        logger.exception("gpt_service.local_dining.error")
        header = {
            "en": f"Here are map results for {search_label}:",
            "es": f"Resultados del mapa para {search_label}:",
            "pt": f"Resultados do mapa para {search_label}:",
        }.get(language, f"Here are map results for {search_label}:")
        return header + "\n\n" + places_block


def generate_clarifying_questions(
    message: str,
    language: str,
    missing_location: bool = False,
    chat_history: list | None = None,
    known_facts: str = "",
) -> str:
    if not client:
        logger.info("gpt_service.clarifying.skip reason=no_openai_client")
        if missing_location:
            return "To give you the best answer, I need your state, county, and ZIP code. Could you share those?"
        return "Could you tell me a bit more about what you're looking for? For example, which state or topic?"

    lang_name = getattr(settings, "LANGUAGE_NAMES", {}).get(language, "English")
    from chatbot.ellu.persona import get_system_prompt

    ellu_base = get_system_prompt(language or "pt")
    system = f"""{ellu_base}

YOUR TASK FOR THIS RESPONSE:
{_lang_system_prefix(language)}The user's message was unclear or missing important details.
Your job is to ask 2 or 3 short, specific clarifying questions in {lang_name}. Do not use bullet points or dashes; write one or two flowing sentences with questions.
Do not answer the question yourself. Do not add a closing phrase. Keep the conversation open."""

    if missing_location:
        system += (
            " If known session facts already include state, county, or ZIP, do NOT ask for those again; "
            "ask only what is still missing."
        )
        system += " Otherwise emphasize that you need their state, county, and ZIP code for location-specific information."

    user_parts = []
    if (known_facts or "").strip():
        user_parts.append(f"Known session facts:\n{known_facts.strip()[:2000]}")
    user_parts.append(f"User message: {message}\n\nGenerate 2-3 clarifying questions in {lang_name}:")
    user = "\n\n".join(user_parts)

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=openai_messages_with_history([system], chat_history, user, max_messages=16),
            temperature=0.4,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else "Could you share your state, county, and ZIP code, and tell me a bit more about what you need?"
    except Exception as e:
        logger.warning("GPT generate_clarifying_questions failed: %s", e)
        logger.exception("gpt_service.clarifying.error")
        return "To help you better, I need your state, county, and ZIP code. What would you like to know?"


def generate_business_comparison(
    user_message: str,
    businesses_context: str,
    language: str,
    chat_history: list | None = None,
) -> str:
    if not client or not businesses_context:
        if not client:
            logger.info("gpt_service.business_comparison.skip reason=no_openai_client")
        return "I couldn't find enough information to compare those businesses. Try naming them again or ask for businesses in your area."

    lang_name = getattr(settings, "LANGUAGE_NAMES", {}).get(language, "English")
    from chatbot.ellu.persona import get_system_prompt

    ellu_base = get_system_prompt(language or "pt")
    system = f"""{ellu_base}

YOUR TASK FOR THIS RESPONSE:
{_lang_system_prefix(language)}Compare the given businesses based on the provided context. Write in {lang_name}.
Do NOT use bullet points or dashes. Use flowing paragraphs. Be direct and objective. Do not add a closing statement. Keep the conversation open.
Use prior conversation turns if the user refers to businesses mentioned earlier."""

    user = f"Context:\n{businesses_context}\n\nUser request: {user_message}\n\nProvide a clear comparison in {lang_name}:"

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=openai_messages_with_history([system], chat_history, user, max_messages=20),
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip() or "I couldn't generate a comparison. Please try again."
    except Exception as e:
        logger.warning("GPT generate_business_comparison failed: %s", e)
        logger.exception("gpt_service.business_comparison.error")
        return "Something went wrong. Please try again."


def translate_verified_answer(text: str, target_language: str, preserve_structure: bool = False) -> str:
    if not client or not text or not text.strip():
        if not client:
            logger.info("gpt_service.translate_answer.skip reason=no_openai_client")
        return text or ""
    lang_name = getattr(settings, "LANGUAGE_NAMES", {"en": "English", "es": "Spanish", "pt": "Portuguese"}).get(target_language, "English")
    if preserve_structure:
        system = _lang_system_prefix(target_language) + f"""Translate the following text to {lang_name}. Keep the same structure, line breaks, and formatting. Do not summarize."""
    else:
        system = _lang_system_prefix(target_language) + f"""Translate the following text to {lang_name}. Write in flowing paragraphs. Do NOT use bullet points (•) or dashes. Do not add closing phrases. Translate only."""

    user = f"Translate to {lang_name}:\n\n{text}"

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else text
    except Exception as e:
        logger.warning("GPT translate_verified_answer failed: %s", e)
        logger.exception("gpt_service.translate_answer.error")
        return text


def generate_response(
    user_message: str,
    context: str,
    language: str,
    knowledge_answer: str = None,
    businesses_text: str = None,
    translate_answer: bool = True,
    chat_history: list | None = None,
) -> str:
    if not client:
        logger.info("gpt_service.generate_response.skip reason=no_openai_client")
        return _fallback_response(language, knowledge_answer, businesses_text)

    if knowledge_answer:
        if translate_answer:
            reply = translate_verified_answer(knowledge_answer, language, preserve_structure=False)
        else:
            reply = knowledge_answer
        if businesses_text:
            reply = reply + "\n\n" + businesses_text
        return reply

    lang_name = getattr(settings, "LANGUAGE_NAMES", {"en": "English", "es": "Spanish", "pt": "Portuguese"}).get(language, "English")
    from chatbot.ellu.persona import get_system_prompt

    ellu_base = get_system_prompt(language or "pt")
    system = f"""{ellu_base}

YOUR TASK FOR THIS RESPONSE:
{_lang_system_prefix(language)}Respond only in {lang_name}.
Be concise. Do not use bullet points or dashes. Do not end with a closing phrase. Keep the conversation open."""

    user = f"The user asked: {user_message}\n\nGive a short helpful response in {lang_name} and suggest they provide their state, county, or ZIP for better answers. No bullets, no closing phrase."

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=openai_messages_with_history([system], chat_history, user, max_messages=16),
            temperature=0.4,
        )
        reply = (resp.choices[0].message.content or "").strip()
        if businesses_text:
            reply = reply + "\n\n" + businesses_text
        return reply
    except Exception as e:
        logger.warning("GPT generate_response failed: %s", e)
        logger.exception("gpt_service.generate_response.error")
        return _fallback_response(language, knowledge_answer, businesses_text)


def generate_exact_kb_answer(
    user_message: str,
    kb_entry: dict,
    language: str,
    chat_history: list | None = None,
    known_facts: str = "",
) -> str:
    """
    Called when the top KB match has high similarity (strong / exact match).
    Instructs OpenAI to deliver the pre-defined KB answer naturally and precisely,
    translating into the user's language if needed. Falls back to the raw KB answer
    if OpenAI is unavailable.
    """
    kb_question = kb_entry.get("question", "")
    kb_answer = kb_entry.get("answer", "")

    if not client:
        # No OpenAI — return the raw KB answer, translated inline if needed
        logger.info("gpt_service.generate_exact_kb.skip reason=no_openai_client")
        return kb_answer or "I don't have a specific answer for that right now."

    lang_name = getattr(settings, "LANGUAGE_NAMES", {"en": "English", "es": "Spanish", "pt": "Portuguese"}).get(language, "English")

    from chatbot.ellu.persona import get_system_prompt
    ellu_base = get_system_prompt(language or "pt")
    
    system = f"""{ellu_base}

YOUR TASK FOR THIS RESPONSE:
You have found a strong match in your knowledge base for the user's question.
Your job: deliver this answer naturally and completely in {lang_name}.

STRICT RULES:
1. Base your response ONLY on the knowledge base answer provided below. Do NOT add or invent information.
2. If the KB answer is in a different language than {lang_name}, translate it naturally — not word-for-word.
3. Prefer flowing paragraphs. If the user explicitly asks for step-by-step or numbered steps and the KB answer contains distinct steps or bullet points, you MAY format those as a short numbered list (1, 2, 3) taken only from the KB text.
4. Avoid salesy closings like "Let me know if I can help further."
5. Be warm, clear, and concise. End with exactly one short follow-up question related to their topic so the conversation stays open."""

    user_prompt = f"""Knowledge Base Entry:
Question: {kb_question}
Answer: {kb_answer}

User asked: {user_message}"""
    if (known_facts or "").strip():
        user_prompt += f"\n\nKnown session facts:\n{known_facts.strip()[:2000]}"
    user_prompt += f"\n\nDeliver the knowledge base answer naturally in {lang_name}:"

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=openai_messages_with_history([system], chat_history, user_prompt, max_messages=24),
            temperature=0.2,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else kb_answer
    except Exception as e:
        logger.warning("GPT generate_exact_kb_answer failed: %s", e)
        logger.exception("gpt_service.generate_exact_kb.error")
        return kb_answer or "I don't have a specific answer for that right now."


def _fallback_response(language: str, knowledge_answer: str = None, businesses_text: str = None) -> str:
    if knowledge_answer:
        out = knowledge_answer
    else:
        out = "I'm here to help with questions about living in the USA and to connect you with local services. Please ask in English, Spanish, or Portuguese."
    if businesses_text:
        out = out + "\n\n" + businesses_text
    return out
