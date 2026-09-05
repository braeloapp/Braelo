"""
Named environment resolution for Braelo.

Used by settings.py so development / staging / production behave consistently
without hardcoded LAN IPs or insecure production defaults.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

INSECURE_SECRET_KEY = "django-insecure-dev-only-change-me"
PRODUCTION_PUBLIC_HOST = (
    "https://braelo-v1-bdaqhdc4c7d9fdb7.canadacentral-01.azurewebsites.net"
)
DEVELOPMENT_PUBLIC_HOST = "http://127.0.0.1:8000"

VALID_ENVIRONMENTS = ("development", "staging", "production")


def _env_get(env: dict, name: str, default: str = "") -> str:
    raw = env.get(name, default)
    if raw is None:
        return default
    return str(raw).strip()


def resolve_django_env(env: dict | None = None) -> str:
    """
    Resolve DJANGO_ENV.

    Order:
    1. Explicit DJANGO_ENV
    2. Azure App Service (WEBSITE_SITE_NAME) → production
    3. development
    """
    env = env if env is not None else os.environ
    explicit = _env_get(env, "DJANGO_ENV").lower()
    if explicit in VALID_ENVIRONMENTS:
        return explicit
    if explicit in ("dev", "local"):
        return "development"
    if explicit in ("prod", "prd"):
        return "production"
    if _env_get(env, "WEBSITE_SITE_NAME"):
        return "production"
    return "development"


def is_production_like(django_env: str) -> bool:
    return django_env in ("production", "staging")


def resolve_debug(env: dict | None = None, django_env: str | None = None) -> bool:
    env = env if env is not None else os.environ
    django_env = django_env or resolve_django_env(env)
    raw = env.get("DEBUG")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    return not is_production_like(django_env)


def resolve_secret_key(
    env: dict | None = None,
    django_env: str | None = None,
    debug: bool | None = None,
) -> str:
    env = env if env is not None else os.environ
    django_env = django_env or resolve_django_env(env)
    debug = resolve_debug(env, django_env) if debug is None else debug
    secret = _env_get(env, "SECRET_KEY")
    hosted = is_production_like(django_env) or not debug
    if not secret:
        if hosted:
            raise ImproperlyConfigured(
                "SECRET_KEY must be set when DEBUG is False or "
                "DJANGO_ENV is production/staging."
            )
        return INSECURE_SECRET_KEY
    if secret == INSECURE_SECRET_KEY and hosted:
        raise ImproperlyConfigured(
            "Insecure default SECRET_KEY is not allowed in production/staging."
        )
    return secret


def resolve_cors_allow_all(
    env: dict | None = None,
    debug: bool | None = None,
) -> bool:
    env = env if env is not None else os.environ
    debug = resolve_debug(env) if debug is None else debug
    raw = env.get("CORS_ALLOW_ALL_ORIGINS")
    if raw is None or str(raw).strip() == "":
        raw = env.get("CORS_ORIGIN_ALLOW_ALL")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    return bool(debug)


def resolve_public_backend_url(
    env: dict | None = None,
    django_env: str | None = None,
) -> str:
    """Canonical public origin for QR links and client-facing absolute URLs."""
    env = env if env is not None else os.environ
    django_env = django_env or resolve_django_env(env)
    explicit = (
        _env_get(env, "PUBLIC_BACKEND_URL")
        or _env_get(env, "BRAELO_PUBLIC_URL")
    ).rstrip("/")
    if explicit:
        return explicit
    if is_production_like(django_env):
        return PRODUCTION_PUBLIC_HOST
    return DEVELOPMENT_PUBLIC_HOST
