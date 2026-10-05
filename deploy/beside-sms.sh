#!/usr/bin/env bash
# Install CrowdSource next to the SMS app on the shared droplet.
# Does not edit /var/www/excel-schools, the excel nginx site, or gunicorn.service.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  exec sudo bash "$0" "$@"
fi

APP=/srv/crowdsource
EXCEL_NGINX=/etc/nginx/sites-available/excel-schools
EXCEL_BEFORE=""
if [[ -f "$EXCEL_NGINX" ]]; then
  EXCEL_BEFORE="$(sha256sum "$EXCEL_NGINX")"
fi

if [[ ! -f "$APP/manage.py" ]]; then
  echo "ERROR: $APP/manage.py is missing. Upload the app before running this script."
  exit 1
fi

if ! id crowdsource >/dev/null 2>&1; then
  useradd --system --gid www-data --home-dir "$APP" --shell /usr/sbin/nologin crowdsource
fi

export DEBIAN_FRONTEND=noninteractive
free -h
if [[ -n "$(dpkg --audit)" ]]; then
  dpkg --configure -a
fi
if ! python3 -m venv /tmp/cs-venv-check >/dev/null 2>&1; then
  rm -rf /tmp/cs-venv-check
  apt-get update -y
  apt-get install -y python3-venv
else
  rm -rf /tmp/cs-venv-check
fi
if ! swapon --show | grep -q .; then
  if [[ ! -f /swapfile ]]; then
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile || true
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install --upgrade pip
"$APP/.venv/bin/pip" install --no-cache-dir -r "$APP/requirements.txt"

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='crowdsource'" | grep -q 1; then
  DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE USER crowdsource WITH PASSWORD '${DB_PASSWORD}'"
fi

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='crowdsource'" | grep -q 1; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE crowdsource OWNER crowdsource"
fi
sudo -u postgres psql -v ON_ERROR_STOP=1 -d crowdsource -c "GRANT ALL ON SCHEMA public TO crowdsource"

if [[ ! -f "$APP/.env" ]]; then
  if [[ -z "${DB_PASSWORD:-}" ]]; then
    DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER USER crowdsource WITH PASSWORD '${DB_PASSWORD}'"
  fi
  SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
  umask 077
  cat > "$APP/.env" << EOF
DEBUG=false
SECRET_KEY=${SECRET_KEY}
ALLOWED_HOSTS=137.184.137.222,kenyaimports.com,www.kenyaimports.com
CSRF_TRUSTED_ORIGINS=http://137.184.137.222:8080,http://kenyaimports.com,https://kenyaimports.com,http://www.kenyaimports.com,https://www.kenyaimports.com
SESSION_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
SECURE_SSL_REDIRECT=false
DB_ENGINE=postgres
DB_NAME=crowdsource
DB_USER=crowdsource
DB_PASSWORD=${DB_PASSWORD}
DB_HOST=127.0.0.1
DB_PORT=5432
SITE_NAME=Kenya Imports
SITE_DOMAIN=137.184.137.222:8080
SITE_PROTOCOL=http
PAYMENT_PROVIDER=demo
EOF
fi

chown crowdsource:www-data "$APP/.env"
chmod 640 "$APP/.env"
mkdir -p "$APP/media" "$APP/staticfiles"
chown -R crowdsource:www-data "$APP"

sudo -u crowdsource "$APP/.venv/bin/python" "$APP/manage.py" migrate --noinput
sudo -u crowdsource "$APP/.venv/bin/python" "$APP/manage.py" check
sudo -u crowdsource "$APP/.venv/bin/python" "$APP/manage.py" collectstatic --noinput

cp "$APP/deploy/crowdsource.service" /etc/systemd/system/crowdsource.service
systemctl daemon-reload
systemctl enable crowdsource
systemctl restart crowdsource
systemctl is-active --quiet crowdsource

cat > /etc/nginx/sites-available/crowdsource << 'EOF'
upstream crowdsource_app {
    server unix:/run/crowdsource/crowdsource.sock;
}

server {
    listen 8080;
    listen [::]:8080;
    server_name 137.184.137.222;

    client_max_body_size 25M;

    location /static/ {
        alias /srv/crowdsource/staticfiles/;
        access_log off;
        expires 30d;
    }

    location /media/ {
        alias /srv/crowdsource/media/;
        access_log off;
        expires 7d;
    }

    location / {
        proxy_pass http://crowdsource_app;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        proxy_connect_timeout 120s;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}

server {
    listen 80;
    listen [::]:80;
    server_name kenyaimports.com www.kenyaimports.com;

    client_max_body_size 25M;

    location /static/ {
        alias /srv/crowdsource/staticfiles/;
        access_log off;
        expires 30d;
    }

    location /media/ {
        alias /srv/crowdsource/media/;
        access_log off;
        expires 7d;
    }

    location / {
        proxy_pass http://crowdsource_app;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        proxy_connect_timeout 120s;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
EOF

ln -sfn /etc/nginx/sites-available/crowdsource /etc/nginx/sites-enabled/crowdsource
ufw allow 8080/tcp
nginx -t
systemctl reload nginx

if [[ -n "$EXCEL_BEFORE" ]]; then
  EXCEL_AFTER="$(sha256sum "$EXCEL_NGINX")"
  if [[ "$EXCEL_BEFORE" != "$EXCEL_AFTER" ]]; then
    echo "ERROR: excel nginx site changed."
    exit 1
  fi
fi

echo "CROWDSOURCE $(systemctl is-active crowdsource)"
echo "SMS $(systemctl is-active gunicorn)"
curl -s -o /dev/null -w "crowd_local %{http_code}\n" http://127.0.0.1:8080/
curl -s -o /dev/null -w "sms_local %{http_code}\n" -H "Host: excel-schools.com" http://127.0.0.1/
echo "INSTALL_OK"
