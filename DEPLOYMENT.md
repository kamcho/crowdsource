# Deploying CrowdSource Import to a DigitalOcean Droplet

> **Dedicated droplet quick start:** see [PRODUCTION.md](./PRODUCTION.md)  
> This file is the full reference (includes optional notes for sharing a server).

Stack: **Ubuntu 24.04 + Nginx + Gunicorn (WSGI) + PostgreSQL + GitHub Actions**

Throughout this guide:
- App directory: `/srv/crowdsource`
- App user: `crowdsource`
- Unix socket: `/run/crowdsource/crowdsource.sock`
- Replace `YOUR_DOMAIN` and `DROPLET_IP` with your values

---

## 0. Local sanity check (Windows, before deploying)

Local dev uses **SQLite** automatically (no `DB_ENGINE` in `.env`).

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py runserver 8001
```

---

## 1. Create the droplet & log in

Create an Ubuntu 24.04 droplet, then:

```bash
ssh root@DROPLET_IP
```

## 2. System packages

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-dev build-essential \
    libpq-dev postgresql postgresql-contrib nginx git curl ufw
```

## 3. Firewall

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
```

## 4. Create the app user

```bash
adduser --system --group --home /srv/crowdsource crowdsource
usermod -aG www-data crowdsource
```

## 5. Get the code onto the droplet

**Option A — git (recommended for GitHub Actions):**

```bash
git clone https://github.com/YOUR_USERNAME/crowdsource.git /srv/crowdsource
chown -R crowdsource:www-data /srv/crowdsource
chmod +x /srv/crowdsource/deploy/update.sh
```

**Option B — copy from your PC** (one-time, then convert to git for CI):

```powershell
scp -r C:\Users\USER\Downloads\crowdsource\* root@DROPLET_IP:/srv/crowdsource/
```

## 6. PostgreSQL: create the database & user

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

## 7. Python virtualenv & dependencies

```bash
cd /srv/crowdsource
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## 8. Production `.env`

```bash
cd /srv/crowdsource
cp .env.production.example .env
nano .env
```

Edit `deploy/nginx.conf` on the droplet (or before first push) — replace `YOUR_DOMAIN` and `DROPLET_IP` in the `server_name` line.

Generate a secret key:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Lock down secrets:

```bash
chown crowdsource:www-data /srv/crowdsource/.env
chmod 640 /srv/crowdsource/.env
```

### Google Sign-In

Add authorized JavaScript origins in Google Cloud Console:
- `https://YOUR_DOMAIN`
- `https://www.YOUR_DOMAIN`
- `http://127.0.0.1:8001` (local dev)

### M-Pesa callbacks

After HTTPS is working, set:

```env
MPESA_CALLBACK_BASE_URL=https://YOUR_DOMAIN
```

Safaricom will POST to `https://YOUR_DOMAIN/payments/mpesa/callback/`.

## 9. Migrate, collect static, create admin

```bash
cd /srv/crowdsource
sudo -u crowdsource .venv/bin/python manage.py migrate
sudo -u crowdsource .venv/bin/python manage.py collectstatic --noinput
sudo -u crowdsource .venv/bin/python manage.py createsuperuser
```

Optional seed data:

```bash
sudo -u crowdsource .venv/bin/python manage.py seed_catalog --group-buys
```

## 10. Gunicorn systemd service

```bash
cp /srv/crowdsource/deploy/crowdsource.service /etc/systemd/system/crowdsource.service
systemctl daemon-reload
systemctl enable --now crowdsource
systemctl status crowdsource --no-pager
```

Logs:

```bash
journalctl -u crowdsource -e --no-pager
```

## 11. Nginx

```bash
cp /srv/crowdsource/deploy/nginx.conf /etc/nginx/sites-available/crowdsource
ln -sf /etc/nginx/sites-available/crowdsource /etc/nginx/sites-enabled/crowdsource
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
```

Visit **http://DROPLET_IP** — the site should load.

## 12. HTTPS with Let's Encrypt

DNS A records for `@` and `www` must point to your droplet IP.

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

Restart:

```bash
systemctl restart crowdsource
```

---

## Automatic deploys (GitHub Actions)

On every push to `main`, GitHub Actions SSHs into the droplet and runs `deploy/update.sh`.

### One-time GitHub setup

1. Push this repo to GitHub (`main` branch).
2. On the droplet, `/srv/crowdsource` must be a **git clone** of that repo.
3. In GitHub → **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
|--------|-------|
| `DROPLET_HOST` | Your droplet IP |
| `DROPLET_USER` | `root` |
| `DROPLET_SSH_PASSWORD` | Droplet root password |
| `DROPLET_PORT` | `22` (optional) |

4. Push to `main` or run **Actions → Deploy to droplet → Run workflow**.

The workflow file is `.github/workflows/deploy.yml`.

### Manual redeploy (on droplet)

```bash
cd /srv/crowdsource
bash deploy/update.sh
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| App won't start | `journalctl -u crowdsource -e --no-pager` |
| 502 Bad Gateway | `systemctl status crowdsource`, `ls -l /run/crowdsource/` |
| Static files missing | Re-run `collectstatic`; check nginx `alias` path |
| CSRF errors on login | Add HTTPS origin to `CSRF_TRUSTED_ORIGINS`, restart |
| DB auth fails | Confirm `DB_PASSWORD` matches Postgres role |
| M-Pesa callback not received | Confirm `MPESA_CALLBACK_BASE_URL` is public HTTPS |
| nginx config error | `nginx -t` |

---

## Same droplet as Elearning?

You can run both apps on one droplet:
- Elearning: `/srv/elearning`, socket `/run/elearning/elearning.sock`
- CrowdSource: `/srv/crowdsource`, socket `/run/crowdsource/crowdsource.sock`

Use separate nginx `server_name` blocks (different domains) or different ports during testing.
