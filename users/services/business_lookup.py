'''Shared helpers for locating a user's Mongo Business document.'''

from __future__ import annotations

import logging
import re

logger = logging.getLogger('users.business_lookup')


def _user_id_candidates(user_id):
    '''Build comparable user_id variants (int / str / float) for legacy docs.'''
    candidates = []
    if user_id is None:
        return candidates
    candidates.append(user_id)
    try:
        as_int = int(user_id)
        candidates.extend([as_int, str(as_int), float(as_int)])
    except (TypeError, ValueError):
        pass
    as_str = str(user_id).strip()
    if as_str:
        candidates.append(as_str)
        try:
            candidates.append(int(as_str))
        except (TypeError, ValueError):
            pass
    # de-dupe while preserving order
    seen = set()
    unique = []
    for candidate in candidates:
        key = (type(candidate).__name__, candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def find_user_business(user_id, email=None):
    '''
    Locate the Mongo ``Business`` doc for a user.

    Defends against legacy rows where ``user_id`` was persisted as a string /
    float, or where the doc is only reliably tied via ``business_email``.

    Returns the most-recently-created match (active preferred) or ``None``.
    When a match is found via email but ``user_id`` is wrong/missing, the
    document is self-healed to the canonical int user id.
    '''
    from users.models import Business

    user_id_values = _user_id_candidates(user_id)
    email_value = (email or '').strip().lower()

    or_clauses = []
    if user_id_values:
        or_clauses.append({'user_id': {'$in': user_id_values}})
    if email_value:
        or_clauses.append(
            {
                'business_email': {
                    '$regex': f'^{re.escape(email_value)}$',
                    '$options': 'i',
                }
            }
        )

    business = None
    if or_clauses:
        try:
            business = (
                Business.objects(__raw__={'$or': or_clauses})
                .order_by('-is_active', '-created_at')
                .first()
            )
        except Exception:
            logger.exception(
                'find_user_business raw query failed user_id=%s email=%s',
                user_id,
                email_value,
            )

    # Secondary path: typed mongoengine filters (covers some driver quirks).
    if business is None:
        for candidate in user_id_values:
            try:
                business = (
                    Business.objects(user_id=candidate)
                    .order_by('-is_active', '-created_at')
                    .first()
                )
            except Exception:
                business = None
            if business is not None:
                break

    if business is None and email_value:
        try:
            business = (
                Business.objects(business_email__iexact=email_value)
                .order_by('-is_active', '-created_at')
                .first()
            )
        except Exception:
            logger.exception(
                'find_user_business email query failed email=%s', email_value
            )

    if business is None:
        logger.info(
            'find_user_business miss user_id=%s candidates=%s email=%s',
            user_id,
            user_id_values,
            email_value or None,
        )
        return None

    # Self-heal mismatched / missing user_id so future lookups succeed.
    try:
        canonical = int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        canonical = None
    if canonical is not None and business.user_id != canonical:
        previous = business.user_id
        business.user_id = canonical
        try:
            business.save()
            logger.warning(
                'find_user_business healed user_id %s -> %s business=%s',
                previous,
                canonical,
                getattr(business, 'id', None),
            )
        except Exception:
            logger.exception(
                'find_user_business failed to heal user_id business=%s',
                getattr(business, 'id', None),
            )

    return business
