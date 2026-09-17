# Droplet setup — when you have IP + password

Stack: **sync Gunicorn (WSGI)** + Nginx + PostgreSQL + GitHub Actions — same pattern as SMS-main.

## A. GitHub (do once, from your PC)

1. Push latest code to `main` on `https://github.com/kamcho/crowdsource`.
2. Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|--------|--------|
| `DROPLET_HOST` | Droplet public IP (you’ll provide tomorrow) |
| `DROPLET_USER` | `root` |
| `DROPLET_SSH_PASSWORD` | Root password (you’ll provide tomorrow) |
| `DROPLET_PORT` | `22` (optional) |

After bootstrap, every `git push` to `main` runs `deploy/update.sh` on the server.

## B. First time on the droplet (SSH as root)

From PowerShell (replace IP and password when you have them):

```powershell
ssh root@DROPLET_IP
```

On the server:

```bash
export DROPLET_IP="YOUR_IP_HERE"
export SITE_DOMAIN="kenyaimports.com"
export GIT_REPO="https://github.com/kamcho/crowdsource.git"

git clone "$GIT_REPO" /srv/crowdsource
cd /srv/crowdsource
chmod +x deploy/*.sh
bash deploy/bootstrap.sh
```

Bootstrap installs packages, Postgres, clones/uses repo, creates `.env`, migrates, static files, nginx, systemd.

## C. After bootstrap — secrets in `.env`

```bash
nano /srv/crowdsource/.env
```

Fill in (copy from local `.env` / Excel SMS where shared):

- `OPENAI_*`, `WHATSAPP_*`, `WHATSAPP_PUBLIC_BASE_URL=https://kenyaimports.com`
- `MPESA_*`, `MPESA_CALLBACK_BASE_URL=https://kenyaimports.com`
- `GOOGLE_CLIENT_ID`, `TEXTSMS_*`, email SMTP
- Keep `DEBUG=False`

Then:

```bash
systemctl restart crowdsource
cd /srv/crowdsource
sudo -u crowdsource .venv/bin/python manage.py createsuperuser
sudo -u crowdsource .venv/bin/python manage.py whatsapp_check
```

## D. HTTPS (when DNS points to the droplet)

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d kenyaimports.com -d www.kenyaimports.com
```

Ensure `.env` has `SECURE_SSL_REDIRECT=True` and HTTPS entries in `CSRF_TRUSTED_ORIGINS` (see `.env.production.example`).

```bash
systemctl restart crowdsource
```

## E. Verify

- `http://DROPLET_IP/` or `https://kenyaimports.com/`
- `systemctl status crowdsource`
- GitHub → Actions → **Deploy to droplet** (trigger manually or push to `main`)

## F. If IP or domain changes

```bash
bash /srv/crowdsource/deploy/configure-hosts.sh NEW_IP kenyaimports.com
systemctl restart crowdsource
```

## Local preflight (before you push)

```powershell
cd C:\Users\USER\Downloads\crowdsource
python manage.py check
python manage.py test
git push origin main
```

Optional: `bash deploy/preflight.sh` on WSL/Git Bash.
