#!/usr/bin/env bash
# Azure Oryx extracts the build to /tmp/… and runs this from that directory (not /home/site/wwwroot).
# Portal / workflow startup command must be:  bash startup.sh
# Do not use: bash /home/site/wwwroot/startup.sh  → "No such file" after extract.
#
# Ensures the *production* SQLite file (see settings: /home/data/…) is migrated.

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

# Oryx only puts antenv on PYTHONPATH; project root must be importable as "config", "chats", etc.
export PYTHONPATH="${APP_ROOT}:${PYTHONPATH:-}:${APP_ROOT}/.python_packages/lib/site-packages"

echo "startup.sh: migrate → production DB (not CI runner)"
python manage.py migrate --noinput

python manage.py collectstatic --noinput

PORT="${PORT:-8000}"
echo "startup.sh: ASGI server on 0.0.0.0:${PORT}"
exec python -m daphne -b 0.0.0.0 -p "$PORT" config.asgi:application
