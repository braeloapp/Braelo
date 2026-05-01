#!/bin/bash
# ---------------------------------------------------
# Project:        Braelo
# Date:           Mar 17, 2026
# Author:         Faizan
# ---------------------------------------------------
#
# Startup script for Azure App Service
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

# Run Django migrations
python3 manage.py migrate

# Collect static files
python3 manage.py collectstatic --noinput

# Create default superuser if not exists
echo "
from users.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser(username='admin', password='admin')
" | python3 manage.py shell

echo "Setup complete. Starting Gunicorn..."

# Start Gunicorn on Azure port
PORT=${PORT:-8000}
gunicorn --bind=0.0.0.0:$PORT manage:application
