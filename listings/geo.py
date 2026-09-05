'''
Shared listing/business geo helpers.

Coordinate contract is GeoJSON order: ``[longitude, latitude]``.
Radius is meters. Empty/missing coordinates mean "no geo filter".
'''

import json

from django.conf import settings
from rest_framework.exceptions import ValidationError


def parse_coordinates(raw, field='listing_coordinates'):
    '''Parse a query/body coordinate value as ``[longitude, latitude]``.

    Returns ``(lon, lat)`` or ``None`` when the value is missing/blank.
    '''
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                'Invalid JSON format for coordinates.'
            ) from exc

    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValidationError(
            {field: 'Must be a list with [longitude, latitude].'}
        )

    lon, lat = raw
    if isinstance(lon, bool) or isinstance(lat, bool):
        raise ValidationError({field: 'Longitude and latitude must be numbers.'})
    if not (isinstance(lon, (int, float)) and isinstance(lat, (int, float))):
        raise ValidationError({field: 'Longitude and latitude must be numbers.'})
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValidationError(
            {
                field: (
                    'Longitude must be between -180 and 180, '
                    'latitude must be between -90 and 90.'
                )
            }
        )
    return float(lon), float(lat)


def parse_radius_meters(raw):
    '''Parse optional radius in meters using settings default/min/max.'''
    default = int(getattr(settings, 'LISTING_RADIUS_M', 10000))
    minimum = int(getattr(settings, 'LISTING_RADIUS_MIN_M', 500))
    maximum = int(getattr(settings, 'LISTING_RADIUS_MAX_M', 100000))
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {'radius': 'Radius must be an integer number of meters.'}
        ) from exc
    if value < minimum or value > maximum:
        raise ValidationError(
            {
                'radius': (
                    f'Radius must be between {minimum} and {maximum} meters.'
                )
            }
        )
    return value


def geo_near_filter(lon, lat, radius_m, field='listing_coordinates'):
    '''MongoEngine ``$near`` filter kwargs for a PointField.'''
    return {
        f'{field}__near': [lon, lat],
        f'{field}__max_distance': radius_m,
    }


def request_geo_filter(request, field='listing_coordinates'):
    '''Build an optional geo filter from ``listing_coordinates`` + ``radius``.

    Returns ``{}`` when coordinates are omitted so callers do not silently
    treat an empty string as "search the whole world with a geo query".
    '''
    coordinates = parse_coordinates(
        request.GET.get('listing_coordinates')
        or request.GET.get('coordinates'),
        field=field,
    )
    if coordinates is None:
        return {}
    lon, lat = coordinates
    radius_m = parse_radius_meters(request.GET.get('radius'))
    return geo_near_filter(lon, lat, radius_m, field=field)
