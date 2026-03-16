"""
GPT service: structured intent/entity extraction and conversational response. Uses config.settings.
"""
import json
import logging
from django.conf import settings

logger = logging.getLogger(__name__)
client = None
if getattr(settings, "OPENAI_API_KEY", None):
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
    except Exception:
        client = None

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


def get_structured_output(message: str, conversation_summary: str = "") -> dict:
    if not client:
        return _fallback_structured(message)
    system = """You are an assistant for immigrant communities in the USA (Hispanic and Brazilian).
Classify the user message and extract structured data. Respond with a JSON object only, no markdown.

SCOPE: This chatbot ONLY helps with (1) information about living in the USA (immigration, housing, taxes, jobs, education, health, etc. from the knowledge base), (2) finding local businesses (lawyer, tax preparer, doctor, real estate, etc.), (3) comparing businesses, (4) casual conversation (greetings, thanks, goodbye).
If the user asks for anything OUTSIDE this scope, set intent to "off_topic". Examples of off_topic: writing or explaining code (any language), programming, math problems, weather, jokes, general knowledge questions, recipes, sports, entertainment, or any request unrelated to immigration/living in USA or finding local businesses.

Keys:
- intent: One of "casual", "information_request", "business_search", "business_comparison", "unclear", "off_topic".
- category: legal, tax, housing, immigration, health, job, education, other (or null).
- subcategory: lawyer, tax_preparer, real_estate_agent, doctor, etc. (or null).
- state: US state name if mentioned or null.
- city: city if mentioned or null.
- county: county if mentioned or null.
- zip_code: ZIP code if mentioned or null.
- detected_language: "en", "es", or "pt".
- confidence: number from 0.0 to 1.0. Use low for unclear; use off_topic for out-of-scope requests.

Use null for any field not clearly stated."""

    user = f"User message: {message}"
    if conversation_summary:
        user += f"\n(Recent context: {conversation_summary})"

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
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
        return data
    except Exception:
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
        return query or ""
    try:
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
        return out if out else query
    except Exception as e:
        logger.warning("translate_query_to_portuguese_for_search failed: %s", e)
        return query


BRAELO_RAG_SYSTEM = """You are Braelo, a warm, empathetic, and professional assistant helping immigrants navigate life in the United States. You provide accurate, helpful information based ONLY on the provided knowledge base.

CORE RULES (NEVER VIOLATE):
1. ONLY use information from the provided context. NEVER use external knowledge or guess.
2. When the context CONTAINS relevant information that addresses the user's question (even partially or in different words), you MUST use it to give a full, helpful answer. Do NOT say "I don't have specific information" if the context clearly relates to the question (e.g. context about ITIN when the user asks about "ITIN approval process", or context about a topic when the user rephrases it).
3. ONLY when the context is empty ("No matching content found") or clearly does NOT address the user's question at all, say: "I don't have specific information about that for your area. Could you rephrase your question or tell me your state, county, and ZIP code so I can give you the most accurate answer?"
4. NEVER use bullet points (•), dashes (-), or numbered lists. Write in natural, flowing paragraphs.
5. NEVER guess or make assumptions beyond the context. If the context is relevant, use it; if not, ask one or two specific clarifying questions.
6. NEVER add closing statements like "Let me know if you need help" or "Is there anything else?" Keep the conversation open.
7. Acknowledge the user's location naturally when relevant.
8. Use simple language. Avoid legal jargon or overly technical terms.
9. Be professional for legal/official matters; warm and welcoming for daily life.
10. When the user asks in English, your response MUST be in clear, natural English. If the context is in Portuguese or Spanish, translate it into proper English so it reads naturally, not as a literal translation.

TONE: Emotional and welcoming by default; professional and formal when the situation calls for it. Concise but complete. No unnecessary explanations."""


def generate_rag_response(
    user_message: str,
    retrieved_context: str,
    state: str,
    county: str,
    zip_code: str,
    language: str,
) -> str:
    if not client:
        return "I don't have enough information to answer that right now. Please try again or share your state, county, and ZIP code."

    location_line = f"Location: {state or 'not provided'}, {county or 'not provided'}, ZIP: {zip_code or 'not provided'}"
    lang_instruction = "Provide your response in clear, natural English. Use only the context above."
    if language == "en":
        lang_instruction = (
            "Provide your response in clear, natural English. Use only the context above. "
            "If the context is in Portuguese or Spanish, translate it into proper, natural English so the answer reads well for an English-speaking user (not a literal or word-for-word translation)."
        )
    elif language in ("es", "pt"):
        lang_name = getattr(settings, "LANGUAGE_NAMES", {}).get(language, "English")
        lang_instruction = f"Provide your response in {lang_name}. Use only the context above. If the context is in another language, translate it naturally into {lang_name}."

    user = f"""Context from Knowledge Base:
{retrieved_context or '(No matching content found.)'}

User Information:
{location_line}
Response language: {language}

User Question: {user_message}

{lang_instruction} Write in flowing paragraphs, no bullets or dashes. Do not end with a closing phrase. Keep the conversation open."""

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": BRAELO_RAG_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else "I don't have specific information about that in my knowledge base. Could you rephrase or provide your state, county, and ZIP code?"
    except Exception as e:
        logger.warning("GPT generate_rag_response failed: %s", e)
        return "Something went wrong. Please try again."


def generate_clarifying_questions(message: str, language: str, missing_location: bool = False) -> str:
    if not client:
        if missing_location:
            return "To give you the best answer, I need your state, county, and ZIP code. Could you share those?"
        return "Could you tell me a bit more about what you're looking for? For example, which state or topic?"

    lang_name = getattr(settings, "LANGUAGE_NAMES", {}).get(language, "English")
    system = f"""You are Braelo, a warm assistant for immigrants in the USA. The user's message was unclear or missing important details.
Your job is to ask 2 or 3 short, specific clarifying questions in {lang_name}. Do not use bullet points or dashes; write one or two flowing sentences with questions.
Do not answer the question yourself. Do not add a closing phrase. Keep the conversation open."""

    if missing_location:
        system += " Emphasize that you need their state, county, and ZIP code to provide accurate, location-specific information."

    user = f"User message: {message}\n\nGenerate 2-3 clarifying questions in {lang_name}:"

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else "Could you share your state, county, and ZIP code, and tell me a bit more about what you need?"
    except Exception as e:
        logger.warning("GPT generate_clarifying_questions failed: %s", e)
        return "To help you better, I need your state, county, and ZIP code. What would you like to know?"


def generate_business_comparison(
    user_message: str,
    businesses_context: str,
    language: str,
) -> str:
    if not client or not businesses_context:
        return "I couldn't find enough information to compare those businesses. Try naming them again or ask for businesses in your area."

    lang_name = getattr(settings, "LANGUAGE_NAMES", {}).get(language, "English")
    system = f"""You are Braelo. Compare the given businesses based on the provided context. Write in {lang_name}.
Do NOT use bullet points or dashes. Use flowing paragraphs. Be direct and objective. Do not add a closing statement. Keep the conversation open."""

    user = f"Context:\n{businesses_context}\n\nUser request: {user_message}\n\nProvide a clear comparison in {lang_name}:"

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip() or "I couldn't generate a comparison. Please try again."
    except Exception as e:
        logger.warning("GPT generate_business_comparison failed: %s", e)
        return "Something went wrong. Please try again."


def translate_verified_answer(text: str, target_language: str, preserve_structure: bool = False) -> str:
    if not client or not text or not text.strip():
        return text or ""
    lang_name = getattr(settings, "LANGUAGE_NAMES", {}).get(target_language, "English")
    if preserve_structure:
        system = f"""Translate the following text to {lang_name}. Keep the same structure, line breaks, and formatting. Do not summarize."""
    else:
        system = f"""Translate the following text to {lang_name}. Write in flowing paragraphs. Do NOT use bullet points (•) or dashes. Do not add closing phrases. Translate only."""

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
        return text


def generate_response(
    user_message: str,
    context: str,
    language: str,
    knowledge_answer: str = None,
    businesses_text: str = None,
    translate_answer: bool = True,
) -> str:
    if not client:
        return _fallback_response(language, knowledge_answer, businesses_text)

    if knowledge_answer:
        if translate_answer:
            reply = translate_verified_answer(knowledge_answer, language, preserve_structure=False)
        else:
            reply = knowledge_answer
        if businesses_text:
            reply = reply + "\n\n" + businesses_text
        return reply

    lang_name = getattr(settings, "LANGUAGE_NAMES", {}).get(language, "English")
    system = f"""You are Braelo, a warm assistant for immigrants in the USA. Respond only in {lang_name}.
Be concise. Do not use bullet points or dashes. Do not end with a closing phrase. Keep the conversation open."""

    user = f"The user asked: {user_message}\n\nGive a short helpful response in {lang_name} and suggest they provide their state, county, or ZIP for better answers. No bullets, no closing phrase."

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
        )
        reply = (resp.choices[0].message.content or "").strip()
        if businesses_text:
            reply = reply + "\n\n" + businesses_text
        return reply
    except Exception as e:
        logger.warning("GPT generate_response failed: %s", e)
        return _fallback_response(language, knowledge_answer, businesses_text)


def generate_exact_kb_answer(
    user_message: str,
    kb_entry: dict,
    language: str,
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
        return kb_answer or "I don't have a specific answer for that right now."

    lang_name = getattr(settings, "LANGUAGE_NAMES", {}).get(language, "English")

    system = f"""You are Braelo, a warm assistant helping immigrants navigate life in the USA.
You have found an EXACT answer in your knowledge base for the user's question.
Your job: deliver this answer naturally and completely in {lang_name}.

STRICT RULES:
1. Base your response ONLY on the knowledge base answer provided below. Do NOT add or invent information.
2. If the KB answer is in a different language than {lang_name}, translate it naturally — not word-for-word.
3. Do NOT use bullet points, dashes, or numbered lists. Write in flowing paragraphs.
4. Do NOT add closing phrases like "Let me know if I can help further."
5. Be warm, clear, and concise. Keep the conversation open."""

    user_prompt = f"""Knowledge Base Entry:
Question: {kb_question}
Answer: {kb_answer}

User asked: {user_message}

Deliver the knowledge base answer naturally in {lang_name}:"""

    try:
        resp = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else kb_answer
    except Exception as e:
        logger.warning("GPT generate_exact_kb_answer failed: %s", e)
        return kb_answer or "I don't have a specific answer for that right now."


def _fallback_response(language: str, knowledge_answer: str = None, businesses_text: str = None) -> str:
    if knowledge_answer:
        out = knowledge_answer
    else:
        out = "I'm here to help with questions about living in the USA and to connect you with local services. Please ask in English, Spanish, or Portuguese."
    if businesses_text:
        out = out + "\n\n" + businesses_text
    return out
