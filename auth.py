"""Sign up / log in for KitchenSathi (Flask port of the Node signup server).

Same API the signup page already uses:
  GET  /api/check-username?u=...   POST /api/signup    POST /api/resend-otp
  POST /api/verify-otp             POST /api/login     GET  /api/me
  POST /api/logout
The signup page itself is served at /login (also /signup).
Accounts live in users.db, in the same format the Node server used,
so existing accounts keep working.

Every other page and /api/* route needs a logged-in user.
"""
import hashlib
import hmac
import os
import re
import secrets
import smtplib
import sqlite3
import threading
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

from flask import jsonify, redirect, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
USERS_DB = BASE_DIR / "users.db"

OTP_TTL = 5 * 60
RESEND_GAP = 30
MAX_ATTEMPTS = 5
SESSION_SECONDS = 30 * 24 * 3600
LOGIN_MAX_FAILS = 5
LOGIN_LOCK = 15 * 60

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{3,20}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")

# Endpoints anyone may reach without logging in.
PUBLIC_ENDPOINTS = {
    "static", "auth_page", "auth_check_username", "auth_signup",
    "auth_resend_otp", "auth_verify_otp", "auth_login", "auth_me",
    "auth_logout",
}


def load_env():
    """Read .env (KEY=value lines) without overriding real env vars."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# ---------- password hashing (compatible with the Node server) ----------
def hash_password(password):
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=64)
    return f"{salt.hex()}:{key.hex()}"


def check_password(password, stored):
    try:
        salt_hex, key_hex = stored.split(":")
        key = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex),
            n=16384, r=8, p=1, dklen=64,
        )
        return hmac.compare_digest(key, bytes.fromhex(key_hex))
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password("dummy-password")  # keeps timing similar for unknown users


def otp_hash(email, code):
    return hashlib.sha256(f"{email}:{code}".encode()).hexdigest()


def username_error(u):
    return None if USERNAME_RE.match(u) else \
        "Username must be 3–20 characters: letters, numbers, _ or ."


def password_error(p):
    ok = isinstance(p, str) and 8 <= len(p) <= 128
    return None if ok else "Password must be 8–128 characters."


# ---------- email ----------
def smtp_configured():
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS"))


def deliver_code(email, code):
    """True if emailed; False if SMTP is not set up (code is printed instead)."""
    if not smtp_configured():
        print(f"\n  ┌─ OTP for {email}  (SMTP not configured — NOT emailed)"
              f"\n  └─ {code}   (valid 5 min)\n", flush=True)
        return False

    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM") or os.environ["SMTP_USER"]
    msg["To"] = email
    msg["Subject"] = f"Your verification code: {code}"
    msg.set_content(
        f"Your verification code is {code}. It expires in 5 minutes.\n\n"
        "If you didn't request this, ignore this email."
    )
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", 587))
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=20)
    else:
        server = smtplib.SMTP(host, port, timeout=20)
        server.starttls()
    with server:
        server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        server.send_message(msg)
    return True


def init_auth(app):
    load_env()

    def db():
        conn = sqlite3.connect(USERS_DB)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- schema (old pre-username tables are renamed, never deleted) ----
    with db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        has_users = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if has_users:
            cols = [c["name"] for c in conn.execute("PRAGMA table_info(users)")]
            if "username" not in cols:
                for t in ("sessions", "otps", "users"):
                    if conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)
                    ).fetchone():
                        conn.execute(f"ALTER TABLE {t} RENAME TO {t}_old_v1")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login TEXT
            );
            CREATE TABLE IF NOT EXISTS pending (
                email TEXT PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_sent INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                expires_at INTEGER NOT NULL
            );
        """)
        now_ms = int(time.time() * 1000)
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_ms,))
        conn.execute("DELETE FROM pending WHERE expires_at < ?", (now_ms - 3600_000,))

    now_ms = lambda: int(time.time() * 1000)
    fails = {}                 # username.lower() -> [count, locked_until_ms]
    fails_lock = threading.Lock()

    # ---- helpers ----
    def current_user():
        token = request.cookies.get("sid")
        if not token:
            return None
        with db() as conn:
            return conn.execute(
                "SELECT u.id, u.username, u.email FROM sessions s "
                "JOIN users u ON u.id = s.user_id "
                "WHERE s.token = ? AND s.expires_at > ?",
                (token, now_ms()),
            ).fetchone()

    def with_session(resp, user_id):
        token = secrets.token_hex(32)
        with db() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, now_ms() + SESSION_SECONDS * 1000),
            )
        resp.set_cookie(
            "sid", token, max_age=SESSION_SECONDS,
            httponly=True, samesite="Lax", path="/",
        )
        return resp

    def username_taken(conn, username, except_email=""):
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            return True
        return bool(conn.execute(
            "SELECT 1 FROM pending WHERE username = ? AND email != ? AND expires_at > ?",
            (username, except_email, now_ms()),
        ).fetchone())

    def suggest_usernames(conn, base, except_email=""):
        base = re.sub(r"[^A-Za-z0-9_.]", "", base)[:14] or "user"
        year = time.gmtime().tm_year
        makers = [
            lambda: f"{base}{secrets.randbelow(90) + 10}",
            lambda: f"{base}_{secrets.randbelow(9) + 1}",
            lambda: f"{base}{year}",
            lambda: f"{base}{secrets.randbelow(900) + 100}",
        ]
        out = []
        for i in range(30):
            if len(out) >= 3:
                break
            cand = makers[i % 4]()
            if len(cand) <= 20 and cand not in out and not username_taken(conn, cand, except_email):
                out.append(cand)
        return out

    def issue_code(email):
        """Make a new OTP for a pending signup and send it."""
        code = str(secrets.randbelow(900000) + 100000)
        with db() as conn:
            conn.execute(
                "UPDATE pending SET code_hash = ?, expires_at = ?, attempts = 0, "
                "last_sent = ? WHERE email = ?",
                (otp_hash(email, code), now_ms() + OTP_TTL * 1000, now_ms(), email),
            )
        try:
            emailed = deliver_code(email, code)
        except Exception as exc:  # SMTP problems must not crash the server
            app.logger.error("Email failed: %s", exc)
            return jsonify(error="Could not send the email. Check the SMTP "
                                 "settings in .env (see server terminal)."), 502
        return jsonify(ok=True, emailed=emailed, resendIn=RESEND_GAP)

    def json_body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    # ---- the signup/login page ----
    @app.route("/login")
    @app.route("/signup")
    def auth_page():
        if current_user():
            return redirect("/")
        resp = send_from_directory(BASE_DIR / "auth_pages", "auth.html")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # ---- API ----
    @app.get("/api/check-username")
    def auth_check_username():
        username = request.args.get("u", "").strip()
        bad = username_error(username)
        if bad:
            return jsonify(available=False, error=bad, suggestions=[])
        with db() as conn:
            if not username_taken(conn, username):
                return jsonify(available=True)
            return jsonify(available=False, error="That username is taken.",
                           suggestions=suggest_usernames(conn, username))

    @app.post("/api/signup")
    def auth_signup():
        body = json_body()
        username = str(body.get("username") or "").strip()
        email = str(body.get("email") or "").strip().lower()
        password = body.get("password")

        bad = username_error(username) or \
            (None if EMAIL_RE.match(email) and len(email) <= 254
             else "Enter a valid email address.") or \
            password_error(password)
        if bad:
            return jsonify(error=bad), 400

        with db() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                return jsonify(error="This email is already registered. Log in instead."), 409
            if username_taken(conn, username, email):
                return jsonify(
                    error=f'The username "{username}" is already taken.',
                    suggestions=suggest_usernames(conn, username, email),
                ), 409

            prev = conn.execute(
                "SELECT last_sent FROM pending WHERE email = ?", (email,)
            ).fetchone()
            wait = (prev["last_sent"] + RESEND_GAP * 1000 - now_ms()) if prev else 0
            if wait > 0:
                return jsonify(error=f"Wait {-(-wait // 1000)}s before requesting another code."), 429

            conn.execute(
                "INSERT INTO pending (email, username, password_hash, code_hash, "
                "expires_at, attempts, last_sent) VALUES (?, ?, ?, '', 0, 0, 0) "
                "ON CONFLICT(email) DO UPDATE SET username = excluded.username, "
                "password_hash = excluded.password_hash",
                (email, username, hash_password(password)),
            )
        return issue_code(email)

    @app.post("/api/resend-otp")
    def auth_resend_otp():
        email = str(json_body().get("email") or "").strip().lower()
        with db() as conn:
            row = conn.execute(
                "SELECT last_sent FROM pending WHERE email = ?", (email,)
            ).fetchone()
        if not row:
            return jsonify(error="Start the signup again."), 400
        wait = row["last_sent"] + RESEND_GAP * 1000 - now_ms()
        if wait > 0:
            return jsonify(error=f"Wait {-(-wait // 1000)}s before requesting another code."), 429
        return issue_code(email)

    @app.post("/api/verify-otp")
    def auth_verify_otp():
        body = json_body()
        email = str(body.get("email") or "").strip().lower()
        code = str(body.get("code") or "").strip()

        with db() as conn:
            row = conn.execute("SELECT * FROM pending WHERE email = ?", (email,)).fetchone()
            if not row or row["expires_at"] < now_ms():
                return jsonify(error="This code has expired. Request a new one."), 400
            if row["attempts"] >= MAX_ATTEMPTS:
                return jsonify(error="Too many wrong attempts. Request a new code."), 429

            if not hmac.compare_digest(otp_hash(email, code), row["code_hash"]):
                conn.execute("UPDATE pending SET attempts = attempts + 1 WHERE email = ?", (email,))
                left = MAX_ATTEMPTS - row["attempts"] - 1
                msg = (f"Wrong code. {left} {'try' if left == 1 else 'tries'} left."
                       if left > 0 else "Too many wrong attempts. Request a new code.")
                return jsonify(error=msg), 400

            try:
                cur = conn.execute(
                    "INSERT INTO users (username, email, password_hash, last_login) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (row["username"], email, row["password_hash"]),
                )
            except sqlite3.IntegrityError:
                return jsonify(
                    error="That username was just taken. Go back and pick another.",
                    suggestions=suggest_usernames(conn, row["username"], email),
                ), 409
            user_id = cur.lastrowid
            conn.execute("DELETE FROM pending WHERE email = ?", (email,))

        resp = jsonify(ok=True, user={"username": row["username"], "email": email})
        return with_session(resp, user_id)

    @app.post("/api/login")
    def auth_login():
        body = json_body()
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        key = username.lower()

        with fails_lock:
            f = fails.get(key)
            if f and f[1] > now_ms():
                mins = -(-(f[1] - now_ms()) // 60000)
                return jsonify(error=f"Too many failed attempts. Try again in {mins} min."), 429

        with db() as conn:
            user = conn.execute(
                "SELECT id, username, email, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()

        ok = check_password(password, user["password_hash"] if user else DUMMY_HASH) and bool(user)
        if not ok:
            with fails_lock:
                prev = fails.get(key)
                n = (0 if prev and prev[1] and prev[1] <= now_ms() else (prev[0] if prev else 0)) + 1
                fails[key] = [n, now_ms() + LOGIN_LOCK * 1000 if n >= LOGIN_MAX_FAILS else 0]
            return jsonify(error="Wrong username or password."), 401

        with fails_lock:
            fails.pop(key, None)
        with db() as conn:
            conn.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user["id"],))
        resp = jsonify(ok=True, user={"username": user["username"], "email": user["email"]})
        return with_session(resp, user["id"])

    @app.get("/api/me")
    def auth_me():
        user = current_user()
        return jsonify(user={"username": user["username"], "email": user["email"]} if user else None)

    @app.post("/api/logout")
    def auth_logout():
        token = request.cookies.get("sid")
        if token:
            with db() as conn:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        resp = jsonify(ok=True)
        resp.delete_cookie("sid", path="/")
        return resp

    # ---- lock everything else ----
    @app.before_request
    def require_login():
        if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if current_user():
            return None
        if request.path.startswith("/api/"):
            return jsonify(error="Please log in first."), 401
        target = request.path
        if request.query_string:
            target += "?" + request.query_string.decode()
        return redirect(f"/login?next={quote(target, safe='')}")

    @app.context_processor
    def inject_user():
        return {"current_user": current_user()}

    @app.after_request
    def no_store_for_private_pages(resp):
        # Don't let the browser's back button show site pages after logout.
        if request.endpoint not in PUBLIC_ENDPOINTS and resp.mimetype == "text/html":
            resp.headers["Cache-Control"] = "no-store"
        return resp
