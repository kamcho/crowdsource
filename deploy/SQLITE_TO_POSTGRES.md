# Move data from SQLite to PostgreSQL (no data loss)

Django stores data in whatever database is configured. Switching `DB_ENGINE` only changes **new** connections — it does not copy rows. Use **dump → migrate Postgres → load**.

## Before you start

1. **Back up SQLite**
   ```powershell
   copy db.sqlite3 db.sqlite3.backup
   ```
2. **Install Postgres locally** (optional for a dry run) or use the droplet DB over SSH tunnel.
3. Keep using SQLite in `.env` until the dump step is done.

---

## Step 1 — Export from SQLite (Windows, project root)

Ensure `.env` has **no** `DB_ENGINE=postgres` (or remove it) so Django uses `db.sqlite3`.

```powershell
cd C:\Users\USER\Downloads\crowdsource
.venv\Scripts\activate
python manage.py dumpdata ^
  --natural-foreign --natural-primary ^
  --indent 2 ^
  --exclude contenttypes --exclude auth.Permission ^
  -o deploy\datadump.json
```

`-e contenttypes -e auth.Permission` avoids duplicate key errors on load; Django recreates those from your models.

Check the file size (should not be empty).

---

## Step 2 — Create empty Postgres + schema

On the droplet (or local Postgres), create DB/user (see `deploy/bootstrap.sh`).

Point `.env` at Postgres:

```env
DB_ENGINE=postgres
DB_NAME=crowdsource
DB_USER=crowdsource
DB_PASSWORD=...
DB_HOST=127.0.0.1
DB_PORT=5432
```

Then:

```powershell
python manage.py migrate
```

This builds **empty** tables in Postgres.

---

## Step 3 — Load data into Postgres

```powershell
python manage.py loaddata deploy\datadump.json
```

If you see duplicate PK errors, you ran migrate on a DB that already had data — use a fresh database or flush (destructive):

```powershell
python manage.py flush --no-input   # only on empty/dev Postgres!
python manage.py loaddata deploy\datadump.json
```

---

## Step 4 — Fix Postgres ID sequences (important)

After `loaddata`, auto-increment sequences can lag behind max IDs. Reset them:

```powershell
python manage.py sqlsequencereset users core home | python manage.py dbshell
```

On Windows, if `dbshell` is awkward, run the SQL from the command output manually in `psql`.

Or from Django shell:

```python
python manage.py shell -c "
from django.core.management import call_command
from django.db import connection
for app in ('users', 'core', 'home', 'sessions', 'sites'):
    try:
        sql = call_command('sqlsequencereset', app, stdout=...)
    except: pass
"
```

Simplest on Linux droplet:

```bash
python manage.py sqlsequencereset users core home sessions sites admin | python manage.py dbshell
```

---

## Step 5 — Verify

```powershell
python manage.py check
python manage.py shell -c "from users.models import User; from core.models import Product; print(User.objects.count(), Product.objects.count())"
```

Log in on the site; spot-check group buys, orders, media.

---

## Media & files

`dumpdata` does **not** include uploaded files. Copy the folder to the server:

```powershell
scp -r media root@DROPLET_IP:/srv/crowdsource/
```

---

## Droplet workflow (summary)

| Step | Where | Action |
|------|--------|--------|
| 1 | PC | `dumpdata` while on SQLite |
| 2 | Droplet | `bootstrap.sh` → Postgres + migrate |
| 3 | Droplet | Copy `datadump.json` + `media/` |
| 4 | Droplet | `loaddata` + `sqlsequencereset` |
| 5 | Droplet | `.env` stays on Postgres; restart gunicorn |

---

## Alternatives

- **pgloader** — fast SQLite→Postgres binary copy; can fight with Django migrations. Prefer dumpdata/loaddata unless the DB is huge.
- **Fresh start on prod** — migrate + `createsuperuser` + re-import products only; use if dev SQLite is mostly test junk.

Do **not** commit `deploy/datadump.json` (add to `.gitignore` if you keep dumps in-repo).
