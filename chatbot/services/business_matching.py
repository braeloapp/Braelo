"""
Business matching: geographic (ZIP/county/radius), sponsored first, rotation, paginated results.
Uses MongoDB when USE_MONGO is True.

Mongo: default collection is `businesses` (Lista/flat docs); legacy `business_listings` only if configured in settings.
"""
import functools
import logging
import re
import unicodedata
from django.db import transaction
from django.db.models import F, Q

logger = logging.getLogger(__name__)

def _distance_miles(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        from geopy.distance import geodesic
        return round(geodesic((float(lat1), float(lon1)), (float(lat2), float(lon2))).miles, 1)
    except Exception:
        return None


def _coords_from_braelo_doc(doc):
    coords = doc.get("business_coordinates")
    if not coords or not isinstance(coords, dict):
        return None, None
    c = coords.get("coordinates")
    if not c or len(c) < 2:
        return None, None
    try:
        return float(c[1]), float(c[0])
    except (TypeError, ValueError):
        return None, None


def _contact_info_to_text(ci) -> str:
    """Mongo rows may use string contact_info or an embedded dict (social/phone/email)."""
    if ci is None:
        return ""
    if isinstance(ci, str):
        return ci.strip()
    if isinstance(ci, dict):
        parts = []
        order = ("phone", "email", "social", "website", "web", "address", "notes")
        seen = set()
        for k in order:
            v = ci.get(k)
            if v and str(v).strip():
                parts.append(f"{k.title()}: {str(v).strip()}")
                seen.add(k)
        for k, v in ci.items():
            if k in seen or not v or not str(v).strip():
                continue
            parts.append(f"{k}: {str(v).strip()}")
        return "\n".join(parts)
    return str(ci).strip()


def _normalize_chat_language_code(lang: str | None) -> str:
    """Map detected_language / profile lang to a 2-letter code for directory matching."""
    if not lang:
        return "en"
    t = str(lang).strip().lower()
    if len(t) >= 2 and t[:2] in ("en", "es", "pt", "fr", "de", "it"):
        return t[:2]
    if "english" in t:
        return "en"
    if "spanish" in t or "español" in t or "espanol" in t:
        return "es"
    if "portug" in t:
        return "pt"
    return t[:2] if len(t) >= 2 else "en"


def _listing_allows_chat_language(listing_langs: str | None, chat_code: str) -> bool:
    """Empty or missing listing languages = multilingual / unknown; do not filter out."""
    s = (listing_langs or "").strip()
    if not s:
        return True
    code = (chat_code or "en").lower()[:2]
    parts = [p.strip().lower()[:2] for p in re.split(r"[\s,;|]+", s) if p.strip()]
    return code in parts if parts else True


def _contact_from_braelo_doc(doc):
    parts = []
    if doc.get("business_number"):
        parts.append(str(doc["business_number"]).strip())
    if doc.get("business_email"):
        parts.append(str(doc["business_email"]).strip())
    if doc.get("business_website"):
        parts.append(str(doc["business_website"]).strip())
    return "; ".join(parts) if parts else None


def _whatsapp_url_from_number(number):
    if not number:
        return ""
    digits = "".join(c for c in str(number) if c.isdigit())
    if not digits:
        return ""
    return f"https://wa.me/{digits}"


def _mongo_category_any_field(term: str) -> dict:
    """Match a single token against category or subcategory (flat or legacy field names)."""
    if not term or not str(term).strip():
        return {}
    t = re.escape(str(term).strip())
    return {
        "$or": [
            {"category": {"$regex": t, "$options": "i"}},
            {"business_category": {"$regex": t, "$options": "i"}},
            {"subcategory": {"$regex": t, "$options": "i"}},
            {"business_subcategory": {"$regex": t, "$options": "i"}},
        ],
    }


def mongo_comparison_query(structured: dict) -> dict:
    """Full Mongo filter for business comparison context snippets."""
    base = {
        "is_active": True,
        "$or": [{"is_banned": False}, {"is_banned": {"$exists": False}}],
    }
    c1 = (structured.get("category") or "").strip()
    c2 = (structured.get("subcategory") or "").strip()
    cat = _mongo_category_clause_from_labels(c1, c2)
    if cat:
        return {"$and": [base, cat]}
    return base


# When the LLM says "food" / "restaurant" but the directory uses Portuguese (e.g. Gastronomia), match any alias.
_BUSINESS_CATEGORY_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset(
        {
            "food",
            "foods",
            "restaurant",
            "restaurants",
            "dining",
            # Lista / PT directory labels (case-insensitive regex still matches mixed case in Mongo)
            "gastronomia",
            "restaurantes",
            "restaurante",
            "gastronomy",
            "cuisine",
            "culinary",
            "comida",
            "churrascaria",
            "churrascarias",
            "churrasco",
            "lanchonete",
            "lanchonetes",
            "eat",
            "eats",
            "meal",
            "meals",
            "cafe",
            "café",
            "coffee",
            "bar",
            "grill",
            "bakery",
            "bakeries",
            "doceria",
            "bolos",
        }
    ),
    frozenset(
        {
            "beauty",
            "salon",
            "salão",
            "salao",
            "hair",
            "nails",
            "esthetic",
            "estética",
            "estetica",
            "spa",
            "beleza",
            "skincare",
            "barber",
        }
    ),
    frozenset(
        {
            "health",
            "medical",
            "doctor",
            "clinic",
            "dentist",
            "dental",
            "odontologia",
            "saúde",
            "saude",
            "médico",
            "medico",
        }
    ),
    frozenset(
        {
            "legal",
            "lawyer",
            "attorney",
            "law",
            "juridico",
            "jurídico",
            "advogado",
            "abogado",
            "immigration",
            "imigração",
            "imigracao",
        }
    ),
    frozenset(
        {
            "retail",
            "shop",
            "store",
            "boutique",
            "commerce",
            "comércio",
            "comercio",
            "loja",
            "lojas",
        }
    ),
    frozenset(
        {
            "services",
            "service",
            "professional",
            "serviços",
            "servicos",
            "serviço",
            "servico",
        }
    ),
)

# Demonyms / cuisine / origin phrases in user text → tokens to match in listing name, tags, categories, etc.
_DIRECTORY_ORIGIN_TRIGGERS: tuple[tuple[re.Pattern, frozenset[str]], ...] = (
    (
        re.compile(
            r"\b(brazilian|brasileir[ao]s?|brasilian|brasilier[ao])\b",
            re.I,
        ),
        frozenset({"brazil", "brasil", "brasileir", "brasileira", "brasileño", "brasileno"}),
    ),
    (
        re.compile(r"\b(brazil|brasil)\b", re.I),
        frozenset({"brazil", "brasil", "brasileir", "brasileira"}),
    ),
    (
        re.compile(r"\b(mexican|méxic[ao]s?|mexicano|mexicana)\b", re.I),
        frozenset({"mexico", "méxico", "mexican", "mexicano", "taco", "taqueria"}),
    ),
    (
        re.compile(r"\b(italian|italiano|italiana|italy|italia)\b", re.I),
        frozenset({"italy", "italia", "italian", "italiano", "italiana"}),
    ),
    (
        re.compile(
            r"\b(chinese|china|cantonese|mandarin|sichuan|szechuan|dim\s*sum)\b",
            re.I,
        ),
        frozenset({"china", "chinese", "cantonese", "mandarin", "sichuan", "szechuan"}),
    ),
    (
        re.compile(r"\b(japanese|japan|japones|nihon|sushi(?:\s+bar)?)\b", re.I),
        frozenset({"japan", "japanese", "japones", "tokyo", "osaka", "sushi"}),
    ),
    (
        re.compile(r"\b(korean|korea)\b", re.I),
        frozenset({"korea", "korean", "seoul"}),
    ),
    (
        re.compile(r"\b(thai|thailand|tailândia|tailandia)\b", re.I),
        frozenset({"thai", "thailand"}),
    ),
    (
        re.compile(r"\b(indian|india|biryani|tandoori|masala)\b", re.I),
        frozenset({"india", "indian", "biryani", "tandoori"}),
    ),
    (
        re.compile(
            r"\b(french|france|français|francais|parisian)\b",
            re.I,
        ),
        frozenset({"france", "french", "français", "francais", "paris"}),
    ),
    (
        re.compile(r"\b(spanish|spain|español|espanhol|tapas)\b", re.I),
        frozenset({"spain", "spanish", "español", "espanhol", "tapas"}),
    ),
    (
        re.compile(
            r"\b(portuguese|portugal|português|portugues)\b",
            re.I,
        ),
        frozenset({"portugal", "portuguese", "português", "portugues", "portugu"}),
    ),
    (
        re.compile(r"\b(greek|greece|griek)\b", re.I),
        frozenset({"greece", "greek", "athens"}),
    ),
    (
        re.compile(r"\b(lebanese|lebanon|libanês|libanes)\b", re.I),
        frozenset({"lebanon", "lebanese", "libanês", "libanes"}),
    ),
    (
        re.compile(r"\b(vietnamese|vietnam|vietnamita)\b", re.I),
        frozenset({"vietnam", "vietnamese"}),
    ),
    (
        re.compile(
            r"\b(turkish|turkey|turquia|istanbul|kebab)\b",
            re.I,
        ),
        frozenset({"turkey", "turkish", "istanbul", "turquia", "kebab"}),
    ),
    (
        re.compile(
            r"\b(ethiopian|ethiopia|etíope|etiope|injera)\b",
            re.I,
        ),
        frozenset({"ethiopia", "ethiopian", "injera"}),
    ),
    (
        re.compile(
            r"\b(colombian|colombia|colômbia|colombia)\b",
            re.I,
        ),
        frozenset({"colombia", "colombian", "colômbia"}),
    ),
    (
        re.compile(r"\b(peruvian|peru)\b", re.I),
        frozenset({"peru", "peruvian", "cusco", "lima"}),
    ),
    (
        re.compile(r"\b(cuban|cuba)\b", re.I),
        frozenset({"cuba", "cuban", "habana", "havana"}),
    ),
    (
        re.compile(r"\b(argentin|argentino|argentinian|argentina)\b", re.I),
        frozenset({"argentina", "argentinian", "argentino", "buenos"}),
    ),
    (
        re.compile(r"\b(polish|poland|polska|polónia|polonia)\b", re.I),
        frozenset({"poland", "polish", "polska"}),
    ),
    (
        re.compile(r"\b(german|germany|deutsch|alemanha|alemania)\b", re.I),
        frozenset({"germany", "german", "deutsch", "berlin"}),
    ),
    (
        re.compile(r"\b(halal)\b", re.I),
        frozenset({"halal"}),
    ),
    (
        re.compile(r"\b(kosher)\b", re.I),
        frozenset({"kosher"}),
    ),
)

# Fields where cuisine / origin tokens from the user message are matched (CSV + legacy shapes).
_MONGO_DIRECTORY_TEXT_FIELDS = (
    "name",
    "business_name",
    "tags",
    "category",
    "business_category",
    "subcategory",
    "business_subcategory",
    "description",
)


def extract_directory_attribute_terms(message: str | None) -> list[str]:
    """
    Split cues like “Brazilian restaurant” or “sushi in Florida” into tokens for Mongo $regex
    on listing name, tags, and category fields. Empty if no origin/cuisine phrase detected
    (then callers show full category+location results without text narrowing).
    """
    if not message or not str(message).strip():
        return []
    found: set[str] = set()
    try:
        from chatbot.services.business_search_service import extract_listing_name_filter_terms

        found.update(extract_listing_name_filter_terms(message))
    except Exception:
        logger.exception("business_matching.extract_listing_name_filter_terms_failed")
    for pat, tokens_if_match in _DIRECTORY_ORIGIN_TRIGGERS:
        if pat.search(message):
            for t in tokens_if_match:
                s = str(t).strip()
                if len(s) >= 2:
                    found.add(s)
    if not found:
        return []
    return sorted(found, key=len, reverse=True)[:20]


def _mongo_extra_attribute_clause(terms: list[str] | None) -> dict | None:
    """Require at least one token match on searchable text fields (AND with category clause)."""
    if not terms:
        return None
    clean = sorted({str(t).strip() for t in terms if str(t).strip()}, key=len, reverse=True)
    if not clean:
        return None
    return _mongo_regex_or_on_business_fields(clean[:20], _MONGO_DIRECTORY_TEXT_FIELDS)


def _search_terms_for_directory_label(label: str) -> list[str]:
    """Expand a user/LLM category or subcategory label to all directory aliases in the same bucket."""
    raw = (label or "").strip()
    if not raw:
        return []
    lab = raw.lower()
    for group in _BUSINESS_CATEGORY_ALIAS_GROUPS:
        if lab in group:
            return sorted(group)
    return [raw]


def _mongo_regex_or_on_business_fields(terms: list[str], field_names: tuple[str, ...]) -> dict | None:
    if not terms:
        return None
    uniq = sorted({str(t).strip() for t in terms if str(t).strip()}, key=len, reverse=True)
    alt = "|".join(re.escape(t) for t in uniq)
    if not alt:
        return None
    return {
        "$or": [
            {fn: {"$regex": alt, "$options": "i"}}
            for fn in field_names
        ]
    }


def _mongo_category_filter(category: str, subcategory: str) -> dict:
    parts = []
    TEXT_FIELDS = ("category", "business_category", "subcategory", "business_subcategory", "tags")
    if category and str(category).strip():
        cterms = _search_terms_for_directory_label(str(category).strip())
        block = _mongo_regex_or_on_business_fields(cterms, TEXT_FIELDS)
        if block:
            parts.append(block)
    if subcategory and str(subcategory).strip():
        sterms = _search_terms_for_directory_label(str(subcategory).strip())
        block = _mongo_regex_or_on_business_fields(sterms, TEXT_FIELDS)
        if block:
            parts.append(block)
    if not parts:
        return {}
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


def _mongo_category_clause_from_labels(category: str, subcategory: str) -> dict:
    """
    Prefer Lista PT + seed EN in one $or (business_search_service), then fall back to
    legacy $and expansion. Fixes mixed-schema collections where AND across PT/EN misses one shape.
    """
    c = (category or "").strip()
    s = (subcategory or "").strip()
    synthetic = f"{c} {s}".strip()
    try:
        from chatbot.services.business_search_service import (
            _dual_schema_category_or,
            convert_query_to_portuguese_fields,
        )

        if synthetic:
            p = convert_query_to_portuguese_fields(synthetic)
            dual = _dual_schema_category_or(
                p.get("category_pt"),
                p.get("subcategory_pt"),
                p.get("category_en"),
                p.get("subcategory_en"),
            )
            if dual:
                return dual
    except Exception:
        logger.exception("business_matching.mongo_dual_schema_failed")

    if c and s:
        return _mongo_category_filter(c, s)
    if c or s:
        return _mongo_category_any_field(c or s)
    return {}


def _mongo_row_eligible(doc: dict) -> bool:
    if doc.get("is_banned"):
        return False
    cap = doc.get("impression_cap")
    if cap is not None:
        try:
            if int(doc.get("impressions_used") or 0) >= int(cap):
                return False
        except (TypeError, ValueError):
            pass
    return True


def _fetch_mongo_business_docs_broad_location(
    db,
    collection_names: list,
    state: str | None,
    city: str | None,
    county: str | None,
    zip_code: str | None,
    *,
    max_docs: int = 600,
) -> list:
    """
    Category-agnostic fetch: active businesses constrained by region fields only.
    Cursor limit caps load when the directory is large.
    """
    base = {
        "is_active": True,
        "$or": [{"is_banned": False}, {"is_banned": {"$exists": False}}],
    }
    and_parts: list = [base]
    st = (state or "").strip()
    ct = (city or "").strip()
    cy = (county or "").strip()
    uz = _zip5(zip_code)
    if st:
        and_parts.append({
            "$or": [
                {"state": {"$regex": re.escape(st), "$options": "i"}},
                {"business_state": {"$regex": re.escape(st), "$options": "i"}},
            ]
        })
    if ct:
        and_parts.append({
            "$or": [
                {"city": {"$regex": re.escape(ct), "$options": "i"}},
                {"business_city": {"$regex": re.escape(ct), "$options": "i"}},
            ]
        })
    if cy:
        and_parts.append({
            "$or": [
                {"county": {"$regex": re.escape(cy), "$options": "i"}},
                {"business_county": {"$regex": re.escape(cy), "$options": "i"}},
            ]
        })
    if uz:
        and_parts.append({
            "$or": [
                {"zip_code": {"$regex": "^" + re.escape(uz)}},
                {"business_zip": {"$regex": "^" + re.escape(uz)}},
            ]
        })
    query = {"$and": and_parts} if len(and_parts) > 1 else and_parts[0]
    seen: set[str] = set()
    out: list = []
    cap = max(50, min(int(max_docs or 600), 2000))
    for coll_name in collection_names:
        try:
            for doc in db[coll_name].find(query).limit(cap):
                sid = str(doc.get("_id"))
                if sid in seen:
                    continue
                seen.add(sid)
                if not _mongo_row_eligible(doc):
                    continue
                out.append(doc)
        except Exception:
            logger.exception("business_matching.mongo.broad_collection_failed name=%s", coll_name)
    logger.info(
        "business_matching.mongo.broad_location state=%s city=%s n=%s cap=%s",
        st or None,
        ct or None,
        len(out),
        cap,
    )
    return out


def _fetch_mongo_business_docs(
    db,
    collection_names: list,
    category: str,
    subcategory: str,
    extra_match_terms: list[str] | None = None,
) -> list:
    base = {
        "is_active": True,
        "$or": [{"is_banned": False}, {"is_banned": {"$exists": False}}],
    }
    cat_q = _mongo_category_clause_from_labels(category or "", subcategory or "")
    attr_q = _mongo_extra_attribute_clause(extra_match_terms)
    parts = [base]
    if cat_q:
        parts.append(cat_q)
    if attr_q:
        parts.append(attr_q)
    query = {"$and": parts} if len(parts) > 1 else parts[0]
    seen = set()
    out = []
    for coll_name in collection_names:
        try:
            for doc in db[coll_name].find(query):
                sid = str(doc.get("_id"))
                if sid in seen:
                    continue
                seen.add(sid)
                if not _mongo_row_eligible(doc):
                    continue
                out.append(doc)
        except Exception:
            logger.exception("business_matching.mongo.collection_failed name=%s", coll_name)
    return out


def _normalize_mongo_business(doc: dict) -> dict:
    name = doc.get("name") or doc.get("business_name") or ""
    category = doc.get("category") or doc.get("business_category") or ""
    subcategory = doc.get("subcategory") or doc.get("business_subcategory") or ""
    st = doc.get("state")
    ct = doc.get("city")
    cy = doc.get("county")
    z = doc.get("zip_code")
    lat, lon = None, None
    if doc.get("latitude") is not None and doc.get("longitude") is not None:
        try:
            lat, lon = float(doc["latitude"]), float(doc["longitude"])
        except (TypeError, ValueError):
            lat, lon = _coords_from_braelo_doc(doc)
    else:
        lat, lon = _coords_from_braelo_doc(doc)
    legacy_contact = _contact_from_braelo_doc(doc)
    raw_ci = doc.get("contact_info")
    contact = _contact_info_to_text(raw_ci) or (legacy_contact or "") or ""
    wa_raw = doc.get("whatsapp_url")
    if isinstance(wa_raw, str):
        wa = wa_raw.strip()
    elif wa_raw is not None:
        wa = str(wa_raw).strip()
    else:
        wa = ""
    if not wa and doc.get("business_number"):
        wa = _whatsapp_url_from_number(doc.get("business_number"))
    langs = doc.get("languages")
    if isinstance(langs, list):
        langs_out = ",".join(str(x) for x in langs)
    else:
        langs_out = langs if langs else None
    cap = doc.get("impression_cap")
    if cap is None:
        cap = 10**9
    used = int(doc.get("impressions_used") or 0)
    rot = int(doc.get("rotation_index") or 0)
    remaining = max(0, int(cap) - used)
    sponsored = bool(doc.get("ad_package_name"))
    return {
        "doc": doc,
        "name": name,
        "category": category,
        "subcategory": subcategory,
        "state": st,
        "city": ct,
        "county": cy,
        "zip_code": z,
        "lat": lat,
        "lon": lon,
        "contact": contact,
        "whatsapp_url": wa,
        "languages": langs_out,
        "rotation_index": rot,
        "impressions_used": used,
        "remaining": remaining,
        "is_sponsored": sponsored,
    }


def _nz_loc(v) -> str:
    if v is None:
        return ""
    return str(v).strip().lower()


def _fold_location_key(s: str | None) -> str:
    """
    Accent-insensitive, case-insensitive geographic key (matches Lista PT uppercase labels vs EN names).
    e.g. California, CALIFÓRNIA, califórnia → same key.
    """
    if s is None:
        return ""
    t = str(s).strip()
    if not t:
        return ""
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def _canonical_us_state_label(raw: str | None) -> str:
    """Map PT/EN/spelling variants to the same English canonical name as Lista CSV import."""
    if not raw or not str(raw).strip():
        return ""
    t = str(raw).strip()
    try:
        from chatbot.management.commands.import_lista_business_csv import normalize_us_state

        return (normalize_us_state(t) or t).strip()
    except Exception:
        logger.exception("business_matching.canonical_us_state_failed raw=%s", t[:80])
        return t


def _mongo_state_matches(user_state: str | None, listing_state: str | None) -> bool:
    u = (user_state or "").strip()
    l = (listing_state or "").strip()
    if not u or not l:
        return False
    return _fold_location_key(_canonical_us_state_label(u)) == _fold_location_key(
        _canonical_us_state_label(l)
    )


def _mongo_locale_text_matches(user_text: str | None, listing_text: str | None) -> bool:
    """City/county: fold equality or contained-in (handles minor formatting differences)."""
    u = (user_text or "").strip()
    l = (listing_text or "").strip()
    if not u:
        return True
    if not l:
        return False
    fu, fl = _fold_location_key(u), _fold_location_key(l)
    if fu == fl:
        return True
    if len(fu) >= 3 and fu in fl:
        return True
    if len(fl) >= 3 and fl in fu:
        return True
    return False


def _zip5(z) -> str:
    if z is None:
        return ""
    d = re.sub(r"\D", "", str(z))
    return d[:5] if d else ""


def _norm_row_matches_user_location(n: dict, state: str, city: str, county: str, zip_code: str) -> bool:
    """Every non-empty user location field must match the listing (strict)."""
    uz = _zip5(zip_code)
    if uz:
        bz = _zip5(n.get("zip_code"))
        # Many directory rows have no ZIP; do not reject them when the user has a profile ZIP.
        if bz and uz != bz:
            return False
    if state and not _mongo_state_matches(state, n.get("state")):
        return False
    if county and not _mongo_locale_text_matches(county, n.get("county")):
        return False
    if city and not (
        _mongo_locale_text_matches(city, n.get("city"))
        or _mongo_locale_text_matches(city, n.get("county"))
    ):
        return False
    return True


def _mongo_apply_strict_location(
    norms: list,
    state: str,
    city: str,
    county: str,
    zip_code: str,
    user_lat,
    user_lon,
    radius_miles: float,
) -> list:
    """Strict: match provided address fields; if GPS + listing coords, also require distance <= radius."""
    out = []
    for n in norms:
        if not _norm_row_matches_user_location(n, state, city, county, zip_code):
            continue
        if user_lat is not None and user_lon is not None and n["lat"] is not None and n["lon"] is not None:
            d = _distance_miles(user_lat, user_lon, n["lat"], n["lon"])
            if d is None or d > radius_miles:
                continue
        out.append(n)
    return out


def _prefilter_mongo_by_region(
    norms: list,
    state: str,
    county: str,
    zip_code: str,
    user_lat,
    user_lon,
) -> tuple:
    """When GPS is unavailable, narrow candidates by ZIP → county+state → state."""
    if user_lat is not None and user_lon is not None:
        return norms, None, False
    zraw = _nz_loc(zip_code)
    z = zraw.split("-")[0] if zraw else ""
    has_state = bool((state or "").strip())
    has_county = bool((county or "").strip())

    tried_tight = False
    if z:
        tier = [n for n in norms if _nz_loc(n["zip_code"]).startswith(z) or _nz_loc(n["zip_code"]) == zraw]
        tried_tight = True
        if tier:
            return tier, None, False
    if has_state and has_county:
        tier = [
            n
            for n in norms
            if _mongo_state_matches(state, n.get("state"))
            and _mongo_locale_text_matches(county, n.get("county"))
        ]
        tried_tight = True
        if tier:
            return tier, None, False
    if has_state:
        tier = [n for n in norms if _mongo_state_matches(state, n.get("state"))]
        tried_tight = True
        if tier:
            return tier, None, False
    note = None
    if tried_tight and norms:
        note = "No exact matches in your area. Here are the closest available options."
    return norms, note, tried_tight


def _ad_package_priority_map(db) -> dict:
    out = {}
    try:
        for p in db.ad_packages.find():
            n = p.get("name")
            if n:
                out[str(n)] = int(p.get("priority") or 0)
    except Exception:
        logger.exception("business_matching.mongo.ad_packages_read_failed")
    return out


def _get_top_businesses_mongo(
    category: str = None,
    subcategory: str = None,
    state: str = None,
    city: str = None,
    county: str = None,
    zip_code: str = None,
    user_lat=None,
    user_lon=None,
    language: str = None,
    limit: int = None,
    offset: int = 0,
    external_id: str = None,
    session_id: str = None,
    strict_location: bool = False,
    sort_mode: str = "default",
    extra_match_terms: list[str] | None = None,
    *,
    broad_location_only: bool = False,
) -> dict:
    from django.conf import settings

    if limit is None:
        limit = getattr(settings, "MAX_BUSINESS_RESULTS", 20)
    off = max(0, int(offset or 0))
    radius_miles = getattr(settings, "BUSINESS_RADIUS_MILES", 25)
    radius_fallback = getattr(settings, "BUSINESS_RADIUS_FALLBACK_MILES", 50)
    collection_names = getattr(settings, "MONGO_BUSINESS_COLLECTIONS", None) or ["businesses"]
    if isinstance(collection_names, str):
        collection_names = [x.strip() for x in collection_names.split(",") if x.strip()]

    try:
        from chatbot.geo_constants import backfill_state_from_major_us_city
        from chatbot.services.business_search_service import normalize_state_for_db

        st_bf = backfill_state_from_major_us_city(state, city)
        if st_bf:
            state = normalize_state_for_db(st_bf) or st_bf
        elif state:
            state = normalize_state_for_db(state) or state
    except Exception:
        logger.exception("business_matching.mongo.state_backfill_failed")

    try:
        from chatbot.mongo_db import get_db
        db = get_db()
        if broad_location_only:
            all_rows = _fetch_mongo_business_docs_broad_location(
                db,
                collection_names,
                state,
                city,
                county,
                zip_code,
            )
            if extra_match_terms:
                terms_l = [str(t).lower() for t in extra_match_terms if t]
                filtered = []
                for doc in all_rows:
                    hay = " ".join(
                        filter(
                            None,
                            [
                                doc.get("name"),
                                doc.get("business_name"),
                                doc.get("category"),
                                doc.get("business_category"),
                                doc.get("subcategory"),
                                doc.get("business_subcategory"),
                                doc.get("tags"),
                            ],
                        )
                    ).lower()
                    if any(t in hay for t in terms_l):
                        filtered.append(doc)
                if filtered:
                    all_rows = filtered
        else:
            all_rows = _fetch_mongo_business_docs(
                db,
                collection_names,
                category,
                subcategory,
                extra_match_terms=extra_match_terms,
            )
    except Exception:
        logger.exception("business_matching.mongo.query_failed")
        return {"businesses": [], "see_more": False, "location_note": None}

    norms = []
    for b in all_rows:
        try:
            norms.append(_normalize_mongo_business(b))
        except Exception:
            logger.exception("business_matching.mongo.skip_bad_doc id=%s", b.get("_id"))
    if language and str(language).strip():
        lang_code = _normalize_chat_language_code(language)
        norms = [
            n for n in norms
            if _listing_allows_chat_language(n.get("languages"), lang_code)
        ]

    region_note = None
    if strict_location:
        norms = _mongo_apply_strict_location(
            norms, state, city, county, zip_code, user_lat, user_lon, radius_miles
        )
    else:
        norms, region_note, _ = _prefilter_mongo_by_region(norms, state, county, zip_code, user_lat, user_lon)

    pkg_prio = _ad_package_priority_map(db)

    def sort_key_default(n):
        pkg_p = pkg_prio.get(str(n["doc"].get("ad_package_name") or ""), 0)
        dist = None
        if user_lat is not None and user_lon is not None and n["lat"] is not None and n["lon"] is not None:
            dist = _distance_miles(user_lat, user_lon, n["lat"], n["lon"])
        dist_val = dist if dist is not None else 9999
        sponsored = bool(pkg_p > 0 or n["is_sponsored"])
        return (-pkg_p, -int(sponsored), dist_val, n["rotation_index"], -n["remaining"])

    def sort_key_fairness(n):
        dist = None
        if user_lat is not None and user_lon is not None and n["lat"] is not None and n["lon"] is not None:
            dist = _distance_miles(user_lat, user_lon, n["lat"], n["lon"])
        dist_val = dist if dist is not None else 0.0
        return (n["rotation_index"], n.get("impressions_used") or 0, dist_val)

    if sort_mode == "fairness":
        norms.sort(key=sort_key_fairness)
    else:
        norms.sort(key=sort_key_default)

    within_primary = []
    within_fallback = []
    for n in norms:
        dist = None
        if user_lat is not None and user_lon is not None and n["lat"] is not None and n["lon"] is not None:
            dist = _distance_miles(user_lat, user_lon, n["lat"], n["lon"])
        raw = n["doc"]
        if strict_location:
            within_primary.append((raw, dist))
            continue
        if dist is not None:
            if dist <= radius_miles:
                within_primary.append((raw, dist))
            elif dist <= radius_fallback:
                within_fallback.append((raw, dist))
        else:
            within_primary.append((raw, None))

    if strict_location:
        ordered = list(within_primary)
    elif within_primary or within_fallback:
        ordered = within_primary + within_fallback
    else:
        ordered = [(n["doc"], None) for n in norms]

    if strict_location:
        location_note = None
    elif within_primary:
        location_note = region_note
    else:
        location_note = region_note or "No exact matches in your area. Here are the closest available options."

    selected_pairs = ordered[off : off + limit]
    see_more = off + len(selected_pairs) < len(ordered)

    out_list = []
    for b, dist in selected_pairs:
        n = _normalize_mongo_business(b)
        bid = str(b.get("_id"))
        contact_line = n["contact"]
        if n["whatsapp_url"] and n["whatsapp_url"] not in contact_line:
            contact_line = f"{contact_line}  {n['whatsapp_url']}".strip()
        out_list.append({
            "id": bid,
            "name": n["name"],
            "category": n["category"],
            "subcategory": n["subcategory"],
            "state": n["state"],
            "city": n["city"],
            "county": n["county"],
            "zip_code": n.get("zip_code"),
            "languages": n["languages"],
            "contact_info": n["contact"] or None,
            "whatsapp_url": n["whatsapp_url"] or "",
            "distance_miles": dist,
            "is_sponsored": bool(n["is_sponsored"] or pkg_prio.get(str(b.get("ad_package_name") or ""), 0) > 0),
        })
        try:
            db.impressions_log.insert_one({
                "business_id": bid,
                "external_id": external_id,
                "session_id": session_id,
                "created_at": __import__("datetime").datetime.utcnow(),
            })
        except Exception:
            logger.exception("business_matching.mongo.impression_log_failed business_id=%s", bid)

    logger.info(
        "business_matching.mongo.result category=%s subcategory=%s attr_terms=%s results=%s see_more=%s broad=%s",
        category,
        subcategory,
        len(extra_match_terms or []),
        len(out_list),
        see_more,
        broad_location_only,
    )
    return {"businesses": out_list, "see_more": see_more, "location_note": location_note}


def get_top_businesses(
    category: str = None,
    subcategory: str = None,
    state: str = None,
    city: str = None,
    county: str = None,
    zip_code: str = None,
    user_lat=None,
    user_lon=None,
    language: str = None,
    limit: int = None,
    offset: int = 0,
    external_id: str = None,
    session_id: str = None,
    strict_location: bool = False,
    sort_mode: str = "default",
    extra_match_terms: list[str] | None = None,
    *,
    broad_location_only: bool = False,
) -> dict:
    from django.conf import settings
    if not broad_location_only and not (str(category or "").strip() or str(subcategory or "").strip()):
        logger.info("business_matching.skip empty category+subcategory")
        return {"businesses": [], "see_more": False, "location_note": None}
    if broad_location_only and not getattr(settings, "USE_MONGO", False):
        logger.info("business_matching.skip broad_location_only requires USE_MONGO")
        return {"businesses": [], "see_more": False, "location_note": None}
    if getattr(settings, "USE_MONGO", False):
        return _get_top_businesses_mongo(
            category=category,
            subcategory=subcategory,
            state=state,
            city=city,
            county=county,
            zip_code=zip_code,
            user_lat=user_lat,
            user_lon=user_lon,
            language=language,
            limit=limit,
            offset=offset,
            external_id=external_id,
            session_id=session_id,
            strict_location=strict_location,
            sort_mode=sort_mode,
            extra_match_terms=extra_match_terms,
            broad_location_only=broad_location_only,
        )

    from chatbot.models import Business, AdPackage, ImpressionsLog

    if limit is None:
        limit = getattr(settings, "MAX_BUSINESS_RESULTS", 20)
    off = max(0, int(offset or 0))
    radius_miles = getattr(settings, "BUSINESS_RADIUS_MILES", 25)
    radius_fallback = getattr(settings, "BUSINESS_RADIUS_FALLBACK_MILES", 50)
    min_results = getattr(settings, "MIN_BUSINESS_RESULTS", 3)

    def _django_matches_strict(b) -> bool:
        if not strict_location:
            return True
        uz = _zip5(zip_code)
        if uz:
            bz = _zip5(getattr(b, "zip_code", None))
            if bz and uz != bz:
                return False
        if state and _nz_loc(state) != _nz_loc(getattr(b, "state", None)):
            return False
        if county and _nz_loc(county) != _nz_loc(getattr(b, "county", None)):
            return False
        if city and _nz_loc(city) != _nz_loc(getattr(b, "city", None)):
            return False
        if user_lat is not None and user_lon is not None and b.latitude is not None and b.longitude is not None:
            d = _distance_miles(user_lat, user_lon, b.latitude, b.longitude)
            if d is None or d > radius_miles:
                return False
        return True

    try:
        qs = Business.objects.filter(
            is_active=True,
            is_banned=False,
        ).filter(impressions_used__lt=F("impression_cap"))
        if category:
            cq = Q()
            for t in _search_terms_for_directory_label(category):
                cq |= (
                    Q(category__icontains=t)
                    | Q(subcategory__icontains=t)
                    | Q(tags__icontains=t)
                )
            qs = qs.filter(cq)
        if subcategory:
            sq = Q()
            for t in _search_terms_for_directory_label(subcategory):
                sq |= (
                    Q(category__icontains=t)
                    | Q(subcategory__icontains=t)
                    | Q(tags__icontains=t)
                )
            qs = qs.filter(sq)
        if state and not strict_location:
            qs = qs.filter(state__icontains=state)
        if city and not strict_location:
            qs = qs.filter(city__icontains=city)
        if county and not strict_location:
            qs = qs.filter(county__icontains=county)
        if zip_code and not strict_location:
            qs = qs.filter(zip_code=zip_code)
        if language:
            code = _normalize_chat_language_code(language)
            qs = qs.filter(
                Q(languages__isnull=True)
                | Q(languages="")
                | Q(languages__icontains=code)
            )

        all_rows = [b for b in list(qs) if _django_matches_strict(b)]

        def priority_and_distance(b):
            pkg_priority = 0
            if b.ad_package_id:
                try:
                    pkg = AdPackage.objects.get(pk=b.ad_package_id)
                    pkg_priority = pkg.priority or 0
                except AdPackage.DoesNotExist:
                    pass
            dist = None
            if user_lat is not None and user_lon is not None and b.latitude is not None and b.longitude is not None:
                dist = _distance_miles(user_lat, user_lon, b.latitude, b.longitude)
            remaining = (b.impression_cap or 0) - (b.impressions_used or 0)
            return (pkg_priority, dist, b.rotation_index or 0, -remaining)

        def sort_key_default(b):
            pkg_priority, dist, rot, rem = priority_and_distance(b)
            dist_val = dist if dist is not None else 9999
            return (-pkg_priority, dist_val, rot, rem)

        def sort_key_fairness(b):
            dist = None
            if user_lat is not None and user_lon is not None and b.latitude is not None and b.longitude is not None:
                dist = _distance_miles(user_lat, user_lon, b.latitude, b.longitude)
            dist_val = dist if dist is not None else 0.0
            return (b.rotation_index or 0, b.impressions_used or 0, dist_val)

        if sort_mode == "fairness":
            all_rows.sort(key=sort_key_fairness)
        else:
            all_rows.sort(key=sort_key_default)

        within_primary = []
        within_fallback = []
        for b in all_rows:
            dist = None
            if user_lat is not None and user_lon is not None and b.latitude is not None and b.longitude is not None:
                dist = _distance_miles(user_lat, user_lon, b.latitude, b.longitude)
            if strict_location:
                within_primary.append((b, dist))
                continue
            if dist is not None:
                if dist <= radius_miles:
                    within_primary.append((b, dist))
                elif dist <= radius_fallback:
                    within_fallback.append((b, dist))
            else:
                within_primary.append((b, None))

        if strict_location:
            ordered = list(within_primary)
        elif within_primary or within_fallback:
            ordered = within_primary + within_fallback
        else:
            ordered = [(b, None) for b in all_rows]

        if strict_location:
            location_note = None
        elif within_primary:
            location_note = None
        else:
            location_note = "No exact matches in your area. Here are the closest available options."

        selected_pairs = ordered[off : off + limit]
        see_more = off + len(selected_pairs) < len(ordered)

        out_list = []
        with transaction.atomic():
            for b, dist in selected_pairs:
                out_list.append({
                    "id": b.id,
                    "name": b.name,
                    "category": b.category,
                    "subcategory": b.subcategory,
                    "state": b.state,
                    "city": b.city,
                    "county": getattr(b, "county", None),
                    "zip_code": getattr(b, "zip_code", None),
                    "languages": b.languages,
                    "contact_info": b.contact_info,
                    "whatsapp_url": getattr(b, "whatsapp_url", None) or "",
                    "distance_miles": dist,
                    "is_sponsored": bool(b.ad_package_id),
                })
                b.impressions_used = (b.impressions_used or 0) + 1
                b.save(update_fields=["impressions_used"])
                ImpressionsLog.objects.create(
                    business=b,
                    external_id=external_id,
                    session_id=session_id,
                )

        return {
            "businesses": out_list,
            "see_more": see_more,
            "location_note": location_note,
        }
    except Exception:
        logger.exception("business_matching.django.query_failed")
        return {"businesses": [], "see_more": False, "location_note": None}


@functools.lru_cache(maxsize=1)
def _business_alias_token_lower_set() -> frozenset[str]:
    s = set()
    for g in _BUSINESS_CATEGORY_ALIAS_GROUPS:
        for t in g:
            s.add(str(t).lower())
    return frozenset(s)


_MONGO_DISCOVERY_GENERIC_HINTS = frozenset(
    {"local businesses", "businesses", "business", "local business", "establishment", "establishments"}
)


def _is_generic_local_business_listing_message(message: str) -> bool:
    """True when user asks for broad local listings without a specific vertical (lawyer, food, etc.)."""
    m = (message or "").lower()
    needles = (
        "local business",
        "local businesses",
        "location business",
        "location businesses",
        "businesses in",
        "business in",
        "providers in",
        "services in",
        "companies in",
        "establishments in",
        "list of business",
        "any business",
        "some business",
    )
    return any(n in m for n in needles)


def _mongo_pick_category_from_discovery_terms(terms: list[str]) -> str | None:
    """First discovery term that clearly names a directory category alias (food, salon, etc.)."""
    alias = _business_alias_token_lower_set()
    for t in terms:
        raw = str(t).strip()
        if len(raw) < 3:
            continue
        tl = raw.lower()
        if tl in alias:
            return raw
        for a in alias:
            if len(a) >= 4 and (tl in a or a in tl):
                return raw
    return None


def _mongo_resolve_discovery_category_labels(
    message: str,
    category: str | None,
    subcategory: str | None,
    category_hint: str | None,
) -> tuple[str | None, str | None]:
    inferred_c, inferred_s = None, None
    try:
        from chatbot.chat_flow import _infer_service_category_from_text

        inferred_c, inferred_s = _infer_service_category_from_text(message or "")
    except Exception:
        logger.debug("business_matching.discovery_category_inference_skip", exc_info=True)

    c = (category or "").strip() or None
    s = (subcategory or "").strip() or None
    # Same as chat_flow Tier 1b: user-text regex beats LLM labels so Lista PT categories match.
    if inferred_c or inferred_s:
        return (inferred_c or c), (inferred_s or s)
    if c or s:
        return c, s
    hint = (category_hint or "").strip()
    if (
        hint
        and hint.lower() not in _MONGO_DISCOVERY_GENERIC_HINTS
        and len(hint) <= 120
    ):
        return hint, None
    terms = _discovery_search_terms(message, category, subcategory, category_hint)
    picked = _mongo_pick_category_from_discovery_terms(terms)
    if picked:
        return picked, None
    return None, None


_DISCOVERY_STOPWORDS = frozenset(
    """
    what when where which while with from that this there these those they them then than
    your you are was were will with have has had how help here near find some local business
    businesses business please tell give show list recommend best good any can could would
    should need want looking search looking for about into over more most much very just only
    also like such make made many other another each every both few
    """.split()
)


def _discovery_search_terms(
    message: str,
    category: str | None,
    subcategory: str | None,
    category_hint: str | None,
) -> list[str]:
    terms: list[str] = []
    for x in (category, subcategory, category_hint):
        if x and len(str(x).strip()) >= 3:
            terms.append(str(x).strip())
    msg_l = (message or "").lower()
    for w in re.findall(r"[a-zA-Záéíóúãõç]{4,}", msg_l):
        wl = w.lower()
        if wl not in _DISCOVERY_STOPWORDS:
            terms.append(w)
    if "brazil" in msg_l or "brazilian" in msg_l or "brasileir" in msg_l:
        for extra in ("brasil", "brazilian", "brazil", "brasileira"):
            if extra not in msg_l:
                terms.append(extra)
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        tl = t.lower()[:80]
        if len(tl) < 3 or tl in seen:
            continue
        seen.add(tl)
        out.append(t[:80])
    return out[:14]


def _django_discovery_location_candidates(
    state: str | None,
    city: str | None,
    county: str | None,
    zip_code: str | None,
) -> list:
    """
    Tiered geographic filter (Lista CSV often has no ZIP — fall back to state/city).
    """
    from chatbot.models import Business

    base = (
        Business.objects.filter(is_active=True, is_banned=False)
        .filter(impressions_used__lt=F("impression_cap"))
    )
    uz = _zip5(zip_code)
    st = (state or "").strip()
    ct = (city or "").strip()
    cy = (county or "").strip()

    def _as_list(qs):
        return list(qs)

    if uz:
        qz = base.filter(
            Q(zip_code__startswith=uz)
            | Q(zip_code__istartswith=uz)
        )
        if qz.exists():
            return _as_list(qz)
    if st and ct:
        q = base.filter(state__icontains=st, city__icontains=ct)
        if q.exists():
            return _as_list(q)
    if st and cy:
        q = base.filter(state__icontains=st, county__icontains=cy)
        if q.exists():
            return _as_list(q)
    if st:
        q = base.filter(state__icontains=st)
        if q.exists():
            return _as_list(q)
    if ct:
        q = base.filter(city__icontains=ct)
        if q.exists():
            return _as_list(q)
    if cy:
        q = base.filter(county__icontains=cy)
        if q.exists():
            return _as_list(q)
    return []


def _django_discovery_sort_key(b, city: str | None, county: str | None):
    score = 0
    if city and _nz_loc(b.city) == _nz_loc(city):
        score += 4
    elif city and _nz_loc(city) and _nz_loc(city) in _nz_loc(b.city):
        score += 2
    if county and _nz_loc(b.county) == _nz_loc(county):
        score += 1
    dist = 9999.0
    return (-score, dist, b.rotation_index or 0, b.impressions_used or 0)


def search_business_directory_for_discovery(
    message: str,
    category: str | None = None,
    subcategory: str | None = None,
    category_hint: str | None = None,
    state: str | None = None,
    city: str | None = None,
    county: str | None = None,
    zip_code: str | None = None,
    user_lat=None,
    user_lon=None,
    language: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    external_id: str | None = None,
    session_id: str | None = None,
) -> dict:
    """
    Directory-first discovery before Google Places / LLM location flow.

    - When USE_MONGO is False: Django Business table (broad text + location).
    - When USE_MONGO is True: same entry shape via get_top_businesses → Mongo businesses.
    """
    from django.conf import settings

    has_text_loc = bool(
        _zip5(zip_code)
        or (state or "").strip()
        or (city or "").strip()
        or (county or "").strip()
    )
    has_gps = user_lat is not None and user_lon is not None
    if getattr(settings, "USE_MONGO", False):
        if not has_text_loc and not has_gps:
            return {"businesses": [], "see_more": False, "location_note": None}
        if limit is None:
            limit = int(getattr(settings, "MAX_BUSINESS_RESULTS", 20))
        cat, sub = _mongo_resolve_discovery_category_labels(
            message, category, subcategory, category_hint
        )
        attr_terms = extract_directory_attribute_terms(message)
        if not cat and not sub:
            if _is_generic_local_business_listing_message(message or ""):
                return get_top_businesses(
                    category=None,
                    subcategory=None,
                    state=state,
                    city=city,
                    county=county,
                    zip_code=zip_code,
                    user_lat=user_lat,
                    user_lon=user_lon,
                    language=language,
                    limit=limit,
                    offset=offset,
                    external_id=external_id,
                    session_id=session_id,
                    strict_location=False,
                    sort_mode="default",
                    extra_match_terms=attr_terms or None,
                    broad_location_only=True,
                )
            return {"businesses": [], "see_more": False, "location_note": None}
        return get_top_businesses(
            category=cat,
            subcategory=sub,
            state=state,
            city=city,
            county=county,
            zip_code=zip_code,
            user_lat=user_lat,
            user_lon=user_lon,
            language=language,
            limit=limit,
            offset=offset,
            external_id=external_id,
            session_id=session_id,
            strict_location=False,
            sort_mode="default",
            extra_match_terms=attr_terms or None,
        )

    if not has_text_loc:
        return {"businesses": [], "see_more": False, "location_note": None}

    if limit is None:
        limit = int(getattr(settings, "MAX_BUSINESS_RESULTS", 20))
    off = max(0, int(offset or 0))

    from chatbot.models import ImpressionsLog

    terms = _discovery_search_terms(message, category, subcategory, category_hint)
    candidates = _django_discovery_location_candidates(state, city, county, zip_code)
    if not candidates:
        return {"businesses": [], "see_more": False, "location_note": None}

    if terms:
        tl = [x.lower() for x in terms]
        filtered = []
        for b in candidates:
            hay = " ".join(
                filter(
                    None,
                    [
                        b.name,
                        b.category,
                        b.subcategory,
                        b.tags,
                        b.contact_info,
                    ],
                )
            ).lower()
            if any(t in hay for t in tl):
                filtered.append(b)
        if not filtered:
            return {"businesses": [], "see_more": False, "location_note": None}
        candidates = filtered

    if language and str(language).strip():
        lang = str(language).strip().lower()[:2]
        candidates = [
            b
            for b in candidates
            if not (b.languages or "").strip()
            or lang in (b.languages or "").lower()
        ]

    radius_miles = float(getattr(settings, "BUSINESS_RADIUS_MILES", 25))
    radius_fallback = float(getattr(settings, "BUSINESS_RADIUS_FALLBACK_MILES", 50))
    with_coords = []
    no_coords = []
    for b in candidates:
        if (
            user_lat is not None
            and user_lon is not None
            and b.latitude is not None
            and b.longitude is not None
        ):
            d = _distance_miles(user_lat, user_lon, b.latitude, b.longitude)
            if d is not None:
                with_coords.append((b, d))
                continue
        no_coords.append(b)

    location_note = None
    if with_coords:
        within_p = [(b, d) for b, d in with_coords if d <= radius_miles]
        within_f = [(b, d) for b, d in with_coords if radius_miles < d <= radius_fallback]
        if within_p:
            ordered_pairs = sorted(within_p, key=lambda x: (x[1], x[0].rotation_index or 0))
        elif within_f:
            ordered_pairs = sorted(within_f, key=lambda x: (x[1], x[0].rotation_index or 0))
            location_note = "No exact matches in your area. Here are the closest available options."
        else:
            ordered_pairs = sorted(with_coords, key=lambda x: (x[1], x[0].rotation_index or 0))
            location_note = "No exact matches in your area. Here are the closest available options."
        selected_pairs = ordered_pairs[off : off + limit]
        see_more = off + len(selected_pairs) < len(ordered_pairs)
    else:
        no_coords.sort(key=lambda b: _django_discovery_sort_key(b, city, county))
        ordered_nc = [(b, None) for b in no_coords]
        selected_pairs = ordered_nc[off : off + limit]
        see_more = off + len(selected_pairs) < len(ordered_nc)

    out_list = []
    try:
        with transaction.atomic():
            for b, dist in selected_pairs:
                out_list.append(
                    {
                        "id": b.id,
                        "name": b.name,
                        "category": b.category,
                        "subcategory": b.subcategory,
                        "state": b.state,
                        "city": b.city,
                        "county": getattr(b, "county", None),
                        "zip_code": getattr(b, "zip_code", None),
                        "languages": b.languages,
                        "contact_info": b.contact_info,
                        "whatsapp_url": getattr(b, "whatsapp_url", None) or "",
                        "distance_miles": dist,
                        "is_sponsored": bool(b.ad_package_id),
                    }
                )
                b.impressions_used = (b.impressions_used or 0) + 1
                b.save(update_fields=["impressions_used"])
                ImpressionsLog.objects.create(
                    business=b,
                    external_id=external_id,
                    session_id=session_id,
                )
    except Exception:
        logger.exception("business_matching.discovery_django.failed")
        return {"businesses": [], "see_more": False, "location_note": None}

    logger.info(
        "business_matching.discovery_django terms=%s results=%s",
        len(terms),
        len(out_list),
    )
    return {
        "businesses": out_list,
        "see_more": see_more,
        "location_note": location_note,
    }
