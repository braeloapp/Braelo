'''
---------------------------------------------------
Project:        Braelo
Date:           Apr 22, 2026
Author:         Faizan
---------------------------------------------------

Description:
Case/format-insensitive resolvers for the category and subcategory taxonomy.

Inputs from API clients are normalized (lowercased, "&" -> "and", spaces /
underscores / hyphens stripped) and then matched against the canonical strings
defined in ``helpers.constants.meta.CATEGORIES``. The canonical string is
returned so that callers continue to work against ``CATEGORIES`` and
``MODEL_MAP`` without any taxonomy or DB migration.
---------------------------------------------------
'''

from helpers.constants import CATEGORIES


_ALL_TOKENS = {'all'}

# Flutter historically sent Kids slug "activities" for Sports & Hobby.
# Canonical Sports subcategory is outdooractivities.
_SUBCATEGORY_ALIASES = {
    'sportsandhobby': {
        'activities': 'outdooractivities',
        'outdooractivity': 'outdooractivities',
    },
}


def _normalize_token(value):
    '''Return a comparison key for a category/subcategory string.

    Lowercases the value, replaces ``&`` with ``and``, and strips spaces,
    underscores, and hyphens. Non-strings are returned unchanged.
    '''
    if not isinstance(value, str):
        return value
    return (
        value.strip()
        .lower()
        .replace('&', 'and')
        .replace(' ', '')
        .replace('_', '')
        .replace('-', '')
    )


def is_all_token(value):
    '''True if the input is the wildcard sentinel (e.g. ``ALL`` / ``all``).'''
    return isinstance(value, str) and _normalize_token(value) in _ALL_TOKENS


def resolve_category(value):
    '''Return the canonical ``CATEGORIES`` key matching ``value``, or ``None``.

    Matching is case-insensitive and ignores spaces, underscores, hyphens, and
    ``&``/``and`` differences. The returned string is the exact key as defined
    in ``CATEGORIES`` so that downstream lookups (``MODEL_MAP``, etc.) work.
    '''
    if value is None:
        return None
    target = _normalize_token(value)
    if not target:
        return None
    for key in CATEGORIES.keys():
        if _normalize_token(key) == target:
            return key
    return None


def resolve_subcategory(category_key, value):
    '''Return the canonical subcategory string for ``category_key``, or ``None``.

    ``category_key`` must already be a canonical ``CATEGORIES`` key (use
    :func:`resolve_category` first). Matching follows the same rules as
    :func:`resolve_category`.
    '''
    if value is None:
        return None
    if category_key not in CATEGORIES:
        return None
    target = _normalize_token(value)
    if not target:
        return None
    for sub in CATEGORIES[category_key]:
        if _normalize_token(sub) == target:
            return sub
    alias_target = _SUBCATEGORY_ALIASES.get(category_key, {}).get(target)
    if alias_target:
        for sub in CATEGORIES[category_key]:
            if _normalize_token(sub) == _normalize_token(alias_target):
                return sub
        return alias_target
    return None
