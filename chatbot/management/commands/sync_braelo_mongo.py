"""
Sync Braelo MongoDB (Atlas) data into the chatbot's local MongoDB. Uses config.settings.
Usage: python manage.py sync_braelo_mongo [--dry-run]
Set BRAELO_MONGO_URI in .env for Braelo Atlas connection string.
"""
from django.core.management.base import BaseCommand
from django.conf import settings

BRAELO_COLLECTIONS = [
    "business_listings",
    "vehicle_listing",
    "services_listing",
    "real_estate_listing",
    "jobs_listing",
    "kids_listing",
    "fashion_listing",
    "furniture_listing",
    "events_listing",
    "electronics_listing",
    "sports_hobby_listing",
    "saved_listings",
    "listsync",
    "interests",
    "device_token",
    "notifications",
    "messages",
    "chats",
    "report_issue",
    "reported_users",
    "feedbacks",
    "banners_by_admin",
]


def sync_collection(source_coll, dest_coll, dry_run: bool, stdout):
    count = 0
    for doc in source_coll.find({}):
        if dry_run:
            count += 1
            continue
        doc_id = doc.get("_id")
        if doc_id is not None:
            dest_coll.replace_one({"_id": doc_id}, doc, upsert=True)
        else:
            dest_coll.insert_one(doc)
        count += 1
    return count


class Command(BaseCommand):
    help = "Sync Braelo Atlas MongoDB into chatbot local MongoDB (same tables and data format)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only list what would be synced; do not write.")

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        braelo_uri = getattr(settings, "BRAELO_MONGO_URI", "")

        if not braelo_uri:
            self.stderr.write(self.style.ERROR("BRAELO_MONGO_URI is not set. Add it to braelo .env (Braelo Atlas connection string)."))
            return

        try:
            from pymongo import MongoClient
        except ImportError:
            self.stderr.write(self.style.ERROR("pymongo is required. pip install pymongo"))
            return

        try:
            from chatbot.mongo_db import get_db
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Chatbot MongoDB config failed: {e}"))
            return

        try:
            source_client = MongoClient(braelo_uri, serverSelectionTimeoutMS=10000)
            source_client.admin.command("ping")
            source_db = source_client.get_database("braelo")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Could not connect to Braelo MongoDB: {e}"))
            return

        try:
            dest_db = get_db()
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Could not connect to chatbot MongoDB: {e}"))
            source_client.close()
            return

        if dry_run:
            self.stdout.write("DRY RUN: no data will be written.")

        total = 0
        for coll_name in BRAELO_COLLECTIONS:
            try:
                source_coll = source_db[coll_name]
                dest_coll = dest_db[coll_name]
                n = source_coll.count_documents({})
                if n == 0:
                    self.stdout.write(f"  {coll_name}: 0 docs (skip)")
                    continue
                if not dry_run:
                    synced = sync_collection(source_coll, dest_coll, dry_run=False, stdout=self.stdout)
                else:
                    synced = n
                total += synced
                self.stdout.write(self.style.SUCCESS(f"  {coll_name}: {synced} docs"))
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"  {coll_name}: {e}"))

        source_client.close()
        self.stdout.write(self.style.SUCCESS(f"Sync complete. Total documents: {total}"))
