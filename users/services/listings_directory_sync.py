"""
Mirror marketplace listings (vehicle_listing, services_listing, …) into Mongo `businesses`.

Runs when Mongo is configured — **not** gated on chatbot USE_MONGO (see LISTINGS_DIRECTORY_MIRROR_ENABLED).

Upsert key: user_listing_id + listing_source (MongoEngine collection name).
"""
from __future__ import annotations

import logging
from datetime import datetime, date, timezone as dt_timezone
from decimal import Decimal
from typing import Any, Optional, Tuple

from django.conf import settings as django_settings
from django.utils import timezone

from helpers.google_geocoding import reverse_geocode_latlng
from users.services.businesses_directory_sync import (
    _coerce_float,
    _normalize_geojson_lon_lat,
    _raw_coordinates_from_point,
)

logger = logging.getLogger(__name__)

LISTING_MARKER_BY_COLLECTION = {
    "vehicle_listing": "[VehicleListing]",
    "services_listing": "[ServicesListing]",
    "real_estate_listing": "[RealEstateListing]",
    "jobs_listing": "[JobsListing]",
    "kids_listing": "[KidsListing]",
    "furniture_listing": "[FurnitureListing]",
    "fashion_listing": "[FashionListing]",
    "events_listing": "[EventsListing]",
    "electronics_listing": "[ElectronicsListing]",
    "sports_hobby_listing": "[SportsHobbyListing]",
}

# Attributes merged into tags + contact_info for search (per vertical).
ATTRS_BY_COLLECTION: dict[str, tuple[str, ...]] = {
    "vehicle_listing": (
        "make",
        "model",
        "year",
        "color",
        "mileage",
        "fuel_type",
        "transmission",
        "condition",
        "price",
        "negotiable",
        "number_of_doors",
        "purpose",
        "vehicle_type",
        "rental_duration",
        "part_name",
        "bike_type",
        "boat_length",
        "passenger_capacity",
        "Load_capacity",
        "for_sale",
        "rentals",
    ),
    "services_listing": (
        "service_fee",
        "service_type",
        "availability",
        "certifications",
        "other",
        "pricing_structure",
        "service_area",
        "cleaning_type",
        "experience_qualifications",
        "licence_type",
        "landscaping_services",
        "construction_services",
        "technology_services",
        "visa_services",
        "movers_services",
        "photography_services",
        "interior_services",
        "cuisine_type",
        "platform",
    ),
    "real_estate_listing": (
        "property_type",
        "bedrooms",
        "bathrooms",
        "size",
        "condition",
        "furnished",
        "price",
        "negotiable",
        "lease_managed_by",
        "lease_terms",
        "land_type",
        "hoa_fees",
        "rent_price",
        "security_deposit",
        "basement",
        "parking_and_cost",
        "utilities_included",
        "pet_policy",
    ),
    "jobs_listing": (
        "job_tittle",
        "required_skills",
        "experience_level",
        "employment_type",
        "salary_range",
        "negotiable",
        "working_hours",
        "benefits_offered",
        "project_type",
        "contract_duration",
        "flexibility",
        "remote_work_tools",
        "service_type",
        "duties",
    ),
    "kids_listing": (
        "donation",
        "price",
        "negotiable",
        "age_range",
        "product_type",
        "toy_type",
        "vehicle_type",
        "subject",
        "experience_level",
        "activity_type",
        "babysitter_experience",
        "grades",
        "certification",
    ),
    "furniture_listing": (
        "material_type",
        "color",
        "dimensions",
        "condition",
        "donation",
        "price",
        "negotiable",
        "seating_capacity",
        "table_type",
        "chair_type",
        "bed_size",
        "customization",
        "lead_time",
        "upholstery_material",
    ),
    "fashion_listing": (
        "brand",
        "size",
        "color",
        "material_type",
        "gender",
        "condition",
        "donation",
        "price",
        "negotiable",
        "shoe_type",
        "accessories_type",
        "skin_type",
        "metal_type",
        "gem_stone",
    ),
    "events_listing": (
        "event_type",
        "event_date",
        "expected_audience",
        "special_feature",
        "ticket_price",
        "negotiable",
        "industry_focus",
        "speaker_list",
        "genre",
        "no_of_days",
        "theme",
        "major_attraction",
    ),
    "electronics_listing": (
        "brand",
        "model",
        "warranty",
        "condition",
        "price",
        "negotiable",
        "operating_system",
        "carrier_lock",
        "processor",
        "ram",
        "storage_type",
        "energy_rating",
        "dimension",
        "platforms",
        "part_type",
        "compatible_model",
    ),
    "sports_hobby_listing": (
        "item_type",
        "condition",
        "activity_type",
        "price",
        "negotiable",
    ),
}


def listing_source_for_model(model_cls) -> str:
    """MongoEngine collection name for a listing Document subclass."""
    meta = getattr(model_cls, "_meta", None)
    if meta is not None and hasattr(meta, "get"):
        c = meta.get("collection")
        if c:
            return c
    return model_cls.__name__


def _listing_mirror_enabled() -> bool:
    if getattr(django_settings, "LISTINGS_DIRECTORY_MIRROR_ENABLED", True) is False:
        return False
    uri = (getattr(django_settings, "MONGO_URI", None) or "").strip()
    return bool(uri)


def _listing_collection_name(instance) -> str:
    return listing_source_for_model(instance.__class__)


def _format_scalar(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (list, tuple)):
        inner = [_format_scalar(x) for x in val if x is not None]
        return ", ".join(x for x in inner if x)
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, Decimal):
        return format(val, "f")
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return str(val).strip()


def _vertical_detail_parts(instance, listing_source: str) -> Tuple[str, list[str]]:
    """Return (tags_suffix_chunk, extra contact lines) from vertical-specific fields."""
    keys = ATTRS_BY_COLLECTION.get(listing_source, ())
    tag_parts: list[str] = []
    contact_lines: list[str] = []
    for key in keys:
        if not hasattr(instance, key):
            continue
        try:
            raw = getattr(instance, key, None)
        except Exception:
            continue
        if raw is None or raw == "" or raw == []:
            continue
        text = _format_scalar(raw)
        if not text:
            continue
        label = key.replace("_", " ").title()
        tag_parts.append(text)
        contact_lines.append(f"{label}: {text}")
    blob = " ".join(tag_parts)
    return blob, contact_lines


def _extract_lon_lat_listing(instance) -> Tuple[Optional[float], Optional[float]]:
    pt = getattr(instance, "listing_coordinates", None)
    pair = _raw_coordinates_from_point(pt)
    if pair is None and hasattr(instance, "to_mongo"):
        try:
            raw_doc = instance.to_mongo()
            raw_pt = (
                raw_doc.get("listing_coordinates") if isinstance(raw_doc, dict) else None
            )
            pair = _raw_coordinates_from_point(raw_pt)
        except Exception:
            logger.exception("listings_directory_sync.to_mongo_coordinates_failed")
    if not pair:
        return None, None
    a, b = pair
    lon = _coerce_float(a)
    lat = _coerce_float(b)
    if lon is None or lat is None:
        return None, None
    lon, lat = _normalize_geojson_lon_lat(lon, lat)
    return lon, lat


def _created_at_naive_utc(instance):
    ca = getattr(instance, "created_at", None)
    if not ca:
        return datetime.utcnow()
    if timezone.is_aware(ca):
        return ca.astimezone(dt_timezone.utc).replace(tzinfo=None)
    return ca


def _contact_info_generic(
    instance, listing_source: str, vertical_contact_lines: list[str]
) -> str:
    marker = LISTING_MARKER_BY_COLLECTION.get(listing_source, "[Listing]")
    title = (getattr(instance, "title", None) or "").strip()
    desc = (getattr(instance, "description", None) or "").strip()
    if len(desc) > 800:
        desc = desc[:797] + "..."
    uid = getattr(instance, "user_id", None)
    lines = [marker, f"Title: {title}" if title else ""]
    if desc:
        lines.append(f"Description: {desc}")
    lines.extend(vertical_contact_lines)
    if uid is not None:
        lines.append(f"Lister user_id: {uid}")
    return "\n".join(x for x in lines if x).strip()


def _keywords_blob(instance) -> str:
    kw = getattr(instance, "keywords", None) or []
    if isinstance(kw, (list, tuple)):
        return " ".join(str(x) for x in kw if x)
    return str(kw) if kw else ""


def build_listing_businesses_doc(instance, listing_source: str) -> dict:
    """Build a `businesses`-shaped document from a marketplace listing."""
    listing_id = str(instance.id)
    lon, lat = _extract_lon_lat_listing(instance)
    geo = {}
    if lat is not None and lon is not None:
        geo_rev = reverse_geocode_latlng(lat, lon) or {}
        if geo_rev:
            geo = geo_rev

    title = (getattr(instance, "title", None) or "").strip()
    category = (getattr(instance, "category", None) or "").strip()
    subcategory = (getattr(instance, "subcategory", None) or "").strip()
    description = (getattr(instance, "description", None) or "").strip()
    kw_blob = _keywords_blob(instance)

    vertical_tags, vertical_contact = _vertical_detail_parts(instance, listing_source)

    base_tags = f"{category} {subcategory} {title}".strip()
    goals_blob = f"{description[:600]} {kw_blob} {vertical_tags}".strip()

    extra_tokens = []
    try:
        from chatbot.services.business_search_service import (
            collect_directory_search_tokens_from_listing_text,
        )

        extra_tokens = collect_directory_search_tokens_from_listing_text(
            title, category, subcategory, goals_blob
        )
    except Exception:
        logger.exception("listings_directory_sync.collect_search_tokens_failed")

    if extra_tokens:
        unique_extra = list(dict.fromkeys(extra_tokens))
        extra_blob = " | ".join(unique_extra)
        tags = f"{base_tags} | {extra_blob}" if base_tags else extra_blob
    else:
        tags = base_tags

    if kw_blob and kw_blob not in tags:
        tags = f"{tags} | {kw_blob}".strip(" |") if tags else kw_blob
    if vertical_tags:
        tags = f"{tags} | {vertical_tags}".strip(" |") if tags else vertical_tags

    is_active = bool(getattr(instance, "is_active", True))

    doc = {
        "user_listing_id": listing_id,
        "listing_source": listing_source,
        "name": title,
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
        "contact_info": _contact_info_generic(instance, listing_source, vertical_contact),
        "whatsapp_url": "",
        "impression_cap": 1000,
        "impressions_used": 0,
        "rotation_index": 0,
        "is_active": is_active,
        "is_banned": False,
        "created_at": _created_at_naive_utc(instance),
        "tags": tags,
        "TAGS": tags,
    }
    return doc


def upsert_listing_directory_doc(instance) -> None:
    """
    Insert or replace one `businesses` row for this listing, keyed by user_listing_id + listing_source.
    Does not raise on failure (logs only).
    """
    if not _listing_mirror_enabled():
        logger.debug(
            "listings_directory_sync.skip_disabled id=%s",
            getattr(instance, "id", None),
        )
        return
    listing_source = _listing_collection_name(instance)
    if listing_source not in LISTING_MARKER_BY_COLLECTION:
        logger.warning(
            "listings_directory_sync.skip_unknown_collection collection=%s id=%s",
            listing_source,
            getattr(instance, "id", None),
        )
        return
    try:
        try:
            instance.reload()
        except Exception:
            logger.debug(
                "listings_directory_sync.reload_skipped id=%s", getattr(instance, "id", None)
            )

        from chatbot.mongo_db import get_db

        coll = get_db()["businesses"]
        listing_id = str(instance.id)
        doc = build_listing_businesses_doc(instance, listing_source)
        existing = coll.find_one(
            {"user_listing_id": listing_id, "listing_source": listing_source},
            projection=["created_at"],
        )
        if existing and existing.get("created_at") is not None:
            doc["created_at"] = existing["created_at"]
        else:
            doc["created_at"] = _created_at_naive_utc(instance)

        coll.replace_one(
            {"user_listing_id": listing_id, "listing_source": listing_source},
            doc,
            upsert=True,
        )
        logger.info(
            "listings_directory_sync.upsert ok listing_source=%s user_listing_id=%s name=%s",
            listing_source,
            listing_id,
            doc.get("name"),
        )
    except Exception:
        logger.exception(
            "listings_directory_sync.upsert failed listing_source=%s id=%s",
            listing_source,
            getattr(instance, "id", None),
        )


def remove_listing_directory_doc(listing_id: str, listing_source: str) -> None:
    """Remove mirrored row from `businesses` when the source listing is deleted."""
    if not _listing_mirror_enabled():
        return
    if listing_source not in LISTING_MARKER_BY_COLLECTION:
        return
    try:
        from chatbot.mongo_db import get_db

        r = get_db()["businesses"].delete_one(
            {"user_listing_id": str(listing_id), "listing_source": listing_source}
        )
        if r.deleted_count:
            logger.info(
                "listings_directory_sync.remove ok listing_source=%s user_listing_id=%s",
                listing_source,
                listing_id,
            )
    except Exception:
        logger.exception(
            "listings_directory_sync.remove failed listing_source=%s id=%s",
            listing_source,
            listing_id,
        )


def set_listing_directory_active(listing_id: str, listing_source: str, is_active: bool) -> None:
    """Set is_active on the mirrored `businesses` row for a marketplace listing."""
    if not _listing_mirror_enabled():
        return
    try:
        from chatbot.mongo_db import get_db

        coll = get_db()["businesses"]
        coll.update_one(
            {"user_listing_id": str(listing_id), "listing_source": listing_source},
            {"$set": {"is_active": bool(is_active)}},
        )
        logger.info(
            "listings_directory_sync.set_active listing_source=%s id=%s is_active=%s",
            listing_source,
            listing_id,
            is_active,
        )
    except Exception:
        logger.exception(
            "listings_directory_sync.set_active failed listing_source=%s id=%s",
            listing_source,
            listing_id,
        )


def sync_all_listings_to_businesses_mirror(limit_per_collection: int | None = None) -> dict[str, int]:
    """
    Upsert every active listing into `businesses` (for backfill after manual Mongo inserts or deploy).
    Returns counts per collection name.
    """
    from listings.models import (
        ElectronicsListing,
        EventsListing,
        FashionListing,
        FurnitureListing,
        JobsListing,
        KidsListing,
        RealEstateListing,
        ServicesListing,
        SportsHobbyListing,
        VehicleListing,
    )

    models = (
        VehicleListing,
        ServicesListing,
        RealEstateListing,
        JobsListing,
        KidsListing,
        FurnitureListing,
        FashionListing,
        EventsListing,
        ElectronicsListing,
        SportsHobbyListing,
    )
    counts: dict[str, int] = {}
    if not _listing_mirror_enabled():
        logger.warning("listings_directory_sync.sync_all skipped (mirror disabled or no MONGO_URI)")
        return counts

    for model in models:
        src = listing_source_for_model(model)
        qs = model.objects
        if limit_per_collection is not None:
            qs = qs[:limit_per_collection]
        n = 0
        for inst in qs:
            upsert_listing_directory_doc(inst)
            n += 1
        counts[src] = n
    return counts
