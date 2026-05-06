'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Custom Django Channels middleware that authenticates WebSocket
connections using a SimpleJWT access token supplied as a query-string
parameter (``?token=<JWT>``). Falls back to an ``Authorization: Bearer``
header or the ``Sec-WebSocket-Protocol`` sub-protocol so the same
handshake works from browsers, mobile clients and Postman.

Design notes
------------
* This middleware **never raises** during the handshake. On any failure
  it sets ``scope["user"] = AnonymousUser()`` and lets the consumer
  decide how to reject. Raising ``DenyConnection`` from a middleware
  causes Daphne / uvicorn to surface a raw HTTP 403 during the upgrade,
  which is exactly the symptom seen on Azure Web App.
* Django ORM access happens through ``channels.db.database_sync_to_async``
  which auto-closes stale connections (important for App Service where
  workers idle for a while between WS handshakes).
---------------------------------------------------
'''

from __future__ import annotations

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from channels.security.websocket import AllowedHostsOriginValidator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import close_old_connections
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

logger = logging.getLogger("chats.ws.auth")


@database_sync_to_async
def _get_user(user_id):
    '''
    Resolve a Django user by primary key in a thread-safe way.
    Returns ``AnonymousUser`` if the user is missing or inactive.
    '''
    close_old_connections()
    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except (User.DoesNotExist, ValueError, TypeError):
        return AnonymousUser()
    if not getattr(user, "is_active", True):
        return AnonymousUser()
    return user


def _extract_token(scope) -> str | None:
    '''
    Pull the JWT from (in priority order):
        1. ``?token=<JWT>`` query-string parameter
        2. ``Authorization: Bearer <JWT>`` header
        3. ``Sec-WebSocket-Protocol: bearer, <JWT>`` (browser-friendly)
    '''
    qs_raw = scope.get("query_string") or b""
    if qs_raw:
        params = parse_qs(qs_raw.decode("utf-8", errors="ignore"))
        token = (params.get("token") or [None])[0]
        if token:
            return token.strip()

    headers = dict(scope.get("headers") or [])
    auth = headers.get(b"authorization") or headers.get(b"Authorization")
    if auth:
        auth_str = auth.decode("utf-8", errors="ignore").strip()
        if auth_str.lower().startswith("bearer "):
            return auth_str.split(" ", 1)[1].strip()

    swp = headers.get(b"sec-websocket-protocol")
    if swp:
        parts = [p.strip() for p in swp.decode("utf-8", errors="ignore").split(",")]
        if len(parts) == 2 and parts[0].lower() in {"bearer", "jwt"}:
            return parts[1]

    return None


class JWTAuthMiddleware(BaseMiddleware):
    '''
    Channels middleware that validates a SimpleJWT access token and
    attaches the authenticated user to ``scope["user"]``.
    '''

    async def __call__(self, scope, receive, send):
        scope["user"] = AnonymousUser()
        path = scope.get("path", "<unknown>")

        token = _extract_token(scope)
        if not token:
            logger.warning("WS auth: no token in handshake (path=%s)", path)
            return await super().__call__(scope, receive, send)

        logger.debug(
            "WS auth: token received (path=%s, len=%d)", path, len(token)
        )

        try:
            validated = AccessToken(token)
        except (InvalidToken, TokenError) as exc:
            logger.warning(
                "WS auth: invalid/expired token on %s -> %s", path, exc
            )
            return await super().__call__(scope, receive, send)
        except Exception:  # noqa: BLE001 - never break the handshake
            logger.exception("WS auth: unexpected error decoding token on %s", path)
            return await super().__call__(scope, receive, send)

        user_id = validated.get("user_id") or validated.get("sub")
        if not user_id:
            logger.warning("WS auth: token has no user_id/sub claim (path=%s)", path)
            return await super().__call__(scope, receive, send)

        user = await _get_user(user_id)
        scope["user"] = user

        if user.is_authenticated:
            logger.info(
                "WS auth: success user_id=%s path=%s", user_id, path
            )
        else:
            logger.warning(
                "WS auth: user_id=%s not found / inactive (path=%s)",
                user_id,
                path,
            )

        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    '''
    Drop-in replacement for ``channels.auth.AuthMiddlewareStack``.

    Wraps the inner application with origin validation **and** JWT auth.
    Origin validation honours ``ALLOWED_HOSTS`` so the Azure custom
    domain you already configured is accepted automatically.
    '''
    return AllowedHostsOriginValidator(JWTAuthMiddleware(inner))
