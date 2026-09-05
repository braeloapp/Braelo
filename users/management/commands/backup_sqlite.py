"""Copy the configured SQLite file to a timestamped backup path."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Copy the Django SQLite database to a timestamped file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            default="",
            help="Directory for the backup file. Defaults to the SQLite parent / backups.",
        )

    def handle(self, *args, **options):
        db_name = settings.DATABASES.get("default", {}).get("NAME")
        if not db_name:
            raise CommandError("No SQLite NAME configured.")
        source = Path(db_name).expanduser()
        if not source.exists():
            raise CommandError(f"SQLite file does not exist: {source}")
        output_dir = Path(
            options["output_dir"] or (source.parent / "backups")
        ).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = output_dir / f"braelo-sqlite-{stamp}.sqlite3"
        shutil.copy2(source, destination)
        self.stdout.write(self.style.SUCCESS(str(destination)))
