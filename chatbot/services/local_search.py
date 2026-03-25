"""
Lightweight nearby-place lookup using OpenStreetMap Nominatim.
Used for queries like "nearest DMV office in my area".
"""
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import logging

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def _nominatim_search(
    place_query: str,
    state: str = None,
    county: str = None,
    city: str = None,
    zip_code: str = None,
    limit: int = 3,
    max_results: int = 5,
    user_agent_note: str = "local lookup",
) -> list:
    if not place_query:
        return []

    location_parts = [p for p in [zip_code, city, county, state, "USA"] if p]
    location_str = ", ".join(location_parts)
    q = f"{place_query}, {location_str}" if location_str else f"{place_query}, USA"
    cap = max(1, min(int(max_results or 5), 15))
    params = {
        "q": q,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": max(1, min(int(limit or 3), cap)),
        "countrycodes": "us",
    }
    url = f"{_NOMINATIM_URL}?{urlencode(params)}"

    req = Request(
        url,
        headers={
            "User-Agent": f"BraeloChatbot/1.0 ({user_agent_note})",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
    except Exception:
        logger.exception("local_search.nominatim_request_failed")
        return []

    out = []
    for item in data if isinstance(data, list) else []:
        lat = item.get("lat")
        lon = item.get("lon")
        display = item.get("display_name") or ""
        map_url = None
        if lat and lon:
            map_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        out.append(
            {
                "name": item.get("name") or place_query,
                "display_name": display,
                "lat": lat,
                "lon": lon,
                "map_url": map_url,
            }
        )
    return out


def find_nearby_places(
    place_query: str,
    state: str = None,
    county: str = None,
    city: str = None,
    zip_code: str = None,
    limit: int = 3,
) -> list:
    """Government/office-style POIs; Nominatim limit capped at 5."""
    return _nominatim_search(
        place_query,
        state=state,
        county=county,
        city=city,
        zip_code=zip_code,
        limit=limit,
        max_results=5,
        user_agent_note="local office lookup",
    )


def find_nearby_pois(
    poi_query: str,
    state: str = None,
    county: str = None,
    city: str = None,
    zip_code: str = None,
    limit: int = 8,
) -> list:
    """Restaurants and other discoverable POIs; allows more results than office lookup."""
    return _nominatim_search(
        poi_query,
        state=state,
        county=county,
        city=city,
        zip_code=zip_code,
        limit=limit,
        max_results=10,
        user_agent_note="local poi lookup",
    )
