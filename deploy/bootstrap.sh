#!/usr/bin/env bash
# One-time CrowdSource droplet setup (Ubuntu 24.04). Run as root.
#
# Usage:
#   export DROPLET_IP="203.0.113.10"
#   export SITE_DOMAIN="kenyaimports.com"          # optional until DNS is ready
#   export DB_PASSWORD="$(openssl rand -base64 24)"
#   export GIT_REPO="https://github.com/kamcho/crowdsource.git"
#   bash /srv/crowdsource/deploy/bootstrap.sh
#
# Or clone first, then:
#   cd /srv/crowdsource && bash deploy/bootstrap.sh
set -euo pipefail

APP_DIR="/srv/crowdsource"
APP_USER="crowdsource"
GIT_REPO="${GIT_REPO:-https://github.com/kamcho/crowdsource.git}"
DROPLET_IP="${DROPLET_IP:-}"
SITE_DOMAIN="${SITE_DOMAIN:-kenyaimports.com}"
DB_PASSWORD="${DB_PASSWORD:-}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root (e.g. ssh root@DROPLET_IP)."
  exit 1
fi

echo "==> System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get upgrade -y
apt-get install -y python3 python3-venv python3-dev build-essential \
  libpq-dev postgresql postgresql-contrib nginx git curl ufw openssl

if ! ufw status | grep -q "Status: active"; then
  ufw allow OpenSSH
  ufw allow "Nginx Full"
  ufw --force enable
fi

if ! id "$APP_USER" &>/dev/null; then
  echo "==> App user $APP_USER"
  adduser --system --group --home "$APP_DIR" "$APP_USER"
  usermod -aG www-data "$APP_USER"
fi

mkdir -p "$APP_DIR"
if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "==> Cloning $GIT_REPO"
  git clone "$GIT_REPO" "$APP_DIR"
else
  echo "==> Repo already at $APP_DIR"
fi

chown -R "$APP_USER:www-data" "$APP_DIR"
chmod +x "$APP_DIR/deploy/"*.sh 2>/dev/null || true

if [[ -z "$DB_PASSWORD" ]]; then
  DB_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
  echo "==> Generated DB password (save this): $DB_PASSWORD"
fi

echo "==> PostgreSQL database"
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${APP_USER}'" | grep -q 1; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE USER ${APP_USER} WITH PASSWORD '${DB_PASSWORD}';"
else
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER USER ${APP_USER} WITH PASSWORD '${DB_PASSWORD}';"
fi
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${APP_USER}'" | grep -q 1; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${APP_USER} OWNER ${APP_USER};"
fi
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER ROLE ${APP_USER} SET client_encoding TO 'utf8';"
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER ROLE ${APP_USER} SET default_transaction_isolation TO 'read committed';"
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER ROLE ${APP_USER} SET timezone TO 'Africa/Nairobi';"
sudo -u postgres psql -d "$APP_USER" -v ON_ERROR_STOP=1 -c "GRANT ALL ON SCHEMA public TO ${APP_USER};"

echo "==> Python virtualenv"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "==> Creating .env from template"
  cp "$APP_DIR/.env.production.example" "$APP_DIR/.env"
  SECRET_KEY="$(sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(64))")"
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" "$APP_DIR/.env"
  sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$DB_PASSWORD|" "$APP_DIR/.env"
  chown "$APP_USER:www-data" "$APP_DIR/.env"
  chmod 640 "$APP_DIR/.env"
fi

if [[ -n "$DROPLET_IP" ]] || [[ -n "$SITE_DOMAIN" ]]; then
  bash "$APP_DIR/deploy/configure-hosts.sh" "${DROPLET_IP:-}" "${SITE_DOMAIN:-}"
fi

echo "==> Nginx + systemd"
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/crowdsource
ln -sf /etc/nginx/sites-available/crowdsource /etc/nginx/sites-enabled/crowdsource
rm -f /etc/nginx/sites-enabled/default
cp "$APP_DIR/deploy/crowdsource.service" /etc/systemd/system/crowdsource.service
systemctl daemon-reload
systemctl enable crowdsource

echo "==> Migrate + static"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" migrate --noinput
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" collectstatic --noinput

nginx -t
systemctl restart nginx
systemctl restart crowdsource

echo ""
echo "=============================================="
echo " Bootstrap complete."
echo " App:     http://${DROPLET_IP:-DROPLET_IP}/"
echo " DB pass: $DB_PASSWORD  (also in $APP_DIR/.env)"
echo ""
echo " Next:"
echo "  1. Edit $APP_DIR/.env — M-Pesa, WhatsApp, OpenAI, Google, SMS"
echo "  2. sudo -u crowdsource $APP_DIR/.venv/bin/python manage.py createsuperuser"
echo "  3. GitHub Actions secrets: DROPLET_HOST, DROPLET_USER=root, DROPLET_SSH_PASSWORD"
echo "  4. After DNS: certbot --nginx -d $SITE_DOMAIN -d www.$SITE_DOMAIN"
echo "     See deploy/TOMORROW.md"
echo "=============================================="
