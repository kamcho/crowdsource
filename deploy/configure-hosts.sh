#!/usr/bin/env bash
# Patch nginx server_name and .env hosts for droplet IP + domain.
# Usage: bash deploy/configure-hosts.sh DROPLET_IP [SITE_DOMAIN]
set -euo pipefail

APP_DIR="/srv/crowdsource"
DROPLET_IP="${1:-}"
SITE_DOMAIN="${2:-kenyaimports.com}"
NGINX_SITE="/etc/nginx/sites-available/crowdsource"
ENV_FILE="$APP_DIR/.env"

if [[ -z "$DROPLET_IP" && -z "$SITE_DOMAIN" ]]; then
  echo "Usage: configure-hosts.sh DROPLET_IP [SITE_DOMAIN]"
  exit 1
fi

build_server_name() {
  local parts=()
  if [[ -n "$SITE_DOMAIN" ]]; then
    parts+=("$SITE_DOMAIN" "www.$SITE_DOMAIN")
  fi
  if [[ -n "$DROPLET_IP" ]]; then
    parts+=("$DROPLET_IP")
  fi
  echo "${parts[*]}"
}

SERVER_NAMES="$(build_server_name)"

if [[ -f "$APP_DIR/deploy/nginx.conf" ]]; then
  sed -i "s/^\s*server_name .*/    server_name $SERVER_NAMES;/" "$APP_DIR/deploy/nginx.conf"
fi
if [[ -f "$NGINX_SITE" ]]; then
  sed -i "s/^\s*server_name .*/    server_name $SERVER_NAMES;/" "$NGINX_SITE"
fi

if [[ -f "$ENV_FILE" ]]; then
  ALLOWED=""
  CSRF=""
  if [[ -n "$SITE_DOMAIN" ]]; then
    ALLOWED="$SITE_DOMAIN,www.$SITE_DOMAIN"
    CSRF="https://$SITE_DOMAIN,https://www.$SITE_DOMAIN,http://$SITE_DOMAIN,http://www.$SITE_DOMAIN"
  fi
  if [[ -n "$DROPLET_IP" ]]; then
    [[ -n "$ALLOWED" ]] && ALLOWED+=","
    ALLOWED+="$DROPLET_IP"
    [[ -n "$CSRF" ]] && CSRF+=","
    CSRF+="http://$DROPLET_IP"
  fi

  set_env() {
    local key="$1"
    local val="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
      sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    else
      printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
    fi
  }

  [[ -n "$ALLOWED" ]] && set_env ALLOWED_HOSTS "$ALLOWED"
  [[ -n "$CSRF" ]] && set_env CSRF_TRUSTED_ORIGINS "$CSRF"
  [[ -n "$SITE_DOMAIN" ]] && set_env SITE_DOMAIN "$SITE_DOMAIN"
  if [[ -n "$SITE_DOMAIN" ]]; then
    set_env WHATSAPP_PUBLIC_BASE_URL "https://$SITE_DOMAIN"
    set_env MPESA_CALLBACK_BASE_URL "https://$SITE_DOMAIN"
  elif [[ -n "$DROPLET_IP" ]]; then
    set_env WHATSAPP_PUBLIC_BASE_URL "http://$DROPLET_IP"
    set_env MPESA_CALLBACK_BASE_URL "http://$DROPLET_IP"
  fi
fi

echo "Configured server_name: $SERVER_NAMES"
if [[ -f "$NGINX_SITE" ]] && nginx -t 2>/dev/null; then
  systemctl reload nginx
fi
