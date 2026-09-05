'''Authoritative listing taxonomy for admin CMS and /listing/meta.

Category and subcategory keys stay owned by ``helpers.constants.CATEGORIES``.
Admin may override label, active flag, sort order, and icon. New listing
types still require a backend model/serializer and cannot be invented here.
'''

from __future__ import annotations

from helpers.constants import CATEGORIES
from helpers.normalize import resolve_category, resolve_subcategory

CATEGORY_LABELS = {
    'Vehicles': 'Vehicles',
    'Services': 'Services',
    'realestate': 'Real Estate',
    'electronics': 'Electronics',
    'events': 'Events',
    'jobs': 'Jobs',
    'furniture': 'Furniture',
    'fashion': 'Fashion',
    'kids': 'Kids',
    'sportsandhobby': 'Sports & Hobby',
}

SUBCATEGORY_LABELS = {
    'partsandaccessories': 'Parts and Accessories',
    'mobilehome': 'Mobile Home',
    'vacationhome': 'Vacation Home',
    'servicesandparts': 'Services & Parts',
    'networkingevents': 'Networking Events',
    'fulltime': 'Full Time',
    'parttime': 'Part Time',
    'homeoffice': 'Home Office',
    'customfurniture': 'Custom Furniture',
    'beautyproducts': 'Beauty Products',
    'schooloffices': 'School Offices',
    'afterschoolprogram': 'Afterschool Program',
    'sportsequipment': 'Sports Equipment',
    'musicalinstruments': 'Musical Instruments',
    'collecteditems': 'Collected Items',
    'outdooractivities': 'Outdoor Activities',
    'Home Care (Health)': 'Home Care (Health)',
    'Home Care ( Health)': 'Home Care (Health)',
    'Classes & Courses': 'Classes & Courses',
    'Immigration and Visa': 'Immigration and Visa',
    'Movers & Packers': 'Movers & Packers',
    'Farm & Fresh Food': 'Farm & Fresh Food',
    'Video & Photography': 'Video & Photography',
    'Interior Design': 'Interior Design',
    'Insurance Services': 'Insurance Services',
    'AC Services': 'AC Services',
    'Personal Trainer': 'Personal Trainer',
    'Personal Training': 'Personal Training',
    'Transport Services': 'Transport Services',
    'Event Services': 'Event Services',
    'Finger Food': 'Finger Food',
    'fine_dining': 'Fine Dining',
    'fastfood': 'Fast Food',
    'foodtruck': 'Food Truck',
}


def humanize_key(value: str) -> str:
    if not value:
        return ''
    if value in CATEGORY_LABELS:
        return CATEGORY_LABELS[value]
    if value in SUBCATEGORY_LABELS:
        return SUBCATEGORY_LABELS[value]
    text = str(value).replace('_', ' ').replace('-', ' ')
    if text != text.lower() and ' ' in text:
        return text
    if text.lower() == text and ' ' not in text:
        return text.replace('and', ' and ').title().replace(' And ', ' & ')
    return text.title()


def override_lookup_key(kind: str, key: str, parent_key: str = '') -> str:
    if kind == 'subcategory':
        return f'{parent_key}:{key}'
    return key


def build_taxonomy_catalog(overrides=None) -> list[dict]:
    '''Merge code taxonomy with optional Mongo override rows.'''
    rows = {}
    for item in overrides or []:
        item_key = getattr(item, 'key', None) or (item.get('key') if isinstance(item, dict) else None)
        if item_key:
            rows[item_key] = item

    catalog = []
    for index, (category_key, subkeys) in enumerate(CATEGORIES.items()):
        cat_override = rows.get(category_key)
        category = {
            'key': category_key,
            'label': _override_value(cat_override, 'label')
            or CATEGORY_LABELS.get(category_key)
            or humanize_key(category_key),
            'is_active': _override_bool(cat_override, 'is_active', True),
            'sort_order': _override_int(cat_override, 'sort_order', index),
            'icon': _override_value(cat_override, 'icon') or '',
            'source': 'code',
            'subcategories': [],
        }
        for sub_index, subkey in enumerate(subkeys):
            lookup = override_lookup_key('subcategory', subkey, category_key)
            sub_override = rows.get(lookup)
            category['subcategories'].append(
                {
                    'key': subkey,
                    'parent_key': category_key,
                    'label': _override_value(sub_override, 'label')
                    or SUBCATEGORY_LABELS.get(subkey)
                    or humanize_key(subkey),
                    'is_active': _override_bool(sub_override, 'is_active', True),
                    'sort_order': _override_int(
                        sub_override, 'sort_order', sub_index
                    ),
                    'icon': _override_value(sub_override, 'icon') or '',
                    'source': 'code',
                }
            )
        category['subcategories'].sort(key=lambda row: row['sort_order'])
        catalog.append(category)
    catalog.sort(key=lambda row: row['sort_order'])
    return catalog


def validate_taxonomy_target(kind: str, key: str, parent_key: str = ''):
    if kind not in ('category', 'subcategory'):
        raise ValueError('kind must be category or subcategory')
    if kind == 'category':
        canonical = resolve_category(key)
        if canonical is None:
            raise ValueError(f'Unknown category key: {key}')
        return canonical, ''
    parent = resolve_category(parent_key or key.split(':')[0] if ':' in key else parent_key)
    sub = key.split(':', 1)[1] if ':' in key else key
    if parent is None:
        raise ValueError(f'Unknown parent category: {parent_key}')
    canonical_sub = resolve_subcategory(parent, sub)
    if canonical_sub is None:
        raise ValueError(f'Unknown subcategory key: {sub}')
    return parent, canonical_sub


def _override_value(row, field):
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(field)
    return getattr(row, field, None)


def _override_bool(row, field, default):
    value = _override_value(row, field)
    if value is None:
        return default
    return bool(value)


def _override_int(row, field, default):
    value = _override_value(row, field)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
