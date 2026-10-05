#!/usr/bin/env bash
# HTTPS for kenyaimports.com on the shared droplet.
# Leaves the SMS nginx site and gunicorn service unchanged.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  exec sudo bash "$0" "$@"
fi

APP=/srv/crowdsource
EXCEL_NGINX=/etc/nginx/sites-available/excel-schools
WEBROOT=/var/www/certbot
CERT=/etc/letsencrypt/live/kenyaimports.com/fullchain.pem
KEY=/etc/letsencrypt/live/kenyaimports.com/privkey.pem

EXCEL_BEFORE=""
if [[ -f "$EXCEL_NGINX" ]]; then
  EXCEL_BEFORE="$(sha256sum "$EXCEL_NGINX")"
fi

mkdir -p "$WEBROOT" /etc/nginx/snippets

cat > /etc/nginx/snippets/crowdsource-locations.conf << 'EOF'
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
EOF

write_site() {
  local with_ssl="$1"
  cat > /etc/nginx/sites-available/crowdsource << EOF
upstream crowdsource_app {
    server unix:/run/crowdsource/crowdsource.sock;
}

server {
    listen 8080;
    listen [::]:8080;
    server_name 137.184.137.222;
    include /etc/nginx/snippets/crowdsource-locations.conf;
}

server {
    listen 80;
    listen [::]:80;
    server_name kenyaimports.com www.kenyaimports.com;

    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
    }
EOF
  if [[ "$with_ssl" == "yes" ]]; then
    cat >> /etc/nginx/sites-available/crowdsource << 'EOF'
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name kenyaimports.com www.kenyaimports.com;

    ssl_certificate /etc/letsencrypt/live/kenyaimports.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kenyaimports.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:CrowdsourceSSL:10m;

    include /etc/nginx/snippets/crowdsource-locations.conf;
}
EOF
  else
    cat >> /etc/nginx/sites-available/crowdsource << 'EOF'
    include /etc/nginx/snippets/crowdsource-locations.conf;
}
EOF
  fi
}

ln -sfn /etc/nginx/sites-available/crowdsource /etc/nginx/sites-enabled/crowdsource

if [[ ! -f "$CERT" || ! -f "$KEY" ]]; then
  write_site no
  nginx -t
  systemctl reload nginx
  export DEBIAN_FRONTEND=noninteractive
  if ! command -v certbot >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y certbot
  fi
  certbot certonly --webroot -w "$WEBROOT" \
    -d kenyaimports.com -d www.kenyaimports.com \
    --non-interactive --agree-tos --register-unsafely-without-email \
    --keep-until-expiring \
    --deploy-hook "systemctl reload nginx"
fi

write_site yes
nginx -t
systemctl reload nginx

if [[ -f "$APP/.env" ]]; then
  set_env() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=" "$APP/.env"; then
      sed -i "s|^${key}=.*|${key}=${value}|" "$APP/.env"
    else
      printf '%s=%s\n' "$key" "$value" >> "$APP/.env"
    fi
  }
  set_env SITE_PROTOCOL https
  set_env SITE_DOMAIN kenyaimports.com
  set_env SESSION_COOKIE_SECURE true
  set_env CSRF_COOKIE_SECURE true
  set_env SECURE_SSL_REDIRECT false
  chown crowdsource:www-data "$APP/.env"
  chmod 640 "$APP/.env"
  systemctl restart crowdsource
fi

if [[ -n "$EXCEL_BEFORE" ]]; then
  EXCEL_AFTER="$(sha256sum "$EXCEL_NGINX")"
  if [[ "$EXCEL_BEFORE" != "$EXCEL_AFTER" ]]; then
    echo "ERROR: excel nginx site changed."
    exit 1
  fi
fi

echo "=== CERT kenyaimports ==="
echo | openssl s_client -connect 127.0.0.1:443 -servername kenyaimports.com 2>/dev/null | openssl x509 -noout -subject -ext subjectAltName
echo "=== CERT sms ==="
echo | openssl s_client -connect 127.0.0.1:443 -servername excel-schools.com 2>/dev/null | openssl x509 -noout -subject
echo "CROWDSOURCE $(systemctl is-active crowdsource)"
echo "SMS $(systemctl is-active gunicorn)"
curl -s -o /dev/null -w "crowd_https %{http_code}\n" https://kenyaimports.com/
curl -s -o /dev/null -w "sms_https %{http_code}\n" https://excel-schools.com/
echo "HTTPS_OK"
