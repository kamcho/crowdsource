#!/usr/bin/env bash
# Run locally before first production push (Git Bash / WSL / Linux / macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Django check"
python manage.py check

echo "==> Tests"
python manage.py test --keepdb -v 1

echo "==> Deploy settings smoke (DEBUG=False)"
SECRET_KEY="$(python -c "import secrets; print(secrets.token_urlsafe(64))")" \
DEBUG=False \
ALLOWED_HOSTS=kenyaimports.com \
SECURE_SSL_REDIRECT=True \
SESSION_COOKIE_SECURE=True \
CSRF_COOKIE_SECURE=True \
SECURE_HSTS_SECONDS=31536000 \
python manage.py check --deploy

echo "==> OK — safe to push main and run bootstrap on droplet"
