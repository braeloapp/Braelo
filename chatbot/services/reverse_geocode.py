"""
Reverse geocode lat/lon with OpenStreetMap Nominatim (same policy as local_search: respectful User-Agent).
Fills city / state / county / postcode when the client had GPS but no typed address.
"""
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import logging

logger = logging.getLogger(__name__)

_NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"


def reverse_geocode_us_location(latitude: float, longitude: float) -> dict:
    """
    Return normalized address fields for the US, or {} on failure.
    Keys: city, county, state, zip_code, display_name
    """
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return {}

    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "addressdetails": 1,
        "zoom": 18,
    }
    url = f"{_NOMINATIM_REVERSE}?{urlencode(params)}"
    req = Request(
        url,
        headers={
            "User-Agent": "BraeloChatbot/1.0 (reverse geocode for chat location)",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
    except Exception:
        logger.exception("reverse_geocode.nominatim_failed lat=%s lon=%s", latitude, longitude)
        return {}

    if not isinstance(data, dict) or data.get("error"):
        return {}

    addr = data.get("address") or {}

    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("hamlet")
        or addr.get("municipality")
        or addr.get("suburb")
        or ""
    )
    county = addr.get("county") or ""
    if county and isinstance(county, str) and county.lower().endswith(" county"):
        county = county[:-7].strip()

    # US reverse results usually use full state name ("Alaska"); matches KB state strings better than "US-AK".
    state = addr.get("state") or ""
    zip_code = addr.get("postcode") or ""
    if isinstance(zip_code, str) and "-" in zip_code:
        zip_code = zip_code.split("-")[0][:10]

    country_code = (addr.get("country_code") or "").strip().lower()
    country_name = (addr.get("country") or "").strip()

    out = {
        "city": str(city).strip() if city else "",
        "county": str(county).strip() if county else "",
        "state": str(state).strip() if state else "",
        "zip_code": str(zip_code).strip() if zip_code else "",
        "display_name": (data.get("display_name") or "").strip(),
        "country_code": country_code,
        "country": str(country_name) if country_name else "",
    }
    return {
        k: v
        for k, v in out.items()
        if v or k in ("display_name", "country_code", "country")
    }


def merge_gps_into_location(location: dict) -> dict:
    """
    Copy location and fill missing city/county/state/zip_code from reverse geocode
    when latitude and longitude are present.
    """
    if not location:
        return {}
    loc = dict(location)
    lat, lon = loc.get("latitude"), loc.get("longitude")
    if lat is None or lon is None:
        return loc

    explicit = bool(loc.get("explicit_address_in_request"))
    need = not (
        loc.get("city")
        and loc.get("state")
        and loc.get("zip_code")
        and loc.get("county")
    )
    if not need:
        return loc

    found = reverse_geocode_us_location(lat, lon)
    if not found:
        return loc

    cc = (found.get("country_code") or "").strip().lower()
    verified_city = (found.get("city") or "").strip()
    country_name = (found.get("country") or "").strip()

    if verified_city:
        loc["display_city"] = verified_city
    if country_name:
        loc["country"] = country_name
    if cc:
        loc["country_code"] = cc

    if cc == "us":
        loc.pop("use_device_location_only", None)
        if not loc.get("city") and verified_city:
            loc["city"] = verified_city
        if not loc.get("county") and found.get("county"):
            loc["county"] = found["county"]
        if not loc.get("state") and found.get("state"):
            loc["state"] = found["state"]
        if not loc.get("zip_code") and found.get("zip_code"):
            loc["zip_code"] = found["zip_code"]
        logger.info(
            "reverse_geocode.merged_us city=%s state=%s zip=%s",
            loc.get("city"),
            loc.get("state"),
            loc.get("zip_code"),
        )
    else:
        # Non-US: keep use_device_location_only for KB/RAG (US-specific fields), but pass verified city/country to LLM.
        loc["use_device_location_only"] = True
        if verified_city:
            loc["city"] = verified_city
        logger.info(
            "reverse_geocode.merged_intl city=%s country=%s country_code=%s lat=%s lon=%s",
            loc.get("city"),
            loc.get("country"),
            cc or "?",
            lat,
            lon,
        )

    return loc
