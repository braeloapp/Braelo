"""
Knowledge base: embeddings and semantic search over client DOCX Q&A. Uses config.settings.
"""
import json
import math
import re
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
    # English
    "the", "a", "an", "for", "to", "in", "on", "at", "can", "me", "you", "is", "are",
    "and", "or", "but", "that", "this", "it", "of", "with", "from", "as", "so",
    "what", "how", "when", "where", "which", "who", "tell", "give", "get", "please",
    "about", "do", "does", "did", "be", "was", "were", "will", "would", "could",
    "should", "have", "has", "had", "my", "your", "their", "our", "its", "if",
    # Portuguese
    "o", "a", "os", "as", "um", "uma", "uns", "umas",
    "de", "do", "da", "dos", "das", "no", "na", "nos", "nas",
    "em", "por", "para", "com", "sem", "se", "que", "mas", "ou",
    "e", "eu", "tu", "voce", "ele", "ela", "nos", "eles", "elas",
    "me", "te", "lhe", "nos", "vos", "lhes",
    "este", "esta", "esse", "essa", "aquele", "aquela",
    "isso", "isto", "aquilo",
    "qual", "quais", "como", "quando", "onde", "quem", "quanto",
    "pode", "posso", "dizer", "falar", "informar", "saber", "conhecer",
    "por", "pelo", "pela", "pelos", "pelas",
    "ao", "aos", "ao", "a",
    "foi", "sao", "esta", "tem", "ter", "ser", "estar", "fazer",
    "mais", "muito", "muitos", "muita", "muitas", "todo", "toda",
    "meu", "minha", "seu", "sua", "nosso", "nossa",
    "preciso", "quero", "gostaria", "poderia",
    # Spanish
    "el", "los", "las", "unos", "unas",
    "yo", "tu", "el", "ella", "nosotros", "vosotros", "ellos",
    "me", "te", "le", "nos", "os", "les",
    "del", "al", "por", "para", "con", "sin",
    "que", "cual", "cuales", "como", "cuando", "donde", "quien",
    "puedo", "puede", "puedes", "decir", "hablar", "saber",
    "este", "esta", "ese", "esa", "aquel", "aquella",
    "es", "son", "era", "fue", "tiene", "tener",
    "mas", "muy", "todo", "toda", "mi", "su",
}


def _significant_query_words(query: str) -> set:
    words = _words(query or "", min_len=2)
    return words - _QUERY_STOPWORDS


_US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "ny",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming",
}


def _extract_state_from_query(query: str) -> str:
    """Return a US state name if it is literally mentioned in the query (case-insensitive)."""
    q = _normalize(query or "")
    for state in _US_STATES:
        if re.search(r'\b' + re.escape(state) + r'\b', q):
            # Return capitalised form matching Mongo documents
            return state.title()
    return None


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


def preprocess_query_for_search(text: str) -> str:
    """Collapse whitespace and strip; keep text suitable for LLM rewrite and embeddings."""
    if not text:
        return ""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def build_kb_search_fields(question: str, answer: str) -> dict:
    """Indexed fields for hybrid retrieval (Mongo + optional Django JSONField)."""
    q = question or ""
    a = answer or ""
    combined = preprocess_query_for_search(f"{q}\n{a}")
    tokens = sorted(_words(q, min_len=2) | _words(a, min_len=2))
    return {
        "search_text_normalized": _normalize(combined)[:8000],
        "search_tokens": tokens,
    }


def _lexical_similarity(query_tokens: set, doc_tokens: set) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    inter = query_tokens & doc_tokens
    if not inter:
        return 0.0
    union = query_tokens | doc_tokens
    jacc = len(inter) / len(union)
    recall = len(inter) / len(query_tokens)
    return min(1.0, 0.42 * jacc + 0.58 * recall)


def _row_get(row, key: str):
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _parse_embedding_field(raw):
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw if raw else None
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) and v else None
        except Exception:
            return None
    return None


def _row_doc_tokens(row) -> set:
    st = _row_get(row, "search_tokens")
    if isinstance(st, str):
        try:
            st = json.loads(st)
        except Exception:
            st = None
    if isinstance(st, (list, tuple)) and st:
        out = set()
        for x in st:
            xs = str(x).strip().lower()
            xs = "".join(c for c in xs if c.isalnum() or c == " ")
            for w in xs.split():
                if len(w) >= 2:
                    out.add(w)
        return out
    q = _row_get(row, "question") or ""
    a = _row_get(row, "answer") or ""
    return _words(q, min_len=2) | _words(a, min_len=2)


def _hybrid_rank_rows(rows: list, query: str, state: str, user_language: str, limit: int) -> list:
    """
    Combine embedding similarity (original + optional LLM rewrite + PT translation embed)
    with lexical overlap on KB tokens. Returns list of {question, answer, state, county, similarity}.
    """
    pre = preprocess_query_for_search(query or "")
    if not pre and not (query or "").strip():
        return []
    if not rows:
        return []

    alpha = float(getattr(settings, "RAG_HYBRID_EMBEDDING_WEIGHT", 0.58))
    emb_floor = float(getattr(settings, "RAG_EMBEDDING_MIN_FOR_MATCH", 0.18))
    th = float(getattr(settings, "RAG_SIMILARITY_THRESHOLD", 0.38))
    fb = float(getattr(settings, "RAG_SIMILARITY_FALLBACK", 0.24))

    lang = user_language or "en"
    rewrite = ""
    if getattr(settings, "RAG_QUERY_REWRITE", True) and getattr(settings, "OPENAI_API_KEY", None):
        try:
            from chatbot.services.gpt_service import rewrite_query_for_kb_retrieval
            rewrite = (rewrite_query_for_kb_retrieval(pre, lang) or "").strip()
        except Exception:
            logger.exception("knowledge_service.rewrite_query_failed")
    if rewrite and _normalize(rewrite) == _normalize(pre):
        rewrite = ""

    q_tokens = _significant_query_words(pre)
    if rewrite:
        q_tokens |= _significant_query_words(rewrite)

    use_state = state or _extract_state_from_query(query)

    def emb_base(s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        if use_state and use_state.lower() not in s.lower():
            return f"{s} {use_state}".strip()
        return s

    qe = get_embedding(emb_base(pre))
    qe_rw = get_embedding(emb_base(rewrite)) if rewrite else []
    qe_pt = None
    if qe and lang != "pt":
        try:
            from chatbot.services.gpt_service import translate_query_to_portuguese_for_search
            qt = translate_query_to_portuguese_for_search(pre)
            if qt and qt.strip():
                qe_pt = get_embedding(emb_base(qt.strip()))
        except Exception:
            logger.exception("knowledge_service.translate_for_embed_failed")

    scored = []
    for row in rows:
        q = _row_get(row, "question") or ""
        a = _row_get(row, "answer") or ""
        emb = _parse_embedding_field(_row_get(row, "embedding"))
        if emb is None:
            emb = _parse_embedding_field(_row_get(row, "embedding_json"))

        dtoks = _row_doc_tokens(row)
        if emb:
            s_emb = _score_doc_with_cross_lingual(qe, qe_pt, emb)
            if qe_rw:
                s_emb = max(s_emb, _score_doc_with_cross_lingual(qe_rw, qe_pt, emb))
        else:
            s_emb = 0.0

        lex = _lexical_similarity(q_tokens, dtoks) if q_tokens else 0.0
        if not q_tokens:
            hybrid = s_emb
        elif emb is None:
            hybrid = lex
        else:
            hybrid = alpha * s_emb + (1.0 - alpha) * lex

        if emb and s_emb < emb_floor and lex < 0.32:
            hybrid = 0.0

        scored.append({
            "question": q,
            "answer": a,
            "state": _row_get(row, "state"),
            "county": _row_get(row, "county"),
            "similarity": round(hybrid, 4),
            "_emb": round(s_emb, 4),
            "_lex": round(lex, 4),
        })

    scored.sort(key=lambda x: (-x["similarity"], -x["_lex"]))

    def pick(min_score: float):
        out = []
        for x in scored:
            if x["similarity"] >= min_score:
                out.append({
                    "question": x["question"],
                    "answer": x["answer"],
                    "state": x["state"],
                    "county": x["county"],
                    "similarity": x["similarity"],
                })
            if len(out) >= limit:
                break
        return out

    results = pick(th)
    if not results and fb < th:
        results = pick(fb)

    if not results and q_tokens:
        for x in sorted(scored, key=lambda z: -z["_lex"]):
            if x["_lex"] >= 0.22:
                results.append({
                    "question": x["question"],
                    "answer": x["answer"],
                    "state": x["state"],
                    "county": x["county"],
                    "similarity": round(max(x["similarity"], x["_lex"]), 4),
                })
            if len(results) >= limit:
                break

    if not results and q_tokens:
        qc = _normalize(pre)
        for x in scored:
            qn = _normalize(x["question"] or "")
            if qc and qn and (qc in qn or qn in qc or qc == qn):
                results.append({
                    "question": x["question"],
                    "answer": x["answer"],
                    "state": x["state"],
                    "county": x["county"],
                    "similarity": 1.0,
                })
                break

    logger.info(
        "knowledge_service.hybrid_rank rows=%s pre_len=%s rewrite=%s q_tokens=%s top=%s emb_top=%s lex_top=%s",
        len(rows),
        len(pre),
        bool(rewrite),
        len(q_tokens),
        (scored[0]["similarity"] if scored else None),
        (scored[0]["_emb"] if scored else None),
        (scored[0]["_lex"] if scored else None),
    )
    return results[:limit]


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
        limit = getattr(settings, "RAG_TOP_K", 8)
    if not state:
        state = _extract_state_from_query(query)
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

    final = _hybrid_rank_rows(rows, query, state, user_language, limit)
    logger.info(
        "knowledge_service.mongo.search query_len=%s lang=%s state=%s rows=%s results=%s top_similarity=%s",
        len(query or ""),
        user_language or "unknown",
        state or "none",
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
        limit = getattr(settings, "RAG_TOP_K", 8)
    if not state:
        state = _extract_state_from_query(query)

    qs = KnowledgeBase.objects.all()
    if state:
        qs = qs.filter(Q(state__iexact=state) | Q(state__isnull=True) | Q(state=""))
    if county:
        qs = qs.filter(Q(county__iexact=county) | Q(county__isnull=True) | Q(county=""))
    rows = list(qs)

    final = _hybrid_rank_rows(rows, query, state, user_language, limit)
    logger.info(
        "knowledge_service.django.search query_len=%s lang=%s rows=%s results=%s top_similarity=%s",
        len(query or ""),
        user_language or "unknown",
        len(rows),
        len(final),
        (final[0].get("similarity") if final else None),
    )
    return final
