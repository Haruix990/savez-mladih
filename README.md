# Savez Mladih - Zelene Beretke (local dev)

Simple Flask + static frontend project for managing news posts.

Quick start

1. Create virtualenv and install deps (Windows PowerShell):

```powershell
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Copy `.env` (already present in repo) or set your own env vars. Key variables:

- `ADMIN_PASSWORD` — password for admin login (default set in `.env`).
- `SECRET_KEY` — Flask session secret.

3. Run locally:

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
- Make sure to set `ADMIN_PASSWORD` and `SECRET_KEY` in deployment environment variables.
