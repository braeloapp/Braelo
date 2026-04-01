import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PLACES_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
PLACES_TEXT_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"


def search_nearby_places(
    latitude: float,
    longitude: float,
    keyword: str,
    radius_meters: int = 6000,
    max_results: int = 7,
) -> list:
    """
    Calls Google Places Nearby Search API to get real businesses
    within radius_meters of the given lat/lng.

    Returns a list of dicts with:
      - name: business name
      - address: formatted address (English)
      - rating: float or None
      - total_ratings: int
      - phone: phone number or None
      - maps_url: direct Google Maps URL to this place
      - place_id: Google place ID
      - open_now: bool or None
      - types: list of business type strings
    """
    api_key = getattr(settings, "GOOGLE_PLACES_API_KEY", None)
    if not api_key:
        logger.warning("[GooglePlaces] GOOGLE_PLACES_API_KEY not set in settings")
        return []

    params = {
        "location": f"{latitude},{longitude}",
        "radius": radius_meters,
        "keyword": keyword,
        "key": api_key,
        "language": "en",
    }

    try:
        response = requests.get(
            PLACES_NEARBY_URL,
            params=params,
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()

        status = data.get("status")
        if status == "ZERO_RESULTS":
            logger.info(
                "[GooglePlaces] No results for '%s' near %s,%s",
                keyword,
                latitude,
                longitude,
            )
            return []
        if status != "OK":
            logger.warning("[GooglePlaces] API returned status: %s", status)
            return []

        results = data.get("results", [])[:max_results]
        places = []

        for place in results:
            place_id = place.get("place_id", "")

            phone = _get_place_phone(place_id, api_key)

            maps_url = (
                f"https://www.google.com/maps/place/?q=place_id:{place_id}"
                if place_id
                else f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
            )

            opening_hours = place.get("opening_hours", {})

            places.append(
                {
                    "name": place.get("name", ""),
                    "address": place.get("vicinity", ""),
                    "rating": place.get("rating"),
                    "total_ratings": place.get("user_ratings_total", 0),
                    "phone": phone,
                    "maps_url": maps_url,
                    "place_id": place_id,
                    "open_now": opening_hours.get("open_now"),
                    "types": place.get("types", []),
                }
            )

        logger.info(
            "[GooglePlaces] Found %s results for '%s' near %.4f,%.4f",
            len(places),
            keyword,
            latitude,
            longitude,
        )
        return places

    except requests.exceptions.Timeout:
        logger.error("[GooglePlaces] Request timed out")
        return []
    except requests.exceptions.RequestException as e:
        logger.error("[GooglePlaces] Request failed: %s", e)
        return []
    except Exception as e:
        logger.error("[GooglePlaces] Unexpected error: %s", e)
        return []


def _get_place_phone(place_id: str, api_key: str):
    """
    Calls Places Details API to get the phone number for a place.
    Returns None if unavailable or on error.
    """
    if not place_id:
        return None
    try:
        params = {
            "place_id": place_id,
            "fields": "formatted_phone_number",
            "key": api_key,
            "language": "en",
        }
        response = requests.get(
            PLACES_DETAILS_URL,
            params=params,
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        result = data.get("result", {})
        return result.get("formatted_phone_number")
    except Exception as e:
        logger.debug("[GooglePlaces] Phone fetch failed for %s: %s", place_id, e)
        return None


def format_places_for_response(
    places: list,
    detected_language: str = "en",
) -> str:
    """
    Formats the Google Places results into a clean numbered list
    ready to send to the user.
    """
    if not places:
        return ""

    labels = {
        "en": {
            "rating": "Rating",
            "reviews": "reviews",
            "phone": "Phone",
            "open": "Open now",
            "closed": "Closed now",
            "unknown": "Hours unknown",
            "maps": "Google Maps",
            "footer": (
                "I recommend calling ahead to confirm hours and availability."
            ),
        },
        "es": {
            "rating": "Calificación",
            "reviews": "reseñas",
            "phone": "Teléfono",
            "open": "Abierto ahora",
            "closed": "Cerrado ahora",
            "unknown": "Horario desconocido",
            "maps": "Google Maps",
            "footer": (
                "Te recomiendo llamar antes para confirmar horarios y disponibilidad."
            ),
        },
        "pt": {
            "rating": "Avaliação",
            "reviews": "avaliações",
            "phone": "Telefone",
            "open": "Aberto agora",
            "closed": "Fechado agora",
            "unknown": "Horário desconhecido",
            "maps": "Google Maps",
            "footer": (
                "Recomendo ligar antes para confirmar horários e disponibilidade."
            ),
        },
    }

    lang = labels.get((detected_language or "en").lower()[:2], labels["en"])
    lines = []

    for i, place in enumerate(places, 1):
        name = place.get("name", "Unknown")
        address = place.get("address", "")
        rating = place.get("rating")
        total = place.get("total_ratings", 0)
        phone = place.get("phone")
        maps_url = place.get("maps_url", "")
        open_now = place.get("open_now")

        if rating:
            rounded = int(round(float(rating)))
            rounded = max(0, min(5, rounded))
            stars = "★" * rounded + "☆" * (5 - rounded)
            rating_str = f"{stars} {rating}/5 ({total} {lang['reviews']})"
        else:
            rating_str = ""

        if open_now is True:
            status_str = f"✅ {lang['open']}"
        elif open_now is False:
            status_str = f"🔴 {lang['closed']}"
        else:
            status_str = f"🕐 {lang['unknown']}"

        block = [f"{i}. {name}"]
        if address:
            block.append(f"   📍 {address}")
        if rating_str:
            block.append(f"   {rating_str}")
        block.append(f"   {status_str}")
        if phone:
            block.append(f"   📞 {lang['phone']}: {phone}")
        if maps_url:
            block.append(f"   🗺️ {lang['maps']}: {maps_url}")

        lines.append("\n".join(block))

    result_text = "\n\n".join(lines)
    result_text += f"\n\n{lang['footer']}"
    return result_text


def search_places_text(
    query: str,
    latitude: float = None,
    longitude: float = None,
    radius_meters: int = None,
    max_results: int = 7,
) -> list:
    """
    Text Search API — useful when keyword alone is not specific enough.
    When latitude/longitude are omitted, search is not biased to a map center.
    """
    api_key = getattr(settings, "GOOGLE_PLACES_API_KEY", None)
    if not api_key:
        return []

    params = {
        "query": query,
        "key": api_key,
        "language": "en",
    }
    if latitude is not None and longitude is not None:
        params["location"] = f"{latitude},{longitude}"
        if radius_meters is not None:
            params["radius"] = radius_meters

    try:
        response = requests.get(
            PLACES_TEXT_URL,
            params=params,
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            logger.warning("[GooglePlaces TextSearch] status: %s", data.get("status"))
            return []

        results = data.get("results", [])[:max_results]
        places = []

        for place in results:
            place_id = place.get("place_id", "")
            phone = _get_place_phone(place_id, api_key)
            maps_url = (
                f"https://www.google.com/maps/place/?q=place_id:{place_id}"
                if place_id
                else ""
            )
            opening_hours = place.get("opening_hours", {})

            places.append(
                {
                    "name": place.get("name", ""),
                    "address": place.get("formatted_address", ""),
                    "rating": place.get("rating"),
                    "total_ratings": place.get("user_ratings_total", 0),
                    "phone": phone,
                    "maps_url": maps_url,
                    "place_id": place_id,
                    "open_now": opening_hours.get("open_now"),
                    "types": place.get("types", []),
                }
            )

        return places

    except Exception as e:
        logger.error("[GooglePlaces TextSearch] Error: %s", e)
        return []
