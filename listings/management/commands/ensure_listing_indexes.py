"""
Create Mongo indexes declared on ListSync and Business documents.

  python manage.py ensure_listing_indexes

Safe to re-run. Production should run this once after deploy so $near
and search filters use 2dsphere / compound indexes.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure ListSync and Business Mongo indexes (including 2dsphere)."

    def handle(self, *args, **options):
        from helpers.models.listsync import ListSync
        from users.models.business import Business

        ListSync.ensure_indexes()
        self.stdout.write(self.style.SUCCESS('ListSync indexes ensured.'))
        Business.ensure_indexes()
        self.stdout.write(self.style.SUCCESS('Business indexes ensured.'))
