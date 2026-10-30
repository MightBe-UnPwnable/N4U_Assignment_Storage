import os
import re
import html
import time
import secrets
import hashlib
import sqlite3
from datetime import datetime, timezone

from flask import Flask, request, render_template, redirect, url_for, send_from_directory, g
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(BASE_DIR, 'data'))
UPLOAD_DIR = os.environ.get('UPLOAD_DIR', os.path.join(BASE_DIR, 'uploads'))
THUMB_DIR = os.path.join(UPLOAD_DIR, 'thumbs')
DB_PATH = os.path.join(DATA_DIR, 'board.db')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)

SITE_NAME = os.environ.get('SITE_NAME', 'ANONBOARD')
SITE_SUBTITLE = os.environ.get('SITE_SUBTITLE', 'I spent three weeks configing this btw')
THREADS_PER_PAGE = 10
MAX_COMMENT_LEN = 2000
MAX_NAME_LEN = 75
MAX_SUBJECT_LEN = 100
MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 5 * 1024 * 1024))  # 5 MB default
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
POST_COOLDOWN_SECONDS = int(os.environ.get('POST_COOLDOWN_SECONDS', 15))
THUMB_MAX = 250

# Admin key used to delete posts. Set this via an environment variable in
# real deployments. If it isn't set, a random one is generated at startup
# and printed to the logs so the app is still usable on a first run.
ADMIN_KEY = os.environ.get('ADMIN_KEY')
if not ADMIN_KEY:
    ADMIN_KEY = secrets.token_hex(16)
    print('=' * 72)
    print(' No ADMIN_KEY environment variable was set.')
    print(f' Generated a temporary admin/delete password: {ADMIN_KEY}')
    print(' Set ADMIN_KEY yourself so it does not change on every restart.')
    print('=' * 72)

application = Flask(__name__)
application.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE + (256 * 1024)

# very small in-memory flood protection: ip_hash -> last post unix time
_last_post_by_ip = {}


class UploadError(Exception):
    pass


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA foreign_keys=ON')
    return db


@application.teardown_appcontext
def close_db(_exc):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id   INTEGER NOT NULL DEFAULT 0,
            name        TEXT NOT NULL DEFAULT 'Anonymous',
            subject     TEXT,
            comment     TEXT NOT NULL DEFAULT '',
            image       TEXT,
            image_name  TEXT,
            image_size  INTEGER,
            image_w     INTEGER,
            image_h     INTEGER,
            created_at  TEXT NOT NULL,
            bumped_at   TEXT,
            ip_hash     TEXT
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_posts_parent ON posts(parent_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_posts_bumped ON posts(bumped_at)')
    conn.commit()
    conn.close()


init_db()

# ---------------------------------------------------------------------------
# Helpers: flood control, comment rendering, uploads
# ---------------------------------------------------------------------------

def client_ip():
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'


def hash_ip(ip):
    return hashlib.sha256(f'{ADMIN_KEY}:{ip}'.encode()).hexdigest()[:16]


def is_flooding(ip_hash):
    last = _last_post_by_ip.get(ip_hash)
    return last is not None and (time.time() - last) < POST_COOLDOWN_SECONDS


def record_post_time(ip_hash):
    _last_post_by_ip[ip_hash] = time.time()


QUOTE_RE = re.compile(r'&gt;&gt;(\d+)')
REF_RE = re.compile(r'>>(\d+)')


def render_comment(raw_comment):
    """Escape user text, then apply >>quote links and >greentext.
    Only ever builds markup out of already-escaped text, so this is safe
    to mark `| safe` in the template."""
    escaped = html.escape(raw_comment)
    out_lines = []
    for line in escaped.split('\n'):
        linked = QUOTE_RE.sub(
            lambda m: f'<a href="#p{m.group(1)}" class="quotelink">&gt;&gt;{m.group(1)}</a>',
            line,
        )
        if line.startswith('&gt;') and not line.startswith('&gt;&gt;'):
            out_lines.append(f'<span class="quote">{linked}</span>')
        else:
            out_lines.append(linked)
    return '<br>'.join(out_lines)


def compute_backlinks(rows):
    """rows: iterable of sqlite3.Row with 'id' and 'comment' (raw text).
    Returns {post_id: [ids of posts that reference it]}."""
    backlinks = {}
    for row in rows:
        for ref in REF_RE.findall(row['comment'] or ''):
            backlinks.setdefault(int(ref), []).append(row['id'])
    return backlinks


def format_time(iso_str):
    dt = datetime.fromisoformat(iso_str)
    return dt.strftime('%m/%d/%y(%a)%H:%M:%S')


def post_to_dict(row, backlinks):
    return {
        'id': row['id'],
        'name': row['name'],
        'subject': row['subject'],
        'comment_html': render_comment(row['comment'] or ''),
        'image': row['image'],
        'image_name': row['image_name'],
        'image_size': row['image_size'],
        'image_w': row['image_w'],
        'image_h': row['image_h'],
        'created_at': format_time(row['created_at']),
        'backlinks': backlinks.get(row['id'], []),
    }


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file_storage):
    """Validates and stores an uploaded image + thumbnail.
    Returns a dict of file metadata, or raises UploadError."""
    filename = file_storage.filename
    if not allowed_file(filename):
        raise UploadError('Unsupported file type. Allowed: ' + ', '.join(sorted(ALLOWED_EXTENSIONS)))

    ext = filename.rsplit('.', 1)[1].lower()
    unique_name = f'{int(time.time() * 1000)}{secrets.token_hex(4)}.{ext}'
    filepath = os.path.join(UPLOAD_DIR, unique_name)

    file_storage.save(filepath)
    size = os.path.getsize(filepath)

    if size > MAX_FILE_SIZE:
        os.remove(filepath)
        raise UploadError(f'File too large (max {MAX_FILE_SIZE // (1024 * 1024)} MB).')

    try:
        with Image.open(filepath) as check:
            check.verify()
        with Image.open(filepath) as img:
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            thumb = img.copy()
            thumb.thumbnail((THUMB_MAX, THUMB_MAX))
            if thumb.mode in ('RGBA', 'P') and ext in ('jpg', 'jpeg'):
                thumb = thumb.convert('RGB')
            thumb.save(os.path.join(THUMB_DIR, unique_name))
    except UploadError:
        raise
    except Exception:
        if os.path.exists(filepath):
            os.remove(filepath)
        raise UploadError('That file is not a valid image.')

    return {
        'stored_name': unique_name,
        'orig_name': secure_filename(filename) or 'file',
        'size': size,
        'width': width,
        'height': height,
    }


def insert_post(parent_id, name, subject, comment, upload, created_at, bumped_at, ip_hash):
    db = get_db()
    cur = db.execute(
        '''INSERT INTO posts
           (parent_id, name, subject, comment, image, image_name, image_size, image_w, image_h, created_at, bumped_at, ip_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            parent_id, name, subject, comment,
            upload['stored_name'] if upload else None,
            upload['orig_name'] if upload else None,
            upload['size'] if upload else None,
            upload['width'] if upload else None,
            upload['height'] if upload else None,
            created_at, bumped_at, ip_hash,
        ),
    )
    db.commit()
    return cur.lastrowid


def get_threads_page(page):
    db = get_db()
    total = db.execute('SELECT COUNT(*) AS c FROM posts WHERE parent_id = 0').fetchone()['c']
    total_pages = max(1, (total + THREADS_PER_PAGE - 1) // THREADS_PER_PAGE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * THREADS_PER_PAGE

    op_rows = db.execute(
        'SELECT * FROM posts WHERE parent_id = 0 ORDER BY bumped_at DESC LIMIT ? OFFSET ?',
        (THREADS_PER_PAGE, offset),
    ).fetchall()

    threads = []
    for op in op_rows:
        reply_rows = db.execute(
            'SELECT * FROM posts WHERE parent_id = ? ORDER BY id ASC', (op['id'],)
        ).fetchall()
        backlinks = compute_backlinks([op] + list(reply_rows))
        threads.append({
            'op': post_to_dict(op, backlinks),
            'replies': [post_to_dict(r, backlinks) for r in reply_rows],
            'reply_count': len(reply_rows),
        })
    return threads, page, total_pages


# ---------------------------------------------------------------------------
# Routes -- everything lives on "/", there are no other pages
# ---------------------------------------------------------------------------

def render_board(page, error=None, form_values=None, reply_to=None, status=200):
    threads, page, total_pages = get_threads_page(page)
    body = render_template(
        'index.html',
        site_name=SITE_NAME,
        site_subtitle=SITE_SUBTITLE,
        threads=threads,
        page=page,
        total_pages=total_pages,
        error=error,
        form_values=form_values or {},
        reply_to=reply_to,
    )
    return body, status


@application.route('/', methods=['GET'])
def index():
    page = request.args.get('page', 1, type=int)
    return render_board(page)


@application.route('/', methods=['POST'])
def submit():
    if request.form.get('action') == 'delete':
        return handle_delete()
    return handle_post()


def handle_post():
    page = request.args.get('page', 1, type=int)

    # Honeypot field: invisible to real users via CSS, often auto-filled by bots.
    if request.form.get('website'):
        return redirect(url_for('index'))

    thread_id_raw = request.form.get('thread_id', '').strip()
    reply_to = int(thread_id_raw) if thread_id_raw.isdigit() else None

    name = (request.form.get('name', '').strip() or 'Anonymous')[:MAX_NAME_LEN]
    email = request.form.get('email', '').strip()[:MAX_NAME_LEN]
    subject = request.form.get('subject', '').strip()[:MAX_SUBJECT_LEN]
    comment = request.form.get('comment', '').strip()

    ip_hash = hash_ip(client_ip())

    if is_flooding(ip_hash):
        return render_board(page, error='Flood detected. Please wait before posting again.',
                             form_values=request.form, reply_to=reply_to, status=429)

    if len(comment) > MAX_COMMENT_LEN:
        return render_board(page, error=f'Comment too long (max {MAX_COMMENT_LEN} characters).',
                             form_values=request.form, reply_to=reply_to)

    upload_result = None
    file_storage = request.files.get('file')
    if file_storage and file_storage.filename:
        try:
            upload_result = save_upload(file_storage)
        except UploadError as e:
            return render_board(page, error=str(e), form_values=request.form, reply_to=reply_to)

    if not comment and not upload_result:
        return render_board(page, error='Post must include a comment or an image.',
                             form_values=request.form, reply_to=reply_to)

    now = datetime.now(timezone.utc).isoformat()
    db = get_db()

    if reply_to is not None:
        parent = db.execute('SELECT id FROM posts WHERE id = ? AND parent_id = 0', (reply_to,)).fetchone()
        if not parent:
            return render_board(page, error='That thread no longer exists.',
                                 form_values=request.form, reply_to=reply_to)
        new_id = insert_post(reply_to, name, None, comment, upload_result, now, None, ip_hash)
        if email.lower() != 'sage':
            db.execute('UPDATE posts SET bumped_at = ? WHERE id = ?', (now, reply_to))
            db.commit()
    else:
        new_id = insert_post(0, name, subject or None, comment, upload_result, now, now, ip_hash)

    record_post_time(ip_hash)
    return redirect(url_for('index') + f'#p{new_id}')


def handle_delete():
    page = request.args.get('page', 1, type=int)
    post_id_raw = request.form.get('post_id', '').strip()
    password = request.form.get('password', '')

    if not secrets.compare_digest(password, ADMIN_KEY):
        return render_board(page, error='Incorrect password.', status=403)

    if not post_id_raw.isdigit():
        return render_board(page, error='Invalid post.')

    post_id = int(post_id_raw)
    db = get_db()
    row = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    if not row:
        return render_board(page, error='Post not found.')

    rows_to_purge = [row]
    if row['parent_id'] == 0:
        rows_to_purge += list(db.execute('SELECT * FROM posts WHERE parent_id = ?', (post_id,)).fetchall())

    for r in rows_to_purge:
        if r['image']:
            for folder in (UPLOAD_DIR, THUMB_DIR):
                path = os.path.join(folder, r['image'])
                if os.path.exists(path):
                    os.remove(path)

    if row['parent_id'] == 0:
        db.execute('DELETE FROM posts WHERE parent_id = ?', (post_id,))
    db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    db.commit()

    return redirect(url_for('index'))


@application.route('/uploads/full/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@application.route('/uploads/thumb/<filename>')
def uploaded_thumb(filename):
    return send_from_directory(THUMB_DIR, filename)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    application.run(host='0.0.0.0', port=port, debug=True)
