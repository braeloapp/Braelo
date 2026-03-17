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

# Run Django migrations
python3 manage.py migrate

# Collect static files
python3 manage.py collectstatic --noinput

# Create default superuser if not exists
echo "
from users.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser(username='admin', password='admin')
" | python manage.py shell

echo "Setup complete. Starting Gunicorn..."

# Start Gunicorn on Azure port
PORT=${PORT:-8000}
gunicorn --bind=0.0.0.0:$PORT manage:application
