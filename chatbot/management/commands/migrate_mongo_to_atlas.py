"""
Copy chatbot MongoDB data from local MongoDB to MongoDB Atlas.

Examples:
  python manage.py migrate_mongo_to_atlas --dry-run
  python manage.py migrate_mongo_to_atlas --drop-target
  python manage.py migrate_mongo_to_atlas --collections users knowledge_base chat_history
  python manage.py migrate_mongo_to_atlas --source-uri mongodb://localhost:27017 --target-uri "mongodb+srv://..."
"""
from django.conf import settings
from django.core.management.base import BaseCommand


DEFAULT_COLLECTIONS = [
    "users",
    "knowledge_base",
    "chat_history",
    "ad_packages",
    "businesses",
    "business_listings",
    "impressions_log",
    "contact_tracking",
]


def _sum_docs_for_collections(db, collections):
    total = 0
    for name in collections:
        try:
            total += db[name].count_documents({})
        except Exception:
            continue
    return total


class Command(BaseCommand):
    help = "Migrate chatbot MongoDB data from local MongoDB to MongoDB Atlas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-uri",
            default="mongodb://localhost:27017",
            help="Source Mongo URI (default: mongodb://localhost:27017).",
        )
        parser.add_argument(
            "--source-db",
            default=getattr(settings, "MONGO_DB_NAME", "braelo"),
            help="Source database name (default: settings.MONGO_DB_NAME).",
        )
        parser.add_argument(
            "--target-uri",
            default=getattr(settings, "MONGO_DB_URI", ""),
            help="Target Mongo URI (default: settings.MONGO_DB_URI).",
        )
        parser.add_argument(
            "--target-db",
            default=getattr(settings, "MONGO_DB_NAME", "braelo"),
            help="Target database name (default: settings.MONGO_DB_NAME).",
        )
        parser.add_argument(
            "--collections",
            nargs="+",
            default=DEFAULT_COLLECTIONS,
            help="Collections to migrate.",
        )
        parser.add_argument(
            "--drop-target",
            action="store_true",
            help="Drop target collections before copying.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show counts only; do not write to target.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Batch size for writes (default: 500).",
        )

    def handle(self, *args, **options):
        source_uri = options["source_uri"]
        source_db_name = options["source_db"]
        target_uri = options["target_uri"]
        target_db_name = options["target_db"]
        collections = options["collections"] or DEFAULT_COLLECTIONS
        drop_target = options["drop_target"]
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        if not target_uri:
            self.stderr.write(self.style.ERROR("Target URI is empty. Set --target-uri or MONGO_DB_URI in .env."))
            return

        if "@3lO" in target_uri:
            self.stdout.write(
                self.style.WARNING(
                    "Target URI appears to contain an unescaped '@' in password. Use URL-encoded password in URI."
                )
            )

        try:
            from pymongo import MongoClient, ReplaceOne
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"pymongo import failed: {e}"))
            return

        self.stdout.write(f"Source: {source_uri} / {source_db_name}")
        self.stdout.write(f"Target: [hidden-uri] / {target_db_name}")
        self.stdout.write(f"Collections: {', '.join(collections)}")
        self.stdout.write(f"Mode: {'DRY RUN' if dry_run else 'WRITE'}")

        try:
            source_client = MongoClient(source_uri, serverSelectionTimeoutMS=10000)
            target_client = MongoClient(target_uri, serverSelectionTimeoutMS=10000)
            source_client.admin.command("ping")
            target_client.admin.command("ping")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Mongo connection failed: {e}"))
            return

        source_db = source_client[source_db_name]
        target_db = target_client[target_db_name]

        # Auto-detect common local source DB mismatch: user passes "braelo" but local chatbot data lives in "BraeloDB".
        source_total = _sum_docs_for_collections(source_db, collections)
        if source_total == 0:
            candidates = ["BraeloDB", "braelo"]
            candidates = [c for c in candidates if c != source_db_name]
            best_name = source_db_name
            best_total = source_total
            for cand in candidates:
                cand_total = _sum_docs_for_collections(source_client[cand], collections)
                if cand_total > best_total:
                    best_name = cand
                    best_total = cand_total
            if best_name != source_db_name and best_total > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"Source DB '{source_db_name}' is empty for selected collections; auto-switching to '{best_name}' ({best_total} docs)."
                    )
                )
                source_db_name = best_name
                source_db = source_client[source_db_name]

        grand_total = 0
        grand_written = 0

        for col_name in collections:
            src = source_db[col_name]
            dst = target_db[col_name]
            try:
                source_count = src.count_documents({})
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"[{col_name}] count failed on source: {e}"))
                continue

            grand_total += source_count
            self.stdout.write(f"[{col_name}] source docs: {source_count}")

            if dry_run:
                continue

            if drop_target:
                try:
                    dst.drop()
                    self.stdout.write(self.style.WARNING(f"[{col_name}] dropped target collection"))
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"[{col_name}] drop failed: {e}"))
                    continue

            try:
                cursor = src.find({}, no_cursor_timeout=True)
                ops = []
                written = 0
                for doc in cursor:
                    # Upsert by _id to avoid duplicates across reruns.
                    ops.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
                    if len(ops) >= batch_size:
                        res = dst.bulk_write(ops, ordered=False)
                        written += (res.upserted_count or 0) + (res.modified_count or 0) + (res.matched_count or 0)
                        ops = []
                if ops:
                    res = dst.bulk_write(ops, ordered=False)
                    written += (res.upserted_count or 0) + (res.modified_count or 0) + (res.matched_count or 0)
                cursor.close()
                grand_written += written
                self.stdout.write(self.style.SUCCESS(f"[{col_name}] migration done"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"[{col_name}] migration failed: {e}"))

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run complete. Total source docs across selected collections: {grand_total}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Migration complete. Processed collections docs: {grand_total}"))
            self.stdout.write(self.style.SUCCESS(f"Bulk operations (matched/modified/upserted aggregate): {grand_written}"))
            self.stdout.write("Next step: set MONGO_DB_URI on Azure App Settings to your Atlas URI and restart the app.")
