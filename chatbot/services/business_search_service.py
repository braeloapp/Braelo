"""
Mongo business directory search for mixed schemas in the same collection:

- Schema A (seed/legacy): English lowercase category, snake_case subcategory, languages string, etc.
- Schema B (Lista): Portuguese category/subcategory, optional tags, languages array, etc.

Queries use $or across both shapes; API rows are normalized for the chatbot.

Optional cues (e.g. Brazilian, sushi) narrow matches to ``name`` / ``business_name`` / ``tags`` or ``TAGS``;
generic queries skip that so full category+location results are returned.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from django.conf import settings

logger = logging.getLogger(__name__)

# (Lista category, Lista subcategory, English category, English subcategory) — any tuple entry may be None
KEYWORD_TO_BOTH_SCHEMAS: dict[str, tuple[str | None, str | None, str | None, str | None]] = {
    "brazilian food": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "brazilian restaurant": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "food truck": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "coffee shop": ("Gastronomia", "Restaurantes", "food", "cafe"),
    "places to eat": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "where to eat": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "restaurants": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "restaurant": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "restaurantes": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "restaurante": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "food": ("Gastronomia", None, "food", None),
    "comida": ("Gastronomia", None, "food", None),
    "gastronomia": ("Gastronomia", None, "food", None),
    "gastronom": ("Gastronomia", None, "food", None),
    "eat": ("Gastronomia", None, "food", None),
    "eating": ("Gastronomia", None, "food", None),
    "dining": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "dine": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "dinner": ("Gastronomia", None, "food", None),
    "lunch": ("Gastronomia", None, "food", None),
    "breakfast": ("Gastronomia", None, "food", None),
    "steakhouse": ("Gastronomia", "Churrascarias", "food", "steakhouse"),
    "steak": ("Gastronomia", "Churrascarias", "food", "steakhouse"),
    "churrasco": ("Gastronomia", "Churrascarias", "food", "steakhouse"),
    "churrascaria": ("Gastronomia", "Churrascarias", "food", "steakhouse"),
    "churrascarias": ("Gastronomia", "Churrascarias", "food", "steakhouse"),
    "bbq": ("Gastronomia", "Churrascarias", "food", "steakhouse"),
    "grill": ("Gastronomia", "Churrascarias", "food", "restaurant"),
    "bakery": ("Gastronomia", "Padarias", "food", "bakery"),
    "padaria": ("Gastronomia", "Padarias", "food", "bakery"),
    "pizza": ("Gastronomia", "Pizzarias", "food", "pizza"),
    "pizzaria": ("Gastronomia", "Pizzarias", "food", "pizza"),
    "bar": ("Gastronomia", "Bares", "food", "bar"),
    "cafe": ("Gastronomia", "Lanchonetes", "food", "cafe"),
    "café": ("Gastronomia", "Lanchonetes", "food", "cafe"),
    "coffee": ("Gastronomia", "Lanchonetes", "food", "cafe"),
    "snack": ("Gastronomia", "Lanchonetes", "food", "snack"),
    "lanchonete": ("Gastronomia", "Lanchonetes", "food", "snack"),
    "acai": ("Gastronomia", "Lanchonetes", "food", "snack"),
    "açaí": ("Gastronomia", "Lanchonetes", "food", "snack"),
    "dessert": ("Gastronomia", "Lanchonetes", "food", "dessert"),
    "cake": ("Gastronomia", "Lanchonetes", "food", "dessert"),
    "grocery": ("Gastronomia", "Mercado", "food", "grocery"),
    "market": ("Gastronomia", "Mercado", "food", "grocery"),
    "mercado": ("Gastronomia", "Mercado", "food", "grocery"),
    "supermarket": ("Gastronomia", "Mercado", "food", "grocery"),
    "salon": ("Serviços", "Beleza e Estética", "services", "salon"),
    "salão": ("Serviços", "Beleza e Estética", "services", "salon"),
    "beauty": ("Serviços", "Beleza e Estética", "services", "beauty"),
    "spa": ("Serviços", "Beleza e Estética", "services", "spa"),
    "hair": ("Serviços", "Beleza e Estética", "services", "salon"),
    "nails": ("Serviços", "Beleza e Estética", "services", "nails"),
    "unhas": ("Serviços", "Beleza e Estética", "services", "nails"),
    "beleza": ("Serviços", "Beleza e Estética", "services", "beauty"),
    "skincare": ("Serviços", "Beleza e Estética", "services", "beauty"),
    "barber": ("Serviços", "Barbearias", "services", "barber"),
    "barbershop": ("Serviços", "Barbearias", "services", "barber"),
    "barbearia": ("Serviços", "Barbearias", "services", "barber"),
    "lawyer": ("Serviços", "Jurídico", "legal", "lawyer"),
    "lawyers": ("Serviços", "Jurídico", "legal", "lawyer"),
    "attorney": ("Serviços", "Jurídico", "legal", "lawyer"),
    "immigration": ("Serviços", "Jurídico", "legal", "immigration"),
    "advogado": ("Serviços", "Jurídico", "legal", "lawyer"),
    "legal": ("Serviços", "Jurídico", "legal", None),
    "jurídico": ("Serviços", "Jurídico", "legal", None),
    "insurance": ("Serviços", "Agências de Seguros", "services", "insurance"),
    "seguro": ("Serviços", "Agências de Seguros", "services", "insurance"),
    "seguros": ("Serviços", "Agências de Seguros", "services", "insurance"),
    "construction": ("Serviços", "Construção", "construction", None),
    "construção": ("Serviços", "Construção", "construction", None),
    "renovation": ("Serviços", "Reformas e Reparos", "construction", "renovation"),
    "repair": ("Serviços", "Reformas e Reparos", "construction", "repair"),
    "flooring": ("Serviços", "Reformas e Reparos", "construction", "flooring"),
    "reforma": ("Serviços", "Reformas e Reparos", "construction", "renovation"),
    "doctor": ("Saúde", "Medicina", "health", "doctor"),
    "médico": ("Saúde", "Medicina", "health", "doctor"),
    "clinic": ("Saúde", "Medicina", "health", "clinic"),
    "hospital": ("Saúde", "Hospitais", "health", "hospital"),
    "dentist": ("Saúde", "Odontologia", "health", "dentist"),
    "dental": ("Saúde", "Odontologia", "health", "dentist"),
    "dentista": ("Saúde", "Odontologia", "health", "dentist"),
    "psychologist": ("Saúde", "Saúde da Mente", "health", "mental_health"),
    "therapy": ("Saúde", "Saúde da Mente", "health", "therapy"),
    "mental health": ("Saúde", "Saúde da Mente", "health", "mental_health"),
    "pharmacy": ("Saúde", "Farmácias", "health", "pharmacy"),
    "farmácia": ("Saúde", "Farmácias", "health", "pharmacy"),
    "gym": ("Serviços", "Academias", "health", "gym"),
    "academia": ("Serviços", "Academias", "health", "gym"),
    "fitness": ("Serviços", "Academias", "health", "gym"),
    "accounting": ("Financeiro", "Contabilidade", "financial", "accounting"),
    "accountant": ("Financeiro", "Contabilidade", "financial", "accounting"),
    "contabilidade": ("Financeiro", "Contabilidade", "financial", "accounting"),
    "tax": ("Financeiro", "Contabilidade", "financial", "tax"),
    "bank": ("Financeiro", "Bancos", "financial", "bank"),
    "banco": ("Financeiro", "Bancos", "financial", "bank"),
    "financial": ("Financeiro", None, "financial", None),
    "financeiro": ("Financeiro", None, "financial", None),
    "real estate": ("Serviços", "Imobiliário", "housing", "real_estate_agent"),
    "imóveis": ("Serviços", "Imobiliário", "housing", "real_estate_agent"),
    "imoveis": ("Serviços", "Imobiliário", "housing", "real_estate_agent"),
    "housing": ("Serviços", "Imobiliário", "housing", None),
    "realtor": ("Serviços", "Imobiliário", "housing", "real_estate_agent"),
    "mortgage": ("Serviços", "Imobiliário", "housing", "mortgage"),
    "shop": ("Comércio", "Lojas", "retail", "store"),
    "store": ("Comércio", "Lojas", "retail", "store"),
    "loja": ("Comércio", "Lojas", "retail", "store"),
    "lojas": ("Comércio", "Lojas", "retail", "store"),
    "clothing": ("Comércio", "Lojas", "retail", "clothing"),
    "roupa": ("Comércio", "Lojas", "retail", "clothing"),
    "jewelry": ("Comércio", "Lojas", "retail", "jewelry"),
    "event": ("Serviços", "Eventos", "services", "event_planning"),
    "events": ("Serviços", "Eventos", "services", "event_planning"),
    "party": ("Serviços", "Eventos", "services", "event_planning"),
    "festa": ("Serviços", "Eventos", "services", "event_planning"),
    "photographer": ("Serviços", "Fotografia", "services", "photography"),
    "photography": ("Serviços", "Fotografia", "services", "photography"),
    "fotografia": ("Serviços", "Fotografia", "services", "photography"),
    "moving": ("Serviços", "Transportes", "services", "moving"),
    "transport": ("Serviços", "Transportes", "services", "transport"),
    "mudança": ("Serviços", "Transportes", "services", "moving"),
    "technology": ("Serviços", "Tecnologia da Informação (TI)", "technology", None),
    "tecnologia": ("Serviços", "Tecnologia da Informação (TI)", "technology", None),
    "marketing": ("Serviços", "Marketing Digital", "services", "marketing"),
    "school": ("Educação", None, "education", None),
    "escola": ("Educação", None, "education", None),
    "university": ("Educação", "Universidades", "education", "university"),
    "dance": ("Educação", "Escolas de Dança", "education", "dance"),
    "hotel": ("Turismo", "Hotelaria", "tourism", "hotel"),
    "travel": ("Turismo", None, "tourism", None),
    "turismo": ("Turismo", None, "tourism", None),
    "cleaning": ("Serviços", "Serviços Domésticos", "services", "cleaning"),
    "limpeza": ("Serviços", "Serviços Domésticos", "services", "cleaning"),
    # Admin panel (EN/ES) + helpers.constants.meta — extra phrases so mirrored rows match Lista/EN queries
    "homemade food": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "farm & fresh food": ("Gastronomia", "Mercado", "food", "grocery"),
    "catering": ("Gastronomia", "Eventos", "food", "catering"),
    "chef": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "consultancy": ("Serviços", "Consultoria", "services", "consulting"),
    "consulting": ("Serviços", "Consultoria", "services", "consulting"),
    "immigration and visa": ("Serviços", "Jurídico", "legal", "immigration"),
    "event services": ("Serviços", "Eventos", "services", "event_planning"),
    "movers & packers": ("Serviços", "Transportes", "services", "moving"),
    "transport services": ("Serviços", "Transportes", "services", "transport"),
    "ac services": ("Serviços", "Reformas e Reparos", "construction", "repair"),
    "personal trainer": ("Serviços", "Academias", "health", "gym"),
    "finger food": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "buffet": ("Gastronomia", "Eventos", "food", "catering"),
    "video & photography": ("Serviços", "Fotografia", "services", "photography"),
    "interior design": ("Serviços", "Design de Interiores", "services", "design"),
    "home care (health)": ("Saúde", "Medicina", "health", "doctor"),
    "insurance services": ("Serviços", "Agências de Seguros", "services", "insurance"),
    "networking events": ("Serviços", "Eventos", "services", "event_planning"),
    "classes & courses": ("Educação", None, "education", None),
    "home automation": ("Serviços", "Tecnologia da Informação (TI)", "technology", None),
    "services": ("Serviços", None, "services", None),
    "servicios": ("Serviços", None, "services", None),
    "serviços": ("Serviços", None, "services", None),
    # helpers.constants.meta client slugs + common bad LLM/typo phrases (e.g. rent a car)
    "partsandaccessories": ("Veículos", "Parts and Accessories", "vehicles", "parts"),
    "rentals": ("Veículos", "Rentals", "vehicles", "rental"),
    "car_rental": ("Veículos", "Rentals", "vehicles", "rental"),
    "rent a car": ("Veículos", "Rentals", "vehicles", "rental"),
    "networkingevents": ("Serviços", "Eventos", "services", "event_planning"),
    "sportsequipment": ("Comércio", "Lojas", "retail", "store"),
    "musicalinstruments": ("Educação", "Escolas de Dança", "education", "dance"),
    "collecteditems": ("Comércio", "Lojas", "retail", "store"),
    "outdooractivities": ("Sports", "Outdoor", "services", None),
    "beautyproducts": ("Serviços", "Beleza e Estética", "services", "beauty"),
    "schooloffices": ("Educação", None, "education", None),
    "afterschoolprogram": ("Educação", None, "education", None),
    "customfurniture": ("Comércio", "Lojas", "retail", "store"),
    "servicesandparts": ("Electronics", "Services and Parts", "electronics", "parts"),
    "mobilehome": ("Serviços", "Imobiliário", "housing", "real_estate_agent"),
    "vacationhome": ("Serviços", "Imobiliário", "housing", "real_estate_agent"),
    "fastfood": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "fine_dining": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    "foodtruck": ("Gastronomia", "Restaurantes", "food", "restaurant"),
    # Kids marketplace listings (Mongo: category=kids, subcategory=babysitter)
    "baby sitter": (None, None, "kids", "babysitter"),
    "baby-sitter": (None, None, "kids", "babysitter"),
    "babysitter": (None, None, "kids", "babysitter"),
    "babysitting": (None, None, "kids", "babysitter"),
    "babysitters": (None, None, "kids", "babysitter"),
    "nanny": (None, None, "kids", "babysitter"),
    "nannies": (None, None, "kids", "babysitter"),
    "day care": (None, None, "kids", "babysitter"),
    "daycare": (None, None, "kids", "babysitter"),
    "child care": (None, None, "kids", "babysitter"),
    "childcare": (None, None, "kids", "babysitter"),
    "au pair": (None, None, "kids", "babysitter"),
    "kids": (None, None, "kids", None),
}


def collect_directory_search_tokens_from_listing_text(*parts: str | None) -> list[str]:
    """
    Scan listing text for KEYWORD_TO_BOTH_SCHEMAS hits; return Lista + English seed tokens.
    Used when syncing admin/user listings to Mongo so EN/ES labels match chatbot directory queries.
    """
    hay = " ".join(str(p or "").strip() for p in parts if p and str(p).strip())
    if not hay:
        return []
    hay_lower = " ".join(hay.lower().split())
    collected: set[str] = set()
    for kw in sorted(KEYWORD_TO_BOTH_SCHEMAS.keys(), key=len, reverse=True):
        kw_lower = kw.lower()
        if " " in kw:
            if kw_lower not in hay_lower:
                continue
        else:
            if len(kw) < 3:
                continue
            if not re.search(
                r"(?<![a-z0-9áàâãéêíóôõúüçñ])"
                + re.escape(kw_lower)
                + r"(?![a-z0-9áàâãéêíóôõúüçñ])",
                hay_lower,
            ):
                continue
        for t in KEYWORD_TO_BOTH_SCHEMAS[kw]:
            if t and str(t).strip():
                collected.add(str(t).strip())
    return list(collected)


STATE_NORMALIZE_TO_ENGLISH: dict[str, str] = {
    "florida": "Florida",
    "california": "California",
    "north carolina": "North Carolina",
    "south carolina": "South Carolina",
    "georgia": "Georgia",
    "new york": "New York",
    "texas": "Texas",
    "arizona": "Arizona",
    "maryland": "Maryland",
    "massachusetts": "Massachusetts",
    "pennsylvania": "Pennsylvania",
    "virginia": "Virginia",
    "connecticut": "Connecticut",
    "new jersey": "New Jersey",
    "nevada": "Nevada",
    "ohio": "Ohio",
    "washington dc": "District of Columbia",
    "district of columbia": "District of Columbia",
    "idaho": "Idaho",
    "kansas": "Kansas",
    "utah": "Utah",
    "rhode island": "Rhode Island",
    "new hampshire": "New Hampshire",
    "alabama": "Alabama",
    "alaska": "Alaska",
    "arkansas": "Arkansas",
    "colorado": "Colorado",
    "delaware": "Delaware",
    "hawaii": "Hawaii",
    "illinois": "Illinois",
    "indiana": "Indiana",
    "iowa": "Iowa",
    "kentucky": "Kentucky",
    "louisiana": "Louisiana",
    "maine": "Maine",
    "michigan": "Michigan",
    "minnesota": "Minnesota",
    "mississippi": "Mississippi",
    "missouri": "Missouri",
    "montana": "Montana",
    "nebraska": "Nebraska",
    "new mexico": "New Mexico",
    "north dakota": "North Dakota",
    "oklahoma": "Oklahoma",
    "oregon": "Oregon",
    "south dakota": "South Dakota",
    "tennessee": "Tennessee",
    "vermont": "Vermont",
    "washington": "Washington",
    "west virginia": "West Virginia",
    "wisconsin": "Wisconsin",
    "wyoming": "Wyoming",
    "flórida": "Florida",
    "califórnia": "California",
    "carolina do norte": "North Carolina",
    "carolina do sul": "South Carolina",
    "geórgia": "Georgia",
    "geôrgia": "Georgia",
    "nova york": "New York",
    "pensilvânia": "Pennsylvania",
    "virgínia": "Virginia",
    "nova jersey": "New Jersey",
}

STATE_ABBR_TO_ENGLISH: dict[str, str] = {
    "fl": "Florida",
    "ca": "California",
    "nc": "North Carolina",
    "sc": "South Carolina",
    "ga": "Georgia",
    "ny": "New York",
    "tx": "Texas",
    "az": "Arizona",
    "md": "Maryland",
    "ma": "Massachusetts",
    "pa": "Pennsylvania",
    "va": "Virginia",
    "ct": "Connecticut",
    "nj": "New Jersey",
    "nv": "Nevada",
    "oh": "Ohio",
    "id": "Idaho",
    "ks": "Kansas",
    "ut": "Utah",
    "ri": "Rhode Island",
    "nh": "New Hampshire",
    "al": "Alabama",
    "ak": "Alaska",
    "ar": "Arkansas",
    "co": "Colorado",
    "de": "Delaware",
    "hi": "Hawaii",
    "il": "Illinois",
    "in": "Indiana",
    "ia": "Iowa",
    "ky": "Kentucky",
    "la": "Louisiana",
    "me": "Maine",
    "mi": "Michigan",
    "mn": "Minnesota",
    "mo": "Missouri",
    "mt": "Montana",
    "ne": "Nebraska",
    "nm": "New Mexico",
    "nd": "North Dakota",
    "ok": "Oklahoma",
    "or": "Oregon",
    "sd": "South Dakota",
    "tn": "Tennessee",
    "vt": "Vermont",
    "wa": "Washington",
    "wv": "West Virginia",
    "wi": "Wisconsin",
    "wy": "Wyoming",
    "dc": "District of Columbia",
}

BUSINESS_SEARCH_TRIGGERS: tuple[str, ...] = (
    "can you find",
    "find me",
    "find a",
    "find an",
    "find the",
    "looking for",
    "i am looking",
    "i'm looking",
    "where is",
    "where are",
    "where can i find",
    "show me",
    "give me",
    "get me",
    "list of",
    "i need a",
    "i need an",
    "i want a",
    "i want to find",
    "is there a",
    "are there any",
    "any restaurants",
    "any businesses",
    "any shops",
    "any services",
    "recommend",
    "suggest",
    "know any",
    "can you give me",
    "can i find",
    "near me",
    "near my",
    "in my area",
    "around me",
    "nearby",
    "closest",
    "buscar",
    "encontrar",
    "estoy buscando",
    "hay ",
    "dónde hay",
    "busco",
    "procuro",
    "estou procurando",
    "tem algum",
    "onde tem",
    "pode me indicar",
    "preciso de",
)

# --- Directory geo policy (US Lista; used by search_businesses_in_mongodb / layered queries) ---
# - **State** is the main anchor: explicit state, profile/caller state, or inferred from a known city.
# - **City / county** narrow the match when provided; if city implies a state, that beats a
#   conflicting profile state (e.g. “Los Angeles” → California even if profile said Texas).
# - **US country** (“USA”, “United States”, …) with no city and no state anywhere: do not guess a
#   state — search broader so real DB rows are not filtered out (still category-scoped).
# - With US country + profile state: keep profile state (“consider state” with country).
# - **Database first**: `_execute_directory_mongo_levels` still runs tighter clauses first, then
#   state-only, then category-only, unioning hits until the limit.

_US_COUNTRY_PHRASES = re.compile(
    r"\b(united states|u\.s\.a\.?|u\.s\.|usa|the us|estados unidos|ee\.?\s*u\.?\s*u\.?)\b",
    re.I,
)


def message_mentions_us_country(text: str | None) -> bool:
    """True if the user names the US as a country (not the pronoun 'us')."""
    if not (text or "").strip():
        return False
    return bool(_US_COUNTRY_PHRASES.search(text))


def _strip_redundant_state_from_city_label(city: str | None, state_en: str | None) -> str | None:
    """
    convert_query often yields city='Orlando Florida' while Mongo stores city='Orlando'.
    Regex `^Orlando\\s*Florida$` then matches nothing; geo tiers empty and we fall back to state-only.
    Strip a trailing state token when it duplicates the resolved state (name or 2-letter abbr).
    """
    c = (city or "").strip()
    if not c:
        return None
    st = normalize_state_for_db(state_en) if (state_en or "").strip() else None
    if not st:
        return c
    words = c.split()
    st_words = st.split()
    st_l = st.lower()
    # Trailing multi-word state (e.g. ... North Carolina)
    if len(st_words) >= 1 and len(words) > len(st_words):
        tail = " ".join(words[-len(st_words) :]).lower()
        if tail == st_l:
            rest = " ".join(words[: -len(st_words)]).strip()
            return rest or c
    # Single-word state name (Florida) as last token
    if len(st_words) == 1 and len(words) >= 2 and words[-1].lower() == st_words[0].lower():
        return " ".join(words[:-1]).strip() or c
    # Trailing USPS-style abbreviation (Miami FL) when state is known
    last = words[-1].lower().rstrip(".")
    for abbr, full in STATE_ABBR_TO_ENGLISH.items():
        if len(str(abbr)) != 2:
            continue
        if full.lower() != st_l:
            continue
        if last == str(abbr).lower():
            return " ".join(words[:-1]).strip() or c
        break
    return c


def _merge_caller_and_message_geo(
    city: str | None,
    county: str | None,
    state: str | None,
    parsed: dict,
) -> tuple[str | None, str | None, str | None]:
    """
    State: message / parse wins over profile when set (see _apply_message_location upstream).

    City/county: **caller** (pipeline: regex hints + profile merge) wins over parse blobs like
    'Orlando Florida' so Mongo city regex matches a single placename.

    If the message names only a state (parse has state_en, no city), drop city/county so we do not
    AND a stale profile city with the new state.
    """
    msg_city = (parsed.get("city") or "").strip() or None
    msg_county = (parsed.get("county") or "").strip() or None
    msg_state = (parsed.get("state_en") or "").strip() or None

    caller_city = (city or "").strip() or None
    caller_county = (county or "").strip() or None
    caller_state = (state or "").strip() or None

    st_raw = msg_state or caller_state or None

    if caller_city:
        city_s = caller_city
        county_s = caller_county or msg_county
    elif msg_city:
        city_s = msg_city
        county_s = msg_county or caller_county
    elif msg_state:
        city_s = None
        county_s = None
    else:
        city_s = None
        county_s = caller_county or msg_county

    if city_s and st_raw:
        city_s = _strip_redundant_state_from_city_label(city_s, st_raw)

    return city_s, county_s, st_raw


def _finalize_directory_state(
    query: str,
    st_raw: str | None,
    city_s: str | None,
    zip_code: str | None,
) -> str | None:
    """
    US-country-only → no state filter; else city→state backfill + normalize.
    """
    from chatbot.geo_constants import backfill_state_from_major_us_city

    us_only = message_mentions_us_country(query) and not city_s and not st_raw
    if us_only:
        return None
    st_merged = backfill_state_from_major_us_city(st_raw, city_s)
    return normalize_state_for_db(st_merged) if st_merged else None


def _lista_tripod_clause(
    category_pt: str | None,
    subcategory_pt: str | None,
    state_en: str | None,
) -> dict | None:
    """
    Same shape as manual Lista queries: category + subcategory + state (case-insensitive).
    Also matches legacy field names business_category / business_subcategory.
    """
    if not category_pt or not subcategory_pt or not state_en:
        return None
    c = _rx(str(category_pt).strip())
    s = _rx(str(subcategory_pt).strip())
    st = _rx(str(state_en).strip())
    if not c or not s or not st:
        return None
    return {
        "$and": [
            {"$or": [{"category": c}, {"business_category": c}]},
            {"$or": [{"subcategory": s}, {"business_subcategory": s}]},
            {"state": st},
        ]
    }


_KNOWN_CITIES: tuple[str, ...] = (
    "los angeles",
    "san francisco",
    "san diego",
    "san antonio",
    "san jose",
    "new york",
    "las vegas",
    "kansas city",
    "oklahoma city",
    "salt lake city",
    "el paso",
    "fort worth",
    "long beach",
    "santa ana",
    "corpus christi",
    "beverly hills",
    "santa monica",
    "west hollywood",
    "panama city",
    "phoenix",
    "tucson",
    "mesa",
    "chandler",
    "scottsdale",
)

# Message cues → substrings we OR-match on listing ``name``, ``business_name``, ``tags``, ``TAGS``.
# Only when a pattern hits do we narrow results; generic queries (e.g. “restaurants in Florida”) hit none → no extra filter.
_LISTING_NAME_HINT_GROUPS: tuple[tuple[re.Pattern, tuple[str, ...]], ...] = (
    (
        re.compile(
            r"\b(brazilian|brasil|brazil|brasileir[oa]s?|brasilian)\b",
            re.I,
        ),
        ("brazil", "brasil", "brazilian", "brasileiro", "brasileira", "brasilian"),
    ),
    (re.compile(r"\bsushi\b", re.I), ("sushi",)),
    (re.compile(r"\b(japanese|japan|nihon)\b", re.I), ("japanese", "japan", "sushi")),
    (re.compile(r"\b(mexican|méxico|mexico|taco|taqueria)\b", re.I), ("mexican", "mexico", "méxico", "taco", "taqueria")),
    (re.compile(r"\bitalian\b|\bit[ae]ly\b|\bitalia\b", re.I), ("italian", "italy", "italia")),
    (re.compile(r"\bthai\b", re.I), ("thai",)),
    (re.compile(r"\bchinese\b|\bchina\b", re.I), ("chinese", "china")),
    (re.compile(r"\bkorean\b|\bkorea\b", re.I), ("korean", "korea")),
    (re.compile(r"\bindian\b|\bindia\b", re.I), ("indian", "india")),
    (re.compile(r"\bvietnamese\b|\bvietnam\b", re.I), ("vietnamese", "vietnam")),
    (re.compile(r"\bcuban\b|\bcuba\b", re.I), ("cuban", "cuba")),
    (re.compile(r"\bcolombian\b|\bcolombia\b", re.I), ("colombian", "colombia")),
    (re.compile(r"\bperuvian\b|\bperu\b", re.I), ("peruvian", "peru")),
    (re.compile(r"\bseafood\b|\bmariscos\b|\bmarisqueiro\b", re.I), ("seafood", "mariscos", "marisqueiro")),
    (
        re.compile(
            r"\b(bbq|barbecue|barbeque|steak|steakhouse|churrasco|churrascaria|churrasqueiros?)\b",
            re.I,
        ),
        (
            "bbq",
            "barbecue",
            "barbeque",
            "steak",
            "steakhouse",
            "churrasco",
            "churrascaria",
            "churrasqueiro",
            "churrasqueiros",
        ),
    ),
    (re.compile(r"\b(vegan|veggie|vegetarian|vegano|vegetariano)\b", re.I), ("vegan", "vegetarian", "vegano", "vegetariano")),
    (re.compile(r"\b(kosher|halal)\b", re.I), ("kosher", "halal")),
    (re.compile(r"\b(ethiopian|ethiopia)\b", re.I), ("ethiopian", "ethiopia")),
    (re.compile(r"\b(french|france|frança|frances)\b", re.I), ("french", "france", "frances")),
    (re.compile(r"\b(greek|greece|grego)\b", re.I), ("greek", "greece", "grego")),
    (re.compile(r"\b(spanish|spain|españ|espanhol)\b", re.I), ("spanish", "spain", "español", "espanhol")),
    (re.compile(r"\b(portuguese|portugal)\b", re.I), ("portuguese", "portugal")),
    (re.compile(r"\b(middle eastern|lebanese|shawarma|árabe)\b", re.I), ("lebanese", "shawarma", "arab", "árabe")),
    (re.compile(r"\b(pizza|pizzaria|pizzeria)\b", re.I), ("pizza", "pizzaria", "pizzeria")),
    (re.compile(r"\b(burger|hamburger)\b", re.I), ("burger", "hamburger")),
    (re.compile(r"\b(ramen|izakaya)\b", re.I), ("ramen", "izakaya")),
    (re.compile(r"\b(tapas|paella)\b", re.I), ("tapas", "paella")),
)


def _llm_expand_tag_search_tokens(message: str | None, base_terms: list[str]) -> list[str]:
    """
    Add Portuguese/English tokens that appear in Lista ``TAGS`` (e.g. Churrasqueiros) when the user
    says BBQ, Brazilian, etc. Heuristic patterns stay the source of truth; this only adds synonyms.
    """
    if not getattr(settings, "TAG_SEARCH_LLM_EXPAND", True):
        return []
    msg = (message or "").strip()
    if not msg:
        return []
    base_terms = base_terms or []
    if not base_terms:
        return []
    try:
        from chatbot.services import gpt_service

        cli = getattr(gpt_service, "client", None)
        if not cli:
            return []
        model = getattr(settings, "GPT_MODEL", "gpt-4o-mini")
        sys = """You help search a MongoDB business directory. Each listing may have:
- TAGS: Portuguese labels separated by | (example: "Churrascaria Brasileira|Churrasqueiros|Bar")
- name in English or Portuguese

Given the user message and the heuristic tokens we already extracted, output JSON only:
{"tokens": ["...", ...]}

Rules:
- Add short tokens (2–40 chars) likely to appear in TAGS or names: Portuguese equivalents, demonyms, cuisine words (e.g. BBQ/barbecue → churrasco, churrascaria, churrasqueiros when relevant).
- Do not repeat the obvious category word "restaurant" unless needed. Max 16 tokens. No full sentences."""
        user = f"User message:\n{msg[:1200]}\n\nHeuristic tokens:\n{', '.join(base_terms[:22])}"
        resp = cli.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            max_tokens=320,
            temperature=0.15,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = json.loads(raw)
        arr = data.get("tokens")
        if not isinstance(arr, list):
            return []
        out: list[str] = []
        for x in arr:
            s = str(x).strip()
            if 2 <= len(s) <= 48:
                out.append(s)
        logger.info(
            "business_search_service.tag_llm_expand n_heuristic=%s n_added=%s",
            len(base_terms),
            len(out),
        )
        return out[:16]
    except Exception:
        logger.exception("business_search_service.tag_token_llm_expand_failed")
        return []


def extract_listing_name_filter_terms(message: str | None) -> list[str]:
    """
    If the user names a cuisine/style (Brazilian, sushi, …), return tokens to match on listing
    name/business_name/tags/TAGS. Empty list → do not narrow (show all category+location matches).
    """
    if not message or not str(message).strip():
        return []
    out: set[str] = set()
    for pat, terms in _LISTING_NAME_HINT_GROUPS:
        if pat.search(message):
            out.update(terms)
    base = sorted(out)
    for t in _llm_expand_tag_search_tokens(message, base):
        out.add(t)
    return sorted(out)[:28]


def _listing_text_hint_clause(terms: list[str]) -> dict | None:
    """$or across name, business_name, tags, TAGS (any term matches)."""
    if not terms:
        return None
    uniq = sorted({t.strip() for t in terms if t and str(t).strip()})
    if not uniq:
        return None
    alt = "|".join(re.escape(t) for t in uniq)
    rx = {"$regex": alt, "$options": "i"}
    return {
        "$or": [
            {"name": rx},
            {"business_name": rx},
            {"tags": rx},
            {"TAGS": rx},
        ]
    }


def tokenize_query(text: str) -> list[str]:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\sáàâãéêíóôõúüçñ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    tokens = list(words)
    for i in range(len(words) - 1):
        tokens.append(f"{words[i]} {words[i + 1]}")
    for i in range(len(words) - 2):
        tokens.append(f"{words[i]} {words[i + 1]} {words[i + 2]}")
    return tokens


def _rx(val: str | None) -> dict | None:
    if not val or not str(val).strip():
        return None
    return {"$regex": re.escape(str(val).strip()), "$options": "i"}


def _rx_tags_token(term: str | None) -> dict | None:
    """
    Match a token inside Lista ``tags`` or ``TAGS`` (space / comma / pipe separated) without substring false positives.
    """
    if not term or not str(term).strip():
        return None
    t = str(term).strip()
    if len(t) < 2:
        return None
    esc = re.escape(t)
    piece = {
        "$regex": rf"(?:^|[\s,|])(?:{esc})(?:$|[\s,|])",
        "$options": "i",
    }
    return {"$or": [{"tags": piece}, {"TAGS": piece}]}


def detect_document_schema(doc: dict | None) -> str:
    """
    Heuristic: Schema B = Lista/CSV shape; Schema A = English seed shape.
    Used for debugging and conditional formatting — not required for queries.
    """
    if not doc or not isinstance(doc, dict):
        return "unknown"
    if isinstance(doc.get("languages"), list):
        return "B"
    ci = doc.get("contact_info")
    if isinstance(ci, str) and "[ListaBusiness" in ci:
        return "B"
    if doc.get("tags"):
        return "B"
    cat = str(doc.get("category") or doc.get("business_category") or "").strip()
    sub = str(doc.get("subcategory") or doc.get("business_subcategory") or "").strip()
    if sub and "_" in sub and (not cat or cat == cat.lower()):
        return "A"
    if cat and cat == cat.lower() and not re.search(r"[À-ÿ]", cat):
        return "A"
    if cat and cat[:1].isupper() and any(ch.islower() for ch in cat[1:]):
        return "B"
    return "mixed"


def _base_filter() -> dict:
    return {
        "is_active": True,
        "$or": [{"is_banned": False}, {"is_banned": {"$exists": False}}],
    }


def _city_regex(city: str) -> dict:
    c = " ".join(str(city).split()).strip()
    if not c:
        return {}
    parts = [re.escape(p) for p in c.split() if p]
    if not parts:
        return {}
    pat = r"\s*".join(parts)
    return {"city": {"$regex": f"^{pat}$", "$options": "i"}}


def _county_regex(county: str) -> dict:
    c = " ".join(str(county).split()).strip()
    if not c:
        return {}
    parts = [re.escape(p) for p in c.split() if p]
    pat = r"\s*".join(parts)
    return {"county": {"$regex": f"^{pat}$", "$options": "i"}}


def _city_or_county_clause(city: str | None) -> dict | None:
    """
    Match city field OR county field against the same place name.
    Lista rows may use city=Beverly Hills with county=Los Angeles; users often say "Los Angeles".
    """
    c = (city or "").strip()
    if not c:
        return None
    cq = _city_regex(c)
    kq = _county_regex(c)
    if not cq or not kq or not cq.get("city") or not kq.get("county"):
        return cq if cq and cq.get("city") else (kq if kq and kq.get("county") else None)
    return {"$or": [cq, kq]}


def _zip_clause(zip_code: str | None) -> dict | None:
    if not zip_code:
        return None
    z = re.sub(r"\D", "", str(zip_code))[:5]
    if not z:
        return None
    return {
        "$or": [
            {"zip_code": {"$regex": f"^{re.escape(z)}", "$options": "i"}},
            {"zip_code": z},
        ]
    }


def _state_clause(st_en: str | None) -> dict | None:
    if not st_en:
        return None
    n = st_en.strip()
    if n.upper() in ("DC",) or n == "District of Columbia":
        rx_dc = _rx("District of Columbia")
        rx_short = _rx("DC")
        parts = [x for x in (rx_dc, rx_short) if x]
        if len(parts) == 1:
            return {"state": parts[0]}
        return {"$or": [{"state": parts[0]}, {"state": parts[1]}]}
    r = _rx(n)
    return {"state": r} if r else None


def _dual_schema_category_or(
    cat_pt: str | None,
    sub_pt: str | None,
    cat_en: str | None,
    sub_en: str | None,
) -> dict | None:
    """
    $or across Schema B (PT title case), Schema A (EN lowercase / snake_case),
    legacy `business_*` fields, and Lista `tags` (EN hint tokens from import).
    """
    parts: list[dict] = []
    seen_rx: set[str] = set()

    def _add(field: str, label: str | None):
        rx = _rx(label)
        if not rx:
            return
        key = f"{field}:{label}"
        if key in seen_rx:
            return
        seen_rx.add(key)
        parts.append({field: rx})

    def _add_tags_bounded(label: str | None):
        tg = _rx_tags_token(label)
        if not tg:
            return
        key = f"tags~:{label}"
        if key in seen_rx:
            return
        seen_rx.add(key)
        parts.append(tg)

    if sub_pt:
        _add("subcategory", sub_pt)
        _add("business_subcategory", sub_pt)
    if cat_pt:
        _add("category", cat_pt)
        _add("business_category", cat_pt)
    if sub_en:
        _add("subcategory", sub_en)
        _add("business_subcategory", sub_en)
    if cat_en:
        _add("category", cat_en)
        _add("business_category", cat_en)

    # Schema B: tags embed EN search hints + PT labels (import_lista_business_csv _build_tags).
    for term in (sub_pt, cat_pt, sub_en, cat_en):
        if term:
            _add_tags_bounded(term)

    if not parts:
        return None
    return {"$or": parts} if len(parts) > 1 else parts[0]


def build_dual_schema_mongo_query(
    *,
    category_pt: str | None = None,
    subcategory_pt: str | None = None,
    category_en: str | None = None,
    subcategory_en: str | None = None,
    state_en: str | None = None,
    city: str | None = None,
    county: str | None = None,
    zip_code: str | None = None,
) -> dict | None:
    """
    Public helper: base filter + dual-schema category $or + best-effort location AND.
    Returns None if there is no category axis.
    """
    dual = _dual_schema_category_or(
        category_pt, subcategory_pt, category_en, subcategory_en
    )
    if not dual:
        return None
    st_part = _state_clause(state_en)
    loc_q = _city_or_county_clause(city) if (city or "").strip() else None
    county_q = _county_regex(county) if (county or "").strip() else None
    zip_part = _zip_clause(zip_code)
    extra = _merge_and_parts(dual, loc_q, county_q, st_part, zip_part)
    if not extra:
        return None
    return {"$and": [_base_filter(), extra]}


def normalize_state_for_db(state_input: str | None) -> str | None:
    if not state_input or not str(state_input).strip():
        return None
    raw = str(state_input).strip()
    key = raw.lower().strip()
    if key in STATE_NORMALIZE_TO_ENGLISH:
        return STATE_NORMALIZE_TO_ENGLISH[key]
    if key in STATE_ABBR_TO_ENGLISH:
        return STATE_ABBR_TO_ENGLISH[key]
    return raw.title()


def convert_query_to_portuguese_fields(message: str | None) -> dict:
    """
    Map user text → Lista (PT) + seed (EN) category hints, English geo, and trigger flag.
    """
    result: dict = {
        "is_business_search": False,
        "category_pt": None,
        "subcategory_pt": None,
        "category_en": None,
        "subcategory_en": None,
        "state_en": None,
        "city": None,
        "county": None,
        "matched_keyword": None,
        "mentions_us_country": False,
    }
    msg = (message or "").strip()
    if not msg:
        return result
    msg_lower = msg.lower()
    tokens = tokenize_query(msg)

    if re.search(
        r"\b(food stamp|food stamps|snap\s|wic\s|food bank|food pantry)\b",
        msg_lower,
    ):
        if "restaurant" not in msg_lower and "dining" not in msg_lower and "eat out" not in msg_lower:
            return result

    for trigger in BUSINESS_SEARCH_TRIGGERS:
        if trigger in msg_lower:
            result["is_business_search"] = True
            break

    for keyword in sorted(KEYWORD_TO_BOTH_SCHEMAS.keys(), key=len, reverse=True):
        if " " in keyword:
            hit = keyword in tokens or keyword in msg_lower
        else:
            hit = keyword in tokens
        if hit:
            cat_pt, sub_pt, cat_en, sub_en = KEYWORD_TO_BOTH_SCHEMAS[keyword]
            result["category_pt"] = cat_pt
            result["subcategory_pt"] = sub_pt
            result["category_en"] = cat_en
            result["subcategory_en"] = sub_en
            result["matched_keyword"] = keyword
            result["is_business_search"] = True
            break

    for sk in sorted(STATE_NORMALIZE_TO_ENGLISH.keys(), key=len, reverse=True):
        if len(sk) < 3:
            continue
        if sk in tokens or re.search(rf"\b{re.escape(sk)}\b", msg_lower):
            result["state_en"] = STATE_NORMALIZE_TO_ENGLISH[sk]
            break

    if not result["state_en"]:
        for m in re.finditer(r"\b([A-Z]{2})\b", msg):
            ab = m.group(1).lower()
            if ab in STATE_ABBR_TO_ENGLISH:
                result["state_en"] = STATE_ABBR_TO_ENGLISH[ab]
                break

    for city_l in sorted(_KNOWN_CITIES, key=len, reverse=True):
        if city_l in msg_lower:
            result["city"] = " ".join(w.title() for w in city_l.split())
            break

    if not result["city"]:
        _skip_after_in = frozenset(
            {
                "my",
                "the",
                "a",
                "an",
                "our",
                "your",
                "this",
                "that",
                "there",
                "town",
                "downtown",
                "area",
                "order",
                "general",
                "case",
            }
        )
        mo_lc = re.search(
            r"\bin\s+([a-z][a-z]+(?:\s+[a-z]+){0,4})(?:\?|$|,|\s+and\b|\s+near\b|\s+please\b)",
            msg_lower,
        )
        if mo_lc:
            cand_l = mo_lc.group(1).strip()
            cand_l = re.sub(r"\s+(please|thanks|thank you)\s*$", "", cand_l).strip()
            first_tok = cand_l.split()[0] if cand_l else ""
            if (
                cand_l not in _skip_after_in
                and first_tok not in _skip_after_in
                and cand_l not in STATE_NORMALIZE_TO_ENGLISH
                and cand_l not in STATE_ABBR_TO_ENGLISH
                and first_tok not in STATE_ABBR_TO_ENGLISH
                and len(cand_l) > 2
            ):
                result["city"] = " ".join(w.title() for w in cand_l.split())

        if not result["city"]:
            mo = re.search(
                r"\bin\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b",
                msg,
            )
            if mo:
                cand = mo.group(1).strip()
                cand_norm = re.sub(r"\s+(please|thanks|thank you)\s*$", "", cand.lower()).strip()
                ft = cand_norm.split()[0] if cand_norm else ""
                if (
                    cand_norm not in STATE_NORMALIZE_TO_ENGLISH
                    and cand_norm not in _skip_after_in
                    and ft not in _skip_after_in
                ):
                    result["city"] = cand

    mo2 = re.search(
        r"\b([A-Za-z][A-Za-z\s]{2,40}?)\s*,\s*([A-Za-z]{2}|[A-Za-z][a-z]+(?:\s+[a-z]+)?)\s*(?:\?|$|,)",
        msg,
    )
    if mo2:
        c0 = mo2.group(1).strip()
        s0 = mo2.group(2).strip()
        st_key = s0.lower()
        st_res = STATE_ABBR_TO_ENGLISH.get(st_key) or STATE_NORMALIZE_TO_ENGLISH.get(st_key)
        if st_res:
            if not result["city"]:
                result["city"] = c0.title() if c0.islower() else c0
            if not result["state_en"]:
                result["state_en"] = st_res

    result["mentions_us_country"] = message_mentions_us_country(msg)

    return result


def is_business_search_query(message: str | None) -> bool:
    m = (message or "").lower()
    if not m.strip():
        return False
    parsed = convert_query_to_portuguese_fields(message)
    if parsed.get("is_business_search") or parsed.get("category_pt") or parsed.get("category_en"):
        return True
    dining = (
        "restaurant",
        "restaurante",
        "restaurants",
        "dining",
        "eatery",
        "eateries",
        "gastronom",
        "café",
        "cafe",
        "bakery",
        "food near",
        "food in",
        "comida",
        "churrasc",
        "lanchonete",
        "where to eat",
        "places to eat",
        "somewhere to eat",
        "go out to eat",
    )
    if any(d in m for d in dining):
        return True
    triggers = (
        "find ",
        "search ",
        "look for",
        "looking for",
        "need a ",
        "show me",
        "list of",
        "give me",
        "recommend",
        "any ",
    )
    nouns = ("restaurant", "food", "business", "lawyer", "doctor", "plumber", "attorney", "salon", "shop")
    if any(t in m for t in triggers) and any(n in m for n in nouns):
        return True
    return False


def _merge_and_parts(*parts: dict | None) -> dict | None:
    merged = [p for p in parts if p]
    if not merged:
        return None
    if len(merged) == 1:
        return merged[0]
    return {"$and": merged}


def _llm_directory_search_hints(query: str) -> dict | None:
    """
    When heuristics miss Lista PT labels or geo, one structured LLM pass fills category + location fields.
    """
    q = (query or "").strip()
    if not q or len(q) > 600:
        return None
    try:
        from chatbot.geo_constants import backfill_state_from_major_us_city
        from chatbot.services import gpt_service

        cli = getattr(gpt_service, "client", None)
        if not cli:
            return None
        model = getattr(settings, "GPT_MODEL", "gpt-4o-mini")
        sys = """From the user message, extract Braelo directory search fields. Return JSON only with keys:
category_pt, subcategory_pt, category_en, subcategory_en, city, state_en, county
Each value is a string or null. Use Lista Portuguese labels when clear (e.g. restaurants -> Gastronomia, Restaurantes).
state_en must be a full US state name in English (e.g. California) or null.
Only include fields you are reasonably sure about; use null for unknown."""
        resp = cli.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": q[:900]},
            ],
            max_tokens=200,
            temperature=0.15,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        out: dict = {}
        for k in (
            "category_pt",
            "subcategory_pt",
            "category_en",
            "subcategory_en",
            "city",
            "state_en",
            "county",
        ):
            v = data.get(k)
            if v is not None and str(v).strip():
                out[k] = str(v).strip()
        if not out:
            return None
        c = out.get("city")
        s = out.get("state_en")
        if c and s:
            merged = backfill_state_from_major_us_city(s, c)
            if merged:
                out["state_en"] = merged
        elif c and not s:
            inf = backfill_state_from_major_us_city(None, c)
            if inf:
                out["state_en"] = inf
        return out or None
    except Exception:
        logger.exception("business_search_service.llm_directory_hints_failed")
        return None


def _execute_directory_mongo_levels(
    db,
    col_names: list,
    dual: dict,
    *,
    lista_cat_pt: str | None = None,
    lista_sub_pt: str | None = None,
    state_en: str | None,
    city: str | None,
    county: str | None,
    zip_code: str | None,
    limit: int,
    listing_name_terms: list[str] | None = None,
) -> list[dict]:
    """
    Layered Mongo filters, union results up to ``limit`` (cap per page, not a minimum).

    When the user supplied city, county, or ZIP, we run **geo tiers** first: city/county/ZIP-scoped
    queries. If any row matches those tiers, we **stop** — we do not keep broadening to state-only or
    category-only just to fill ``limit`` rows. That keeps the list length equal to real matches (up
    to the cap) instead of padding with out-of-area listings.

    If strict geo tiers return nothing, we fall back: Lista tripod + state-scoped dual queries, then
    category-only (national) as a last resort.

    When ``listing_name_terms`` is set (e.g. Brazilian, sushi), AND name/tags match across tiers.
    """
    loc_q = _city_or_county_clause(city) if city else None
    county_q = _county_regex(county) if county else None
    st_part = _state_clause(state_en)
    zip_part = _zip_clause(zip_code)
    name_part = _listing_text_hint_clause(listing_name_terms or [])

    seen_lvl: set[str] = set()
    levels_local: list[dict] = []
    levels_regional: list[dict] = []
    levels_global: list[dict] = []

    def _add_level(bucket: list[dict], *parts: dict | None):
        seq = [p for p in parts if p]
        if name_part:
            seq.append(name_part)
        m = _merge_and_parts(*seq)
        if not m:
            return
        key = str(m)
        if key in seen_lvl:
            return
        seen_lvl.add(key)
        bucket.append(m)

    tripod = _lista_tripod_clause(lista_cat_pt, lista_sub_pt, state_en)
    if tripod:
        _add_level(levels_regional, tripod)

    if loc_q:
        _add_level(levels_local, dual, loc_q, st_part, zip_part)
        _add_level(levels_local, dual, loc_q, st_part)
        _add_level(levels_local, dual, loc_q, zip_part)
        _add_level(levels_local, dual, loc_q)
    if county_q:
        _add_level(levels_local, dual, county_q, st_part, zip_part)
        _add_level(levels_local, dual, county_q, st_part)
        _add_level(levels_local, dual, county_q)
    if st_part:
        if zip_part:
            _add_level(levels_local, dual, st_part, zip_part)
        _add_level(levels_regional, dual, st_part)
    if zip_part:
        _add_level(levels_local, dual, zip_part)
    _add_level(levels_global, dual)

    has_precise_geo = bool(
        (city or "").strip()
        or (county or "").strip()
        or (zip_code and str(zip_code).strip())
    )

    seen: set[str] = set()
    out: list[dict] = []
    lim = max(1, int(limit or 7))

    def _run_bucket(bucket: list[dict]) -> bool:
        """Run queries in ``bucket``; return True if ``lim`` rows collected."""
        for extra in bucket:
            q = {"$and": [_base_filter(), extra]}
            for coll_name in col_names:
                try:
                    cur = db[coll_name].find(q).limit(lim * 2)
                    for doc in cur:
                        sid = str(doc.get("_id"))
                        if sid in seen:
                            continue
                        if doc.get("is_banned"):
                            continue
                        seen.add(sid)
                        out.append(doc)
                        if len(out) >= lim:
                            logger.info(
                                "business_search_service.hits dual_schema coll=%s n=%s",
                                coll_name,
                                len(out),
                            )
                            return True
                except Exception:
                    logger.exception("business_search_service.query_failed coll=%s", coll_name)
        return False

    if has_precise_geo:
        _run_bucket(levels_local)
        if out:
            return out[:lim]
        # User named a city: do not pad with state-only or national rows (wrong metro).
        if (city or "").strip():
            return out[:lim]
        _run_bucket(levels_regional)
        if out:
            return out[:lim]
        _run_bucket(levels_global)
        return out[:lim]

    ordered = levels_regional + levels_local + levels_global
    for extra in ordered:
        q = {"$and": [_base_filter(), extra]}
        for coll_name in col_names:
            try:
                cur = db[coll_name].find(q).limit(lim * 2)
                for doc in cur:
                    sid = str(doc.get("_id"))
                    if sid in seen:
                        continue
                    if doc.get("is_banned"):
                        continue
                    seen.add(sid)
                    out.append(doc)
                    if len(out) >= lim:
                        logger.info(
                            "business_search_service.hits dual_schema coll=%s n=%s",
                            coll_name,
                            len(out),
                        )
                        return out[:lim]
            except Exception:
                logger.exception("business_search_service.query_failed coll=%s", coll_name)
    return out[:lim]


def search_businesses_in_mongodb(
    *,
    query: str,
    state: str | None = None,
    city: str | None = None,
    county: str | None = None,
    zip_code: str | None = None,
    category_pt: str | None = None,
    subcategory_pt: str | None = None,
    category_en: str | None = None,
    subcategory_en: str | None = None,
    limit: int = 7,
    offset: int = 0,
    caller_geo_only: bool = False,
) -> dict:
    """
    Lista / mixed-schema Mongo directory search.

    Location follows the directory geo policy documented at the top of this module: state as anchor,
    city and county when provided, US-country-only without inventing state, then layered strict→loose
    queries so database matches are preferred over empty results.
    """
    if not getattr(settings, "USE_MONGO", False):
        return {"businesses": [], "see_more": False}

    parsed = convert_query_to_portuguese_fields(query)
    ep = dict(parsed)
    if caller_geo_only:
        ep = {**ep, "city": None, "state_en": None, "county": None}

    def _cat_axis_ok(d: dict) -> bool:
        return bool(
            (category_pt or d.get("category_pt") or "").strip()
            or (subcategory_pt or d.get("subcategory_pt") or "").strip()
            or (category_en or d.get("category_en") or "").strip()
            or (subcategory_en or d.get("subcategory_en") or "").strip()
        )

    if not _cat_axis_ok(ep):
        hints0 = _llm_directory_search_hints(query)
        if hints0:
            for k, v in hints0.items():
                if isinstance(v, str) and v.strip():
                    ep[k] = v.strip()

    cat_pt = (category_pt or ep.get("category_pt") or "").strip() or None
    sub_pt = (subcategory_pt or ep.get("subcategory_pt") or "").strip() or None
    cat_en = (category_en or ep.get("category_en") or "").strip() or None
    sub_en = (subcategory_en or ep.get("subcategory_en") or "").strip() or None

    if not any([cat_pt, sub_pt, cat_en, sub_en]):
        logger.info("business_search_service.skip no category axis")
        return {"businesses": [], "see_more": False}

    city_s, county_s, st_raw = _merge_caller_and_message_geo(city, county, state, ep)
    st_en = _finalize_directory_state(query, st_raw, city_s, zip_code)

    try:
        from chatbot.mongo_db import get_db

        db = get_db()
    except Exception:
        logger.exception("business_search_service.mongo_connect_failed")
        return {"businesses": [], "see_more": False}

    col_names = getattr(settings, "MONGO_BUSINESS_COLLECTIONS", None) or ["businesses"]
    if isinstance(col_names, str):
        col_names = [x.strip() for x in col_names.split(",") if x.strip()]

    dual = _dual_schema_category_or(cat_pt, sub_pt, cat_en, sub_en)
    if not dual:
        return {"businesses": [], "see_more": False}

    off = max(0, int(offset or 0))
    page_lim = max(1, int(limit or 7))
    fetch_lim = off + page_lim + 1
    listing_name_terms = extract_listing_name_filter_terms(query)
    if listing_name_terms:
        logger.info(
            "business_search_service.listing_name_terms %s",
            listing_name_terms,
        )

    out = _execute_directory_mongo_levels(
        db,
        col_names,
        dual,
        lista_cat_pt=cat_pt,
        lista_sub_pt=sub_pt,
        state_en=st_en,
        city=city_s,
        county=county_s,
        zip_code=zip_code,
        limit=fetch_lim,
        listing_name_terms=listing_name_terms,
    )
    if not out and listing_name_terms:
        out = _execute_directory_mongo_levels(
            db,
            col_names,
            dual,
            lista_cat_pt=cat_pt,
            lista_sub_pt=sub_pt,
            state_en=st_en,
            city=city_s,
            county=county_s,
            zip_code=zip_code,
            limit=fetch_lim,
            listing_name_terms=None,
        )
        if out:
            logger.info(
                "business_search_service.listing_name_fallback_no_text_match n=%s",
                len(out),
            )

    if not out:
        hints = _llm_directory_search_hints(query)
        if hints:
            ep2 = dict(parsed)
            for k, v in hints.items():
                if isinstance(v, str) and v.strip():
                    ep2[k] = v.strip()
            cat_pt = cat_pt or ep2.get("category_pt")
            sub_pt = sub_pt or ep2.get("subcategory_pt")
            cat_en = cat_en or ep2.get("category_en")
            sub_en = sub_en or ep2.get("subcategory_en")
            city_s, county_s, st_raw = _merge_caller_and_message_geo(city, county, state, ep2)
            st_en = _finalize_directory_state(query, st_raw, city_s, zip_code)
            dual2 = _dual_schema_category_or(cat_pt, sub_pt, cat_en, sub_en)
            if dual2:
                out = _execute_directory_mongo_levels(
                    db,
                    col_names,
                    dual2,
                    lista_cat_pt=cat_pt,
                    lista_sub_pt=sub_pt,
                    state_en=st_en,
                    city=city_s,
                    county=county_s,
                    zip_code=zip_code,
                    limit=fetch_lim,
                    listing_name_terms=listing_name_terms,
                )
                if not out and listing_name_terms:
                    out = _execute_directory_mongo_levels(
                        db,
                        col_names,
                        dual2,
                        lista_cat_pt=cat_pt,
                        lista_sub_pt=sub_pt,
                        state_en=st_en,
                        city=city_s,
                        county=county_s,
                        zip_code=zip_code,
                        limit=fetch_lim,
                        listing_name_terms=None,
                    )
                if out:
                    logger.info(
                        "business_search_service.llm_geo_category_retry n=%s",
                        len(out),
                    )

    logger.info(
        "business_search_service.done n=%s pt=%s/%s en=%s/%s state=%s city=%s",
        len(out),
        cat_pt,
        sub_pt,
        cat_en,
        sub_en,
        st_en,
        city_s,
    )
    page = out[off : off + page_lim]
    see_more = len(out) > off + page_lim
    return {"businesses": page, "see_more": see_more}


BANNED_SUGGESTIONS_BLOCK = """
CRITICAL — NEVER suggest any of these (inappropriate for this app):
- "Visit libraries or community centers"
- "Ask at city hall" or government offices for basic business listings
- "Visit social services" or "ask neighbors" or bulletin boards
- Generic offline walk-around advice instead of online search tools

ONLY suggest practical online resources when the directory has no rows:
- Google Maps (with a specific search query for the category and area)
- Yelp or a category-relevant app (Uber, Zillow, ZocDoc, etc. when appropriate)
- Trusted local Facebook or WhatsApp groups for Brazilian/Latino immigrants in that city
"""


def _strip_banned_suggestion_phrases(text: str) -> str:
    if not text:
        return text
    low = text.lower()
    banned_fragments = (
        "visit libraries",
        "community centers for information",
        "ask at city hall",
        "city hall",
        "bulletin board",
        "ask neighbors",
        "social services office",
    )
    if not any(b in low for b in banned_fragments):
        return text
    parts = re.split(r"(?<=[.!?])\s+", text)
    cleaned = [p for p in parts if not any(b in p.lower() for b in banned_fragments)]
    return " ".join(cleaned).strip() or text


def generate_business_not_found_response(
    query: str,
    *,
    city: str | None = None,
    state: str | None = None,
    county: str | None = None,
    zip_code: str | None = None,
    category_pt: str | None = None,
    subcategory_pt: str | None = None,
    category_en: str | None = None,
    subcategory_en: str | None = None,
    detected_language: str = "en",
    language_continuation_note: str = "",
    established_context: dict | None = None,
) -> str:
    """
    After the directory search returns no rows: short, helpful guidance (LLM when available).
    Does not use the old “no listings in Braelo’s directory” refusal tone.
    """
    q = (query or "").strip()
    parsed = convert_query_to_portuguese_fields(q) if q else {}
    cpt = category_pt or parsed.get("category_pt")
    spt = subcategory_pt or parsed.get("subcategory_pt")
    cen = category_en or parsed.get("category_en")
    sen = subcategory_en or parsed.get("subcategory_en")
    city_f = (city or parsed.get("city") or "").strip()
    state_f = (state or parsed.get("state_en") or "").strip()
    county_f = (county or parsed.get("county") or "").strip()
    zip_f = (zip_code or "").strip()

    est = established_context or {}
    if est.get("biz_cat"):
        display_category = est["biz_cat"]
    elif est.get("biz_sub"):
        display_category = est["biz_sub"]
    else:
        display_category = (
            cen
            or cpt
            or sen
            or spt
            or "local businesses"
        )
    loc_parts = [p for p in (city_f, county_f, state_f, zip_f) if p]
    if not loc_parts and est:
        loc_parts = [p for p in (est.get("city"), est.get("state"), est.get("zip_code")) if p]
    location_str = ", ".join(loc_parts) if loc_parts else "your area"

    context_note = ""
    if est and (est.get("biz_cat") or est.get("city") or est.get("state")):
        context_note = f"""
ESTABLISHED CONTEXT (already known — do NOT ask again):
- Category: {est.get('biz_cat') or display_category}
- Location: {est.get('city') or city_f or est.get('state') or state_f or 'user area'}

Do NOT ask "what are you looking for?" or "what type of service?" — continue the same search.
"""

    lang = (detected_language or "en").lower()[:2]
    lang_instruction = {
        "en": "Respond entirely in clear English.",
        "es": "Responde completamente en español.",
        "pt": "Responda inteiramente em português (Brasil).",
    }.get(lang, "Respond in clear English.")

    system_prompt = f"""You are Braelo, a helpful assistant for the US Latino and immigrant community.

The user is looking for: {display_category}
Location context: {location_str}
{context_note}

Braelo's internal partner directory returned no rows for this category + location.

{BANNED_SUGGESTIONS_BLOCK}

Give a SHORT reply (max 80 words):
1. Say clearly (first sentence) that there were no matches in Braelo's directory for {display_category} in {location_str}.
2. Suggest 2–3 SPECIFIC online resources (Google Maps and Yelp with a concrete search phrase, or an app relevant to {display_category}).
3. {lang_instruction}
4. Do NOT ask what they are looking for if category/location are already established above.
5. At most one short follow-up question (e.g. wider area), not a generic "what do you need?" question."""

    if (language_continuation_note or "").strip():
        system_prompt = f"{system_prompt}\n\n{language_continuation_note.strip()[:1200]}"

    try:
        from chatbot.services import gpt_service

        cli = getattr(gpt_service, "client", None)
        if cli:
            model = getattr(settings, "GPT_MODEL", "gpt-4o-mini")
            resp = cli.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": q[:2000] or display_category},
                ],
                max_tokens=220,
                temperature=0.45,
            )
            out = (resp.choices[0].message.content or "").strip()
            if out:
                return _strip_banned_suggestion_phrases(out)
    except Exception:
        logger.exception("business_search_service.generate_business_not_found_response.llm_failed")

    if lang == "es":
        return (
            f"No encontré coincidencias en el directorio de Braelo para {display_category} en {location_str}. "
            f"¿Quieres que pruebe un área más amplia o otra palabra clave? Mientras tanto, puedes buscar en Google Maps, "
            f"en páginas oficiales del estado o en grupos locales de confianza."
        )
    if lang == "pt":
        return (
            f"Não encontrei correspondências no diretório da Braelo para {display_category} em {location_str}. "
            f"Quer que eu tente uma área maior ou outra palavra-chave? Enquanto isso, use o Google Maps, "
            f"sites oficiais do estado ou grupos locais de confiança."
        )
    return (
        f"I did not find matches in Braelo's directory for {display_category} in {location_str}. "
        f"Want me to try a wider area or a different keyword? Meanwhile you can search Google Maps, "
        f"official state pages, or trusted local community groups."
    )


def _languages_to_display(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, list):
        return ",".join(str(x) for x in val if x)
    s = str(val).strip()
    return s or None


def _normalize_contact_display(raw) -> str:
    """Readable one-line or short block for Schema A phone vs Lista block."""
    if raw is None:
        return ""
    if isinstance(raw, dict):
        parts = [f"{k}: {v}" for k, v in raw.items() if v and str(v).strip()]
        return " | ".join(parts)
    s = str(raw).strip()
    if not s:
        return ""
    if "[ListaBusiness" in s or "Social:" in s or "Phone:" in s.split("\n")[0]:
        lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
        return "\n".join(lines[:6])
    return s


def _mongo_tag_match_blob(doc: dict) -> str:
    """Single lowercase-ish haystack for name + tags/TAGS + categories (directory confirmation / filters)."""
    parts: list[str] = []
    for k in (
        "name",
        "business_name",
        "tags",
        "TAGS",
        "category",
        "business_category",
        "subcategory",
        "business_subcategory",
        "description",
    ):
        v = doc.get(k)
        if v is None:
            continue
        if isinstance(v, list):
            parts.append(" ".join(str(x) for x in v))
        else:
            parts.append(str(v))
    return " ".join(parts).strip()


def mongo_docs_to_api_businesses(
    docs: list[dict],
    external_id: str | None,
    session_id: str | None,
) -> list[dict]:
    """API rows: consistent languages string + contact display for both schemas."""
    if not docs:
        return []
    try:
        from chatbot.mongo_db import get_db
        from chatbot.services.business_matching import _normalize_mongo_business, _ad_package_priority_map

        db = get_db()
        pkg_prio = _ad_package_priority_map(db)
    except Exception:
        logger.exception("business_search_service.normalize_import_failed")
        return []

    out_list = []
    for b in docs:
        try:
            n = _normalize_mongo_business(b)
        except Exception:
            logger.exception("business_search_service.skip_bad_doc")
            continue
        bid = str(b.get("_id"))
        langs = _languages_to_display(b.get("languages")) or n.get("languages")
        contact_line = n["contact"] or _normalize_contact_display(b.get("contact_info"))
        contact_line = _normalize_contact_display(contact_line) if contact_line else ""
        if n["whatsapp_url"] and n["whatsapp_url"] not in contact_line:
            contact_line = f"{contact_line}  {n['whatsapp_url']}".strip()
        out_list.append(
            {
                "id": bid,
                "name": n["name"],
                "tag_match_text": _mongo_tag_match_blob(b),
                "category": n["category"],
                "subcategory": n["subcategory"],
                "state": n["state"],
                "city": n["city"],
                "county": n["county"],
                "zip_code": n.get("zip_code"),
                "languages": langs,
                "contact_info": contact_line or None,
                "whatsapp_url": n["whatsapp_url"] or "",
                "distance_miles": None,
                "is_sponsored": bool(
                    n["is_sponsored"] or pkg_prio.get(str(b.get("ad_package_name") or ""), 0) > 0
                ),
            }
        )
        try:
            db.impressions_log.insert_one(
                {
                    "business_id": bid,
                    "external_id": external_id,
                    "session_id": session_id,
                    "created_at": datetime.utcnow(),
                }
            )
        except Exception:
            logger.exception("business_search_service.impression_log_failed business_id=%s", bid)
    return out_list


def format_business_results_for_response(
    *,
    businesses: list[dict],
    query: str,
    detected_language: str,
) -> str:
    if not businesses:
        return ""
    lines = []
    for i, b in enumerate(businesses, 1):
        name = b.get("name") or "Business"
        city = b.get("city") or ""
        st = b.get("state") or ""
        loc = ", ".join(x for x in (city, st) if x)
        lines.append(f"{i}. {name}" + (f" — {loc}" if loc else ""))
    return "\n".join(lines)
