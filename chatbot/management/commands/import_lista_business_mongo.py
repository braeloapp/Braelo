"""
Import Lista CSV into MongoDB collection `businesses` (same field style as your existing docs).

Requires: MONGO_URI and MONGO_DB_NAME in .env (e.g. MONGO_DB_NAME=braelo).

Run from the `braelo` folder:
  python manage.py import_lista_business_mongo
  python manage.py import_lista_business_mongo --replace
  python manage.py import_lista_business_mongo --path "D:\\path\\Lista de business 1 - ListaBusiness1.csv" --limit 100
"""
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from chatbot.management.commands.import_lista_business_csv import LISTA_MARKER, iter_lista_business_dicts


class Command(BaseCommand):
    help = "Import Lista de business CSV into MongoDB `businesses` collection."

    def add_arguments(self, parser):
        default_csv = Path(settings.BASE_DIR).parent / "Lista de business 1 - ListaBusiness1.csv"
        parser.add_argument(
            "--path",
            type=str,
            default=str(default_csv),
            help="Path to ListaBusiness1.csv",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help=f'Delete existing docs whose contact_info starts with {LISTA_MARKER!r} (Lista import only).',
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Import at most N rows (0 = all).",
        )

    def handle(self, *args, **opts):
        path = Path(opts["path"])
        if not path.is_file():
            self.stderr.write(self.style.ERROR(f"CSV not found: {path}"))
            return

        from chatbot.mongo_db import get_db

        db = get_db()
        coll = db.businesses

        if opts["replace"]:
            r = coll.delete_many({"contact_info": {"$regex": r"^\[ListaBusiness1\]"}})
            self.stdout.write(
                self.style.WARNING(
                    f"Removed {r.deleted_count} Mongo businesses (Lista marker in contact_info)."
                )
            )

        lim = int(opts["limit"] or 0)
        now = datetime.utcnow()
        batch = []
        total = 0

        for d in iter_lista_business_dicts(path, limit=lim):
            # Align with existing `businesses` docs (e.g. Desert Legal): languages as array, datetimes, no lista_source key.
            doc = {
                "name": d["name"],
                "category": d["category"],
                "subcategory": d["subcategory"],
                "state": d["state"],
                "city": d["city"],
                "county": d["county"],
                "zip_code": None,
                "latitude": None,
                "longitude": None,
                "languages": ["en", "es", "pt"],
                "contact_info": d["contact_info"],
                "whatsapp_url": d["whatsapp_url"] or "",
                "impression_cap": 1000,
                "impressions_used": 0,
                "rotation_index": 0,
                "is_active": True,
                "is_banned": False,
                "created_at": now,
            }
            if d.get("tags"):
                doc["tags"] = d["tags"]
            batch.append(doc)
            if len(batch) >= 300:
                coll.insert_many(batch)
                total += len(batch)
                batch = []

        if batch:
            coll.insert_many(batch)
            total += len(batch)

        if total == 0:
            self.stderr.write(self.style.ERROR("No rows imported (empty CSV or header not found)."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Inserted {total} documents into {getattr(settings, 'MONGO_DB_NAME', 'BraeloDB')}.businesses"
            )
        )
        self.stdout.write(
            "Tip: set USE_MONGO=true in .env so get_top_businesses uses this collection. "
            "Avoid load_mongo_data seed step that calls businesses.delete_many({}) unless you re-import Lista after."
        )
