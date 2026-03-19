"""
MongoDB connection and collection access for chatbot (uses config.settings).
Database: MONGO_DB_NAME @ MONGO_DB_URI (or shared Braelo MongoDB).
"""
import logging
from django.conf import settings

_client = None
logger = logging.getLogger(__name__)


def get_client():
    """Return pymongo MongoClient (singleton)."""
    global _client
    if _client is None:
        try:
            from pymongo import MongoClient
            logger.info(
                "mongo_db.connect.start uri_set=%s db=%s",
                bool(getattr(settings, "MONGO_DB_URI", None)),
                getattr(settings, "MONGO_DB_NAME", "BraeloDB"),
            )
            _client = MongoClient(
                getattr(settings, "MONGO_DB_URI", "mongodb://localhost:27017"),
                serverSelectionTimeoutMS=5000,
            )
            _client.admin.command("ping")
            logger.info("mongo_db.connect.success")
        except Exception as e:
            logger.exception("mongo_db.connect.failed")
            raise RuntimeError(f"MongoDB connection failed: {e}") from e
    return _client


def get_db():
    """Return chatbot MongoDB database (uses MONGO_DB_URI / MONGO_DB_NAME from config.settings)."""
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
        db.users.create_index("external_id", unique=True)
    except Exception:
        logger.exception("mongo_db.ensure_indexes.users_failed")
