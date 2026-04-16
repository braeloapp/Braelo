"""
Mirror `business_listings` (MongoEngine) into flat Mongo `businesses` docs for chatbot/directory search.

Upsert key: `user_listing_id` (stringified ObjectId of the Business document).
"""
import json
import logging
import re
from datetime import datetime, timezone as py_tz
from typing import Any, Optional, Tuple

from django.conf import settings
from django.utils import timezone

from helpers.google_geocoding import forward_geocode_address, reverse_geocode_latlng

logger = logging.getLogger(__name__)

USER_LISTING_MARKER = "[UserListing]"


def _emit_sync_payload(doc: dict, *, geo_from_google: Optional[dict] = None) -> None:
    """Log (and optionally print) the payload written to Mongo `businesses` for local testing."""
    dbg = getattr(settings, "BUSINESS_DIRECTORY_SYNC_DEBUG", False)
    if not dbg:
        return
    extra = {"geo_from_google": geo_from_google} if geo_from_google is not None else {}
    blob = {
        "mongodb_businesses_payload": doc,
        **({"reverse_geocode": extra} if extra else {}),
    }
    text = json.dumps(blob, default=str, indent=2)
    logger.info("businesses_directory_sync debug payload:\n%s", text)
    print(
        "\n========== BUSINESS_DIRECTORY_SYNC ==========\n",
        text,
        "\n============================================\n",
        flush=True,
    )


def _digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def phone_to_whatsapp_url(phone: str) -> str:
    """Build https://wa.me/<digits> when enough digits exist."""
    d = _digits_only(phone)
    if len(d) < 8:
        return ""
    return f"https://wa.me/{d}"


def _contact_info_from_listing(instance) -> str:
    parts = [f"{USER_LISTING_MARKER}\n"]
    web = (getattr(instance, "business_website", None) or "").strip()
    email = (getattr(instance, "business_email", None) or "").strip()
    phone = (getattr(instance, "business_number", None) or "").strip()
    addr = (getattr(instance, "business_address", None) or "").strip()
    if web:
        parts.append(f"Website: {web}")
    if email:
        parts.append(f"Email: {email}")
    if phone:
        parts.append(f"Phone: {phone}")
    if addr:
        parts.append(f"Address: {addr}")
    return "\n".join(parts).strip()


def _coerce_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _raw_coordinates_from_point(pt) -> Optional[Tuple[Any, Any]]:
    """
    MongoEngine PointField may be stored/loaded as:
    - GeoJSON dict: {'type': 'Point', 'coordinates': [lon, lat]}
    - SON (dict subclass)
    - plain list/tuple [lon, lat] (see mongoengine PointField docs)
    """
    if pt is None:
        return None
    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
        return (pt[0], pt[1])
    if isinstance(pt, dict):
        c = pt.get("coordinates")
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            return (c[0], c[1])
    coords = getattr(pt, "coordinates", None)
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        return (coords[0], coords[1])
    return None


def _normalize_geojson_lon_lat(lon: float, lat: float) -> Tuple[float, float]:
    """
    GeoJSON order is [longitude, latitude]. Fix:
    - invalid pairs (lat cannot exceed 90 in magnitude when used as latitude)
    - common mistake: [latitude, longitude] for positive lon/lat (e.g. 31N, 74E).
    """
    if abs(lat) > 90 or abs(lon) > 180:
        lon, lat = lat, lon
    if (
        lon > 0
        and lat > 0
        and lon < lat
        and lon < 55
        and lat > 55
    ):
        lon, lat = lat, lon
    return lon, lat


def _extract_lon_lat(instance):
    pt = getattr(instance, "business_coordinates", None)
    pair = _raw_coordinates_from_point(pt)
    if pair is None and hasattr(instance, "to_mongo"):
        try:
            raw_doc = instance.to_mongo()
            raw_pt = (
                raw_doc.get("business_coordinates")
                if isinstance(raw_doc, dict)
                else None
            )
            pair = _raw_coordinates_from_point(raw_pt)
        except Exception:
            logger.exception("businesses_directory_sync.to_mongo_coordinates_failed")
    if not pair:
        return None, None
    a, b = pair
    lon = _coerce_float(a)
    lat = _coerce_float(b)
    if lon is None or lat is None:
        return None, None
    lon, lat = _normalize_geojson_lon_lat(lon, lat)
    return lon, lat


def _infer_country_from_address_text(address: str) -> Optional[str]:
    """Last segment after commas often is country (e.g. 'Los Angeles, CA, USA')."""
    a = (address or "").strip()
    if not a:
        return None
    parts = [p.strip() for p in a.split(",") if p.strip()]
    if not parts:
        return None
    tail = parts[-1].upper()
    if tail in ("USA", "US", "U.S.", "U.S.A.", "UNITED STATES", "UNITED STATES OF AMERICA"):
        return "United States"
    if tail in ("UK", "U.K.", "UNITED KINGDOM", "GREAT BRITAIN", "GB"):
        return "United Kingdom"
    if tail in ("CA", "CAN", "CANADA"):
        return "Canada"
    if tail in ("BR", "BRASIL", "BRAZIL"):
        return "Brazil"
    if tail in ("PK", "PAKISTAN"):
        return "Pakistan"
    return None


def _geo_fallback_from_address(address: str) -> dict:
    """When geocoding is unavailable: expose free-text in city; infer country from tail if possible."""
    a = (address or "").strip()
    if not a:
        return {
            "country": None,
            "state": None,
            "city": None,
            "county": None,
            "zip_code": None,
        }
    country = _infer_country_from_address_text(a)
    return {
        "country": country,
        "state": None,
        "city": a,
        "county": None,
        "zip_code": None,
    }


def _created_at_naive_utc(instance):
    ca = getattr(instance, "created_at", None)
    if not ca:
        return datetime.utcnow()
    if timezone.is_aware(ca):
        return ca.astimezone(py_tz.utc).replace(tzinfo=None)
    return ca


def build_businesses_doc(instance) -> Tuple[dict, Optional[dict]]:
    """
    Build a Lista-shaped dict (without _id) for the `businesses` collection.

    Returns (doc, geo_from_google_or_none) for logging.
    """
    listing_id = str(instance.id)
    lon, lat = _extract_lon_lat(instance)

    address_text = (getattr(instance, "business_address", None) or "").strip()

    geo_from_google = None
    geo = {}

    # Prefer free-text address so state/city/county/zip match what the user entered
    # (e.g. "Los Angeles, CA, USA"). Coordinates alone reverse-geocode the pin only
    # and can disagree when the map pin and typed address differ.
    if address_text:
        geo_addr = forward_geocode_address(address_text) or {}
        if any(
            geo_addr.get(k)
            for k in ("country", "state", "city", "county", "zip_code")
        ):
            geo = geo_addr
            geo_from_google = {"forward_address": geo_addr}

    if not geo or not any(
        geo.get(k) for k in ("country", "state", "city", "county", "zip_code")
    ):
        if lat is not None and lon is not None:
            geo_rev = reverse_geocode_latlng(lat, lon) or {}
            if geo_rev:
                if not geo:
                    geo = geo_rev
                else:
                    for k in ("country", "state", "city", "county", "zip_code"):
                        if not geo.get(k) and geo_rev.get(k):
                            geo[k] = geo_rev[k]
                if geo_from_google is None:
                    geo_from_google = {}
                geo_from_google["reverse_latlng"] = geo_rev

    if not geo or not any(
        geo.get(k) for k in ("country", "state", "city", "county", "zip_code")
    ):
        fb = _geo_fallback_from_address(address_text)
        for k, v in fb.items():
            if v and not geo.get(k):
                geo[k] = v

    name = getattr(instance, "business_name", None) or ""
    category = getattr(instance, "business_category", None) or ""
    subcategory = getattr(instance, "business_subcategory", None) or ""
    goals = (getattr(instance, "business_goals", None) or "").strip()
    base_tags = goals if goals else f"{category} {subcategory}".strip()

    # Align EN/ES admin labels with Lista + seed EN tokens used by chatbot Mongo search
    try:
        from chatbot.services.business_search_service import (
            collect_directory_search_tokens_from_listing_text,
        )

        extra_tokens = collect_directory_search_tokens_from_listing_text(
            name, category, subcategory, goals
        )
    except Exception:
        logger.exception("businesses_directory_sync.collect_search_tokens_failed")
        extra_tokens = []

    if extra_tokens:
        unique_extra = list(dict.fromkeys(extra_tokens))
        extra_blob = " | ".join(unique_extra)
        tags = f"{base_tags} | {extra_blob}" if base_tags else extra_blob
    else:
        tags = base_tags

    is_active = bool(getattr(instance, "is_active", True))

    doc = {
        "user_listing_id": listing_id,
        "name": name,
        "category": category,
        "subcategory": subcategory,
        "country": geo.get("country"),
        "state": geo.get("state"),
        "city": geo.get("city"),
        "county": geo.get("county"),
        "zip_code": geo.get("zip_code"),
        "latitude": lat,
        "longitude": lon,
        "languages": ["en", "es", "pt"],
        "contact_info": _contact_info_from_listing(instance),
        "whatsapp_url": phone_to_whatsapp_url(getattr(instance, "business_number", None) or ""),
        "impression_cap": 1000,
        "impressions_used": 0,
        "rotation_index": 0,
        "is_active": is_active,
        "is_banned": False,
        "created_at": _created_at_naive_utc(instance),
        "tags": tags,
        "TAGS": tags,
    }
    return doc, geo_from_google


def upsert_businesses_directory_doc(instance) -> None:
    """
    Insert or replace one document in `businesses` keyed by `user_listing_id`.
    Does not raise on failure (logs only) so listing API stays reliable.
    """
    try:
        try:
            instance.reload()
        except Exception:
            logger.debug(
                "businesses_directory_sync.reload_skipped listing_id=%s",
                getattr(instance, "id", None),
            )

        from chatbot.mongo_db import get_db

        coll = get_db()["businesses"]
        listing_id = str(instance.id)
        doc, geo_from_google = build_businesses_doc(instance)
        existing = coll.find_one({"user_listing_id": listing_id}, projection=["created_at"])
        if existing and existing.get("created_at") is not None:
            doc["created_at"] = existing["created_at"]
        else:
            doc["created_at"] = _created_at_naive_utc(instance)

        coll.replace_one({"user_listing_id": listing_id}, doc, upsert=True)
        _emit_sync_payload(doc, geo_from_google=geo_from_google)
        logger.info(
            "businesses_directory_sync.upsert ok user_listing_id=%s name=%s category=%s "
            "country=%s state=%s city=%s county=%s zip=%s lat=%s lon=%s",
            listing_id,
            doc.get("name"),
            doc.get("category"),
            doc.get("country"),
            doc.get("state"),
            doc.get("city"),
            doc.get("county"),
            doc.get("zip_code"),
            doc.get("latitude"),
            doc.get("longitude"),
        )
    except Exception:
        logger.exception("businesses_directory_sync.upsert failed user_listing_id=%s", instance.id)


def set_businesses_directory_active(listing_id: str, is_active: bool) -> None:
    """Set is_active on the mirrored `businesses` row."""
    try:
        from chatbot.mongo_db import get_db

        coll = get_db()["businesses"]
        coll.update_one(
            {"user_listing_id": str(listing_id)},
            {"$set": {"is_active": bool(is_active)}},
        )
        logger.info(
            "businesses_directory_sync.set_active listing_id=%s is_active=%s",
            listing_id,
            is_active,
        )
    except Exception:
        logger.exception(
            "businesses_directory_sync.set_active failed listing_id=%s active=%s",
            listing_id,
            is_active,
        )
