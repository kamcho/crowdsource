#!/usr/bin/env bash
# Production update script — run on the droplet as root.
# Called by GitHub Actions on push to main (and safe to run manually).
set -euo pipefail

APP_DIR="/srv/crowdsource"
APP_USER="crowdsource"
VENV="$APP_DIR/.venv/bin"
NGINX_SITE="/etc/nginx/sites-available/crowdsource"

cd "$APP_DIR"

echo "==> Pulling latest code"
git fetch origin
git reset --hard origin/main
echo "    HEAD is now: $(git rev-parse --short HEAD) — $(git log -1 --pretty=%s)"

echo "==> Ensuring ownership"
chown -R "$APP_USER":www-data "$APP_DIR"
if [[ -f "$APP_DIR/.env" ]]; then
  chown "$APP_USER":www-data "$APP_DIR/.env"
  chmod 640 "$APP_DIR/.env"
fi

echo "==> Ensuring SEO site settings in .env"
ENV_FILE="$APP_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  set_env_var() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
      sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
      printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
  }
  set_env_var SITE_NAME "Kenya Imports"
  set_env_var SITE_DOMAIN "kenyaimports.com"
  set_env_var SITE_PROTOCOL "https"
  chown "$APP_USER":www-data "$ENV_FILE"
  chmod 640 "$ENV_FILE"
fi

echo "==> Installing Python dependencies"
sudo -u "$APP_USER" "$VENV/pip" install --upgrade pip
sudo -u "$APP_USER" "$VENV/pip" install -r requirements.txt

echo "==> Running migrations"
sudo -u "$APP_USER" "$VENV/python" manage.py migrate --noinput

echo "==> Collecting static files"
sudo -u "$APP_USER" "$VENV/python" manage.py collectstatic --noinput

echo "==> Syncing nginx site config"
if [[ -f "$APP_DIR/deploy/nginx.conf" ]]; then
  if [[ -f "$NGINX_SITE" ]] && grep -qE 'ssl_certificate|managed by Certbot' "$NGINX_SITE"; then
    echo "    Keeping existing nginx site (SSL already configured by Certbot)"
  else
    cp "$APP_DIR/deploy/nginx.conf" "$NGINX_SITE"
    ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/crowdsource
    rm -f /etc/nginx/sites-enabled/default
    echo "    Installed $NGINX_SITE from deploy/nginx.conf"
  fi
  grep -E '^\s*server_name' "$NGINX_SITE" || true
fi

echo "==> Restarting app (gunicorn)"
systemctl restart crowdsource
systemctl is-active --quiet crowdsource

echo "==> Reloading nginx"
if nginx -t; then
  systemctl reload nginx
fi

echo "==> Deploy complete"
systemctl status crowdsource --no-pager -l | head -n 20
