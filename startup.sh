#!/usr/bin/env bash
# Run on Azure Linux App Service before the web server.
# Ensures the *production* SQLite file (see SQLITE_DATABASE_PATH / /home/data/…) is migrated.
# GitHub Actions "migrate" on the runner does NOT touch this database — do not rely on it.

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_ROOT"

if [[ ! -f manage.py ]]; then
  echo "startup.sh: manage.py not found in ${APP_ROOT}" >&2
  exit 1
fi

for _venv in "$APP_ROOT/antenv" "$APP_ROOT/.venv"; do
  if [[ -f "${_venv}/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "${_venv}/bin/activate"
    break
  fi
done
unset _venv

export PYTHONPATH="${PYTHONPATH:-}:${APP_ROOT}/.python_packages/lib/site-packages"

echo "startup.sh: migrate → production DB (not CI runner)"
python manage.py migrate --noinput

python manage.py collectstatic --noinput

PORT="${PORT:-8000}"
echo "startup.sh: ASGI server on 0.0.0.0:${PORT}"
exec python -m daphne -b 0.0.0.0 -p "$PORT" config.asgi:application
