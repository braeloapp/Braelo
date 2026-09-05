'''
Canonical listing field/value aliases.

Clients historically send display labels, camelCase, and typos.
Normalize them to the MongoEngine field names and choice values
before serializer validation.
'''

from helpers.normalize import _normalize_token

# Incoming key → canonical model field
FIELD_ALIASES = {
    'loadcapcity': 'Load_capacity',
    'loadcapacity': 'Load_capacity',
    'load_capacity': 'Load_capacity',
    'partname': 'part_name',
    'partName': 'part_name',
    'fueltype': 'fuel_type',
    'fuelType': 'fuel_type',
    'transmission': 'transmission',
    'Transmission': 'transmission',
    'purpose': 'purpose',
    'Purpose': 'purpose',
    'numberofdoors': 'number_of_doors',
    'Number of Doors': 'number_of_doors',
    'number_of_doors': 'number_of_doors',
    'forsale': 'for_sale',
    'For Sale': 'for_sale',
    'rentals': 'rentals',
    'Rentals': 'rentals',
    'vehicletype': 'vehicle_type',
    'duration': 'rental_duration',
    'biketype': 'bike_type',
    'listing_address': 'location',
    'address': 'location',
}

_CONTEXT_FIELD_ALIASES = {
    'bike': {'type': 'bike_type'},
    'outdooractivities': {'processor': 'activity_type'},
    'activities': {
        'activity': 'activity_type',
        'required': 'equipment_required',
        'processor': 'activity_type',
    },
}

# Context-sensitive keys (depend on subcategory)
_LENGTH_BY_SUBCATEGORY = {
    'boat': 'boat_length',
    'van': 'passenger_capacity',
}

# Display / mixed-case values → canonical choice values
VALUE_ALIASES = {
    'automatic': 'AUTOMATIC',
    'manual': 'MANUAL',
    'sale': 'SALE',
    'rental': 'RENTAL',
    'yes': 'YES',
    'no': 'NO',
    'new': 'NEW',
    'used': 'USED',
    '4': '4/5',
    '3': '1/3',
    '5': '4/5',
}

CHOICE_FIELDS = {
    'transmission',
    'condition',
    'purpose',
    'negotiable',
    'for_sale',
    'rentals',
    'number_of_doors',
    'furnished',
}


def apply_field_aliases(payload, subcategory=None):
    '''Return a copy of ``payload`` with aliased keys/values normalized.'''
    if not isinstance(payload, dict):
        return payload

    sub_key = _normalize_token(subcategory or payload.get('subcategory'))
    context_aliases = _CONTEXT_FIELD_ALIASES.get(sub_key, {})
    remapped = {}
    for key, value in payload.items():
        canonical = context_aliases.get(key) or FIELD_ALIASES.get(key)
        if canonical is None and isinstance(key, str):
            normalized_key = _normalize_token(key)
            for alias, target in {**FIELD_ALIASES, **context_aliases}.items():
                if _normalize_token(alias) == normalized_key:
                    canonical = target
                    break
        if key == 'length' or (
            isinstance(key, str) and _normalize_token(key) == 'length'
        ):
            canonical = _LENGTH_BY_SUBCATEGORY.get(sub_key, key)
        remapped[canonical or key] = value

    for field in CHOICE_FIELDS:
        if field not in remapped or remapped[field] in (None, ''):
            continue
        raw = remapped[field]
        if not isinstance(raw, str):
            continue
        alias = VALUE_ALIASES.get(raw.strip().lower())
        if alias:
            remapped[field] = alias
        elif raw.strip().upper() in ('YES', 'NO', 'NEW', 'USED', 'SALE', 'RENTAL', 'AUTOMATIC', 'MANUAL'):
            remapped[field] = raw.strip().upper()

    location = remapped.get('location') or remapped.get('listing_address')
    if location not in (None, ''):
        remapped['location'] = str(location).strip()
    return remapped


def extract_coordinates(raw):
    '''Normalize GeoJSON / list / JSON-string coordinates to [lon, lat].'''
    if raw in (None, '', []):
        return None
    coords = raw
    if isinstance(raw, str):
        import json

        try:
            coords = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if (
        isinstance(coords, dict)
        and coords.get('type') == 'Point'
        and isinstance(coords.get('coordinates'), (list, tuple))
        and len(coords['coordinates']) >= 2
    ):
        coords = coords['coordinates']
    if not isinstance(coords, (list, tuple)) or len(coords) != 2:
        return None
    try:
        lon, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        return None
    return [lon, lat]


def point_to_lon_lat(point):
    '''Extract [lon, lat] from a MongoEngine PointField value.'''
    if point is None:
        return None
    if isinstance(point, (list, tuple)) and len(point) == 2:
        return [float(point[0]), float(point[1])]
    if isinstance(point, dict):
        coords = point.get('coordinates')
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            return [float(coords[0]), float(coords[1])]
    return None
