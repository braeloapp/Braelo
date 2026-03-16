"""
Business matching: geographic (ZIP/county/radius), sponsored first, rotation, 3–5 results.
Uses MongoDB when USE_MONGO is True. Reads from Braelo-format collection business_listings.
"""
from django.db import transaction
from django.db.models import F


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
    external_id: str = None,
    session_id: str = None,
) -> dict:
    from django.conf import settings

    if limit is None:
        limit = getattr(settings, "MAX_BUSINESS_RESULTS", 5)
    radius_miles = getattr(settings, "BUSINESS_RADIUS_MILES", 25)
    radius_fallback = getattr(settings, "BUSINESS_RADIUS_FALLBACK_MILES", 50)
    try:
        from chatbot.mongo_db import get_db
        db = get_db()
        q = {"is_active": True}
        if category:
            q["business_category"] = {"$regex": category, "$options": "i"}
        if subcategory:
            q["business_subcategory"] = {"$regex": subcategory, "$options": "i"}
        all_rows = list(db.business_listings.find(q))
    except Exception:
        return {"businesses": [], "see_more": False, "location_note": None}

    def priority_and_distance(b):
        lat, lon = _coords_from_braelo_doc(b)
        dist = _distance_miles(user_lat, user_lon, lat, lon) if all(x is not None for x in (user_lat, user_lon, lat, lon)) else None
        return (0, dist, 0, 0)

    def sort_key(b):
        pkg_priority, dist, rot, rem = priority_and_distance(b)
        dist_val = dist if dist is not None else 9999
        return (-pkg_priority, dist_val, rot, rem)

    all_rows.sort(key=sort_key)

    within_primary = []
    within_fallback = []
    for b in all_rows:
        lat, lon = _coords_from_braelo_doc(b)
        dist = None
        if user_lat is not None and user_lon is not None and lat is not None and lon is not None:
            dist = _distance_miles(user_lat, user_lon, lat, lon)
        if dist is not None:
            if dist <= radius_miles:
                within_primary.append((b, dist))
            elif dist <= radius_fallback:
                within_fallback.append((b, dist))
        else:
            within_primary.append((b, None))

    if within_primary:
        selected_pairs = within_primary[:limit]
        location_note = None
    else:
        selected_pairs = within_fallback[:limit] if within_fallback else [(b, None) for b in all_rows[:limit]]
        location_note = "No exact matches in your area. Here are the closest available options."

    total_available = len(within_primary) or len(within_fallback) or len(all_rows)
    see_more = total_available > limit

    out_list = []
    for b, dist in selected_pairs:
        bid = str(b["_id"])
        contact = _contact_from_braelo_doc(b)
        number = b.get("business_number")
        out_list.append({
            "id": bid,
            "name": b.get("business_name", ""),
            "category": b.get("business_category"),
            "subcategory": b.get("business_subcategory"),
            "state": None,
            "city": None,
            "county": None,
            "zip_code": None,
            "languages": None,
            "contact_info": contact,
            "whatsapp_url": _whatsapp_url_from_number(number) if number else "",
            "distance_miles": dist,
            "is_sponsored": False,
        })
        try:
            db.impressions_log.insert_one({
                "business_id": bid,
                "external_id": external_id,
                "session_id": session_id,
                "created_at": __import__("datetime").datetime.utcnow(),
            })
        except Exception:
            pass

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
    external_id: str = None,
    session_id: str = None,
) -> dict:
    from django.conf import settings
    if getattr(settings, "USE_MONGO", False):
        return _get_top_businesses_mongo(
            category=category, subcategory=subcategory, state=state, city=city,
            county=county, zip_code=zip_code, user_lat=user_lat, user_lon=user_lon,
            language=language, limit=limit, external_id=external_id, session_id=session_id,
        )

    from chatbot.models import Business, AdPackage, ImpressionsLog

    if limit is None:
        limit = getattr(settings, "MAX_BUSINESS_RESULTS", 5)
    radius_miles = getattr(settings, "BUSINESS_RADIUS_MILES", 25)
    radius_fallback = getattr(settings, "BUSINESS_RADIUS_FALLBACK_MILES", 50)
    min_results = getattr(settings, "MIN_BUSINESS_RESULTS", 3)

    try:
        qs = Business.objects.filter(
            is_active=True,
            is_banned=False,
        ).filter(impressions_used__lt=F("impression_cap"))
        if category:
            qs = qs.filter(category__icontains=category)
        if subcategory:
            qs = qs.filter(subcategory__icontains=subcategory)
        if state:
            qs = qs.filter(state__icontains=state)
        if city:
            qs = qs.filter(city__icontains=city)
        if county:
            qs = qs.filter(county__icontains=county)
        if zip_code:
            qs = qs.filter(zip_code=zip_code)
        if language:
            qs = qs.filter(languages__icontains=language)

        all_rows = list(qs)

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
            return (pkg_priority, dist, b.rotation_index, -remaining)

        def sort_key(b):
            pkg_priority, dist, rot, rem = priority_and_distance(b)
            dist_val = dist if dist is not None else 9999
            return (-pkg_priority, dist_val, rot, rem)

        all_rows.sort(key=sort_key)

        within_primary = []
        within_fallback = []
        for b in all_rows:
            dist = None
            if user_lat is not None and user_lon is not None and b.latitude is not None and b.longitude is not None:
                dist = _distance_miles(user_lat, user_lon, b.latitude, b.longitude)
            if dist is not None:
                if dist <= radius_miles:
                    within_primary.append((b, dist))
                elif dist <= radius_fallback:
                    within_fallback.append((b, dist))
            else:
                within_primary.append((b, None))

        if within_primary:
            selected_pairs = within_primary[:limit]
            location_note = None
        else:
            selected_pairs = within_fallback[:limit] if within_fallback else [(b, None) for b in all_rows[:limit]]
            location_note = "No exact matches in your area. Here are the closest available options."

        total_available = len(within_primary) or len(within_fallback) or len(all_rows)
        see_more = total_available > limit

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
        return {"businesses": [], "see_more": False, "location_note": None}
