#!/bin/bash
# ---------------------------------------------------
# Project:        Braelo
# Date:           Mar 17, 2026
# Author:         Faizan
# ---------------------------------------------------
#
# Startup script for Azure App Service
# Secrets (SECRET_KEY, DB, storage, etc.) come from App Settings / .env —
# never hardcode them in this script.
# ---------------------------------------------------

# Set Python packages path
export PYTHONPATH=$PYTHONPATH:/home/site/wwwroot/.python_packages/lib/site-packages

# Upgrade pip in local packages
python3 -m ensurepip --upgrade || true
python3 -m pip install --upgrade pip --target=/home/site/wwwroot/.python_packages/lib/site-packages

# Install/update requirements
python3 -m pip install --upgrade -r /home/site/wwwroot/requirements.txt --target=/home/site/wwwroot/.python_packages/lib/site-packages

# SQLite on Azure Linux defaults to /home/data/braelo.sqlite3 (see config/settings.py).
# /home persists across zip deploy; /home/site/wwwroot does not.
if [ -n "${WEBSITE_SITE_NAME:-}" ]; then
  mkdir -p /home/data
fi
if [ -n "${SQLITE_DATABASE_PATH:-}" ]; then
  mkdir -p "$(dirname "${SQLITE_DATABASE_PATH}")"
fi

# Run Django migrations against the same DB the app uses (see config/settings.py)
python3 manage.py migrate --noinput

# Collect static files
python3 manage.py collectstatic --noinput

# Optional bootstrap admin — only when credentials are provided via env
# (Azure App Settings / local .env). Never hardcode passwords here.
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  DJANGO_SUPERUSER_USERNAME="$DJANGO_SUPERUSER_USERNAME" \
  DJANGO_SUPERUSER_PASSWORD="$DJANGO_SUPERUSER_PASSWORD" \
  DJANGO_SUPERUSER_EMAIL="${DJANGO_SUPERUSER_EMAIL:-}" \
  python3 manage.py shell <<'PY'
import os
from users.models import User

username = os.environ["DJANGO_SUPERUSER_USERNAME"].strip()
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]
email = (os.environ.get("DJANGO_SUPERUSER_EMAIL") or username).strip()
if username and password and not User.objects.filter(username=username).exists():
    User.objects.create_superuser(
        username=username,
        password=password,
        email=email,
        name=username,
    )
    print(f"Created superuser {username!r}")
else:
    print("Superuser bootstrap skipped (exists or incomplete env)")
PY
fi

echo "Setup complete. Starting Daphne (ASGI, Channels)…"

# manage:application is invalid — use config.asgi (see startup.sh)
PORT=${PORT:-8000}
exec python3 -m daphne -b 0.0.0.0 -p "$PORT" config.asgi:application
