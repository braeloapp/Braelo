"""
Server-side Firebase identity verification.

Never trust a client-supplied phone number or social ID. Extract the verified
identity from a Firebase ID token after firebase_admin.auth.verify_id_token.
"""

from __future__ import annotations

import logging

from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)


def verify_firebase_id_token(id_token: str) -> dict:
    token = (id_token or "").strip()
    if not token:
        raise ValidationError({"id_token": "Firebase ID token is required."})

    try:
        from firebase_admin import auth as firebase_auth
    except Exception as exc:  # pragma: no cover - import environment
        logger.warning("firebase_admin.auth unavailable: %s", exc)
        raise ValidationError(
            {"id_token": "Phone verification is unavailable."}
        ) from exc

    try:
        return firebase_auth.verify_id_token(token)
    except Exception as exc:
        name = type(exc).__name__
        if name in ("ExpiredIdTokenError",):
            raise ValidationError(
                {"id_token": "Firebase token has expired. Please verify again."}
            ) from exc
        if name in ("RevokedIdTokenError",):
            raise ValidationError(
                {"id_token": "Firebase token has been revoked. Please verify again."}
            ) from exc
        logger.warning("Firebase token verification failed: %s", exc)
        raise ValidationError({"id_token": "Invalid Firebase token."}) from exc


def phone_from_firebase_claims(claims: dict) -> str:
    phone = str((claims or {}).get("phone_number") or "").strip()
    if not phone:
        raise ValidationError(
            {
                "id_token": (
                    "Firebase token does not contain a verified phone number."
                )
            }
        )
    return phone


def extract_id_token(data: dict | None) -> str:
    payload = data or {}
    for key in ("id_token", "firebase_id_token", "firebase_token"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    return ""
