"""
MongoDB connection and collection access for chatbot (uses config.settings).
Database: MONGO_DB_NAME @ MONGO_URI (or shared Braelo MongoDB).
"""
import logging
import urllib.parse
from django.conf import settings

_client = None
logger = logging.getLogger(__name__)


def _normalize_mongo_uri_credentials(uri: str) -> str:
    """
    Ensure userinfo is RFC 3986 safe for PyMongo (encode special characters).
    Accepts already-encoded credentials (we unquote then re-encode).
    """
    uri = (uri or "").strip()
    if not uri or "://" not in uri:
        return uri
    try:
        scheme, rest = uri.split("://", 1)
        if scheme not in ("mongodb", "mongodb+srv"):
            return uri
        if "@" not in rest:
            return uri
        authority, hostpath = rest.split("@", 1)
        if ":" not in authority:
            return uri
        colon = authority.index(":")
        user_part = authority[:colon]
        pass_part = authority[colon + 1 :]
        if not user_part:
            return uri
        user_raw = urllib.parse.unquote(user_part)
        pass_raw = urllib.parse.unquote(pass_part)
        user_enc = urllib.parse.quote_plus(user_raw, safe="")
        pass_enc = urllib.parse.quote_plus(pass_raw, safe="")
        return f"{scheme}://{user_enc}:{pass_enc}@{hostpath}"
    except Exception:
        return uri


def _ensure_auth_source_admin(uri: str) -> str:
    """Atlas users authenticate against the 'admin' DB; enforce authSource=admin if missing."""
    uri = (uri or "").strip()
    if not uri:
        return uri
    try:
        parsed = urllib.parse.urlsplit(uri)
        q = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if not any(k.lower() == "authsource" for k in q.keys()):
            q["authSource"] = ["admin"]
        new_query = urllib.parse.urlencode(q, doseq=True)
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
        )
    except Exception:
        return uri


def get_client():
    """Return pymongo MongoClient (singleton)."""
    global _client
    if _client is None:
        try:
            from pymongo import MongoClient
            raw_uri = getattr(settings, "MONGO_URI", "") or "mongodb://localhost:27017"
            uri = _ensure_auth_source_admin(_normalize_mongo_uri_credentials(raw_uri))
            logger.info(
                "mongo_db.connect.start uri_set=%s db=%s",
                bool(getattr(settings, "MONGO_URI", None)),
                getattr(settings, "MONGO_DB_NAME", "BraeloDB"),
            )
            _client = MongoClient(
                uri,
                serverSelectionTimeoutMS=5000,
            )
            _client.admin.command("ping")
            logger.info("mongo_db.connect.success")
        except Exception as e:
            logger.exception("mongo_db.connect.failed")
            raise RuntimeError(f"MongoDB connection failed: {e}") from e
    return _client


def get_db():
    """Return chatbot MongoDB database (uses MONGO_URI / MONGO_DB_NAME from config.settings)."""
    db_name = getattr(settings, "MONGO_DB_NAME", "BraeloDB")
    return get_client()[db_name]


def get_collection(name: str):
    """Return collection by name."""
    return get_db()[name]


def ensure_indexes():
    """Create indexes for efficient queries. Safe if a collection does not exist yet."""
    db = get_db()
    try:
        db.knowledge_base.create_index([("state", 1), ("county", 1)])
        db.knowledge_base.create_index("state")
        db.knowledge_base.create_index("region")
        db.knowledge_base.create_index("document_source")
    except Exception:
        logger.exception("mongo_db.ensure_indexes.knowledge_base_failed")
    try:
        db.business_listings.create_index("business_category")
        db.business_listings.create_index("business_subcategory")
        db.business_listings.create_index([("business_category", 1), ("business_subcategory", 1)])
        db.business_listings.create_index("is_active")
    except Exception:
        logger.exception("mongo_db.ensure_indexes.business_listings_failed")
    try:
        db.businesses.create_index("category")
        db.businesses.create_index("subcategory")
        db.businesses.create_index([("category", 1), ("subcategory", 1)])
        db.businesses.create_index("state")
        db.businesses.create_index("zip_code")
        db.businesses.create_index("is_active")
        # User-created listings mirrored from MongoEngine `business_listings` (sparse: Lista rows omit this field)
        db.businesses.create_index(
            [("user_listing_id", 1)], unique=True, sparse=True
        )
        # Marketplace listings (vehicle_listing, …) mirrored with `listing_source` set
        db.businesses.create_index(
            [("user_listing_id", 1), ("listing_source", 1)],
            unique=True,
            partialFilterExpression={"listing_source": {"$exists": True, "$type": "string"}},
        )
        db.businesses.create_index("listing_source")
    except Exception:
        logger.exception("mongo_db.ensure_indexes.businesses_failed")
    try:
        db.users.create_index("external_id", unique=True)
    except Exception:
        logger.exception("mongo_db.ensure_indexes.users_failed")
