from pathlib import Path
import os
import json
import uuid
import datetime
import smtplib
import ssl
from email.message import EmailMessage
from flask import Flask, request, jsonify, redirect, send_from_directory, url_for, session
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
SUPABASE_CLIENT_KEY = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
SUPABASE_TABLE = os.environ.get('SUPABASE_TABLE', 'messages').strip()
NEWS_TABLE = os.environ.get('NEWS_TABLE', 'news').strip()
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'zeleneberetke2026').strip()
NOTIFICATION_EMAIL = os.environ.get('NOTIFICATION_EMAIL', 'harunkapo@gmail.com').strip()
SMTP_HOST = os.environ.get('SMTP_HOST', '').strip()
SMTP_PORT = int(os.environ.get('SMTP_PORT', '0')) if os.environ.get('SMTP_PORT') else 0
SMTP_USER = os.environ.get('SMTP_USER', '').strip()
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '').strip()
MAIL_FROM = os.environ.get('MAIL_FROM', SMTP_USER or f"no-reply@{SUPABASE_URL.split('://')[-1]}").strip()

app = Flask(__name__, static_folder='.', template_folder='.')
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
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASSWORD):
        return False, 'SMTP not configured'
    try:
        msg = EmailMessage()
        msg['Subject'] = f"Nova poruka sa sajta - {entry['name']}"
        msg['From'] = MAIL_FROM
        msg['To'] = NOTIFICATION_EMAIL
        msg.set_content(
            f"Nova poruka sa sajta:\n\n"
            f"Ime: {entry['name']}\n"
            f"Email: {entry['email']}\n"
            f"Poruka:\n{entry['message']}\n\n"
            f"Poslano: {entry['created']}"
        )
        context = ssl.create_default_context()
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls(context=context)
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
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
    return app.send_static_file('index.html')


def get_client_ip():
    # Render and many proxies set X-Forwarded-For with a comma-separated list
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        # take the first IP in the chain
        return forwarded.split(',')[0].strip()
    return request.remote_addr or ''


@app.route('/admin')
def admin():
    allowed_ip = '77.238.220.113'
    client_ip = get_client_ip()
    if client_ip == allowed_ip:
        return app.send_static_file('admin.html')
    return redirect(url_for('index'))


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
            msg = Mail(from_email=MAIL_FROM, to_emails=email, subject=subject, html_content=html)
            sg.send(msg)
            return True
        except ImportError as e:
            print('SendGrid library unavailable:', e)
        except Exception as e:
            print('SendGrid confirm send error:', e)
    # try SMTP
    if SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASSWORD:
        try:
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = MAIL_FROM
            msg['To'] = email
            msg.set_content('Potvrdi prijavu: ' + link)
            msg.add_alternative(html, subtype='html')
            context = ssl.create_default_context()
            if SMTP_PORT == 465:
                with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                    server.starttls(context=context)
                    server.login(SMTP_USER, SMTP_PASSWORD)
                    server.send_message(msg)
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
        # SMTP fallback
        if SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASSWORD:
            import smtplib
            from email.mime.text import MIMEText
            for s in confirmed:
                try:
                    unsub_link = f"{host}/api/unsubscribe?token={s.get('unsub_token')}"
                    body_text = (html or subject) + f"\n\nAko se želiš odjaviti: {unsub_link}"
                    msg = MIMEText(body_text)
                    msg['Subject'] = subject
                    msg['From'] = MAIL_FROM
                    msg['To'] = s.get('email')
                    if SMTP_PORT == 465:
                        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
                    else:
                        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
                        server.starttls()
                    server.login(SMTP_USER, SMTP_PASSWORD)
                    server.sendmail(MAIL_FROM, [s.get('email')], msg.as_string())
                    server.quit()
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


@app.route('/contact', methods=['POST'])
def contact():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    message = request.form.get('message', '').strip()
    if not name or not email or not message:
        return redirect(url_for('index') + '#kontakt')

    entry = {
        'name': name,
        'email': email,
        'message': message,
        'created': datetime.datetime.utcnow().isoformat() + 'Z'
    }

    saved = False
    error_text = None
    if SUPABASE_URL and SUPABASE_CLIENT_KEY:
        saved, error_text = save_to_supabase(entry)

    email_sent = False
    email_error = None
    if SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASSWORD:
        email_sent, email_error = send_notification_email(entry)
        if not email_sent:
            print('Email send failed:', email_error)
    else:
        print('Email notification skipped: SMTP not configured')

    local_saved = True
    save_local(entry)

    response_data = {
        'saved': saved,
        'email_sent': email_sent,
        'local_saved': local_saved,
        'errors': {}
    }
    if error_text:
        response_data['errors']['supabase'] = str(error_text)
    if email_error:
        response_data['errors']['email'] = str(email_error)

    if saved or email_sent:
        return jsonify(response_data), 200

    if local_saved:
        response_data['errors']['fallback'] = 'Poruka je sačuvana lokalno, ali nije poslata na email.'
        return jsonify(response_data), 200

    print('Supabase save failed:', error_text)
    return jsonify(response_data), 500


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
