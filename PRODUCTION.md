# CrowdSource Import — production (dedicated droplet)

This app runs on **its own DigitalOcean droplet**. It does not share a server, database, or nginx site with Elearning or any other project.

| Item | Value |
|------|-------|
| App path | `/srv/crowdsource` |
| Linux user | `crowdsource` |
| Gunicorn socket | `/run/crowdsource/crowdsource.sock` |
| Postgres DB | `crowdsource` |
| GitHub repo | `https://github.com/kamcho/crowdsource` |
| Deploy branch | `main` |

Deploy stack: **Ubuntu 24.04 · Nginx · Gunicorn · PostgreSQL · GitHub Actions**

For extra troubleshooting detail, see [DEPLOYMENT.md](./DEPLOYMENT.md).

---

## 1. Create a fresh droplet

- Ubuntu 24.04 LTS
- At least 1 GB RAM (2 GB recommended)
- SSH in as `root`

Replace placeholders throughout:

- `YOUR_DOMAIN` — e.g. `import.example.com`
- `DROPLET_IP` — droplet public IPv4

---

## 2. One-time server setup

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-dev build-essential \
    libpq-dev postgresql postgresql-contrib nginx git curl ufw

ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

adduser --system --group --home /srv/crowdsource crowdsource
usermod -aG www-data crowdsource

git clone https://github.com/kamcho/crowdsource.git /srv/crowdsource
chown -R crowdsource:www-data /srv/crowdsource
chmod +x /srv/crowdsource/deploy/update.sh
```

### PostgreSQL (dedicated to this app only)

```bash
sudo -u postgres psql <<'SQL'
CREATE DATABASE crowdsource;
CREATE USER crowdsource WITH PASSWORD 'CHANGE_ME_strong_password';
ALTER ROLE crowdsource SET client_encoding TO 'utf8';
ALTER ROLE crowdsource SET default_transaction_isolation TO 'read committed';
ALTER ROLE crowdsource SET timezone TO 'Africa/Nairobi';
GRANT ALL PRIVILEGES ON DATABASE crowdsource TO crowdsource;
\c crowdsource
GRANT ALL ON SCHEMA public TO crowdsource;
SQL
```

### Python env

```bash
cd /srv/crowdsource
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### Production `.env`

```bash
cp .env.production.example .env
nano .env
```

Generate `SECRET_KEY`:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Set at minimum:

- `SECRET_KEY`
- `ALLOWED_HOSTS=YOUR_DOMAIN,www.YOUR_DOMAIN,DROPLET_IP`
- `CSRF_TRUSTED_ORIGINS=...` (http until HTTPS, then https)
- `DB_PASSWORD` (must match Postgres user above)
- `GOOGLE_CLIENT_ID` (if using Google sign-in)
- M-Pesa / SMS / email vars as needed

Lock down:

```bash
chown crowdsource:www-data /srv/crowdsource/.env
chmod 640 /srv/crowdsource/.env
```

### Nginx site config

Edit `deploy/nginx.conf` on the droplet — replace `YOUR_DOMAIN` and `DROPLET_IP` in `server_name`.

```bash
cp /srv/crowdsource/deploy/nginx.conf /etc/nginx/sites-available/crowdsource
ln -sf /etc/nginx/sites-available/crowdsource /etc/nginx/sites-enabled/crowdsource
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
```

### First migrate + static + admin

```bash
cd /srv/crowdsource
sudo -u crowdsource .venv/bin/python manage.py migrate
sudo -u crowdsource .venv/bin/python manage.py collectstatic --noinput
sudo -u crowdsource .venv/bin/python manage.py createsuperuser
```

### Systemd (Gunicorn)

```bash
cp /srv/crowdsource/deploy/crowdsource.service /etc/systemd/system/crowdsource.service
systemctl daemon-reload
systemctl enable --now crowdsource
systemctl status crowdsource --no-pager
```

Visit `http://DROPLET_IP` — the site should load.

---

## 3. HTTPS (after DNS points to the droplet)

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d YOUR_DOMAIN -d www.YOUR_DOMAIN
```

Then update `/srv/crowdsource/.env`:

```env
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
CSRF_TRUSTED_ORIGINS=https://YOUR_DOMAIN,https://www.YOUR_DOMAIN
MPESA_CALLBACK_BASE_URL=https://YOUR_DOMAIN
```

```bash
systemctl restart crowdsource
```

Google OAuth: add `https://YOUR_DOMAIN` and `https://www.YOUR_DOMAIN` as authorized JavaScript origins.

---

## 4. Automatic deploys (GitHub Actions)

Every push to `main` runs `.github/workflows/deploy.yml`, which SSHs to the droplet and executes `deploy/update.sh`.

### GitHub secrets (repo → Settings → Secrets → Actions)

| Secret | Example |
|--------|---------|
| `DROPLET_HOST` | `203.0.113.10` |
| `DROPLET_USER` | `root` |
| `DROPLET_SSH_PASSWORD` | root password |
| `DROPLET_PORT` | `22` (optional) |

Requirements on the droplet:

- `/srv/crowdsource` is a **git clone** of this repo (not a manual scp dump)
- `.env` already exists and is **not** overwritten by deploys
- Postgres and systemd service were set up once (steps above)

### Manual redeploy on the droplet

```bash
cd /srv/crowdsource
bash deploy/update.sh
```

---

## 5. What deploy/update.sh does

1. `git fetch` + reset to `origin/main`
2. `pip install -r requirements.txt`
3. `migrate`
4. `collectstatic`
5. Sync nginx config (skips if Certbot already added SSL)
6. Restart `crowdsource` service + reload nginx

---

## 6. Pre-push checklist (local)

```powershell
python manage.py check
python manage.py test
git push origin main
```

Watch **Actions → Deploy to droplet** on GitHub.

---

## 7. Troubleshooting

| Symptom | Command / fix |
|---------|----------------|
| App crash | `journalctl -u crowdsource -e --no-pager` |
| 502 Bad Gateway | `systemctl status crowdsource`; check `/run/crowdsource/crowdsource.sock` |
| Static 404 | Re-run `collectstatic`; verify nginx `alias /srv/crowdsource/staticfiles/` |
| CSRF on login | Add HTTPS origin to `CSRF_TRUSTED_ORIGINS`, restart gunicorn |
| DB login failed | Match `DB_PASSWORD` in `.env` with Postgres role |
| Deploy fails “not a git repo” | Re-clone into `/srv/crowdsource` |

---

## 8. Dedicated droplet — do not mix with other apps

- Do **not** install Elearning (or other projects) in `/srv/crowdsource`
- Use a **separate droplet** per product if you want isolation
- This nginx site listens only for CrowdSource domains — one `server_name` block in `deploy/nginx.conf`
- Postgres database name `crowdsource` is for this app only
