"""
Repair SQLite django_migrations when `users.0001_initial` was never applied but
dependent apps (admin, fcm_django, token_blacklist) were — causes
InconsistentMigrationHistory and missing `users_user`.

Usage (from `braelo` directory):
  python manage.py repair_migrations_sqlite
  python manage.py migrate

Clears: django_admin_log, FCM devices, JWT blacklist tables (recreated by migrate).
After migrate, sign up / log in again; old JWTs are invalid.
"""
from django.core.management.base import BaseCommand
from django.conf import settings


def _repair_sqlite(db_path: str) -> list[str]:
    import sqlite3

    lines: list[str] = []
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM django_migrations WHERE app='users' AND name='0001_initial'")
    if c.fetchone()[0]:
        lines.append("users.0001_initial already applied - nothing to repair.")
        conn.close()
        return lines

    c.execute("SELECT COUNT(*) FROM django_migrations WHERE app='admin'")
    if c.fetchone()[0]:
        lines.append("Removing admin migration rows + django_admin_log.")
        c.execute("DELETE FROM django_migrations WHERE app='admin'")
        c.execute('DROP TABLE IF EXISTS "django_admin_log"')
        conn.commit()

    c.execute("SELECT COUNT(*) FROM django_migrations WHERE app='fcm_django'")
    if c.fetchone()[0]:
        lines.append("Removing fcm_django migration rows + fcm_django_fcmdevice.")
        c.execute("DELETE FROM django_migrations WHERE app='fcm_django'")
        c.execute('DROP TABLE IF EXISTS "fcm_django_fcmdevice"')
        conn.commit()

    c.execute("SELECT COUNT(*) FROM django_migrations WHERE app='token_blacklist'")
    if c.fetchone()[0]:
        lines.append("Removing token_blacklist migration rows + blacklist tables.")
        c.execute("DELETE FROM django_migrations WHERE app='token_blacklist'")
        c.execute('DROP TABLE IF EXISTS "token_blacklist_blacklistedtoken"')
        c.execute('DROP TABLE IF EXISTS "token_blacklist_outstandingtoken"')
        conn.commit()

    conn.close()
    lines.append("Repair finished. Run: python manage.py migrate")
    return lines


class Command(BaseCommand):
    help = "Fix SQLite migration order when users_user is missing (see module docstring)."

    def handle(self, *args, **options):
        eng = settings.DATABASES["default"].get("ENGINE", "")
        if "sqlite" not in eng:
            self.stderr.write("This command is only for SQLite.")
            return
        path = settings.DATABASES["default"]["NAME"]
        for line in _repair_sqlite(path):
            self.stdout.write(line)
