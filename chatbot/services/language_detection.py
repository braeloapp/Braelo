"""
Language detection: Portuguese, Spanish, English. Uses django.conf.settings.
"""
from django.conf import settings

try:
    from langdetect import detect, LangDetectException
except ImportError:
    detect = None
    LangDetectException = Exception


def detect_language(text: str) -> str:
    if not text or not text.strip():
        return "en"
    text = text.strip()[:500]
    if detect is None:
        return _fallback_detect(text)
    try:
        code = detect(text)
        if code in ("pt", "pt-br", "pt-BR"):
            return "pt"
        if code == "es":
            return "es"
        return "en"
    except LangDetectException:
        return _fallback_detect(text)


def _fallback_detect(text: str) -> str:
    t = text.lower()
    if any(w in t for w in (" como ", " para ", " não ", " mais ", " está ", " você ", " nós ", " são ", " foi ", " tem ", " por ", " com ", " que ", " uma ", " esse ", " isso ")):
        return "pt"
    if any(w in t for w in (" cómo ", " para ", " qué ", " más ", " está ", " usted ", " nosotros ", " son ", " fue ", " tiene ", " por ", " con ", " una ", " ese ", " esto ")):
        return "es"
    return "en"
