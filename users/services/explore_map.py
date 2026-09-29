'''
Explore map data: businesses + listings near a point.

Keeps geo / category filtering out of the API view so ExploreBusiness
stays thin and the same helpers can be reused later (admin map, etc.).
'''

from __future__ import annotations

from helpers.constants import CATEGORIES
from helpers.models import ListSync
from helpers.normalize import is_all_token, resolve_category
from listings.field_contract import point_to_lon_lat
from listings.geo import geo_near_filter, parse_coordinates, parse_radius_meters
from listings.services.taxonomy import apply_taxonomy_display_names
from rest_framework.exceptions import ValidationError
from users.models import Business

# 1 mile ≈ 1609.344 meters. Map UI defaults to 10 mi, max 50 mi.
MILES_TO_METERS = 1609.344
DEFAULT_RADIUS_MILES = 10
MAX_RADIUS_MILES = 50
MIN_RADIUS_MILES = 1


def parse_explore_radius_meters(request):
    '''
    Resolve explore radius in meters.

    Accepts either:
    - ``radius_miles`` (1–50) — preferred by the map UI
    - ``radius`` (meters) — existing listing/business contract

    When neither is sent, defaults to 10 miles so the map always has a
    bounded nearby query.
    '''
    raw_miles = request.GET.get('radius_miles')
    if raw_miles is not None and str(raw_miles).strip() != '':
        try:
            miles = float(raw_miles)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {'radius_miles': 'Must be a number between 1 and 50.'}
            ) from exc
        if miles < MIN_RADIUS_MILES or miles > MAX_RADIUS_MILES:
            raise ValidationError(
                {
                    'radius_miles': (
                        f'Must be between {MIN_RADIUS_MILES} and '
                        f'{MAX_RADIUS_MILES}.'
                    )
                }
            )
        return int(round(miles * MILES_TO_METERS)), miles

    raw = request.GET.get('radius')
    if raw is not None and str(raw).strip() != '':
        meters = parse_radius_meters(raw)
        return meters, meters / MILES_TO_METERS

    meters = int(round(DEFAULT_RADIUS_MILES * MILES_TO_METERS))
    return meters, float(DEFAULT_RADIUS_MILES)


def resolve_explore_category(raw_category):
    '''Normalize category query to canonical key or ``ALL``.'''
    if not raw_category:
        raise ValidationError({'category': 'category is required'})
    if is_all_token(raw_category):
        return 'ALL'
    canonical = resolve_category(raw_category)
    if canonical is None:
        raise ValidationError(
            {
                'category': (
                    f'Must be one of {list(CATEGORIES.keys())} OR "(ALL, all)"'
                )
            }
        )
    return canonical


def parse_explore_point(raw_coordinates):
    '''Parse required ``[longitude, latitude]`` for explore.'''
    coords = parse_coordinates(raw_coordinates, field='coordinates')
    if coords is None:
        raise ValidationError(
            {'coordinates': 'coordinates are required as [longitude, latitude].'}
        )
    return coords


def _geojson_point(lon_lat):
    if not lon_lat or len(lon_lat) != 2:
        return None
    return {'type': 'Point', 'coordinates': [lon_lat[0], lon_lat[1]]}


def serialize_business_for_map(business):
    '''Slim map DTO for a Business document.'''
    lon_lat = point_to_lon_lat(getattr(business, 'business_coordinates', None))
    data = {
        'id': str(business.id),
        'type': 'business',
        'title': business.business_name or '',
        'category': business.business_category or '',
        'subcategory': business.business_subcategory or '',
        'pictures': list(business.business_banner or business.business_images or []),
        'logo': list(business.business_logo or []),
        'location': business.business_address or '',
        'coordinates': _geojson_point(lon_lat),
        'user_id': business.user_id,
        'from_business': True,
        'phone': business.business_number or '',
        'website': business.business_website or '',
    }
    return apply_taxonomy_display_names(data)


def serialize_listing_for_map(listing):
    '''Slim map DTO for a ListSync document.'''
    lon_lat = point_to_lon_lat(getattr(listing, 'listing_coordinates', None))
    pictures = listing.pictures or []
    if not isinstance(pictures, list):
        pictures = list(pictures) if pictures else []
    price = listing.price
    data = {
        'id': str(listing.listing_id),
        'type': 'listing',
        'title': listing.title or '',
        'category': listing.category or '',
        'subcategory': listing.subcategory or '',
        'pictures': pictures,
        'logo': [],
        'location': listing.location or '',
        'coordinates': _geojson_point(lon_lat),
        'user_id': listing.user_id,
        'from_business': bool(listing.from_business),
        'phone': '',
        'price': str(price) if price is not None else None,
    }
    return apply_taxonomy_display_names(data)


def fetch_explore_businesses(lon, lat, radius_m, category):
    '''Active businesses within radius, optional category filter.'''
    filters = {
        'is_active': True,
        **geo_near_filter(
            lon, lat, radius_m, field='business_coordinates'
        ),
    }
    if category != 'ALL' and category in CATEGORIES:
        filters['business_category'] = category
    return [
        serialize_business_for_map(doc)
        for doc in Business.objects.filter(**filters)
        if point_to_lon_lat(getattr(doc, 'business_coordinates', None))
    ]


def fetch_explore_listings(lon, lat, radius_m, category):
    '''Active listings within radius, optional category filter.'''
    filters = {
        'is_active': True,
        **geo_near_filter(
            lon, lat, radius_m, field='listing_coordinates'
        ),
    }
    if category != 'ALL' and category in CATEGORIES:
        filters['category'] = category
    return [
        serialize_listing_for_map(doc)
        for doc in ListSync.objects.filter(**filters)
        if point_to_lon_lat(getattr(doc, 'listing_coordinates', None))
    ]


def build_explore_map_payload(request):
    '''
    Full explore map payload from the request query string.

    Returns dict ready for ``helpers.response(..., data=...)``.
    '''
    category = resolve_explore_category(request.GET.get('category'))
    lon, lat = parse_explore_point(
        request.GET.get('coordinates') or request.GET.get('business_coordinates')
    )
    radius_m, radius_miles = parse_explore_radius_meters(request)

    businesses = fetch_explore_businesses(lon, lat, radius_m, category)
    listings = fetch_explore_listings(lon, lat, radius_m, category)
    total = len(businesses) + len(listings)

    return {
        'businesses': businesses,
        'listings': listings,
        'total': total,
        'radius_m': radius_m,
        'radius_miles': round(float(radius_miles), 2),
        'coordinates': [lon, lat],
        'category': category,
    }
