"""
Language detection: Portuguese, Spanish, English.

Detection pipeline (in priority order):
  1. Unambiguous Unicode character markers (ã, õ, ñ, ¿, ¡ …)
  2. Known word-list vote (PT / ES token counts)
  3. langdetect library with 3-run majority vote (probabilistic → majority makes it stable)
  4. Fallback keyword scan
"""
import logging
import re

logger = logging.getLogger(__name__)

try:
    from langdetect import detect, LangDetectException
    from langdetect import DetectorFactory
    DetectorFactory.seed = 42          # make langdetect deterministic across restarts
except ImportError:
    detect = None
    LangDetectException = Exception


# ---------------------------------------------------------------------------
# 1. Unambiguous character-level markers
# ---------------------------------------------------------------------------

# Characters / patterns that appear almost exclusively in Portuguese (in Roman script):
#   ã, õ (nasal vowels), ão/ões suffixes, -ção endings, ê (circumflex e common in PT)
_PT_CHAR_RE = re.compile(
    r"[ãõ]"
    r"|ção|ções"           # common PT suffixes
    r"|não\b|também"       # very common PT words
    r"|você\b|vocês",
    re.IGNORECASE | re.UNICODE,
)

# Characters that are almost exclusively Spanish:
#   ñ, inverted punctuation ¿ ¡
_ES_CHAR_RE = re.compile(
    r"[ñ]|¿|¡",
    re.IGNORECASE | re.UNICODE,
)


# ---------------------------------------------------------------------------
# 2. Word-list vote
# ---------------------------------------------------------------------------

_PT_WORDS = frozenset({
    # pronouns / verbs
    "sou", "você", "voce", "também", "tambem", "não", "nao", "está", "estou",
    "são", "sao", "foi", "tem", "temos", "tenho", "preciso", "consigo", "posso",
    # common function words unique to PT
    "para", "com", "numa", "num", "isso", "esse", "essa", "mas", "por", "que",
    "uma", "como", "onde", "quando", "imóvel", "imovel", "aluguel", "fiador",
    "recém", "recem", "crédito", "credito", "minha", "nosso", "nossa",
    # housing / immigration domain
    "arrendamento", "inquilino", "proprietário", "proprietario", "hipoteca",
    "renda", "salário", "salario", "trabalho", "emprego",
})

_ES_WORDS = frozenset({
    # pronouns / verbs
    "soy", "usted", "también", "tambien", "qué", "que", "cómo", "como",
    "está", "están", "son", "fue", "tiene", "tengo", "necesito", "puedo",
    # common function words unique to ES
    "pero", "con", "una", "ese", "esa", "esto", "eso", "mío", "mio",
    "alquiler", "arrendamiento", "inquilino", "propietario", "hipoteca",
    "sueldo", "trabajo", "empleo", "dinero",
})


def _count_hits(text: str, wordset: frozenset) -> int:
    tokens = re.findall(r"[\w'áéíóúàâãêôõüçñ]+", text.lower(), re.UNICODE)
    return sum(1 for t in tokens if t in wordset)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """Return 'en', 'es', or 'pt'."""
    if not text or not text.strip():
        return "en"
    text = text.strip()[:600]

    # 1. Unambiguous character markers — no need to go further
    if _PT_CHAR_RE.search(text):
        logger.info("language_detection.result=pt method=char_marker")
        return "pt"
    if _ES_CHAR_RE.search(text):
        logger.info("language_detection.result=es method=char_marker")
        return "es"

    # 2. Word-list vote
    pt_hits = _count_hits(text, _PT_WORDS)
    es_hits = _count_hits(text, _ES_WORDS)
    if pt_hits > 0 or es_hits > 0:
        if pt_hits > es_hits:
            logger.info("language_detection.result=pt method=word_vote pt=%s es=%s", pt_hits, es_hits)
            return "pt"
        if es_hits > pt_hits:
            logger.info("language_detection.result=es method=word_vote pt=%s es=%s", pt_hits, es_hits)
            return "es"
        # tied — fall through to langdetect

    # 3. langdetect majority vote (3 runs)
    if detect is not None:
        votes: dict[str, int] = {}
        try:
            for _ in range(3):
                raw = detect(text)
                code = "pt" if raw in ("pt", "pt-br", "pt-BR") else ("es" if raw == "es" else "en")
                votes[code] = votes.get(code, 0) + 1
            winner = max(votes, key=lambda k: votes[k])
            logger.info("language_detection.result=%s method=langdetect_vote votes=%s", winner, votes)
            return winner
        except LangDetectException:
            logger.info("language_detection.langdetect_exception")

    # 4. Simple keyword fallback
    result = _fallback_detect(text)
    logger.info("language_detection.result=%s method=fallback", result)
    return result


def _fallback_detect(text: str) -> str:
    t = " " + text.lower() + " "
    pt_kw = (
        " sou ", " você ", " voce ", " não ", " nao ", " também ", " tambem ",
        " está ", " são ", " sao ", " foi ", " tem ", " para ", " com ", " que ",
        " uma ", " isso ", " mas ", " por ", " imóvel ", " imovel ", " aluguel ",
        " preciso ", " consigo ", " fiador ", " crédito ", " credito ",
    )
    es_kw = (
        " cómo ", " qué ", " más ", " usted ", " nosotros ", " son ", " fue ",
        " tiene ", " con ", " una ", " ese ", " esto ", " alquiler ", " pero ",
        " necesito ", " puedo ",
    )
    pt_score = sum(1 for w in pt_kw if w in t)
    es_score = sum(1 for w in es_kw if w in t)
    if pt_score > 0 or es_score > 0:
        return "pt" if pt_score >= es_score else "es"
    return "en"
