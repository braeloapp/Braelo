"""
Backfill Mongo `businesses` from marketplace listing collections (vehicle_listing, …).

Use when rows were inserted directly in Mongo/Compass or before mirror code was deployed.

  python manage.py sync_listing_mirror_to_businesses
  python manage.py sync_listing_mirror_to_businesses --limit 100

Requires MONGO_URI and LISTINGS_DIRECTORY_MIRROR_ENABLED (default: on when URI valid).
"""
from django.core.management.base import BaseCommand

from users.services.listings_directory_sync import sync_all_listings_to_businesses_mirror


class Command(BaseCommand):
    help = "Upsert all marketplace listings into the businesses collection (directory mirror)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max documents per listing collection (omit for all).",
        )

    def handle(self, *args, **opts):
        lim = opts.get("limit")
        counts = sync_all_listings_to_businesses_mirror(limit_per_collection=lim)
        if not counts:
            self.stdout.write(
                self.style.WARNING(
                    "No documents processed (mirror disabled or MONGO_URI unset)."
                )
            )
            return
        total = sum(counts.values())
        self.stdout.write(self.style.SUCCESS(f"Processed {total} listing documents."))
        for src, n in sorted(counts.items()):
            self.stdout.write(f"  {src}: {n}")
