from pathlib import Path
import os
import json
import uuid
import datetime
from flask import Flask, request, jsonify, redirect, send_from_directory, url_for, session
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import resend

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
SUPABASE_CLIENT_KEY = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
SUPABASE_TABLE = os.environ.get('SUPABASE_TABLE', 'messages').strip()
NEWS_TABLE = os.environ.get('NEWS_TABLE', 'news').strip()
MEMBERS_TABLE = os.environ.get('MEMBERS_TABLE', 'members').strip()
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'zeleneberetke2026').strip()
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

app = Flask(__name__, static_folder='.', template_folder='.')
app.config.update({
    'MAIL_SERVER': MAIL_SERVER,
    'MAIL_PORT': MAIL_PORT,
    'MAIL_USE_TLS': MAIL_USE_TLS,
    'MAIL_USE_SSL': MAIL_USE_SSL,
    'MAIL_USERNAME': MAIL_USERNAME,
    'MAIL_PASSWORD': MAIL_PASSWORD,
    'MAIL_DEFAULT_SENDER': MAIL_DEFAULT_SENDER,
})
mail = Mail(app)
app.secret_key = os.environ.get('SECRET_KEY', 'change-me-to-a-secure-random-value')
DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)

# upload folder for news images
UPLOAD_DIR = Path('assets') / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Optional dev CORS support so Live Server or other origins can call API during development.
DEV_ALLOW_CORS = os.environ.get('DEV_ALLOW_CORS', '1').strip()
if DEV_ALLOW_CORS and DEV_ALLOW_CORS != '0':
    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get('Origin') or '*'
        # allow the requesting origin only (safe for development)
        if origin and origin != '':
            response.headers['Access-Control-Allow-Origin'] = origin
        else:
            response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, Accept'
        return response
    
    @app.before_request
    def handle_options():
        # respond to preflight OPTIONS requests during development
        if request.method == 'OPTIONS':
            return ('', 200)

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
        for column in ['name', 'email', 'message', 'created_at']:
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
            subject=f"Nova poruka sa sajta - {entry['name']}",
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[NOTIFICATION_EMAIL],
            reply_to=entry['email']
        )
        msg.body = (
            f"Nova poruka sa sajta:\n\n"
            f"Ime: {entry['name']}\n"
            f"Email: {entry['email']}\n"
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
        payload = {}
        if 'name' in SUPABASE_COLUMNS:
            payload['name'] = entry['name']
        if 'email' in SUPABASE_COLUMNS:
            payload['email'] = entry['email']
        if 'message' in SUPABASE_COLUMNS:
            payload['message'] = entry['message']
        if 'created_at' in SUPABASE_COLUMNS:
            payload['created_at'] = entry['created']

        if not payload:
            return False, 'No supported Supabase columns available'

        result = supabase.from_(SUPABASE_TABLE).insert([payload]).execute()
        error = getattr(result, 'error', None)
        if error:
            return False, error
        return True, None
    except Exception as err:
        return False, str(err)


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


def is_admin_authenticated(password_from_form=None):
    # Allow either session-based admin or password provided in form
    if session.get('is_admin'):
        return True
    if password_from_form and password_from_form == ADMIN_PASSWORD:
        return True
    return False


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
    email = (request.form.get('email') or '').strip().lower()
    name = (request.form.get('name') or '').strip()
    consent = (request.form.get('consent') or '').strip() in ('1','true','on')
    if not email or '@' not in email or not consent:
        return jsonify({'ok': False, 'error': 'Invalid email or consent missing.'}), 400
    subs = load_subscribers()
    # avoid duplicates: if already confirmed, return ok; if unconfirmed, resend token
    for s in subs:
        if s.get('email','').lower() == email:
            if s.get('confirmed'):
                return jsonify({'ok': True, 'message': 'Već pretplaćen.'}), 200
            else:
                token = s.get('confirm_token') or str(uuid.uuid4())
                s['confirm_token'] = token
                save_subscribers(subs)
                # attempt to send confirmation email
                sent = False
                try:
                    sent = send_confirmation_email(email, token)
                except Exception as e:
                    print('Confirm email send failed:', e)
                return jsonify({'ok': True, 'message': 'Potvrda poslana ponovo.', 'sent_email': sent, 'token': (token if not sent else None)}), 200
    # create new pending subscriber
    token = str(uuid.uuid4())
    entry = {'id': str(uuid.uuid4()), 'email': email, 'name': name, 'subscribed_at': datetime.datetime.utcnow().isoformat() + 'Z', 'confirmed': False, 'confirm_token': token}
    subs.append(entry)
    saved = save_subscribers(subs)
    if not saved:
        return jsonify({'ok': False, 'error': 'Ne mogu sačuvati pretplatu.'}), 500
    sent = False
    try:
        sent = send_confirmation_email(email, token)
    except Exception as e:
        print('Confirm email send failed:', e)
    return jsonify({'ok': True, 'entry': entry, 'sent_email': sent, 'token': (None if sent else token)}), 200


@app.route('/api/unsubscribe', methods=['POST','GET'])
def api_unsubscribe():
    # Support unsubscribe by token (preferred) or by email param
    token = (request.values.get('token') or '').strip()
    email = (request.values.get('email') or '').strip().lower()
    if not token and (not email or '@' not in email):
        return jsonify({'ok': False, 'error': 'Neispravan email ili token.'}), 400
    subs = load_subscribers()
    if token:
        filtered = [s for s in subs if s.get('unsub_token') != token]
    else:
        filtered = [s for s in subs if s.get('email','').lower() != email]
    if len(filtered) == len(subs):
        return jsonify({'ok': False, 'error': 'Pretplatnik nije pronađen.'}), 404
    save_subscribers(filtered)
    return jsonify({'ok': True}), 200


@app.route('/api/confirm_subscription', methods=['GET'])
def api_confirm_subscription():
    token = (request.values.get('token') or '').strip()
    if not token:
        return jsonify({'ok': False, 'error': 'Token missing.'}), 400
    subs = load_subscribers()
    found = False
    for s in subs:
        if s.get('confirm_token') == token:
            s['confirmed'] = True
            s.pop('confirm_token', None)
            s['confirmed_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
            found = True
            break
    if not found:
        return jsonify({'ok': False, 'error': 'Token nije važeći.'}), 404
    save_subscribers(subs)
    # redirect to site with success message optional
    # optionally show a minimal confirmation page
    return redirect(url_for('index') + '#newsletter')


@app.route('/api/subscribers', methods=['GET'])
def api_list_subscribers():
    # admin-only
    password = request.args.get('password','').strip()
    if not is_admin_authenticated(password):
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    subs = load_subscribers()
    # do not expose tokens in list if not admin via session
    return jsonify({'ok': True, 'count': len(subs), 'subscribers': subs}), 200


@app.route('/api/subscriber/delete', methods=['POST'])
def api_delete_subscriber():
    password = request.form.get('password','').strip()
    if not is_admin_authenticated(password):
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    email = (request.form.get('email') or '').strip().lower()
    sid = (request.form.get('id') or '').strip()
    if not email and not sid:
        return jsonify({'ok': False, 'error': 'Email ili id su obavezni.'}), 400
    subs = load_subscribers()
    filtered = subs
    if sid:
        filtered = [s for s in subs if s.get('id') != sid]
    else:
        filtered = [s for s in subs if s.get('email','').lower() != email]
    if len(filtered) == len(subs):
        return jsonify({'ok': False, 'error': 'Pretplatnik nije pronađen.'}), 404
    save_subscribers(filtered)
    return jsonify({'ok': True}), 200


@app.route('/api/subscriber/confirm', methods=['POST'])
def api_confirm_subscriber():
    password = request.form.get('password','').strip()
    if not is_admin_authenticated(password):
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    email = (request.form.get('email') or '').strip().lower()
    sid = (request.form.get('id') or '').strip()
    if not email and not sid:
        return jsonify({'ok': False, 'error': 'Email ili id su obavezni.'}), 400
    subs = load_subscribers()
    found = False
    for s in subs:
        if sid and s.get('id') == sid:
            s['confirmed'] = True
            s.pop('confirm_token', None)
            s['confirmed_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
            found = True
            break
        if email and s.get('email','').lower() == email:
            s['confirmed'] = True
            s.pop('confirm_token', None)
            s['confirmed_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
            found = True
            break
    if not found:
        return jsonify({'ok': False, 'error': 'Pretplatnik nije pronađen.'}), 404
    save_subscribers(subs)
    return jsonify({'ok': True}), 200


@app.route('/api/subscribers/export', methods=['GET'])
def api_export_subscribers():
    password = request.args.get('password','').strip()
    if not is_admin_authenticated(password):
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    subs = load_subscribers()
    # CSV header
    lines = ['email,name,confirmed,subscribed_at,confirmed_at']
    for s in subs:
        email = s.get('email','')
        name = s.get('name','')
        confirmed = '1' if s.get('confirmed') else '0'
        subs_at = s.get('subscribed_at','')
        conf_at = s.get('confirmed_at','')
        # escape commas by quoting
        def q(v):
            if v is None: return ''
            v = str(v).replace('"','""')
            if ',' in v or '"' in v or '\n' in v:
                return f'"{v}"'
            return v
        lines.append(','.join([q(email), q(name), q(confirmed), q(subs_at), q(conf_at)]))
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
    # Admin-only endpoint to send a newsletter to all subscribers
    password = request.form.get('password', '').strip()
    if not is_admin_authenticated(password):
        return jsonify({'ok': False, 'error': 'Neautorizovan pristup.'}), 401
    subject = request.form.get('subject', '').strip() or 'Objava od Savez Mladih'
    html = request.form.get('html', '').strip() or request.form.get('body', '')
    subs = load_subscribers()
    # only confirmed subscribers should receive newsletters
    confirmed = [s for s in subs if s.get('confirmed')]
    if not confirmed:
        return jsonify({'ok': False, 'error': 'Nema potvrđenih pretplatnika.'}), 400
    send_errors = []
    host = os.environ.get('PUBLIC_HOST') or request.host_url.rstrip('/')
    # send via SendGrid if available
    if os.environ.get('SENDGRID_API_KEY'):
        try:
            import importlib
            sendgrid = importlib.import_module('sendgrid')
            helpers = importlib.import_module('sendgrid.helpers.mail')
            SendGridAPIClient = sendgrid.SendGridAPIClient
            Mail = helpers.Mail
            sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            for s in confirmed:
                try:
                    unsub_link = f"{host}/api/unsubscribe?token={s.get('unsub_token')}"
                    personalized = f"{html}<hr><p><small>Ako više ne želiš primati poruke, <a href=\"{unsub_link}\">odjavi se</a>.</small></p>"
                    msg = Mail(from_email=MAIL_FROM, to_emails=s.get('email'), subject=subject, html_content=personalized)
                    sg.send(msg)
                except Exception as e:
                    send_errors.append({'email': s.get('email'), 'error': str(e)})
        except ImportError as e:
            send_errors.append({'error': 'SendGrid library unavailable: ' + str(e)})
        except Exception as e:
            send_errors.append({'error': 'SendGrid error: ' + str(e)})
    else:
        # Flask-Mail SMTP fallback
        if MAIL_USERNAME and MAIL_PASSWORD:
            for s in confirmed:
                try:
                    unsub_link = f"{host}/api/unsubscribe?token={s.get('unsub_token')}"
                    msg = Message(
                        subject=subject,
                        sender=app.config['MAIL_DEFAULT_SENDER'],
                        recipients=[s.get('email')]
                    )
                    msg.body = (html or subject) + f"\n\nAko se želiš odjaviti: {unsub_link}"
                    msg.html = (html or subject) + f"<hr><p><small>Ako više ne želiš primati poruke, <a href=\"{unsub_link}\">odjavi se</a>.</small></p>"
                    mail.send(msg)
                except Exception as e:
                    send_errors.append({'email': s.get('email'), 'error': str(e)})
        else:
            return jsonify({'ok': False, 'error': 'Nijedan provider za slanje nije konfiguriran.'}), 500

    return jsonify({'ok': True, 'sent': len(confirmed) - len(send_errors), 'errors': send_errors, 'total_confirmed': len(confirmed)}), 200



@app.route('/api/login', methods=['POST'])
def api_login():
    password = request.form.get('password', '').strip()
    if password == ADMIN_PASSWORD:
        session['is_admin'] = True
        return jsonify({'ok': True}), 200
    return jsonify({'ok': False, 'error': 'Neispravna lozinka.'}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('is_admin', None)
    return jsonify({'ok': True}), 200


@app.route('/api/me', methods=['GET'])
def api_me():
    return jsonify({'is_admin': bool(session.get('is_admin', False))}), 200


@app.route('/api/members', methods=['GET'])
def api_list_members():
    password = request.args.get('password', '').strip()
    if not is_admin_authenticated(password):
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
    password = request.args.get('password', '').strip()
    if not is_admin_authenticated(password):
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

    pdf_buffer = BytesIO()
    pdf = canvas.Canvas(pdf_buffer, pagesize=A4)
    width, height = A4
    pdf.setTitle(f'Protokol {protocol_number}')
    pdf.setAuthor('UB BO SNAE - Zelene Beretke')

    pdf.setFillColorRGB(0.12, 0.18, 0.14)
    pdf.rect(20, 20, width - 40, height - 40, stroke=1, fill=0)

    pdf.setFillColorRGB(0.9, 0.82, 0.45)
    pdf.setFont('Helvetica-Bold', 18)
    pdf.drawString(45, height - 60, 'UB "BOSNAE - ZELENE BERETKE" OPĆINA STARI GRAD')
    pdf.setFillColorRGB(0.88, 0.88, 0.88)
    pdf.setFont('Helvetica', 9)
    pdf.drawString(45, height - 82, 'Obala Kulina bana br. 24/1, 71000 Sarajevo | ID br. 4200343940002 | ASA BANKA d.d. 1340011130037272 | Rješenje br. 03-05-05-7060/06')

    pdf.setFillColorRGB(0.95, 0.95, 0.95)
    pdf.setFont('Helvetica-Bold', 15)
    pdf.drawString(45, height - 120, f'PROTOKOL PRISTUPNICE / ČLANSKE KARTICE - {protocol_number}')
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
    # Ako je zahtjev JSON, koristimo get_json(); inače koristimo form data
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form or {}

    ime = (data.get('ime') or data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    poruka = (data.get('poruka') or data.get('message') or '').strip()

    if not ime or not email or not poruka:
        # Ako je AJAX/JSON, vratimo JSON grešku, inače redirect nazad sa statusom
        if request.is_json:
            return jsonify({'success': False, 'message': 'Ime, email i poruka su obavezni.'}), 400
        else:
            return redirect('/#kontakt')

    if not supabase:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Supabase nije konfigurisan.'}), 500
        else:
            return redirect('/#kontakt')

    payload = {
        'username': ime,
        'email': email,
        'content': poruka
    }

    try:
        result = supabase.from_(SUPABASE_TABLE).insert([payload]).execute()
        error = getattr(result, 'error', None)
        if error:
            if request.is_json:
                return jsonify({'success': False, 'message': str(error)}), 500
            else:
                return redirect('/#kontakt')
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 500
        else:
            return redirect('/#kontakt')

    # Pošalji email obavještenje preko Resenda (ne blokiramo korisnika ako ne uspije)
    if RESEND_API_KEY:
        try:
            html_body = f"""
            <div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
                <h2 style="color: #2e5e2f;">Nova poruka sa web stranice</h2>
                <p><strong>Ime:</strong> {ime}</p>
                <p><strong>Email:</strong> {email}</p>
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                <h3>Poruka:</h3>
                <p style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; white-space: pre-wrap;">{poruka}</p>
            </div>
            """
            resend.Emails.send({
                "from": "Savez Mladih <onboarding@resend.dev>",
                "to": MY_EMAIL,
                "subject": "Nova poruka sa web stranice",
                "html": html_body
            })
            print(f"Email obavještenje poslano za poruku od {ime} ({email})")
        except Exception as email_err:
            print(f"Email slanje neuspješno: {email_err}")

    # Ako je JSON/AJAX, vrati JSON; ako je klasična forma, redirect nazad na kontakt sekciju
    if request.is_json:
        return jsonify({'success': True, 'message': 'Poruka je uspješno poslata!'}), 200
    else:
        return redirect('/#kontakt')


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
    DEBUG = os.environ.get('DEBUG', 'True').lower() in ('1', 'true', 'yes')
    print(f"Starting Flask app on http://0.0.0.0:{PORT} (debug={DEBUG})")
    app.run(host='0.0.0.0', port=PORT, debug=DEBUG)
