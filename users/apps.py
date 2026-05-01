'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
app config; runs SQLite migrations on Azure at process startup when needed.
---------------------------------------------------
'''

from __future__ import annotations

import fcntl
import logging
import os
import sys
from pathlib import Path

from django.apps import AppConfig
from django.conf import settings

log = logging.getLogger(__name__)


def _is_management_cli() -> bool:
    return any(os.path.basename(a) == "manage.py" for a in sys.argv)


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"

    def ready(self) -> None:
        if _is_management_cli():
            return
        if sys.platform == "win32":
            return
        if not os.getenv("WEBSITE_SITE_NAME"):
            return
        if os.getenv("DJANGO_SKIP_STARTUP_MIGRATE", "").lower() in (
            "1",
            "true",
            "yes",
        ):
            return

        db_path = settings.DATABASES["default"].get("NAME", "")
        try:
            lock_dir = Path(str(db_path)).expanduser().parent
        except Exception:
            lock_dir = Path("/home/data")

        try:
            lock_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.warning("users.apps: could not mkdir %s", lock_dir, exc_info=True)
            return

        lock_file = lock_dir / ".django_migrate.lock"
        try:
            with open(lock_file, "w", encoding="utf-8") as fp:
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
                try:
                    from django.core.management import call_command

                    call_command("migrate", "--noinput", verbosity=1)
                finally:
                    fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        except Exception:
            log.exception("users.apps: startup migrate failed")
