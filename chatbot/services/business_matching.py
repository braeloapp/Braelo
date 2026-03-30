"""
Business matching: geographic (ZIP/county/radius), sponsored first, rotation, 3–5 results.
Uses MongoDB when USE_MONGO is True.

Supports legacy `business_listings` and flat `businesses` (name, category, lat/lon, contact_info).
"""
import logging
import re
from django.db import transaction
from django.db.models import F

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
    if c1 and c2:
        cat = _mongo_category_filter(c1, c2)
    elif c1 or c2:
        cat = _mongo_category_any_field(c1 or c2)
    else:
        cat = {}
    if cat:
        return {"$and": [base, cat]}
    return base


def _mongo_category_filter(category: str, subcategory: str) -> dict:
    parts = []
    if category and str(category).strip():
        c = re.escape(str(category).strip())
        parts.append({
            "$or": [
                {"category": {"$regex": c, "$options": "i"}},
                {"business_category": {"$regex": c, "$options": "i"}},
            ],
        })
    if subcategory and str(subcategory).strip():
        s = re.escape(str(subcategory).strip())
        parts.append({
            "$or": [
                {"subcategory": {"$regex": s, "$options": "i"}},
                {"business_subcategory": {"$regex": s, "$options": "i"}},
            ],
        })
    if not parts:
        return {}
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


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


def _fetch_mongo_business_docs(db, collection_names: list, category: str, subcategory: str) -> list:
    base = {
        "is_active": True,
        "$or": [{"is_banned": False}, {"is_banned": {"$exists": False}}],
    }
    cat_q = _mongo_category_filter(category or "", subcategory or "")
    query = {"$and": [base, cat_q]} if cat_q else base
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
    contact = (doc.get("contact_info") or "").strip() or (legacy_contact or "") or ""
    wa = (doc.get("whatsapp_url") or "").strip()
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
        if not bz or uz != bz:
            return False
    if state and _nz_loc(state) != _nz_loc(n.get("state")):
        return False
    if county and _nz_loc(county) != _nz_loc(n.get("county")):
        return False
    if city and _nz_loc(city) != _nz_loc(n.get("city")):
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
    st = _nz_loc(state)
    cy = _nz_loc(county)
    zraw = _nz_loc(zip_code)
    z = zraw.split("-")[0] if zraw else ""

    tried_tight = False
    if z:
        tier = [n for n in norms if _nz_loc(n["zip_code"]).startswith(z) or _nz_loc(n["zip_code"]) == zraw]
        tried_tight = True
        if tier:
            return tier, None, False
    if st and cy:
        tier = [n for n in norms if _nz_loc(n["state"]) == st and _nz_loc(n["county"]) == cy]
        tried_tight = True
        if tier:
            return tier, None, False
    if st:
        tier = [n for n in norms if _nz_loc(n["state"]) == st]
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
    external_id: str = None,
    session_id: str = None,
    strict_location: bool = False,
    sort_mode: str = "default",
) -> dict:
    from django.conf import settings

    if limit is None:
        limit = getattr(settings, "MAX_BUSINESS_RESULTS", 5)
    radius_miles = getattr(settings, "BUSINESS_RADIUS_MILES", 25)
    radius_fallback = getattr(settings, "BUSINESS_RADIUS_FALLBACK_MILES", 50)
    collection_names = getattr(settings, "MONGO_BUSINESS_COLLECTIONS", None) or ["business_listings", "businesses"]
    if isinstance(collection_names, str):
        collection_names = [x.strip() for x in collection_names.split(",") if x.strip()]

    try:
        from chatbot.mongo_db import get_db
        db = get_db()
        all_rows = _fetch_mongo_business_docs(db, collection_names, category, subcategory)
    except Exception:
        logger.exception("business_matching.mongo.query_failed")
        return {"businesses": [], "see_more": False, "location_note": None}

    norms = [_normalize_mongo_business(b) for b in all_rows]
    if language and str(language).strip():
        lang = str(language).strip().lower()
        norms = [
            n for n in norms
            if not n["languages"] or lang in (n["languages"] or "").lower()
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

    if within_primary:
        selected_pairs = within_primary[:limit]
        location_note = region_note if not strict_location else None
    else:
        selected_pairs = within_fallback[:limit] if within_fallback else [(n["doc"], None) for n in norms[:limit]]
        location_note = region_note or "No exact matches in your area. Here are the closest available options."

    total_available = len(within_primary) or len(within_fallback) or len(norms)
    see_more = total_available > limit

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
        "business_matching.mongo.result category=%s subcategory=%s results=%s see_more=%s",
        category,
        subcategory,
        len(out_list),
        see_more,
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
    external_id: str = None,
    session_id: str = None,
    strict_location: bool = False,
    sort_mode: str = "default",
) -> dict:
    from django.conf import settings
    if not (str(category or "").strip() or str(subcategory or "").strip()):
        logger.info("business_matching.skip empty category+subcategory")
        return {"businesses": [], "see_more": False, "location_note": None}
    if getattr(settings, "USE_MONGO", False):
        return _get_top_businesses_mongo(
            category=category, subcategory=subcategory, state=state, city=city,
            county=county, zip_code=zip_code, user_lat=user_lat, user_lon=user_lon,
            language=language, limit=limit, external_id=external_id, session_id=session_id,
            strict_location=strict_location, sort_mode=sort_mode,
        )

    from chatbot.models import Business, AdPackage, ImpressionsLog

    if limit is None:
        limit = getattr(settings, "MAX_BUSINESS_RESULTS", 5)
    radius_miles = getattr(settings, "BUSINESS_RADIUS_MILES", 25)
    radius_fallback = getattr(settings, "BUSINESS_RADIUS_FALLBACK_MILES", 50)
    min_results = getattr(settings, "MIN_BUSINESS_RESULTS", 3)

    def _django_matches_strict(b) -> bool:
        if not strict_location:
            return True
        uz = _zip5(zip_code)
        if uz:
            bz = _zip5(getattr(b, "zip_code", None))
            if not bz or uz != bz:
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
            qs = qs.filter(category__icontains=category)
        if subcategory:
            qs = qs.filter(subcategory__icontains=subcategory)
        if state and not strict_location:
            qs = qs.filter(state__icontains=state)
        if city and not strict_location:
            qs = qs.filter(city__icontains=city)
        if county and not strict_location:
            qs = qs.filter(county__icontains=county)
        if zip_code and not strict_location:
            qs = qs.filter(zip_code=zip_code)
        if language:
            qs = qs.filter(languages__icontains=language)

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
        logger.exception("business_matching.django.query_failed")
        return {"businesses": [], "see_more": False, "location_note": None}
