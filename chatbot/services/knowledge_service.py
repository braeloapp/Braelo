"""
Knowledge base: embeddings and semantic search over client DOCX Q&A. Uses config.settings.
"""
import json
import math
import unicodedata
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
    _client = OpenAI(api_key=settings.OPENAI_API_KEY) if getattr(settings, "OPENAI_API_KEY", None) else None
except Exception:
    _client = None


def get_embedding(text: str) -> list:
    if not text or not _client:
        if not _client:
            logger.info("knowledge_service.embedding.skip reason=no_openai_client")
        return []
    try:
        r = _client.embeddings.create(
            model=getattr(settings, "EMBEDDING_MODEL", "text-embedding-3-small"),
            input=text.strip()[:8000],
        )
        return r.data[0].embedding
    except Exception:
        logger.exception("knowledge_service.embedding.error text_len=%s", len(text or ""))
        return []


def cosine_similarity(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _normalize(s: str) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    n = unicodedata.normalize("NFD", s)
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


def _words(s: str, min_len: int = 2) -> set:
    n = _normalize(s)
    words = set()
    for w in n.replace("?", " ").replace(".", " ").split():
        w = "".join(c for c in w if c.isalnum())
        if len(w) >= min_len:
            words.add(w)
    return words


_QUERY_STOPWORDS = {
    "the", "a", "an", "for", "to", "in", "on", "at", "can", "me", "you", "is", "are",
    "and", "or", "but", "that", "this", "it", "of", "with", "from", "as", "so",
    "what", "how", "when", "where", "which", "who", "tell", "give", "get", "please",
}


def _significant_query_words(query: str) -> set:
    words = _words(query or "", min_len=2)
    return words - _QUERY_STOPWORDS


def _keyword_match_in_qa(query_words: set, question: str, answer: str) -> float:
    if not query_words:
        return 0.0
    combined = _normalize((question or "") + " " + (answer or ""))
    combined_words = _words(combined, min_len=2)
    overlap = len(query_words & combined_words) / len(query_words)
    if len(query_words) <= 3 and overlap >= 0.34:
        return overlap
    if overlap >= 0.30:
        return overlap
    return 0.0


def _score_doc_with_cross_lingual(query_emb: list, query_pt_emb: list, doc_emb: list) -> float:
    if not doc_emb or not query_emb:
        return 0.0
    sim = cosine_similarity(query_emb, doc_emb)
    if query_pt_emb and len(query_pt_emb) == len(doc_emb):
        sim_pt = cosine_similarity(query_pt_emb, doc_emb)
        sim = max(sim, sim_pt)
    return sim


def _search_knowledge_mongo(
    query: str,
    state: str = None,
    county: str = None,
    limit: int = None,
    user_language: str = None,
) -> list:
    if limit is None:
        limit = getattr(settings, "RAG_TOP_K", 5)
    threshold = getattr(settings, "RAG_SIMILARITY_THRESHOLD", getattr(settings, "KNOWLEDGE_SIMILARITY_THRESHOLD", 0.62))
    fallback_threshold = getattr(settings, "RAG_SIMILARITY_FALLBACK", 0.38)
    query_clean = _normalize(query or "")
    query_words = _words(query or "")
    significant_words = _significant_query_words(query or "")
    query_for_emb = (query or "").strip()
    if state and state not in (query_for_emb or ""):
        query_for_emb = f"{query_for_emb} {state}".strip()
    query_emb = get_embedding(query_for_emb)
    query_pt_emb = None
    if query_emb and user_language and user_language != "pt":
        try:
            from chatbot.services.gpt_service import translate_query_to_portuguese_for_search
            query_pt = translate_query_to_portuguese_for_search(query or "")
            if query_pt and query_pt.strip():
                query_pt_for_emb = query_pt.strip()
                if state and state not in query_pt_for_emb:
                    query_pt_for_emb = f"{query_pt_for_emb} {state}".strip()
                query_pt_emb = get_embedding(query_pt_for_emb)
        except Exception:
            logger.exception("knowledge_service.query_translation_for_embedding_failed")
    try:
        from chatbot.mongo_db import get_db
        db = get_db()
        kb = db.knowledge_base
        mongo_filter = {}
        if state:
            mongo_filter["$or"] = [
                {"state": {"$regex": "^" + state + "$", "$options": "i"}},
                {"state": None},
                {"state": ""},
            ]
        if county:
            c_filter = {"$or": [
                {"county": {"$regex": "^" + county + "$", "$options": "i"}},
                {"county": None},
                {"county": ""},
            ]}
            if mongo_filter:
                mongo_filter = {"$and": [mongo_filter, c_filter]}
            else:
                mongo_filter = c_filter
        rows = list(kb.find(mongo_filter)) if mongo_filter else list(kb.find({}))
    except Exception:
        logger.exception("knowledge_service.mongo.query_failed")
        return []

    results = []
    if query_emb:
        for row in rows:
            emb = row.get("embedding")
            if not emb:
                continue
            sim = _score_doc_with_cross_lingual(query_emb, query_pt_emb, emb)
            if sim >= threshold:
                results.append({
                    "question": row.get("question", ""),
                    "answer": row.get("answer", ""),
                    "state": row.get("state"),
                    "county": row.get("county"),
                    "similarity": round(sim, 4),
                })
        results.sort(key=lambda x: x["similarity"], reverse=True)
        results = results[:limit]

    if not results and query_emb and fallback_threshold < threshold:
        for row in rows:
            emb = row.get("embedding")
            if not emb:
                continue
            sim = _score_doc_with_cross_lingual(query_emb, query_pt_emb, emb)
            if sim >= fallback_threshold:
                results.append({
                    "question": row.get("question", ""),
                    "answer": row.get("answer", ""),
                    "state": row.get("state"),
                    "county": row.get("county"),
                    "similarity": round(sim, 4),
                })
        results.sort(key=lambda x: x["similarity"], reverse=True)
        results = results[:limit]

    if not results:
        for row in rows:
            q_clean = _normalize(row.get("question") or "")
            if not q_clean:
                continue
            if query_clean in q_clean or q_clean in query_clean or query_clean == q_clean:
                results.append({
                    "question": row.get("question", ""),
                    "answer": row.get("answer", ""),
                    "state": row.get("state"),
                    "county": row.get("county"),
                    "similarity": 1.0,
                })
                if len(results) >= limit:
                    break
                continue
            if query_words:
                q_words = _words(row.get("question") or "")
                overlap = len(query_words & q_words) / len(query_words)
                if overlap >= 0.6:
                    results.append({
                        "question": row.get("question", ""),
                        "answer": row.get("answer", ""),
                        "state": row.get("state"),
                        "county": row.get("county"),
                        "similarity": round(overlap, 2),
                    })
                    if len(results) >= limit:
                        break
        results.sort(key=lambda x: x["similarity"], reverse=True)

    if not results and significant_words:
        scored = []
        for row in rows:
            q_text = row.get("question") or ""
            a_text = row.get("answer") or ""
            score = _keyword_match_in_qa(significant_words, q_text, a_text)
            if score > 0:
                scored.append({
                    "question": q_text,
                    "answer": a_text,
                    "state": row.get("state"),
                    "county": row.get("county"),
                    "similarity": round(score, 2),
                })
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        results = scored[:limit]
    final = results[:limit]
    logger.info(
        "knowledge_service.mongo.search query_len=%s lang=%s rows=%s results=%s top_similarity=%s",
        len(query or ""),
        user_language or "unknown",
        len(rows),
        len(final),
        (final[0].get("similarity") if final else None),
    )
    return final


def search_knowledge(
    query: str,
    state: str = None,
    county: str = None,
    limit: int = None,
    user_language: str = None,
) -> list:
    if getattr(settings, "USE_MONGO", False):
        return _search_knowledge_mongo(
            query, state=state, county=county, limit=limit, user_language=user_language
        )

    try:
        return _search_knowledge_django(query, state=state, county=county, limit=limit, user_language=user_language)
    except Exception as e:
        from django.db.utils import OperationalError, ProgrammingError
        if isinstance(e, (OperationalError, ProgrammingError)):
            return []
        logger.exception("knowledge_service.django.search_unexpected_error")
        raise


def _search_knowledge_django(
    query: str,
    state: str = None,
    county: str = None,
    limit: int = None,
    user_language: str = None,
) -> list:
    from chatbot.models import KnowledgeBase
    from django.db.models import Q

    if limit is None:
        limit = getattr(settings, "RAG_TOP_K", 5)
    threshold = getattr(settings, "RAG_SIMILARITY_THRESHOLD", getattr(settings, "KNOWLEDGE_SIMILARITY_THRESHOLD", 0.62))
    fallback_threshold = getattr(settings, "RAG_SIMILARITY_FALLBACK", 0.38)
    query_clean = _normalize(query or "")
    query_words = _words(query or "")
    significant_words = _significant_query_words(query or "")
    query_for_emb = (query or "").strip()
    if state and state not in (query_for_emb or ""):
        query_for_emb = f"{query_for_emb} {state}".strip()
    query_emb = get_embedding(query_for_emb)
    query_pt_emb = None
    if query_emb and user_language and user_language != "pt":
        try:
            from chatbot.services.gpt_service import translate_query_to_portuguese_for_search
            query_pt = translate_query_to_portuguese_for_search(query or "")
            if query_pt and query_pt.strip():
                query_pt_for_emb = query_pt.strip()
                if state and state not in query_pt_for_emb:
                    query_pt_for_emb = f"{query_pt_for_emb} {state}".strip()
                query_pt_emb = get_embedding(query_pt_for_emb)
        except Exception:
            logger.exception("knowledge_service.query_translation_for_embedding_failed_django")

    qs = KnowledgeBase.objects.filter(embedding_json__isnull=False)
    if state:
        qs = qs.filter(Q(state__iexact=state) | Q(state__isnull=True) | Q(state=""))
    if county:
        qs = qs.filter(Q(county__iexact=county) | Q(county__isnull=True) | Q(county=""))
    rows = list(qs)

    results = []
    if query_emb:
        for row in rows:
            try:
                emb = json.loads(row.embedding_json) if isinstance(row.embedding_json, str) else row.embedding_json
            except Exception:
                continue
            sim = _score_doc_with_cross_lingual(query_emb, query_pt_emb, emb)
            if sim >= threshold:
                results.append({
                    "question": row.question,
                    "answer": row.answer,
                    "state": row.state,
                    "county": getattr(row, "county", None),
                    "similarity": round(sim, 4),
                })
        results.sort(key=lambda x: x["similarity"], reverse=True)
        results = results[:limit]

    if not results and query_emb and fallback_threshold < threshold:
        for row in rows:
            try:
                emb = json.loads(row.embedding_json) if isinstance(row.embedding_json, str) else row.embedding_json
            except Exception:
                continue
            sim = _score_doc_with_cross_lingual(query_emb, query_pt_emb, emb)
            if sim >= fallback_threshold:
                results.append({
                    "question": row.question,
                    "answer": row.answer,
                    "state": row.state,
                    "county": getattr(row, "county", None),
                    "similarity": round(sim, 4),
                })
        results.sort(key=lambda x: x["similarity"], reverse=True)
        results = results[:limit]

    if not results:
        all_qs = KnowledgeBase.objects.all()
        if state:
            all_qs = all_qs.filter(Q(state__iexact=state) | Q(state__isnull=True) | Q(state=""))
        if county:
            all_qs = all_qs.filter(Q(county__iexact=county) | Q(county__isnull=True) | Q(county=""))
        rows_list = list(all_qs)
        for row in rows_list:
            q_clean = _normalize(row.question or "")
            if not q_clean:
                continue
            if query_clean in q_clean or q_clean in query_clean or query_clean == q_clean:
                results.append({
                    "question": row.question,
                    "answer": row.answer,
                    "state": row.state,
                    "county": getattr(row, "county", None),
                    "similarity": 1.0,
                })
                if len(results) >= limit:
                    break
                continue
            if query_words:
                q_words = _words(row.question or "")
                overlap = len(query_words & q_words) / len(query_words)
                if overlap >= 0.6:
                    results.append({
                        "question": row.question,
                        "answer": row.answer,
                        "state": row.state,
                        "county": getattr(row, "county", None),
                        "similarity": round(overlap, 2),
                    })
                    if len(results) >= limit:
                        break
        results.sort(key=lambda x: x["similarity"], reverse=True)

    if not results and significant_words:
        fallback_qs = KnowledgeBase.objects.all()
        if state:
            fallback_qs = fallback_qs.filter(Q(state__iexact=state) | Q(state__isnull=True) | Q(state=""))
        if county:
            fallback_qs = fallback_qs.filter(Q(county__iexact=county) | Q(county__isnull=True) | Q(county=""))
        scored = []
        for row in fallback_qs:
            score = _keyword_match_in_qa(significant_words, row.question or "", row.answer or "")
            if score > 0:
                scored.append({
                    "question": row.question,
                    "answer": row.answer,
                    "state": row.state,
                    "county": getattr(row, "county", None),
                    "similarity": round(score, 2),
                })
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        results = scored[:limit]

    final = results[:limit]
    logger.info(
        "knowledge_service.django.search query_len=%s lang=%s rows=%s results=%s top_similarity=%s",
        len(query or ""),
        user_language or "unknown",
        len(rows),
        len(final),
        (final[0].get("similarity") if final else None),
    )
    return final
