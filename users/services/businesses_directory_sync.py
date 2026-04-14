"""
Mirror `business_listings` (MongoEngine) into flat Mongo `businesses` docs for chatbot/directory search.

Upsert key: `user_listing_id` (stringified ObjectId of the Business document).
"""
import json
import logging
import re
from datetime import datetime, timezone as py_tz
from typing import Optional, Tuple

from django.conf import settings
from django.utils import timezone

from helpers.google_geocoding import reverse_geocode_latlng

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


def _extract_lon_lat(instance):
    pt = getattr(instance, "business_coordinates", None)
    if not pt:
        return None, None
    coords = None
    if isinstance(pt, dict):
        coords = pt.get("coordinates")
    elif hasattr(pt, "coordinates"):
        coords = getattr(pt, "coordinates", None)
    if not coords or len(coords) < 2:
        return None, None
    try:
        lon, lat = float(coords[0]), float(coords[1])
        return lon, lat
    except (TypeError, ValueError):
        return None, None


def _geo_fallback_from_address(address: str) -> dict:
    """When geocoding is unavailable: expose free-text in city for basic display/search."""
    a = (address or "").strip()
    if not a:
        return {"state": None, "city": None, "county": None, "zip_code": None}
    return {"state": None, "city": a, "county": None, "zip_code": None}


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

    geo_from_google = None
    geo = {}
    if lat is not None and lon is not None:
        geo = reverse_geocode_latlng(lat, lon) or {}
        if geo:
            geo_from_google = dict(geo)
    if not geo or not any(geo.get(k) for k in ("state", "city", "county", "zip_code")):
        fb = _geo_fallback_from_address(getattr(instance, "business_address", None) or "")
        for k, v in fb.items():
            if v and not geo.get(k):
                geo[k] = v

    name = getattr(instance, "business_name", None) or ""
    category = getattr(instance, "business_category", None) or ""
    subcategory = getattr(instance, "business_subcategory", None) or ""
    goals = (getattr(instance, "business_goals", None) or "").strip()
    tags = goals if goals else f"{category} {subcategory}".strip()

    is_active = bool(getattr(instance, "is_active", True))

    doc = {
        "user_listing_id": listing_id,
        "name": name,
        "category": category,
        "subcategory": subcategory,
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
    }
    return doc, geo_from_google


def upsert_businesses_directory_doc(instance) -> None:
    """
    Insert or replace one document in `businesses` keyed by `user_listing_id`.
    Does not raise on failure (logs only) so listing API stays reliable.
    """
    try:
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
            "state=%s city=%s county=%s zip=%s lat=%s lon=%s",
            listing_id,
            doc.get("name"),
            doc.get("category"),
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
