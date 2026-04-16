"""
Reverse geocoding via Google Geocoding API (same API key as Places when enabled in Cloud Console).
Used to derive state, city, county, zip from lat/lng (e.g. Map picker coordinates).
"""
import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def _google_maps_api_key() -> str:
    """
    Use GOOGLE_PLACES_API_KEY from .env (config.settings) for Geocoding API calls.
    Enable "Geocoding API" for that key in Google Cloud Console.
    If empty, fall back to GOOGLE_MAPS_GEOCODING_API_KEY when set.
    """
    places = (getattr(settings, "GOOGLE_PLACES_API_KEY", None) or "").strip()
    if places:
        return places
    return (getattr(settings, "GOOGLE_MAPS_GEOCODING_API_KEY", None) or "").strip()


def _find_component_long_name(components: list[dict], *wanted_types: str) -> str:
    for c in components:
        types = set(c.get("types") or [])
        if types.intersection(wanted_types):
            return (c.get("long_name") or "").strip()
    return ""


def parse_geocode_result(result: dict[str, Any]) -> dict[str, Any]:
    """
    Extract country, state, city, county, zip from one Geocoding API result.

    - ``country``: from the ``country`` component (e.g. United States) — not county.
    - ``county``: US ``administrative_area_level_2`` (e.g. Los Angeles County).
    - ``city``: locality / sublocality — never use level_2 here (that is county, not city).
    """
    components = result.get("address_components") or []
    country = _find_component_long_name(components, "country")
    state = _find_component_long_name(components, "administrative_area_level_1")
    city = (
        _find_component_long_name(components, "locality")
        or _find_component_long_name(
            components, "sublocality", "sublocality_level_1", "neighborhood"
        )
        or _find_component_long_name(components, "administrative_area_level_3")
    )
    county = _find_component_long_name(components, "administrative_area_level_2")
    zip_code = _find_component_long_name(components, "postal_code")
    return {
        "country": country or None,
        "state": state or None,
        "city": city or None,
        "county": county or None,
        "zip_code": zip_code or None,
    }


def reverse_geocode_latlng(lat: float, lng: float) -> dict[str, Any]:
    """
    Call Google Geocoding API reverse geocode. Returns keys: state, city, county, zip_code (values may be None).

    On failure or missing API key, returns empty dict (caller should fall back).
    """
    key = _google_maps_api_key()
    if not key:
        logger.warning("google_geocoding.reverse_geocode_latlng no API key configured")
        return {}

    try:
        r = requests.get(
            GEOCODE_URL,
            params={"latlng": f"{lat},{lng}", "key": key},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        logger.exception("google_geocoding.reverse_geocode_latlng request_failed")
        return {}

    status = data.get("status")
    results = data.get("results") or []
    if status not in ("OK", "ZERO_RESULTS") or not results:
        if status and status not in ("OK", "ZERO_RESULTS"):
            logger.warning(
                "google_geocoding.reverse_geocode_latlng status=%s error=%s",
                status,
                data.get("error_message"),
            )
        return {}

    return parse_geocode_result(results[0])


def forward_geocode_address(address: str) -> dict[str, Any]:
    """
    Geocode a free-text address (e.g. \"Los Angeles, CA, USA\").

    Use this for state/city/county/zip so the `businesses` row matches what the
    user typed. Reverse-geocode from lat/lng alone follows the pin, which can
    disagree with `business_address` when coordinates and address differ.

    Returns same keys as parse_geocode_result; empty dict on failure.
    """
    address = (address or "").strip()
    if not address:
        return {}

    key = _google_maps_api_key()
    if not key:
        logger.warning("google_geocoding.forward_geocode_address no API key configured")
        return {}

    try:
        r = requests.get(
            GEOCODE_URL,
            params={"address": address, "key": key},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        logger.exception("google_geocoding.forward_geocode_address request_failed")
        return {}

    status = data.get("status")
    results = data.get("results") or []
    if status not in ("OK", "ZERO_RESULTS") or not results:
        if status and status not in ("OK", "ZERO_RESULTS"):
            logger.warning(
                "google_geocoding.forward_geocode_address status=%s error=%s",
                status,
                data.get("error_message"),
            )
        return {}

    return parse_geocode_result(results[0])
