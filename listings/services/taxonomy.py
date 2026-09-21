'''Authoritative listing taxonomy for admin CMS and /listing/meta.

Platform keys stay in ``helpers.constants.CATEGORIES``. Admins can create
additional CMS categories/subcategories, relabel entries, toggle active,
and remove entries (soft-remove for code-owned keys, hard-delete for admin).
'''

from __future__ import annotations

import re

from helpers.constants import CATEGORIES
from helpers.normalize import resolve_category, resolve_subcategory
from listings.models.taxonomy import TaxonomyOverride

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


def slugify_taxonomy_key(value: str) -> str:
    text = (value or '').strip().lower()
    text = re.sub(r'[^a-z0-9]+', '', text)
    return text


def override_lookup_key(kind: str, key: str, parent_key: str = '') -> str:
    if kind == 'subcategory':
        return f'{parent_key}:{key}'
    return key


def _is_code_category(key: str) -> bool:
    return key in CATEGORIES


def _is_code_subcategory(parent_key: str, key: str) -> bool:
    return parent_key in CATEGORIES and key in CATEGORIES.get(parent_key, [])


def _admin_category_exists(key: str) -> bool:
    row = TaxonomyOverride.objects(key=key, kind='category').first()
    return bool(row) and not bool(getattr(row, 'is_removed', False))


def build_taxonomy_catalog(overrides=None) -> list[dict]:
    '''Merge code taxonomy with optional Mongo override rows.'''
    rows = {}
    for item in overrides or []:
        item_key = getattr(item, 'key', None) or (
            item.get('key') if isinstance(item, dict) else None
        )
        if item_key:
            rows[item_key] = item

    catalog = []
    code_category_keys = set(CATEGORIES.keys())
    for index, (category_key, subkeys) in enumerate(CATEGORIES.items()):
        cat_override = rows.get(category_key)
        if _override_bool(cat_override, 'is_removed', False):
            continue

        category = {
            'key': category_key,
            'label': _override_value(cat_override, 'label')
            or CATEGORY_LABELS.get(category_key)
            or humanize_key(category_key),
            'is_active': _override_bool(cat_override, 'is_active', True),
            'sort_order': _override_int(cat_override, 'sort_order', index),
            'icon': _override_value(cat_override, 'icon') or '',
            'source': 'code',
            'listing_enabled': True,
            'subcategories': [],
        }
        code_subkeys = set(subkeys)
        for sub_index, subkey in enumerate(subkeys):
            lookup = override_lookup_key('subcategory', subkey, category_key)
            sub_override = rows.get(lookup)
            if _override_bool(sub_override, 'is_removed', False):
                continue
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
                    'listing_enabled': True,
                }
            )
        for lookup, row in rows.items():
            kind = _override_value(row, 'kind')
            parent = _override_value(row, 'parent_key') or ''
            if kind != 'subcategory' or parent != category_key:
                continue
            if _override_bool(row, 'is_removed', False):
                continue
            subkey = lookup.split(':', 1)[1] if ':' in lookup else lookup
            if subkey in code_subkeys:
                continue
            category['subcategories'].append(
                {
                    'key': subkey,
                    'parent_key': category_key,
                    'label': _override_value(row, 'label') or humanize_key(subkey),
                    'is_active': _override_bool(row, 'is_active', True),
                    'sort_order': _override_int(
                        row, 'sort_order', 1000 + len(category['subcategories'])
                    ),
                    'icon': _override_value(row, 'icon') or '',
                    'source': 'admin',
                    'listing_enabled': False,
                }
            )
        category['subcategories'].sort(key=lambda row: row['sort_order'])
        catalog.append(category)

    for lookup, row in rows.items():
        kind = _override_value(row, 'kind')
        if kind != 'category':
            continue
        if lookup in code_category_keys:
            continue
        if _override_bool(row, 'is_removed', False):
            continue

        subcategories = []
        for sub_lookup, sub_row in rows.items():
            if _override_value(sub_row, 'kind') != 'subcategory':
                continue
            if (_override_value(sub_row, 'parent_key') or '') != lookup:
                continue
            if _override_bool(sub_row, 'is_removed', False):
                continue
            subkey = (
                sub_lookup.split(':', 1)[1] if ':' in sub_lookup else sub_lookup
            )
            subcategories.append(
                {
                    'key': subkey,
                    'parent_key': lookup,
                    'label': _override_value(sub_row, 'label')
                    or humanize_key(subkey),
                    'is_active': _override_bool(sub_row, 'is_active', True),
                    'sort_order': _override_int(
                        sub_row, 'sort_order', 1000 + len(subcategories)
                    ),
                    'icon': _override_value(sub_row, 'icon') or '',
                    'source': 'admin',
                    'listing_enabled': False,
                }
            )
        subcategories.sort(key=lambda item: item['sort_order'])

        catalog.append(
            {
                'key': lookup,
                'label': _override_value(row, 'label') or humanize_key(lookup),
                'is_active': _override_bool(row, 'is_active', True),
                'sort_order': _override_int(row, 'sort_order', 1000),
                'icon': _override_value(row, 'icon') or '',
                'source': 'admin',
                'listing_enabled': False,
                'subcategories': subcategories,
            }
        )

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
    parent = resolve_category(
        parent_key or key.split(':')[0] if ':' in key else parent_key
    )
    sub = key.split(':', 1)[1] if ':' in key else key
    if parent is None:
        raise ValueError(f'Unknown parent category: {parent_key}')
    canonical_sub = resolve_subcategory(parent, sub)
    if canonical_sub is None:
        raise ValueError(f'Unknown subcategory key: {sub}')
    return parent, canonical_sub


def resolve_taxonomy_target_or_admin(kind: str, key: str, parent_key: str = ''):
    '''Resolve code-owned keys, or accept existing admin overlay keys.'''
    try:
        return validate_taxonomy_target(kind, key, parent_key)
    except ValueError:
        pass

    if kind == 'category':
        if _admin_category_exists(key):
            return key, ''
        raise ValueError(f'Unknown category key: {key}')

    parent = resolve_category(parent_key) or parent_key
    if not parent:
        raise ValueError('parent_key is required')
    sub = key.split(':', 1)[1] if ':' in key else key
    lookup = override_lookup_key('subcategory', sub, parent)
    row = TaxonomyOverride.objects(key=lookup).first()
    if row is None or bool(getattr(row, 'is_removed', False)):
        raise ValueError(f'Unknown subcategory key: {sub}')
    if not _is_code_category(parent) and not _admin_category_exists(parent):
        raise ValueError(f'Unknown parent category: {parent_key}')
    return parent, sub


def create_taxonomy_entry(payload: dict) -> dict:
    '''Create or upsert a taxonomy overlay from admin create forms.'''
    kind = (payload.get('kind') or 'category').strip()
    label = (payload.get('label') or payload.get('name') or '').strip()
    key = (payload.get('key') or payload.get('slug') or '').strip()
    parent_key = (payload.get('parent_key') or '').strip()
    icon = payload.get('icon') or ''
    is_active = payload.get('is_active', True)
    if isinstance(is_active, str):
        is_active = is_active.lower() in ('1', 'true', 'yes', 'on')

    if kind not in ('category', 'subcategory'):
        raise ValueError('kind must be category or subcategory')
    if not label:
        raise ValueError('label is required')
    if not key:
        key = slugify_taxonomy_key(label)
    if not key:
        raise ValueError('key/slug could not be derived from label')

    sort_order = payload.get('sort_order')
    if sort_order is not None and sort_order != '':
        try:
            sort_order = int(sort_order)
        except (TypeError, ValueError) as exc:
            raise ValueError('sort_order must be an integer') from exc
    else:
        sort_order = None

    listing_enabled = False
    if kind == 'category':
        canonical = resolve_category(key)
        if canonical is not None:
            key = canonical
            listing_enabled = True
        parent_key = ''
    else:
        parent = resolve_category(parent_key)
        if parent is not None:
            parent_key = parent
            canonical_sub = resolve_subcategory(parent, key)
            if canonical_sub is not None:
                key = canonical_sub
                listing_enabled = True
        elif not _admin_category_exists(parent_key):
            raise ValueError('parent_key must be an existing category')

    lookup = override_lookup_key(kind, key, parent_key)
    row = TaxonomyOverride.objects(key=lookup).first()
    created = row is None
    if row is None:
        row = TaxonomyOverride(key=lookup, kind=kind, parent_key=parent_key)

    row.label = label
    row.is_active = bool(is_active)
    row.is_removed = False
    if sort_order is not None:
        row.sort_order = sort_order
    if icon is not None:
        row.icon = icon or ''
    row.kind = kind
    row.parent_key = parent_key
    row.save()

    return {
        'key': key,
        'kind': kind,
        'parent_key': parent_key,
        'label': row.label,
        'is_active': row.is_active,
        'sort_order': row.sort_order,
        'icon': row.icon or '',
        'source': 'code' if listing_enabled else 'admin',
        'listing_enabled': listing_enabled,
        'created': created,
        'lookup': lookup,
    }


def delete_taxonomy_entry(*, kind: str, key: str, parent_key: str = '') -> dict:
    '''Remove a category or subcategory from the admin catalog.

    Code-owned keys are soft-removed (``is_removed=True``). Admin-created
    keys are hard-deleted. Removing a category also clears its subcategories.
    '''
    kind = (kind or '').strip()
    key = (key or '').strip()
    parent_key = (parent_key or '').strip()
    if kind not in ('category', 'subcategory'):
        raise ValueError('kind must be category or subcategory')
    if not key:
        raise ValueError('key is required')

    if kind == 'category':
        if _is_code_category(key):
            # Soft-hide the category only. Code subcategories stay intact so
            # restoring the category brings its full tree back.
            row = TaxonomyOverride.objects(key=key).first()
            if row is None:
                row = TaxonomyOverride(key=key, kind='category', parent_key='')
            row.kind = 'category'
            row.parent_key = ''
            row.is_removed = True
            row.is_active = False
            row.save()
        else:
            existing = TaxonomyOverride.objects(key=key, kind='category').first()
            if existing is None:
                raise ValueError(f'Unknown category key: {key}')
            TaxonomyOverride.objects(key=key).delete()
            TaxonomyOverride.objects(kind='subcategory', parent_key=key).delete()
        return {'kind': kind, 'key': key, 'deleted': True}

    parent = resolve_category(parent_key) or parent_key
    if not parent:
        raise ValueError('parent_key is required')
    sub = key.split(':', 1)[1] if ':' in key else key
    lookup = override_lookup_key('subcategory', sub, parent)

    if _is_code_subcategory(parent, sub):
        row = TaxonomyOverride.objects(key=lookup).first()
        if row is None:
            row = TaxonomyOverride(
                key=lookup, kind='subcategory', parent_key=parent
            )
        row.kind = 'subcategory'
        row.parent_key = parent
        row.is_removed = True
        row.is_active = False
        row.save()
    else:
        deleted = TaxonomyOverride.objects(key=lookup).delete()
        if not deleted:
            raise ValueError(f'Unknown subcategory key: {sub}')

    return {
        'kind': kind,
        'key': sub,
        'parent_key': parent,
        'deleted': True,
    }


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


_label_cache = None


def clear_taxonomy_display_cache():
    global _label_cache
    _label_cache = None


def _label_maps():
    global _label_cache
    if _label_cache is not None:
        return _label_cache
    categories = {}
    subcategories = {}
    try:
        rows = TaxonomyOverride.objects(is_removed=False)
    except Exception:
        _label_cache = (categories, subcategories)
        return _label_cache
    for row in rows:
        label = (getattr(row, 'label', None) or '').strip()
        if not label:
            continue
        if row.kind == 'category':
            categories[row.key] = label
            continue
        if row.kind != 'subcategory':
            continue
        parent = getattr(row, 'parent_key', '') or ''
        sub_key = row.key.split(':', 1)[1] if ':' in (row.key or '') else row.key
        subcategories[(parent, sub_key)] = label
    _label_cache = (categories, subcategories)
    return _label_cache


def category_key_for_label(value):
    '''Return the code category key whose display name matches ``value``.'''
    if not isinstance(value, str) or not value.strip():
        return None
    target = (
        value.strip().lower().replace('&', 'and').replace(' ', '')
        .replace('_', '').replace('-', '')
    )
    categories, _subcategories = _label_maps()
    for key, label in categories.items():
        if key not in CATEGORIES:
            continue
        normalized_label = (
            label.strip().lower().replace('&', 'and').replace(' ', '')
            .replace('_', '').replace('-', '')
        )
        if normalized_label == target:
            return key
    return None


def subcategory_key_for_label(category_key, value):
    '''Return the code subcategory key whose display name matches ``value``.'''
    if not isinstance(value, str) or not value.strip() or category_key not in CATEGORIES:
        return None
    target = (
        value.strip().lower().replace('&', 'and').replace(' ', '')
        .replace('_', '').replace('-', '')
    )
    parent_norm = (
        str(category_key).strip().lower().replace('&', 'and').replace(' ', '')
        .replace('_', '').replace('-', '')
    )
    _categories, subcategories = _label_maps()
    for (parent, sub_key), label in subcategories.items():
        parent_key = parent
        if parent_key not in CATEGORIES:
            matched = None
            for key in CATEGORIES:
                key_norm = (
                    key.strip().lower().replace('&', 'and').replace(' ', '')
                    .replace('_', '').replace('-', '')
                )
                if key_norm == parent_norm:
                    matched = key
                    break
            parent_key = matched
        if parent_key != category_key:
            continue
        if sub_key not in CATEGORIES[category_key]:
            continue
        normalized_label = (
            label.strip().lower().replace('&', 'and').replace(' ', '')
            .replace('_', '').replace('-', '')
        )
        if normalized_label == target:
            return sub_key
    return None


def display_category_name(value):
    if not isinstance(value, str) or not value.strip():
        return value
    categories, _subcategories = _label_maps()
    target = (
        value.strip().lower().replace('&', 'and').replace(' ', '')
        .replace('_', '').replace('-', '')
    )
    for key, label in categories.items():
        key_norm = (
            str(key).strip().lower().replace('&', 'and').replace(' ', '')
            .replace('_', '').replace('-', '')
        )
        if key_norm == target:
            return label
    return value


def display_subcategory_name(category_value, subcategory_value):
    if not isinstance(subcategory_value, str) or not subcategory_value.strip():
        return subcategory_value
    _categories, subcategories = _label_maps()
    parent_norm = (
        str(category_value or '').strip().lower().replace('&', 'and')
        .replace(' ', '').replace('_', '').replace('-', '')
    )
    sub_norm = (
        subcategory_value.strip().lower().replace('&', 'and').replace(' ', '')
        .replace('_', '').replace('-', '')
    )
    for (parent, sub_key), label in subcategories.items():
        parent_check = (
            str(parent).strip().lower().replace('&', 'and').replace(' ', '')
            .replace('_', '').replace('-', '')
        )
        sub_check = (
            str(sub_key).strip().lower().replace('&', 'and').replace(' ', '')
            .replace('_', '').replace('-', '')
        )
        if parent_check == parent_norm and sub_check == sub_norm:
            return label
    return subcategory_value


def apply_taxonomy_display_names(data):
    '''Replace stored category keys with the admin display name.'''
    if not isinstance(data, dict):
        return data
    if data.get('category'):
        raw_category = data.get('category')
        data['category'] = display_category_name(raw_category)
        if data.get('subcategory'):
            data['subcategory'] = display_subcategory_name(
                raw_category, data.get('subcategory')
            )
    if data.get('business_category'):
        raw_category = data.get('business_category')
        data['business_category'] = display_category_name(raw_category)
        if data.get('business_subcategory'):
            data['business_subcategory'] = display_subcategory_name(
                raw_category, data.get('business_subcategory')
            )
    return data
