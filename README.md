# Savez Mladih - Zelene Beretke (local dev)

Simple Flask + static frontend project for managing news posts.

Quick start

1. Create virtualenv and install deps (Windows PowerShell):

```powershell
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Set your own environment variables (keep `.env` out of source control). Key variables:

- `ADMIN_PASSWORD` — local admin password.
- `SECRET_KEY` — Flask session secret; the app generates a temporary key locally if this is omitted.
- `ADMIN_PASSWORD_HASH` — preferred production admin password hash.
- `SUPABASE_ADMIN_EMAIL` — email address allowed to use the protected admin inbox and event editor.
- `SUPABASE_SERVICE_ROLE_KEY` — server-only key required to read private contact messages; never put it in browser code.
- `ENVIRONMENT=production` — enables production security requirements and secure session cookies.
- `DEV_ALLOW_CORS=1` and `DEV_CORS_ORIGINS=...` — optional, local-only CORS settings for Live Server.

Generate a password hash for production with:

```powershell
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash(input('Admin password: ')))"
```

In production, configure both `SECRET_KEY` and `ADMIN_PASSWORD_HASH`. CORS is disabled by default, login attempts are rate-limited, and the admin session cookie is HTTP-only and same-site. Do not enable development CORS in production.

The admin panel also provides a protected contact inbox and event editor. These endpoints validate the Supabase access token and allow only `SUPABASE_ADMIN_EMAIL` (defaults to the admin email shown in the panel). Events are stored in `data/events.json`; inbox status and tags are stored in `data/contact_inbox.sqlite3`. Keep the app's `data` directory on persistent storage in production.

3. Run locally (debug mode is off by default; set `DEBUG=1` only when needed):

```powershell
python app.py
```

Open http://127.0.0.1:5000 and use admin login (password from `.env`) to access the admin panel.

API curl tests

Login and save cookies:

```bash
curl -v -X POST -d "password=YOUR_PASSWORD" http://127.0.0.1:5000/api/login -c cookies.txt
```

Check session:

```bash
curl -v http://127.0.0.1:5000/api/me -b cookies.txt
```

Create news with cookie (multipart upload allowed):

```bash
curl -v -X POST -b cookies.txt -F "title=Test" -F "body=Hello" -F "password=YOUR_PASSWORD" -F "image_file=@./assets/logo.png" http://127.0.0.1:5000/api/news
```

Deployment

- A `Procfile` is included for Heroku/Render with `web: gunicorn app:app`.
- Set `ENVIRONMENT=production`, `ADMIN_PASSWORD_HASH`, and `SECRET_KEY` in deployment environment variables.

Gallery images

The gallery uses responsive WebP files with the original images as a fallback. After adding or replacing gallery photos, regenerate the variants with:

```powershell
python scripts/optimize_gallery_images.py
```
