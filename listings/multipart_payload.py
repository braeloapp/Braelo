'''
Multipart / QueryDict helpers for listing create + update.

Django QueryDict → dict() wraps every value in a list, which breaks
mongoengine/DRF StringField validation ("Not a valid string") and drops
ints like mileage. Always flatten with .get() / getlist() instead.
'''

from __future__ import annotations

import re

from django.core.files.uploadedfile import UploadedFile

from listings.field_contract import (
    apply_field_aliases,
    coerce_optional_int_fields,
    extract_coordinates,
)


_EXISTING_PICTURE_KEY = re.compile(
    r'^existingPictures(?:\[(\d+)\])?$', re.IGNORECASE
)


def normalize_keywords(raw):
    '''
    Build a list[str] for ListField(StringField): split comma-separated text,
    strip accidental wrapping quotes (e.g. 'abc' from Postman), coerce non-strings.
    '''
    if raw is None:
        return []

    def _unwrap_token(s):
        s = str(s).strip()
        if s.startswith('[') and s.endswith(']') and ',' in s:
            s = s[1:-1].strip()
        if (s.startswith("'") and s.endswith("'")) or (
            s.startswith('"') and s.endswith('"')
        ):
            s = s[1:-1].strip()
        return s.strip('[]').strip()

    parts = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            s = _unwrap_token(item)
            if not s:
                continue
            if ',' in s:
                parts.extend(
                    [_unwrap_token(x) for x in s.split(',') if _unwrap_token(x)]
                )
            else:
                parts.append(s)
    else:
        text = _unwrap_token(raw)
        if not text:
            return []
        parts = [_unwrap_token(s) for s in text.split(',') if _unwrap_token(s)]
    out = []
    for p in parts:
        s = _unwrap_token(p)
        if s:
            out.append(s)
    return out


def _unwrap_scalar(value):
    '''Unwrap single-element lists produced by dict(QueryDict).'''
    if isinstance(value, (list, tuple)):
        if len(value) == 1:
            return value[0]
        if len(value) == 0:
            return None
    return value


def _collect_existing_picture_urls(qd):
    '''Gather existingPictures / existingPictures[n] URL strings from multipart.'''
    urls = []
    indexed = []
    keys = list(qd.keys()) if hasattr(qd, 'keys') else []
    for key in keys:
        match = _EXISTING_PICTURE_KEY.match(str(key))
        if not match:
            continue
        value = qd.get(key) if hasattr(qd, 'get') else qd[key]
        value = _unwrap_scalar(value)
        if not isinstance(value, str) or not value.strip():
            continue
        url = value.strip()
        idx = match.group(1)
        if idx is not None:
            indexed.append((int(idx), url))
        else:
            urls.append(url)
    if indexed:
        indexed.sort(key=lambda item: item[0])
        urls.extend(url for _, url in indexed)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique


def flatten_listing_request_data(request, *, for_update=False):
    '''
    Plain dict for listing serializers from multipart or JSON bodies.

    - Scalars via QueryDict.get (never dict(QueryDict))
    - keywords normalized to list[str]
    - optional ints coerced (mileage, Load_capacity, …)
    - pictures: new UploadedFile(s) + existingPictures URL strings
    '''
    qd = request.data
    payload = {}

    if hasattr(qd, 'keys'):
        for key in qd.keys():
            key_s = str(key)
            if key_s in ('pictures', 'keywords', 'listing_coordinates'):
                continue
            if _EXISTING_PICTURE_KEY.match(key_s):
                continue
            if key_s == 'access_token':
                continue
            value = qd.get(key) if hasattr(qd, 'get') else qd[key]
            payload[key_s] = _unwrap_scalar(value)
    elif isinstance(qd, dict):
        for key, value in qd.items():
            key_s = str(key)
            if key_s in ('pictures', 'keywords', 'listing_coordinates'):
                continue
            if _EXISTING_PICTURE_KEY.match(key_s):
                continue
            if key_s == 'access_token':
                continue
            payload[key_s] = _unwrap_scalar(value)

    raw_coords = None
    if hasattr(qd, 'get'):
        raw_coords = qd.get('listing_coordinates')
    elif isinstance(qd, dict):
        raw_coords = qd.get('listing_coordinates')
    raw_coords = _unwrap_scalar(raw_coords)
    if raw_coords not in (None, ''):
        coords = extract_coordinates(raw_coords)
        if coords is not None:
            payload['listing_coordinates'] = coords
        else:
            payload['listing_coordinates'] = raw_coords
    elif for_update:
        payload.pop('listing_coordinates', None)

    if hasattr(qd, 'getlist'):
        kw_list = qd.getlist('keywords')
        if len(kw_list) > 1:
            raw_kw = kw_list
        elif len(kw_list) == 1:
            raw_kw = kw_list[0]
        else:
            raw_kw = qd.get('keywords')
    else:
        raw_kw = payload.get('keywords') if 'keywords' in payload else (
            qd.get('keywords') if hasattr(qd, 'get') else None
        )
    # Always normalize when present; on update omit if client sent nothing
    if raw_kw is not None and raw_kw != '':
        payload['keywords'] = normalize_keywords(raw_kw)
    else:
        payload.pop('keywords', None)

    fb = payload.get('from_business')
    if isinstance(fb, str):
        payload['from_business'] = fb.strip().lower() in (
            'true',
            '1',
            'yes',
        )

    existing_urls = _collect_existing_picture_urls(qd)
    file_list = []
    if getattr(request, 'FILES', None) is not None:
        file_list = list(request.FILES.getlist('pictures') or [])
    # Also accept pictures already parsed into request.data
    if hasattr(qd, 'getlist'):
        for item in qd.getlist('pictures') or []:
            if isinstance(item, UploadedFile):
                file_list.append(item)
            elif isinstance(item, str) and item.strip().startswith('http'):
                existing_urls.append(item.strip())

    pictures = list(existing_urls)
    pictures.extend(file_list)
    if pictures:
        payload['pictures'] = pictures
    elif for_update:
        payload.pop('pictures', None)

    payload = apply_field_aliases(
        payload, subcategory=payload.get('subcategory')
    )
    return coerce_optional_int_fields(payload)
