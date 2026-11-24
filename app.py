from pathlib import Path
import os
import json
import uuid
import datetime
import html
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from contextlib import closing
from flask import Flask, request, jsonify, redirect, send_from_directory, url_for, session
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from dotenv import load_dotenv
import resend
from urllib.parse import quote
from newsletter_service import (
    EMAIL_PATTERN,
    email_shell,
    hash_token,
    make_token,
    normalize_email,
    public_host,
    send_resend,
)

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
SUPABASE_CLIENT_KEY = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
SUPABASE_ADMIN_EMAIL = os.environ.get(
    'SUPABASE_ADMIN_EMAIL',
    'zeleneberetke.savezmladihsg@gmail.com'
).strip().lower()
SUPABASE_TABLE = os.environ.get('SUPABASE_TABLE', 'messages').strip()
NEWS_TABLE = os.environ.get('NEWS_TABLE', 'news').strip()
MEMBERS_TABLE = os.environ.get('MEMBERS_TABLE', 'members').strip()
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '').strip()
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH', '').strip()
NOTIFICATION_EMAIL = os.environ.get('NOTIFICATION_EMAIL', 'harunkapo@gmail.com').strip()
MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '').strip()
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '').strip()
MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com').strip()
MAIL_PORT = int(os.environ.get('MAIL_PORT', '587')) if os.environ.get('MAIL_PORT') else 587
MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').strip().lower() in ('1', 'true', 'yes')
MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').strip().lower() in ('1', 'true', 'yes')
MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', MAIL_USERNAME or f"no-reply@{SUPABASE_URL.split('://')[-1]}").strip()
MAIL_FROM = os.environ.get('MAIL_FROM', MAIL_DEFAULT_SENDER).strip()

# Resend konfiguracija za slanje email obavještenja
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '').strip()
MY_EMAIL = os.environ.get('MY_EMAIL', 'harunkapo@gmail.com').strip()
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

ENVIRONMENT = os.environ.get('ENVIRONMENT', '').strip().lower()
IS_PRODUCTION = (
    ENVIRONMENT == 'production'
    or os.environ.get('FLASK_ENV', '').strip().lower() == 'production'
    or bool(os.environ.get('RENDER'))
    or bool(os.environ.get('DYNO'))
)
SECRET_KEY = os.environ.get('SECRET_KEY', '').strip()
if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError('SECRET_KEY must be configured in production.')
if not (ADMIN_PASSWORD_HASH or ADMIN_PASSWORD):
    raise RuntimeError('Configure ADMIN_PASSWORD_HASH or ADMIN_PASSWORD before starting the app.')
if IS_PRODUCTION and not ADMIN_PASSWORD_HASH:
    raise RuntimeError('Configure ADMIN_PASSWORD_HASH in production.')

app = Flask(__name__, static_folder='.', template_folder='.')
app.config.update({
    'SECRET_KEY': SECRET_KEY or secrets.token_urlsafe(32),
    'MAIL_SERVER': MAIL_SERVER,
    'MAIL_PORT': MAIL_PORT,
    'MAIL_USE_TLS': MAIL_USE_TLS,
    'MAIL_USE_SSL': MAIL_USE_SSL,
    'MAIL_USERNAME': MAIL_USERNAME,
    'MAIL_PASSWORD': MAIL_PASSWORD,
    'MAIL_DEFAULT_SENDER': MAIL_DEFAULT_SENDER,
    'SESSION_COOKIE_HTTPONLY': True,
    'SESSION_COOKIE_SAMESITE': 'Lax',
    'SESSION_COOKIE_SECURE': os.environ.get(
        'SESSION_COOKIE_SECURE', '1' if IS_PRODUCTION else '0'
    ).strip().lower() in ('1', 'true', 'yes'),
    'PERMANENT_SESSION_LIFETIME': datetime.timedelta(hours=8),
})
mail = Mail(app)
app.secret_key = app.config['SECRET_KEY']
DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)
LOGIN_RATE_LIMIT_DB = DATA_DIR / 'login_attempts.sqlite3'
EVENTS_FILE = DATA_DIR / 'events.json'
CONTACT_INBOX_DB = DATA_DIR / 'contact_inbox.sqlite3'
LOGIN_RATE_LIMIT = 5
LOGIN_RATE_WINDOW_SECONDS = 15 * 60
CONTACT_RATE_LIMIT = 5
CONTACT_RATE_WINDOW_SECONDS = 15 * 60
NEWSLETTER_RATE_LIMIT = 5
NEWSLETTER_RATE_WINDOW_SECONDS = 15 * 60

# upload folder for news images
UPLOAD_DIR = Path('assets') / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Optional CORS support for explicitly trusted local development origins.
DEV_ALLOW_CORS = os.environ.get('DEV_ALLOW_CORS', '0').strip().lower() in ('1', 'true', 'yes')
DEV_CORS_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        'DEV_CORS_ORIGINS',
        'http://127.0.0.1:5500,http://localhost:5500'
    ).split(',')
    if origin.strip()
}
if DEV_ALLOW_CORS and not IS_PRODUCTION:
    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get('Origin')
        if origin in DEV_CORS_ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = (
                'Content-Type, Authorization, X-Requested-With, X-Admin-Password, Accept'
            )
            response.vary.add('Origin')
        return response
    
    @app.before_request
    def handle_options():
        if request.method == 'OPTIONS' and request.headers.get('Origin') in DEV_CORS_ORIGINS:
            return ('', 204)

# Human-readable category labels
CATEGORY_LABELS = {
    'obavjestenje': '📌 Obavještenje',
    'humanitarna': '🤝 Humanitarna akcija',
    'aktivnosti': '⚽ Aktivnosti i Sport',
    'historija': '📜 Historija'
}

supabase = None
SUPABASE_COLUMNS = []
if SUPABASE_URL and SUPABASE_CLIENT_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_CLIENT_KEY)
        # Detect which columns are available in the messages table.
        for column in ['name', 'username', 'email', 'message', 'content', 'created_at']:
            try:
                test_res = supabase.from_(SUPABASE_TABLE).select(column).limit(1).execute()
                if getattr(test_res, 'error', None) is None:
                    SUPABASE_COLUMNS.append(column)
            except Exception:
                pass
        if SUPABASE_SERVICE_ROLE_KEY:
            print('Supabase client created with service role key')
        else:
            print('Supabase client created with public key')
        print('Supabase columns detected:', SUPABASE_COLUMNS)
    except Exception as err:
        print('Supabase init failed:', err)


def save_local(entry):
    output_file = DATA_DIR / 'messages.json'
    if output_file.exists():
        try:
            existing = json.loads(output_file.read_text(encoding='utf-8'))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    else:
        existing = []
    existing.append(entry)
    output_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding='utf-8')


def save_news_local(entry):
    output_file = DATA_DIR / 'news.json'
    if output_file.exists():
        try:
            existing = json.loads(output_file.read_text(encoding='utf-8'))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    else:
        existing = []

    entry_copy = dict(entry)
    # ensure id and created_at
    if not entry_copy.get('id'):
        entry_copy['id'] = str(uuid.uuid4())
    if not entry_copy.get('created_at') and entry_copy.get('created'):
        entry_copy['created_at'] = entry_copy['created']
    # normalize optional fields
    if entry_copy.get('pinned') is None:
        entry_copy['pinned'] = False
    if entry_copy.get('status') is None:
        entry_copy['status'] = 'published'
    if entry_copy.get('scheduled_at'):
        # keep as-is; frontend may send ISO string
        pass
    existing.append(entry_copy)
    output_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding='utf-8')


def load_events_local():
    if not EVENTS_FILE.exists():
        return []
    try:
        events = json.loads(EVENTS_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as err:
        raise RuntimeError('Kalendar aktivnosti trenutno nije dostupan.') from err
    if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
        raise RuntimeError('Podaci kalendara nisu ispravni.')
    return events


def save_events_local(events):
    EVENTS_FILE.write_text(
        json.dumps(events, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )


def load_news_local():
    output_file = DATA_DIR / 'news.json'
    if not output_file.exists():
        return []
    try:
        existing = json.loads(output_file.read_text(encoding='utf-8'))
        if not isinstance(existing, list):
            return []
        updated = False
        for item in existing:
            if not item.get('id'):
                item['id'] = str(uuid.uuid4())
                updated = True
            if not item.get('created_at') and item.get('created'):
                item['created_at'] = item['created']
                updated = True
        if updated:
            output_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding='utf-8')
        return existing
    except Exception:
        return []


def delete_news_local(news_id):
    output_file = DATA_DIR / 'news.json'
    if not output_file.exists():
        return False
    try:
        existing = json.loads(output_file.read_text(encoding='utf-8'))
        if not isinstance(existing, list):
            return False
        filtered = [item for item in existing if str(item.get('id')) != str(news_id)]
        if len(filtered) == len(existing):
            return False
        output_file.write_text(json.dumps(filtered, indent=2, ensure_ascii=False), encoding='utf-8')
        return True
    except Exception:
        return False


def update_news_local(news_id, updated_entry):
    output_file = DATA_DIR / 'news.json'
    if not output_file.exists():
        return False
    try:
        existing = json.loads(output_file.read_text(encoding='utf-8'))
        if not isinstance(existing, list):
            return False
        updated = False
        for idx, item in enumerate(existing):
            if str(item.get('id')) == str(news_id):
                entry_copy = dict(item)
                entry_copy['title'] = updated_entry.get('title', entry_copy.get('title', ''))
                entry_copy['body'] = updated_entry.get('body', entry_copy.get('body', ''))
                entry_copy['image_url'] = updated_entry.get('image_url', entry_copy.get('image_url', ''))
                if updated_entry.get('category') is not None:
                    entry_copy['category'] = updated_entry.get('category', entry_copy.get('category', ''))
                # optional fields: pinned, status, scheduled_at
                if 'pinned' in updated_entry:
                    entry_copy['pinned'] = bool(updated_entry.get('pinned'))
                if 'status' in updated_entry and updated_entry.get('status') is not None:
                    entry_copy['status'] = updated_entry.get('status')
                if 'scheduled_at' in updated_entry and updated_entry.get('scheduled_at'):
                    entry_copy['scheduled_at'] = updated_entry.get('scheduled_at')
                entry_copy['created_at'] = entry_copy.get('created_at') or entry_copy.get('created', datetime.datetime.utcnow().isoformat() + 'Z')
                existing[idx] = entry_copy
                updated = True
                break
        if not updated:
            return False
        output_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding='utf-8')
        return True
    except Exception:
        return False


def send_notification_email(entry):
    if not (MAIL_USERNAME and MAIL_PASSWORD):
        return False, 'SMTP not configured'
    try:
        msg = Message(
            subject=f"Nova poruka sa sajta - {entry['topic_label']}",
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[NOTIFICATION_EMAIL],
            reply_to=entry['email']
        )
        msg.body = (
            f"Nova poruka sa sajta:\n\n"
            f"Ime: {entry['name']}\n"
            f"Email: {entry['email']}\n"
            f"Vrsta upita: {entry['topic_label']}\n"
            f"Organizacija: {entry['organization'] or 'Nije navedeno'}\n"
            f"Telefon: {entry['phone'] or 'Nije navedeno'}\n"
            f"Poruka:\n{entry['message']}\n\n"
            f"Poslano: {entry['created']}"
        )
        mail.send(msg)
        return True, None
    except Exception as err:
        return False, str(err)


def save_to_supabase(entry):
    if not supabase:
        return False, 'Supabase client not configured'
    if not SUPABASE_COLUMNS:
        return False, 'Supabase table schema not compatible'
    try:
        name_column = next(
            (column for column in ('name', 'username') if column in SUPABASE_COLUMNS),
            None
        )
        message_column = next(
            (column for column in ('message', 'content') if column in SUPABASE_COLUMNS),
            None
        )
        if not name_column or 'email' not in SUPABASE_COLUMNS or not message_column:
            return False, 'Supabase messages table is missing required columns'

        payload = {
            name_column: entry['name'],
            'email': entry['email'],
            message_column: entry['message']
        }
        if 'created_at' in SUPABASE_COLUMNS:
            payload['created_at'] = entry['created']

        result = supabase.from_(SUPABASE_TABLE).insert([payload]).execute()
        error = getattr(result, 'error', None)
        if error:
            return False, error
        return True, None
    except Exception as err:
        return False, str(err)


def send_contact_notification(entry):
    resend_error = None
    if RESEND_API_KEY:
        try:
            safe_message = html.escape(entry['message']).replace('\n', '<br>')
            html_body = f"""
            <div style="font-family:Arial,sans-serif;color:#333;line-height:1.6">
              <h2 style="color:#2e5e2f">Nova poruka sa web stranice</h2>
              <p><strong>Vrsta upita:</strong> {html.escape(entry['topic_label'])}</p>
              <p><strong>Ime:</strong> {html.escape(entry['name'])}</p>
              <p><strong>Email:</strong> {html.escape(entry['email'])}</p>
              <p><strong>Telefon:</strong> {html.escape(entry['phone'] or 'Nije navedeno')}</p>
              <p><strong>Organizacija:</strong> {html.escape(entry['organization'] or 'Nije navedeno')}</p>
              <hr style="border:0;border-top:1px solid #ddd;margin:20px 0">
              <h3>Poruka</h3>
              <p style="white-space:pre-wrap">{safe_message}</p>
            </div>
            """
            resend.Emails.send({
                'from': 'Savez Mladih <onboarding@resend.dev>',
                'to': MY_EMAIL,
                'reply_to': entry['email'],
                'subject': f"Nova poruka: {entry['topic_label']}",
                'html': html_body
            })
            return True, None
        except Exception as err:
            resend_error = str(err)

    sent, smtp_error = send_notification_email(entry)
    if sent:
        return True, None
    return False, resend_error or smtp_error


@app.route('/')
def index():
    host = request.host.lower()
    site_name = (os.environ.get('WEBSITE_SITE_NAME') or '').lower()
    if 'savez-mladih-admin' in host or 'savez-mladih-admin' in site_name:
        return app.send_static_file('admin-panel-savez.html')
    return app.send_static_file('index.html')


@app.route('/admin-panel-savez.html')
def admin_panel_savez_html():
    return app.send_static_file('admin-panel-savez.html')


@app.route('/admin')
def admin_panel_route():
    return app.send_static_file('admin-panel-savez.html')


def get_client_ip():
    # Render and many proxies set X-Forwarded-For with a comma-separated list
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        # take the first IP in the chain
        return forwarded.split(',')[0].strip()
    return request.remote_addr or ''


def save_news_to_supabase(entry):
    if not supabase:
        return False, 'Supabase client not configured'
    try:
        payload = {
            'title': entry.get('title', ''),
            'body': entry.get('body', ''),
            'image_url': entry.get('image_url', ''),
            'category': entry.get('category', ''),
            'created_at': entry.get('created_at', entry.get('created', ''))
        }
        if entry.get('id'):
            payload['id'] = entry['id']
        result = supabase.from_(NEWS_TABLE).insert([payload]).execute()
        error = getattr(result, 'error', None)
        if error:
            return False, error
        return True, None
    except Exception as err:
        return False, str(err)


def save_uploaded_file(file_storage):
    if not file_storage:
        return ''
    filename = secure_filename(file_storage.filename or '')
    if not filename:
        filename = f"img-{uuid.uuid4().hex}.jpg"
    else:
        # ensure unique
        name, ext = os.path.splitext(filename)
        filename = f"{name}-{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / filename
    try:
        file_storage.save(str(dest))
        return f"/assets/uploads/{filename}"
    except Exception as e:
        print('Upload save failed:', e)
        return ''


def verify_admin_password(password):
    now = time.time()
    client_key = request_client_key()

    with closing(sqlite3.connect(LOGIN_RATE_LIMIT_DB, timeout=5)) as database:
        with database:
            database.execute(
                'CREATE TABLE IF NOT EXISTS admin_login_attempts '
                '(client_key TEXT NOT NULL, attempted_at REAL NOT NULL)'
            )
            database.execute(
                'CREATE INDEX IF NOT EXISTS idx_admin_login_attempts_key_time '
                'ON admin_login_attempts (client_key, attempted_at)'
            )
            database.execute('BEGIN IMMEDIATE')
            database.execute(
                'DELETE FROM admin_login_attempts WHERE attempted_at <= ?',
                (now - LOGIN_RATE_WINDOW_SECONDS,)
            )
            row = database.execute(
                'SELECT COUNT(*), MIN(attempted_at) FROM admin_login_attempts WHERE client_key = ?',
                (client_key,)
            ).fetchone()
            attempt_count, first_attempt = row
            if attempt_count >= LOGIN_RATE_LIMIT:
                retry_after = max(
                    1,
                    int(first_attempt + LOGIN_RATE_WINDOW_SECONDS - now) + 1
                )
                return False, retry_after

            if ADMIN_PASSWORD_HASH:
                authenticated = bool(password) and check_password_hash(ADMIN_PASSWORD_HASH, password)
            else:
                authenticated = bool(password) and hmac.compare_digest(password, ADMIN_PASSWORD)

            if authenticated:
                database.execute(
                    'DELETE FROM admin_login_attempts WHERE client_key = ?',
                    (client_key,)
                )
            else:
                database.execute(
                    'INSERT INTO admin_login_attempts (client_key, attempted_at) VALUES (?, ?)',
                    (client_key, now)
                )
            return authenticated, 0


def is_admin_authenticated(password_from_form=None):
    if session.get('is_admin'):
        return True
    password = password_from_form or request.headers.get('X-Admin-Password', '').strip()
    authenticated, _ = verify_admin_password(password)
    return authenticated


def is_admin_api_authenticated():
    if session.get('is_admin'):
        return True

    authorization = request.headers.get('Authorization', '')
    if authorization.startswith('Bearer '):
        token = authorization[7:].strip()
        if not token or not supabase or not SUPABASE_ADMIN_EMAIL:
            return False
        try:
            user_response = supabase.auth.get_user(token)
            user = getattr(user_response, 'user', None)
            email = (getattr(user, 'email', '') or '').strip().lower()
            return bool(email) and hmac.compare_digest(email, SUPABASE_ADMIN_EMAIL)
        except Exception:
            app.logger.warning('Supabase admin token validation failed')
            return False

    return is_admin_authenticated()


def request_client_key():
    client_ip = request.remote_addr or 'unknown'
    return hmac.new(
        str(app.secret_key).encode('utf-8'),
        client_ip.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def contact_rate_limit_retry_after():
    now = time.time()
    client_key = request_client_key()

    with closing(sqlite3.connect(LOGIN_RATE_LIMIT_DB, timeout=5)) as database:
        with database:
            database.execute(
                'CREATE TABLE IF NOT EXISTS contact_message_attempts '
                '(client_key TEXT NOT NULL, attempted_at REAL NOT NULL)'
            )
            database.execute(
                'CREATE INDEX IF NOT EXISTS idx_contact_message_attempts_key_time '
                'ON contact_message_attempts (client_key, attempted_at)'
            )
            database.execute('BEGIN IMMEDIATE')
            database.execute(
                'DELETE FROM contact_message_attempts WHERE attempted_at <= ?',
                (now - CONTACT_RATE_WINDOW_SECONDS,)
            )
            row = database.execute(
                'SELECT COUNT(*), MIN(attempted_at) FROM contact_message_attempts WHERE client_key = ?',
                (client_key,)
            ).fetchone()
            attempt_count, first_attempt = row
            if attempt_count >= CONTACT_RATE_LIMIT:
                return max(
                    1,
                    int(first_attempt + CONTACT_RATE_WINDOW_SECONDS - now) + 1
                )
            database.execute(
                'INSERT INTO contact_message_attempts (client_key, attempted_at) VALUES (?, ?)',
                (client_key, now)
            )
            return 0


def newsletter_rate_limit_retry_after():
    now = time.time()
    client_key = request_client_key()
    with closing(sqlite3.connect(LOGIN_RATE_LIMIT_DB, timeout=5)) as database:
        with database:
            database.execute(
                'CREATE TABLE IF NOT EXISTS newsletter_attempts '
                '(client_key TEXT NOT NULL, attempted_at REAL NOT NULL)'
            )
            database.execute(
                'CREATE INDEX IF NOT EXISTS idx_newsletter_attempts_key_time '
                'ON newsletter_attempts (client_key, attempted_at)'
            )
            database.execute('BEGIN IMMEDIATE')
            database.execute(
                'DELETE FROM newsletter_attempts WHERE attempted_at <= ?',
                (now - NEWSLETTER_RATE_WINDOW_SECONDS,)
            )
            row = database.execute(
                'SELECT COUNT(*), MIN(attempted_at) FROM newsletter_attempts WHERE client_key = ?',
                (client_key,)
            ).fetchone()
            attempt_count, first_attempt = row
            if attempt_count >= NEWSLETTER_RATE_LIMIT:
                return max(
                    1,
                    int(first_attempt + NEWSLETTER_RATE_WINDOW_SECONDS - now) + 1
                )
            database.execute(
                'INSERT INTO newsletter_attempts (client_key, attempted_at) VALUES (?, ?)',
                (client_key, now)
            )
            return 0


MEMBERS_FILE = DATA_DIR / 'members.json'
PROTOCOLS_DIR = DATA_DIR / 'protocols'
PROTOCOLS_DIR.mkdir(exist_ok=True)


def load_members_local():
    if not MEMBERS_FILE.exists():
        return []
    try:
        data = json.loads(MEMBERS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    normalized = []
    for item in data:
        if not isinstance(item, dict):
            continue
        member = dict(item)
        if not member.get('id'):
            member['id'] = str(uuid.uuid4())
        if not member.get('created_at'):
            member['created_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
        if not member.get('status'):
            member['status'] = 'na_cekanju'
        normalized.append(member)
    if normalized != data:
        MEMBERS_FILE.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding='utf-8')
    return normalized


def save_members_local(entries):
    try:
        MEMBERS_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding='utf-8')
        return True
    except Exception as e:
        print('Failed to save members:', e)
        return False


def save_member_to_supabase(entry):
    if not supabase:
        return False, 'Supabase client not configured'
    try:
        payload = {
            'id': entry.get('id') or str(uuid.uuid4()),
            'prezime': entry.get('prezime', ''),
            'ime': entry.get('ime', ''),
            'ime_oca': entry.get('ime_oca', ''),
            'datum_rodjenja': entry.get('datum_rodjenja', ''),
            'mjesto_rodjenja': entry.get('mjesto_rodjenja', ''),
            'jmbg': entry.get('jmbg', ''),
            'broj_licne_karte': entry.get('broj_licne_karte', ''),
            'adresa': entry.get('adresa', ''),
            'grad': entry.get('grad', ''),
            'opcina': entry.get('opcina', ''),
            'kontakt_broj': entry.get('kontakt_broj', ''),
            'email': entry.get('email', ''),
            'strucna_sprema': entry.get('strucna_sprema', ''),
            'zanimanje': entry.get('zanimanje', ''),
            'zaposlenost': entry.get('zaposlenost', 'NE'),
            'biografija': entry.get('biografija', ''),
            'photo_url': entry.get('photo_url', ''),
            'protocol_pdf_url': entry.get('protocol_pdf_url', ''),
            'signature_data': entry.get('signature_data', ''),
            'status': entry.get('status', 'na_cekanju'),
            'created_at': entry.get('created_at', datetime.datetime.utcnow().isoformat() + 'Z'),
            'updated_at': entry.get('updated_at', datetime.datetime.utcnow().isoformat() + 'Z')
        }
        result = supabase.from_(MEMBERS_TABLE).upsert([payload], on_conflict='id').execute()
        error = getattr(result, 'error', None)
        if error:
            return False, error
        return True, None
    except Exception as err:
        return False, str(err)


SUBSCRIBERS_FILE = DATA_DIR / 'subscribers.json'

def load_subscribers():
    if not SUBSCRIBERS_FILE.exists():
        return []
    try:
        data = json.loads(SUBSCRIBERS_FILE.read_text(encoding='utf-8'))
    except Exception:
        data = []
    if not isinstance(data, list):
        data = []
    # normalize subscriber records to ensure tokens exist
    try:
        subs = data
        updated = False
        for s in subs:
            if 'unsub_token' not in s or not s.get('unsub_token'):
                s['unsub_token'] = str(uuid.uuid4())
                updated = True
            if 'confirmed' not in s:
                s['confirmed'] = bool(s.get('confirmed', False))
        if updated:
            save_subscribers(subs)
        return subs
    except Exception:
        return []

def save_subscribers(subs):
    try:
        SUBSCRIBERS_FILE.write_text(json.dumps(subs, indent=2, ensure_ascii=False), encoding='utf-8')
        return True
    except Exception as e:
        print('Failed to save subscribers:', e)
        return False


@app.route('/api/subscribe', methods=['POST'])
def api_subscribe():
    payload = request.get_json(silent=True) if request.is_json else request.form
    retry_after = newsletter_rate_limit_retry_after()
    if retry_after:
        response = jsonify({'ok': False, 'error': 'Previše zahtjeva. Pokušaj ponovo kasnije.'})
        response.headers['Retry-After'] = str(retry_after)
        return response, 429

    turnstile_secret = os.environ.get('CLOUDFLARE_TURNSTILE_SECRET', '').strip()
    if turnstile_secret:
        turnstile_token = str(payload.get('turnstile_token') or '').strip()
        if not turnstile_token:
            return jsonify({'ok': False, 'error': 'Potvrdi da nisi robot.'}), 400
        try:
            import urllib.parse
            import urllib.request
            verification = urllib.parse.urlencode({
                'secret': turnstile_secret,
                'response': turnstile_token,
                'remoteip': request.remote_addr or '',
            }).encode('utf-8')
            with urllib.request.urlopen(
                'https://challenges.cloudflare.com/turnstile/v0/siteverify',
                verification,
                timeout=5,
            ) as verification_response:
                verification_data = json.loads(verification_response.read().decode('utf-8'))
            if not verification_data.get('success'):
                return jsonify({'ok': False, 'error': 'Sigurnosna provjera nije uspjela. Pokušaj ponovo.'}), 400
        except Exception:
            app.logger.exception('Turnstile verification failed')
            return jsonify({'ok': False, 'error': 'Sigurnosna provjera trenutno nije dostupna.'}), 503

    email = normalize_email(str(payload.get('email', '') or ''))
    name = str(payload.get('name', '') or '').strip()
    consent = str(payload.get('consent', '') or '').strip().lower() in ('1', 'true', 'on', 'yes')

    if not re.fullmatch(EMAIL_PATTERN, email):
        return jsonify({'ok': False, 'error': 'Unesi ispravnu e-mail adresu.'}), 400
    if len(name) < 2 or len(name) > 120:
        return jsonify({'ok': False, 'error': 'Ime i prezime mora imati između 2 i 120 znakova.'}), 400
    if not consent:
        return jsonify({'ok': False, 'error': 'Moraš prihvatiti saglasnost za primanje newslettera.'}), 400
    if not supabase or not SUPABASE_SERVICE_ROLE_KEY:
        app.logger.error('Newsletter Supabase configuration is missing')
        return jsonify({'ok': False, 'error': 'Sistem prijave trenutno nije dostupan. Pokušaj ponovo kasnije.'}), 503

    existing_result = supabase.from_('newsletter_subscribers').select(
        'id,status,email_confirmed_at'
    ).eq('normalized_email', email).limit(1).execute()
    existing_error = getattr(existing_result, 'error', None)
    if existing_error:
        app.logger.error('Newsletter lookup failed: %s', existing_error)
        return jsonify({'ok': False, 'error': 'Pretplata trenutno ne može biti provjerena.'}), 503

    existing_rows = getattr(existing_result, 'data', None) or []
    if existing_rows:
        subscriber = existing_rows[0]
        if subscriber.get('status') == 'aktivan':
            return jsonify({
                'ok': True,
                'message': 'Ova e-mail adresa je već aktivno prijavljena.'
            }), 200
        if subscriber.get('status') == 'odjavljen':
            return jsonify({
                'ok': False,
                'error': 'Ova adresa je odjavljena. Za ponovnu prijavu potrebna je nova saglasnost.'
            }), 409
    else:
        try:
            insert_result = supabase.from_('newsletter_subscribers').insert({
                'full_name': name,
                'email': email,
                'normalized_email': email,
                'status': 'na_cekanju',
                'consent_given': True,
                'consent_given_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }).execute()
            existing_error = getattr(insert_result, 'error', None)
            if existing_error:
                raise RuntimeError(str(existing_error))
            inserted = getattr(insert_result, 'data', None) or []
            if not inserted:
                raise RuntimeError('Baza nije vratila kreiranog pretplatnika.')
            subscriber = inserted[0]
        except Exception as exc:
            app.logger.warning('Newsletter subscriber insert failed: %s', exc)
            if 'duplicate' in str(exc).lower() or 'unique' in str(exc).lower():
                subscriber_result = supabase.from_('newsletter_subscribers').select(
                    'id,status'
                ).eq('normalized_email', email).limit(1).execute()
                rows = getattr(subscriber_result, 'data', None) or []
                if not rows:
                    return jsonify({'ok': False, 'error': 'Pretplata trenutno ne može biti sačuvana.'}), 503
                subscriber = rows[0]
            else:
                return jsonify({'ok': False, 'error': 'Pretplata trenutno ne može biti sačuvana.'}), 503

    if subscriber.get('status') == 'odjavljen':
        return jsonify({
            'ok': False,
            'error': 'Ova adresa je odjavljena. Za ponovnu prijavu potrebna je nova saglasnost.'
        }), 409

    try:
        supabase.from_('newsletter_confirmation_tokens').delete().eq(
            'subscriber_id', subscriber['id']
        ).is_('used_at', 'null').execute()
    except Exception:
        app.logger.exception('Old confirmation tokens could not be cleared')

    token = make_token()
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)
    try:
        supabase.from_('newsletter_confirmation_tokens').insert({
            'subscriber_id': subscriber['id'],
            'token_hash': hash_token(token),
            'expires_at': expires_at.isoformat(),
        }).execute()
        unsubscribe_token = make_token()
        supabase.from_('newsletter_unsubscribe_tokens').upsert({
            'subscriber_id': subscriber['id'],
            'security_token': unsubscribe_token,
        }, on_conflict='subscriber_id').execute()
    except Exception as exc:
        app.logger.exception('Newsletter tokens could not be stored')
        return jsonify({'ok': False, 'error': 'Sigurnosni podaci prijave nisu sačuvani.'}), 503

    host = public_host(request)
    confirmation_url = f"{host}/api/confirm_subscription?token={quote(token, safe='')}"
    unsubscribe_url = f"{host}/api/unsubscribe?token={quote(unsubscribe_token, safe='')}"
    content = (
        f"<h1 style='margin-top:0;color:#f1d28d;'>Potvrdi prijavu, {html.escape(name)}</h1>"
        "<p>Primili smo tvoju prijavu na newsletter Saveza mladih.</p>"
        '<p style="text-align:center;margin:28px 0;">'
        f'<a href="{confirmation_url}" style="display:inline-block;padding:14px 22px;border-radius:999px;'
        'background:#b98f3b;color:#081109;text-decoration:none;font-family:Arial,sans-serif;font-weight:bold;">'
        'Potvrdi e-mail adresu</a></p>'
        "<p>Link vrijedi 24 sata. Ako ti nijesi zatražio prijavu, možeš ignorisati ovu poruku.</p>"
    )
    html = email_shell('Potvrda newsletter prijave', content, unsubscribe_url)
    sent, provider_id, send_error = send_resend(
        email,
        'Potvrdi svoju prijavu na newsletter',
        html,
        unsubscribe_url,
    )

    log_payload = {
        'subscriber_id': subscriber['id'],
        'email_type': 'potvrda',
        'provider_message_id': provider_id,
        'delivery_status': 'poslano' if sent else 'neuspjelo',
        'error_message': send_error,
        'sent_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    try:
        supabase.from_('newsletter_email_logs').insert(log_payload).execute()
    except Exception:
        app.logger.exception('Newsletter email log could not be written')

    if not sent:
        app.logger.error('Resend confirmation failed: %s', send_error)
        return jsonify({
            'ok': False,
            'error': 'Prijava je sačuvana, ali potvrda e-maila nije poslana. Pokušaj ponovo kasnije.'
        }), 502

    return jsonify({
        'ok': True,
        'message': 'Hvala! Provjeri e-mail i potvrdi svoju adresu.'
    }), 200


@app.route('/api/unsubscribe', methods=['POST','GET'])
def api_unsubscribe():
    token = str(request.values.get('token') or '').strip()
    if not token or not supabase or not SUPABASE_SERVICE_ROLE_KEY:
        return jsonify({'ok': False, 'error': 'Link za odjavu nije ispravan.'}), 400

    token_result = supabase.from_('newsletter_unsubscribe_tokens').select(
        'subscriber_id'
    ).eq('security_token', token).limit(1).execute()
    rows = getattr(token_result, 'data', None) or []
    if not rows:
        return jsonify({'ok': False, 'error': 'Link za odjavu je neispravan.'}), 404

    subscriber_id = rows[0]['subscriber_id']
    subscriber_result = supabase.from_('newsletter_subscribers').select(
        'id,email,status,full_name'
    ).eq('id', subscriber_id).limit(1).execute()
    subscribers = getattr(subscriber_result, 'data', None) or []
    if not subscribers:
        return jsonify({'ok': False, 'error': 'Pretplatnik nije pronađen.'}), 404

    subscriber = subscribers[0]
    if subscriber.get('status') != 'odjavljen':
        supabase.from_('newsletter_subscribers').update({
            'status': 'odjavljen',
            'unsubscribed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }).eq('id', subscriber_id).execute()

    try:
        supabase.from_('newsletter_unsubscribe_tokens').delete().eq(
            'subscriber_id', subscriber_id
        ).execute()
    except Exception:
        app.logger.exception('Unsubscribe token could not be consumed')

    content = (
        '<h1 style="margin-top:0;color:#f1d28d;">Odjava je potvrđena</h1>'
        f"<p>{html.escape(subscriber.get('full_name') or 'Poštovani')}, više nećeš primati newsletter poruke od Saveza mladih.</p>"
    )
    sent, provider_id, send_error = send_resend(
        subscriber['email'],
        'Potvrda odjave sa newslettera',
        email_shell('Potvrda odjave', content),
    )
    try:
        supabase.from_('newsletter_email_logs').insert({
            'subscriber_id': subscriber_id,
            'email_type': 'odjava',
            'provider_message_id': provider_id,
            'delivery_status': 'poslano' if sent else 'neuspjelo',
            'error_message': send_error,
            'sent_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }).execute()
    except Exception:
        app.logger.exception('Unsubscribe email log could not be written')

    if request.method == 'GET':
        return redirect(url_for('index') + '#newsletter')
    return jsonify({'ok': True, 'message': 'Odjava je uspješno potvrđena.'}), 200


@app.route('/api/confirm_subscription', methods=['GET'])
def api_confirm_subscription():
    token = str(request.values.get('token') or '').strip()
    if not token or not supabase or not SUPABASE_SERVICE_ROLE_KEY:
        return redirect(url_for('index') + '#newsletter')

    token_result = supabase.from_('newsletter_confirmation_tokens').select(
        'id,subscriber_id,expires_at,used_at'
    ).eq('token_hash', hash_token(token)).limit(1).execute()
    rows = getattr(token_result, 'data', None) or []
    if not rows:
        return jsonify({'ok': False, 'error': 'Link za potvrdu nije ispravan.'}), 404

    token_row = rows[0]
    if token_row.get('used_at'):
        return jsonify({'ok': False, 'error': 'Ovaj link za potvrdu je već korišten.'}), 409

    expires_at = datetime.datetime.fromisoformat(str(token_row['expires_at']).replace('Z', '+00:00'))
    if expires_at <= datetime.datetime.now(datetime.timezone.utc):
        return jsonify({'ok': False, 'error': 'Link za potvrdu je istekao. Zatraži novu prijavu.'}), 410

    consume_result = supabase.from_('newsletter_confirmation_tokens').update({
        'used_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }).eq('id', token_row['id']).is_('used_at', 'null').execute()
    consumed = getattr(consume_result, 'data', None) or []
    if not consumed:
        return jsonify({'ok': False, 'error': 'Ovaj link za potvrdu je već korišten.'}), 409

    subscriber_result = supabase.from_('newsletter_subscribers').select(
        'id,email,full_name,status'
    ).eq('id', token_row['subscriber_id']).limit(1).execute()
    subscribers = getattr(subscriber_result, 'data', None) or []
    if not subscribers:
        return jsonify({'ok': False, 'error': 'Pretplatnik nije pronađen.'}), 404
    subscriber = subscribers[0]
    if subscriber.get('status') == 'odjavljen':
        return jsonify({'ok': False, 'error': 'Pretplata je odjavljena.'}), 409

    supabase.from_('newsletter_subscribers').update({
        'status': 'aktivan',
        'email_confirmed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }).eq('id', subscriber['id']).execute()

    unsubscribe_result = supabase.from_('newsletter_unsubscribe_tokens').select(
        'security_token'
    ).eq('subscriber_id', subscriber['id']).limit(1).execute()
    unsubscribe_rows = getattr(unsubscribe_result, 'data', None) or []
    unsubscribe_url = None
    if unsubscribe_rows:
        host = public_host(request)
        unsubscribe_url = f"{host}/api/unsubscribe?token={quote(unsubscribe_rows[0]['security_token'], safe='')}"

    content = (
        '<h1 style="margin-top:0;color:#f1d28d;">Pretplata je aktivna</h1>'
        f"<p>{html.escape(subscriber.get('full_name') or 'Poštovani')}, hvala što pratiš rad Saveza mladih.</p>"
        "<p>Uskoro ćeš dobiti najave događaja, izvještaje sa akcija i važne obavijesti.</p>"
    )
    sent, provider_id, send_error = send_resend(
        subscriber['email'],
        'Dobrodošli u newsletter Saveza mladih',
        email_shell('Aktivna newsletter pretplata', content, unsubscribe_url),
        unsubscribe_url,
    )
    try:
        supabase.from_('newsletter_email_logs').insert({
            'subscriber_id': subscriber['id'],
            'email_type': 'aktivacija',
            'provider_message_id': provider_id,
            'delivery_status': 'poslano' if sent else 'neuspjelo',
            'error_message': send_error,
            'sent_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }).execute()
    except Exception:
        app.logger.exception('Activation email log could not be written')

    return redirect(url_for('index') + '#newsletter')


@app.route('/api/subscribers', methods=['GET'])
def api_list_subscribers():
    if not is_admin_api_authenticated():
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    if not supabase or not SUPABASE_SERVICE_ROLE_KEY:
        return jsonify({'ok': False, 'error': 'Supabase nije konfigurisan.'}), 503
    try:
        result = supabase.from_('newsletter_subscribers').select(
            'id,full_name,normalized_email,status,consent_given,consent_given_at,'
            'email_confirmed_at,unsubscribed_at,registered_at,updated_at'
        ).order('registered_at', desc=True).limit(1000).execute()
        rows = getattr(result, 'data', None) or []
        subscribers = [{
            'id': row['id'],
            'name': row['full_name'],
            'email': row['normalized_email'],
            'confirmed': row['status'] == 'aktivan',
            'status': row['status'],
            'subscribed_at': row['registered_at'],
            'confirmed_at': row.get('email_confirmed_at'),
        } for row in rows]
        return jsonify({'ok': True, 'count': len(subscribers), 'subscribers': subscribers}), 200
    except Exception:
        app.logger.exception('Newsletter subscribers could not be loaded')
        return jsonify({'ok': False, 'error': 'Pretplatnici se trenutno ne mogu učitati.'}), 503


@app.route('/api/subscriber/delete', methods=['POST'])
def api_delete_subscriber():
    if not is_admin_api_authenticated():
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    payload = request.get_json(silent=True) if request.is_json else request.form
    subscriber_id = str(payload.get('id') or '').strip()
    email = normalize_email(str(payload.get('email') or '').strip())
    if not subscriber_id and not email:
        return jsonify({'ok': False, 'error': 'ID ili e-mail pretplatnika su obavezni.'}), 400
    if not supabase or not SUPABASE_SERVICE_ROLE_KEY:
        return jsonify({'ok': False, 'error': 'Supabase nije konfigurisan.'}), 503

    query = supabase.from_('newsletter_subscribers').select('id,status').limit(1)
    query = query.eq('id', subscriber_id) if subscriber_id else query.eq('normalized_email', email)
    result = query.execute()
    rows = getattr(result, 'data', None) or []
    if not rows:
        return jsonify({'ok': False, 'error': 'Pretplatnik nije pronađen.'}), 404
    if rows[0].get('status') == 'odjavljen':
        return jsonify({'ok': True, 'message': 'Pretplatnik je već odjavljen.'}), 200

    supabase.from_('newsletter_subscribers').update({
        'status': 'odjavljen',
        'unsubscribed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }).eq('id', rows[0]['id']).execute()
    try:
        supabase.from_('newsletter_admin_activity').insert({
            'action': 'newsletter_manual_unsubscribe',
            'details': {'subscriber_id': rows[0]['id']},
        }).execute()
    except Exception:
        app.logger.exception('Newsletter admin activity could not be written')
    return jsonify({'ok': True}), 200


@app.route('/api/subscriber/confirm', methods=['POST'])
def api_confirm_subscriber():
    if not is_admin_api_authenticated():
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    return jsonify({
        'ok': False,
        'error': 'Pretplatnik se ne može ručno potvrditi. Potrebna je nova potvrda e-maila.'
    }), 409


@app.route('/api/subscribers/export', methods=['GET'])
def api_export_subscribers():
    if not is_admin_api_authenticated():
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    if not supabase or not SUPABASE_SERVICE_ROLE_KEY:
        return jsonify({'ok': False, 'error': 'Supabase nije konfigurisan.'}), 503
    result = supabase.from_('newsletter_subscribers').select(
        'normalized_email,full_name,status,registered_at,email_confirmed_at'
    ).order('registered_at', desc=True).execute()
    rows = getattr(result, 'data', None) or []
    lines = ['email,name,status,subscribed_at,confirmed_at']
    for row in rows:
        values = [
            row.get('normalized_email', ''),
            row.get('full_name', ''),
            row.get('status', ''),
            row.get('registered_at', ''),
            row.get('email_confirmed_at', ''),
        ]
        escaped = []
        for value in values:
            text = '' if value is None else str(value).replace('"', '""')
            escaped.append(f'"{text}"')
        lines.append(','.join(escaped))
    csv_body = '\n'.join(lines)
    from flask import Response
    resp = Response(csv_body, mimetype='text/csv')
    resp.headers['Content-Disposition'] = 'attachment; filename="subscribers.csv"'
    return resp


def send_confirmation_email(email, token):
    # Build confirmation link
    host = os.environ.get('PUBLIC_HOST') or request.host_url.rstrip('/')
    link = f"{host}/api/confirm_subscription?token={token}"
    subject = 'Potvrdi svoju prijavu na newsletter'
    html = f"<p>Hvala na prijavi. Klikni ovaj link da potvrdiš: <a href=\"{link}\">Potvrdi prijavu</a></p>"
    # try SendGrid
    if os.environ.get('SENDGRID_API_KEY'):
        try:
            import importlib
            sendgrid = importlib.import_module('sendgrid')
            helpers = importlib.import_module('sendgrid.helpers.mail')
            SendGridAPIClient = sendgrid.SendGridAPIClient
            Mail = helpers.Mail
            sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            msg = Mail(from_email=MAIL_DEFAULT_SENDER, to_emails=email, subject=subject, html_content=html)
            sg.send(msg)
            return True
        except ImportError as e:
            print('SendGrid library unavailable:', e)
        except Exception as e:
            print('SendGrid confirm send error:', e)
    # try Flask-Mail SMTP
    if MAIL_USERNAME and MAIL_PASSWORD:
        try:
            msg = Message(
                subject=subject,
                sender=app.config['MAIL_DEFAULT_SENDER'],
                recipients=[email]
            )
            msg.body = f"Potvrdi prijavu: {link}"
            msg.html = html
            mail.send(msg)
            return True
        except Exception as e:
            print('SMTP confirm send error:', e)
    # not configured — return False so frontend can display token for manual copy
    return False


@app.route('/api/send_newsletter', methods=['POST'])
def api_send_newsletter():
    if not is_admin_api_authenticated():
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    if not supabase or not SUPABASE_SERVICE_ROLE_KEY:
        return jsonify({'ok': False, 'error': 'Supabase nije konfigurisan.'}), 503

    payload = request.get_json(silent=True) if request.is_json else request.form
    subject = str(payload.get('subject') or '').strip()
    content = str(payload.get('html') or payload.get('body') or '').strip()
    if len(subject) < 1 or len(subject) > 160:
        return jsonify({'ok': False, 'error': 'Naslov poruke mora imati između 1 i 160 znakova.'}), 400
    if len(content) < 1:
        return jsonify({'ok': False, 'error': 'Sadržaj kampanje je obavezan.'}), 400

    campaign_result = supabase.from_('newsletter_campaigns').insert({
        'title': subject,
        'email_subject': subject,
        'html_content': content,
        'status': 'poslana',
        'sent_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }).execute()
    campaigns = getattr(campaign_result, 'data', None) or []
    if not campaigns:
        app.logger.error('Newsletter campaign could not be created')
        return jsonify({'ok': False, 'error': 'Kampanja nije sačuvana.'}), 503
    campaign = campaigns[0]

    subscribers_result = supabase.from_('newsletter_subscribers').select(
        'id,email,full_name'
    ).eq('status', 'aktivan').execute()
    subscribers = getattr(subscribers_result, 'data', None) or []
    sent_count = 0
    errors = []
    host = public_host(request)

    for subscriber in subscribers:
        token_result = supabase.from_('newsletter_unsubscribe_tokens').select(
            'security_token'
        ).eq('subscriber_id', subscriber['id']).limit(1).execute()
        token_rows = getattr(token_result, 'data', None) or []
        unsubscribe_url = None
        if token_rows:
            unsubscribe_url = f"{host}/api/unsubscribe?token={quote(token_rows[0]['security_token'], safe='')}"

        html = email_shell(subject, content, unsubscribe_url)
        ok, provider_id, send_error = send_resend(
            subscriber['email'],
            subject,
            html,
            unsubscribe_url,
        )
        if ok:
            sent_count += 1
        else:
            errors.append(send_error or 'Nepoznata greška dostave')
        try:
            supabase.from_('newsletter_email_logs').insert({
                'subscriber_id': subscriber['id'],
                'campaign_id': campaign['id'],
                'email_type': 'kampanja',
                'provider_message_id': provider_id,
                'delivery_status': 'poslano' if ok else 'neuspjelo',
                'error_message': send_error,
                'sent_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }).execute()
        except Exception:
            app.logger.exception('Campaign email log could not be written')

    return jsonify({
        'ok': True,
        'sent': sent_count,
        'errors': errors,
        'total_confirmed': len(subscribers),
    }), 200



@app.route('/api/login', methods=['POST'])
def api_login():
    password = request.form.get('password', '').strip()
    authenticated, retry_after = verify_admin_password(password)
    if retry_after:
        return jsonify({'ok': False, 'error': 'Previše neuspješnih pokušaja. Pokušajte kasnije.'}), 429, {
            'Retry-After': str(retry_after)
        }
    if authenticated:
        session.clear()
        session['is_admin'] = True
        session.permanent = True
        return jsonify({'ok': True}), 200
    return jsonify({'ok': False, 'error': 'Neispravna lozinka.'}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'ok': True}), 200


@app.route('/api/me', methods=['GET'])
def api_me():
    return jsonify({'is_admin': bool(session.get('is_admin', False))}), 200


@app.route('/api/members', methods=['GET'])
def api_list_members():
    if not is_admin_authenticated():
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401

    members = load_members_local()
    if supabase and MEMBERS_TABLE:
        try:
            result = supabase.from_(MEMBERS_TABLE).select('*').order('created_at', desc=True).execute()
            data = getattr(result, 'data', None) or []
            if data:
                return jsonify({'ok': True, 'members': data}), 200
        except Exception as err:
            print('Members fetch failed:', err)
    return jsonify({'ok': True, 'members': members}), 200


@app.route('/api/members', methods=['POST'])
def api_submit_member():
    form_data = request.form or {}
    if not form_data and request.is_json:
        form_data = request.get_json(silent=True) or {}

    if not form_data and not request.files:
        return jsonify({'ok': False, 'error': 'Nema podataka o članstvu.'}), 400

    photo_file = request.files.get('photo')
    photo_url = (form_data.get('photo_url') or '').strip()
    if photo_file:
        saved = save_uploaded_file(photo_file)
        if saved:
            photo_url = saved

    protocol_file = request.files.get('protocol_pdf')
    protocol_pdf_url = ''
    if protocol_file:
        saved_protocol = save_uploaded_file(protocol_file)
        if saved_protocol:
            protocol_pdf_url = saved_protocol

    required_fields = [
        'prezime', 'ime', 'ime_oca', 'datum_rodjenja', 'mjesto_rodjenja', 'jmbg',
        'broj_licne_karte', 'adresa', 'grad', 'opcina', 'kontakt_broj', 'email',
        'strucna_sprema', 'zanimanje', 'zaposlenost', 'biografija'
    ]
    missing = [key for key in required_fields if not (form_data.get(key) or '').strip()]
    if missing:
        return jsonify({'ok': False, 'error': 'Nedostaju obavezna polja: ' + ', '.join(missing)}), 400
    if not (form_data.get('saglasnost') or '').strip() and not (form_data.get('saglasnost') in ('true', '1', 'on')):
        return jsonify({'ok': False, 'error': 'Potrebna je saglasnost za statut i rad udruženja.'}), 400

    created_at = datetime.datetime.utcnow().isoformat() + 'Z'
    entry = {
        'id': str(uuid.uuid4()),
        'prezime': (form_data.get('prezime') or '').strip(),
        'ime': (form_data.get('ime') or '').strip(),
        'ime_oca': (form_data.get('ime_oca') or '').strip(),
        'datum_rodjenja': (form_data.get('datum_rodjenja') or '').strip(),
        'mjesto_rodjenja': (form_data.get('mjesto_rodjenja') or '').strip(),
        'jmbg': (form_data.get('jmbg') or '').strip(),
        'broj_licne_karte': (form_data.get('broj_licne_karte') or '').strip(),
        'adresa': (form_data.get('adresa') or '').strip(),
        'grad': (form_data.get('grad') or '').strip(),
        'opcina': (form_data.get('opcina') or '').strip(),
        'kontakt_broj': (form_data.get('kontakt_broj') or '').strip(),
        'email': (form_data.get('email') or '').strip(),
        'strucna_sprema': (form_data.get('strucna_sprema') or '').strip(),
        'zanimanje': (form_data.get('zanimanje') or '').strip(),
        'zaposlenost': (form_data.get('zaposlenost') or 'NE').strip().upper(),
        'biografija': (form_data.get('biografija') or '').strip(),
        'status': 'na_cekanju',
        'created_at': created_at,
        'updated_at': created_at,
        'photo_url': photo_url,
        'protocol_pdf_url': protocol_pdf_url,
        'signature_data': (form_data.get('signature_data') or '').strip(),
        'saglasnost': 'da'
    }

    members = load_members_local()
    members.append(entry)
    save_members_local(members)

    if SUPABASE_URL and SUPABASE_CLIENT_KEY:
        save_member_to_supabase(entry)

    return jsonify({'ok': True, 'message': 'Zahtjev je uspješno poslan na verificiranje.', 'member': entry}), 200


@app.route('/api/members/<member_id>/verify', methods=['POST'])
def api_verify_member(member_id):
    password = request.form.get('password', '').strip()
    if not is_admin_authenticated(password):
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401

    members = load_members_local()
    member = next((m for m in members if str(m.get('id')) == str(member_id)), None)
    if not member:
        return jsonify({'ok': False, 'error': 'Član nije pronađen.'}), 404

    verify_number = len([m for m in members if m.get('status') == 'verifikovano']) + 1
    protocol_number = f"UB-BZ-{datetime.datetime.utcnow().strftime('%Y%m%d')}-{verify_number:04d}"
    member['status'] = 'verifikovano'
    member['verified_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
    member['protocol_number'] = protocol_number
    member['updated_at'] = member['verified_at']
    updated_members = [m if str(m.get('id')) != str(member_id) else member for m in members]
    save_members_local(updated_members)

    if SUPABASE_URL and SUPABASE_CLIENT_KEY:
        save_member_to_supabase(member)

    return jsonify({'ok': True, 'member': member, 'protocol_number': protocol_number}), 200


@app.route('/api/members/<member_id>', methods=['GET'])
def api_member_detail(member_id):
    if not is_admin_authenticated():
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    members = load_members_local()
    member = next((m for m in members if str(m.get('id')) == str(member_id)), None)
    if not member:
        return jsonify({'ok': False, 'error': 'Član nije pronađen.'}), 404
    return jsonify({'ok': True, 'member': member}), 200


@app.route('/api/members/<member_id>/protocol', methods=['POST'])
def api_member_protocol(member_id):
    password = request.form.get('password', '').strip()
    if not is_admin_authenticated(password):
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401

    members = load_members_local()
    member = next((m for m in members if str(m.get('id')) == str(member_id)), None)
    if not member:
        return jsonify({'ok': False, 'error': 'Član nije pronađen.'}), 404

    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader
        from PIL import Image
        import base64
        from io import BytesIO
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'PDF biblioteka nije dostupna: {exc}'}), 500

    protocol_number = member.get('protocol_number') or f"UB-BZ-{datetime.datetime.utcnow().strftime('%Y%m%d')}-{len([m for m in members if m.get('status') == 'verifikovano']) + 1:04d}"
    member['status'] = 'verifikovano'
    member['verified_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
    member['protocol_number'] = protocol_number
    member['updated_at'] = member['verified_at']
    updated_members = [m if str(m.get('id')) != str(member_id) else member for m in members]
    save_members_local(updated_members)

    if SUPABASE_URL and SUPABASE_CLIENT_KEY:
        save_member_to_supabase(member)

    stored_pdf_url = member.get('protocol_pdf_url') or ''
    if stored_pdf_url:
        stored_pdf_path = Path(stored_pdf_url.lstrip('/'))
        if stored_pdf_path.exists() and stored_pdf_path.is_file():
            pdf_bytes = stored_pdf_path.read_bytes()
            filename = f"protocol_{protocol_number}.pdf"
            response = app.make_response(pdf_bytes)
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
            return response

    pdf_buffer = BytesIO()
    pdf = canvas.Canvas(pdf_buffer, pagesize=A4)
    width, height = A4
    pdf.setTitle(f'Protokol {protocol_number}')
    pdf.setAuthor('UB BO SNAE - Zelene Beretke')

    pdf.setFillColorRGB(0.12, 0.18, 0.14)
    pdf.rect(20, 20, width - 40, height - 40, stroke=1, fill=0)

    crest_left = Path('assets') / 'img' / 'grb-udruzenja.png'
    crest_right = Path('assets') / 'img' / 'grb-zelene-beretke.png'
    for crest_path, crest_x in ((crest_left, 42), (crest_right, width - 102)):
        if crest_path.exists():
            try:
                pdf.drawImage(ImageReader(str(crest_path)), crest_x, height - 105, width=60, height=70, preserveAspectRatio=True, mask='auto')
            except Exception as crest_err:
                print('PDF crest failed:', crest_err)

    pdf.setFillColorRGB(0.9, 0.82, 0.45)
    pdf.setFont('Helvetica-Bold', 18)
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawCentredString(width / 2, height - 52, 'UB "BOSNAE - ZELENE BERETKE" OPĆINE STARI GRAD')
    pdf.setFillColorRGB(0.88, 0.88, 0.88)
    pdf.setFont('Helvetica', 7)
    header_lines = [
        'OBALA KULINA BANA BR. 24/1, 71000 SARAJEVO',
        'Tel/Fax: 033/205-689 | ID br. 4200343940002',
        'ASA BANKA d.d. 1340011130037272',
        'Ministarstvo pravde i uprave Kantona Sarajevo (Rješenje br. 03-05-05-7060/06)'
    ]
    for header_index, header_line in enumerate(header_lines):
        pdf.drawCentredString(width / 2, height - 67 - (header_index * 11), header_line)

    pdf.setFillColorRGB(0.95, 0.95, 0.95)
    pdf.setFont('Helvetica-Bold', 15)
    pdf.drawCentredString(width / 2, height - 130, f'PROTOKOL PRISTUPNICE / ČLANSKE KARTICE - {protocol_number}')
    pdf.setFont('Helvetica', 11)
    pdf.drawString(45, height - 150, f'Datum: {datetime.datetime.utcnow().strftime("%d.%m.%Y.")}')

    image_area_x = 50
    image_area_y = height - 360
    image_area_w = 120
    image_area_h = 150
    pdf.rect(image_area_x, image_area_y, image_area_w, image_area_h, stroke=1, fill=0)
    pdf.setFont('Helvetica-Bold', 9)
    pdf.drawString(image_area_x + 5, image_area_y + image_area_h + 10, 'Mjesto za sliku')

    photo_url = member.get('photo_url') or ''
    if photo_url:
        try:
            if photo_url.startswith('data:image'):
                _, encoded = photo_url.split(',', 1)
                raw = base64.b64decode(encoded)
                img = Image.open(BytesIO(raw))
            else:
                from urllib.request import urlopen
                if photo_url.startswith('/'):
                    full_url = f"{request.host_url.rstrip('/')}{photo_url}"
                else:
                    full_url = photo_url
                raw = urlopen(full_url).read()
                img = Image.open(BytesIO(raw))

            img = img.convert('RGB')
            img.thumbnail((image_area_w - 10, image_area_h - 10), Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format='JPEG', quality=90)
            buf.seek(0)
            pdf.drawImage(buf, image_area_x + 5, image_area_y + 5, width=image_area_w - 10, height=image_area_h - 10, preserveAspectRatio=True)
        except Exception as img_err:
            print('PDF photo failed:', img_err)

    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(210, height - 210, 'PODACI O ČLANU')
    pdf.setFont('Helvetica', 10)
    fields = [
        ('Prezime', member.get('prezime', '')),
        ('Ime', member.get('ime', '')),
        ('Ime oca', member.get('ime_oca', '')),
        ('Datum rođenja', member.get('datum_rodjenja', '')),
        ('Mjesto rođenja', member.get('mjesto_rodjenja', '')),
        ('JMBG', member.get('jmbg', '')),
        ('Broj lične karte', member.get('broj_licne_karte', '')),
        ('Adresa', member.get('adresa', '')),
        ('Grad / općina', f"{member.get('grad', '')} / {member.get('opcina', '')}"),
        ('Kontakt broj', member.get('kontakt_broj', '')),
        ('E-mail', member.get('email', '')),
        ('Stručna sprema', member.get('strucna_sprema', '')),
        ('Zanimanje', member.get('zanimanje', '')),
        ('Zaposlenost', member.get('zaposlenost', 'NE')),
    ]

    y = height - 240
    line_height = 14
    for label, value in fields:
        pdf.drawString(210, y, f'{label}: {value}')
        y -= line_height
        if y < 120:
            pdf.showPage()
            y = height - 80

    sig_data = member.get('signature_data') or ''
    if sig_data.startswith('data:image'):
        _, encoded = sig_data.split(',', 1)
        sig_bytes = base64.b64decode(encoded)
        try:
            sig = Image.open(BytesIO(sig_bytes)).convert('RGB')
            buf = BytesIO(); sig.save(buf, format='PNG'); buf.seek(0)
            pdf.drawString(45, 115, 'POTPIS ČLANA')
            pdf.drawImage(buf, 45, 40, width=180, height=60, preserveAspectRatio=True)
        except Exception:
            pdf.drawString(45, 90, 'POTPIS ČLANA')
    else:
        pdf.drawString(45, 90, 'POTPIS ČLANA')

    pdf.setFont('Helvetica', 9)
    pdf.drawString(45, 35, 'Potvrđeno i protokolirano od strane UB "BOSNAE - ZELENE BERETKE" OPĆINE STARI GRAD')
    pdf.save()

    pdf_bytes = pdf_buffer.getvalue()
    filename = f"protocol_{protocol_number}.pdf"
    protocol_path = PROTOCOLS_DIR / filename
    protocol_path.write_bytes(pdf_bytes)

    response = app.make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


@app.route('/admin-clanstvo.html')
def admin_membership_html():
    return app.send_static_file('admin-clanstvo.html')


@app.route('/send-message', methods=['POST'])
def send_message():
    def error_response(message, status):
        if request.is_json:
            return jsonify({'success': False, 'message': message}), status
        return redirect('/#kontakt')

    if request.content_length and request.content_length > 12_000:
        return error_response('Poruka je prevelika.', 413)

    if request.is_json:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return error_response('Podaci forme nisu ispravni.', 400)
    else:
        data = request.form

    def field(name, alias=None):
        value = data.get(name, '')
        if not value and alias:
            value = data.get(alias, '')
        return value.strip() if isinstance(value, str) else ''

    name = field('name', 'ime')
    email = field('email')
    message = field('message', 'poruka')
    topic = field('topic') or 'general'
    organization = field('organization')
    phone = field('phone')
    activity_date = field('activity_date')
    collaboration_kind = field('collaboration_kind')
    honeypot = field('website')
    consent_value = data.get('consent')
    consent = consent_value is True or (
        isinstance(consent_value, str)
        and consent_value.strip().lower() in ('true', '1', 'on')
    )

    if honeypot:
        return error_response('Poruku nije moguće poslati.', 400)
    if not name or not email or not message:
        return error_response('Ime, email i poruka su obavezni.', 400)
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        return error_response('Unesite ispravnu email adresu.', 400)
    if not consent:
        return error_response('Potvrdite saglasnost za obradu podataka.', 400)
    if topic not in ('general', 'collaboration'):
        return error_response('Odabrana vrsta upita nije ispravna.', 400)

    field_limits = {
        'name': (name, 100),
        'email': (email, 254),
        'message': (message, 3000),
        'organization': (organization, 160),
        'phone': (phone, 40)
    }
    if any(len(value) > limit for value, limit in field_limits.values()):
        return error_response('Neko od polja prelazi dozvoljenu dužinu.', 400)

    collaboration_labels = {
        'education': 'Edukacija i radionice',
        'community_event': 'Događaj i aktivnosti',
        'humanitarian': 'Humanitarna akcija',
        'sports': 'Sport i rekreacija',
        'other': 'Drugo'
    }
    if topic == 'collaboration' and collaboration_kind not in collaboration_labels:
        return error_response('Odaberite oblast saradnje.', 400)
    if activity_date:
        try:
            datetime.date.fromisoformat(activity_date)
        except ValueError:
            return error_response('Datum aktivnosti nije ispravan.', 400)

    topic_label = 'Saradnja i partnerstvo' if topic == 'collaboration' else 'Opći upit'
    message_parts = [f'Vrsta upita: {topic_label}']
    if topic == 'collaboration':
        message_parts.append(f'Oblast saradnje: {collaboration_labels[collaboration_kind]}')
    if organization:
        message_parts.append(f'Organizacija: {organization}')
    if phone:
        message_parts.append(f'Telefon: {phone}')
    if activity_date:
        message_parts.append(f'Predloženi datum: {activity_date}')
    message_parts.extend(('', 'Poruka:', message))

    entry = {
        'name': name,
        'email': email,
        'message': '\n'.join(message_parts),
        'topic_label': topic_label,
        'organization': organization,
        'phone': phone,
        'created': datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    try:
        retry_after = contact_rate_limit_retry_after()
    except sqlite3.Error:
        app.logger.exception('Contact message rate limiter failed')
        return error_response('Slanje poruke trenutno nije dostupno. Pokušajte kasnije.', 503)
    if retry_after:
        response = error_response(
            'Poslali ste više poruka u kratkom vremenu. Pokušajte ponovo kasnije.',
            429
        )
        if request.is_json:
            response[0].headers['Retry-After'] = str(retry_after)
        return response

    saved, save_error = save_to_supabase(entry)
    if not saved:
        app.logger.error('Contact message could not be saved: %s', save_error)
        return error_response('Poruku trenutno nije moguće sačuvati. Pokušajte kasnije.', 503)

    notification_sent, notification_error = send_contact_notification(entry)
    if not notification_sent:
        app.logger.error('Contact notification could not be sent: %s', notification_error)

    if request.is_json:
        return jsonify({
            'success': True,
            'message': 'Poruka je zaprimljena. Hvala, javit ćemo vam se uskoro.'
        }), 201
    return redirect('/#kontakt')


def contact_message_id(row):
    normalized = {
        'created_at': str(row.get('created_at') or row.get('created') or ''),
        'name': str(row.get('name') or row.get('username') or ''),
        'email': str(row.get('email') or ''),
        'message': str(row.get('message') or row.get('content') or '')
    }
    serialized = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hmac.new(
        str(app.secret_key).encode('utf-8'),
        serialized.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def fetch_contact_rows():
    if not supabase or not SUPABASE_TABLE or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError('Supabase messages are not configured')
    result = supabase.from_(SUPABASE_TABLE).select('*').order('created_at', desc=True).limit(200).execute()
    error = getattr(result, 'error', None)
    if error:
        raise RuntimeError('Supabase messages could not be loaded')
    rows = getattr(result, 'data', None) or []
    return [row for row in rows if isinstance(row, dict)]


def load_contact_message_metadata():
    with closing(sqlite3.connect(CONTACT_INBOX_DB, timeout=5)) as database:
        with database:
            database.execute(
                'CREATE TABLE IF NOT EXISTS contact_message_metadata '
                '(message_id TEXT PRIMARY KEY, status TEXT NOT NULL, tag TEXT NOT NULL, updated_at TEXT NOT NULL)'
            )
            rows = database.execute(
                'SELECT message_id, status, tag FROM contact_message_metadata'
            ).fetchall()
    return {
        row[0]: {'status': row[1], 'tag': row[2]}
        for row in rows
    }


def inferred_contact_tag(message):
    if 'Saradnja i partnerstvo' in message:
        return 'collaboration'
    if 'Opći upit' in message:
        return 'general'
    return 'other'


@app.route('/api/admin/messages', methods=['GET'])
def admin_contact_messages():
    if not is_admin_api_authenticated():
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    try:
        rows = fetch_contact_rows()
        metadata = load_contact_message_metadata()
        messages = []
        for row in rows:
            message = str(row.get('message') or row.get('content') or '')
            message_id = contact_message_id(row)
            saved_metadata = metadata.get(message_id, {})
            messages.append({
                'id': message_id,
                'name': str(row.get('name') or row.get('username') or ''),
                'email': str(row.get('email') or ''),
                'message': message,
                'created_at': str(row.get('created_at') or row.get('created') or ''),
                'status': saved_metadata.get('status', 'new'),
                'tag': saved_metadata.get('tag', inferred_contact_tag(message))
            })
        response = jsonify({'ok': True, 'messages': messages})
        response.headers['Cache-Control'] = 'no-store'
        return response, 200
    except Exception:
        app.logger.exception('Admin contact inbox could not be loaded')
        return jsonify({'ok': False, 'error': 'Poruke se trenutno ne mogu učitati.'}), 503


@app.route('/api/admin/messages/<message_id>', methods=['PATCH'])
def update_admin_contact_message(message_id):
    if not is_admin_api_authenticated():
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    if not re.fullmatch(r'[a-f0-9]{64}', message_id):
        return jsonify({'ok': False, 'error': 'ID poruke nije ispravan.'}), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'ok': False, 'error': 'Podaci nisu ispravni.'}), 400

    status = data.get('status')
    tag = data.get('tag')
    if status not in ('new', 'in_progress', 'responded'):
        return jsonify({'ok': False, 'error': 'Status poruke nije ispravan.'}), 400
    if tag not in ('general', 'collaboration', 'other'):
        return jsonify({'ok': False, 'error': 'Oznaka poruke nije ispravna.'}), 400

    try:
        if message_id not in {contact_message_id(row) for row in fetch_contact_rows()}:
            return jsonify({'ok': False, 'error': 'Poruka nije pronađena.'}), 404
        updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with closing(sqlite3.connect(CONTACT_INBOX_DB, timeout=5)) as database:
            with database:
                database.execute(
                    'CREATE TABLE IF NOT EXISTS contact_message_metadata '
                    '(message_id TEXT PRIMARY KEY, status TEXT NOT NULL, tag TEXT NOT NULL, updated_at TEXT NOT NULL)'
                )
                database.execute(
                    'INSERT INTO contact_message_metadata (message_id, status, tag, updated_at) '
                    'VALUES (?, ?, ?, ?) '
                    'ON CONFLICT(message_id) DO UPDATE SET '
                    'status=excluded.status, tag=excluded.tag, updated_at=excluded.updated_at',
                    (message_id, status, tag, updated_at)
                )
        return jsonify({'ok': True, 'status': status, 'tag': tag}), 200
    except Exception:
        app.logger.exception('Admin contact message could not be updated')
        return jsonify({'ok': False, 'error': 'Promjena poruke nije sačuvana.'}), 503


def normalize_event_payload(data):
    if not isinstance(data, dict):
        return None, 'Podaci događaja nisu ispravni.'
    title = data.get('title', '')
    event_date = data.get('date', '')
    event_time = data.get('time', '')
    location = data.get('location', '')
    description = data.get('description', '')
    status = data.get('status', 'published')
    values = (title, event_date, event_time, location, description, status)
    if any(not isinstance(value, str) for value in values):
        return None, 'Podaci događaja nisu ispravni.'
    title = title.strip()
    event_date = event_date.strip()
    event_time = event_time.strip()
    location = location.strip()
    description = description.strip()
    status = status.strip()

    if not title or len(title) > 120 or len(event_date) != 10:
        return None, 'Unesite naslov i ispravan datum događaja.'
    try:
        datetime.date.fromisoformat(event_date)
        if event_time:
            datetime.time.fromisoformat(event_time)
    except ValueError:
        return None, 'Datum ili vrijeme događaja nisu ispravni.'
    if len(event_time) > 8 or len(location) > 160 or len(description) > 3000:
        return None, 'Neko od polja prelazi dozvoljenu dužinu.'
    if status not in ('published', 'draft'):
        return None, 'Status događaja nije ispravan.'
    return {
        'title': title,
        'date': event_date,
        'time': event_time,
        'location': location,
        'description': description,
        'status': status
    }, None


@app.route('/api/events', methods=['GET'])
def public_events():
    try:
        events = load_events_local()
        published = [event for event in events if event.get('status') == 'published']
        published.sort(key=lambda event: (event.get('date', ''), event.get('time', '')))
        return jsonify({'ok': True, 'events': published}), 200
    except Exception:
        app.logger.exception('Public event calendar could not be loaded')
        return jsonify({'ok': False, 'error': 'Kalendar trenutno nije dostupan.'}), 503


@app.route('/api/admin/events', methods=['GET', 'POST'])
def admin_events():
    if not is_admin_api_authenticated():
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    try:
        events = load_events_local()
        if request.method == 'GET':
            return jsonify({'ok': True, 'events': sorted(
                events,
                key=lambda event: (event.get('date', ''), event.get('time', ''))
            )}), 200

        payload, error = normalize_event_payload(request.get_json(silent=True))
        if error:
            return jsonify({'ok': False, 'error': error}), 400
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        event = {
            'id': str(uuid.uuid4()),
            **payload,
            'created_at': now,
            'updated_at': now
        }
        events.append(event)
        save_events_local(events)
        return jsonify({'ok': True, 'event': event}), 201
    except Exception:
        app.logger.exception('Admin events could not be loaded or saved')
        return jsonify({'ok': False, 'error': 'Događaj nije sačuvan.'}), 503


@app.route('/api/admin/events/<event_id>', methods=['PATCH', 'DELETE'])
def update_admin_event(event_id):
    if not is_admin_api_authenticated():
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    try:
        events = load_events_local()
        event_index = next(
            (index for index, event in enumerate(events) if event.get('id') == event_id),
            None
        )
        if event_index is None:
            return jsonify({'ok': False, 'error': 'Događaj nije pronađen.'}), 404
        if request.method == 'DELETE':
            events.pop(event_index)
            save_events_local(events)
            return jsonify({'ok': True}), 200

        payload, error = normalize_event_payload(request.get_json(silent=True))
        if error:
            return jsonify({'ok': False, 'error': error}), 400
        existing = events[event_index]
        events[event_index] = {
            **existing,
            **payload,
            'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        save_events_local(events)
        return jsonify({'ok': True, 'event': events[event_index]}), 200
    except Exception:
        app.logger.exception('Admin event could not be changed')
        return jsonify({'ok': False, 'error': 'Događaj nije sačuvan.'}), 503


@app.route('/api/news', methods=['GET'])
def news_list():
    news_items = load_news_local()
    if supabase and NEWS_TABLE:
        try:
            result = supabase.from_(NEWS_TABLE).select('*').order('created_at', desc=True).limit(20).execute()
            data = getattr(result, 'data', None) or []
            if data:
                return jsonify(data), 200
        except Exception as err:
            print('News fetch failed:', err)
    news_items = sorted(news_items, key=lambda item: item.get('created_at') or item.get('created', ''), reverse=True)
    # attach human-readable label
    for item in news_items:
        cat = item.get('category')
        item['category_label'] = CATEGORY_LABELS.get(cat, cat or '')
    return jsonify(news_items), 200


@app.route('/api/news', methods=['POST'])
def news_create():
    title = request.form.get('title', '').strip()
    body = request.form.get('body', '').strip()
    image_url = request.form.get('image_url', '').strip()
    pinned = request.form.get('pinned', '').strip().lower() in ('1','true','yes')
    status = request.form.get('status', '').strip() or 'published'
    scheduled_at = request.form.get('scheduled_at', '').strip() or ''
    password = request.form.get('password', '').strip()
    category = request.form.get('category', '').strip() or 'obavjestenje'
    # handle file upload
    file = request.files.get('image_file')
    if file:
        saved = save_uploaded_file(file)
        if saved:
            image_url = saved

    if not title or not body:
        return jsonify({'ok': False, 'error': 'Naslov i tekst su obavezni.'}), 400
    if not is_admin_authenticated(password):
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401

    created_at = datetime.datetime.utcnow().isoformat() + 'Z'
    entry = {
        'id': str(uuid.uuid4()),
        'title': title,
        'body': body,
        'image_url': image_url,
        'category': category,
        'created_at': created_at,
        'pinned': bool(pinned),
        'status': status,
        'scheduled_at': scheduled_at
    }

    saved_to_supabase = False
    if SUPABASE_URL and SUPABASE_CLIENT_KEY:
        saved_to_supabase, _ = save_news_to_supabase(entry)
    save_news_local(entry)

    return jsonify({'ok': True, 'saved_to_supabase': saved_to_supabase, 'entry': entry}), 200


@app.route('/api/news/update', methods=['POST'])
def news_update():
    news_id = request.form.get('id', '').strip()
    title = request.form.get('title', '').strip()
    body = request.form.get('body', '').strip()
    image_url = request.form.get('image_url', '').strip()
    password = request.form.get('password', '').strip()
    category = request.form.get('category', '').strip() or None
    # handle file upload
    file = request.files.get('image_file')
    if file:
        saved = save_uploaded_file(file)
        if saved:
            image_url = saved

    if not news_id:
        return jsonify({'ok': False, 'error': 'ID vijesti je obavezan.'}), 400
    if not title or not body:
        return jsonify({'ok': False, 'error': 'Naslov i tekst su obavezni.'}), 400
    if not is_admin_authenticated(password):
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401

    updated_entry = {
        'title': title,
        'body': body,
        'image_url': image_url
    }
    if category:
        updated_entry['category'] = category
    updated_local = update_news_local(news_id, updated_entry)
    updated_supabase = False
    supabase_error = None
    if supabase and NEWS_TABLE:
        try:
            payload = {
                'title': title,
                'body': body,
                'image_url': image_url
            }
            result = supabase.from_(NEWS_TABLE).update(payload).eq('id', news_id).execute()
            error = getattr(result, 'error', None)
            if error:
                supabase_error = str(error)
            else:
                updated_supabase = True
        except Exception as err:
            supabase_error = str(err)

    if not updated_local and not updated_supabase:
        return jsonify({'ok': False, 'error': 'Vijest nije pronađena za ažuriranje.'}), 404
    if supabase_error and not updated_local:
        return jsonify({'ok': False, 'error': f'Greška pri ažuriranju u Supabase: {supabase_error}'}), 500

    return jsonify({'ok': True, 'updated_local': updated_local, 'updated_supabase': updated_supabase}), 200


@app.route('/api/news/delete', methods=['POST'])
def news_delete():
    news_id = request.form.get('id', '').strip()
    password = request.form.get('password', '').strip()

    if not news_id:
        return jsonify({'ok': False, 'error': 'ID vijesti je obavezan.'}), 400
    if not is_admin_authenticated(password):
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401

    deleted_local = delete_news_local(news_id)
    deleted_supabase = False
    supabase_error = None
    if supabase and NEWS_TABLE:
        try:
            result = supabase.from_(NEWS_TABLE).delete().eq('id', news_id).execute()
            error = getattr(result, 'error', None)
            if error:
                supabase_error = str(error)
            else:
                deleted_supabase = True
        except Exception as err:
            supabase_error = str(err)

    if not deleted_local and not deleted_supabase:
        return jsonify({'ok': False, 'error': 'Vijest nije pronađena za brisanje.'}), 404
    if supabase_error and not deleted_local:
        return jsonify({'ok': False, 'error': f'Greška pri brisanju u Supabase: {supabase_error}'}), 500

    return jsonify({'ok': True, 'deleted_local': deleted_local, 'deleted_supabase': deleted_supabase}), 200


@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)


if __name__ == '__main__':
    # Allow overriding port and debug mode via environment variables
    try:
        PORT = int(os.environ.get('PORT', '8000'))
    except Exception:
        PORT = 8000
    DEBUG = os.environ.get('DEBUG', 'False').lower() in ('1', 'true', 'yes')
    if IS_PRODUCTION:
        DEBUG = False
    print(f"Starting Flask app on http://0.0.0.0:{PORT} (debug={DEBUG})")
    app.run(host='0.0.0.0', port=PORT, debug=DEBUG)
