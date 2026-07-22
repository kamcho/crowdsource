# CrowdSource Import

A Django platform for crowd-sourced bulk purchasing from China. Buyers join group orders to meet factory MOQ and unlock wholesale pricing.

## Local setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py runserver 8001
```

Visit **http://127.0.0.1:8001/**

Seed sample catalog:

```powershell
python manage.py seed_catalog --group-buys
```

Create admin:

```powershell
python manage.py createsuperuser
```

## Apps

| App | Purpose |
|-----|---------|
| `core` | Products, group buys, cart, orders, payments, ops dashboard |
| `users` | Phone/password auth, Google Sign-In, roles |
| `home` | Landing page, product browse |

## Production deploy

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full DigitalOcean droplet guide:
- Ubuntu + Nginx + Gunicorn + PostgreSQL
- GitHub Actions auto-deploy on push to `main`
- Copy `.env.production.example` → `.env` on the server

## Key URLs (local)

| Path | Description |
|------|-------------|
| `/` | Landing page |
| `/users/signup/` | Register |
| `/users/signin/` | Sign in |
| `/cart/` | Shopping cart |
| `/pledges/` | My pledges → confirm & pay |
| `/orders/` | My orders |
| `/core/dashboard/` | Ops / admin dashboard |
| `/admin/` | Django admin |

## Payments

- **Dev:** `PAYMENT_PROVIDER=demo` — instant fake payment
- **Prod:** `PAYMENT_PROVIDER=mpesa` + Daraja credentials + public `MPESA_CALLBACK_BASE_URL`

## Notifications

- **Dev:** `NOTIFICATION_BACKEND=console` — logs to terminal
- **Prod:** `NOTIFICATION_BACKEND=textsms` + TextSMS credentials
