// server.js — web server + SQLite database + password login + email OTP verification at signup.
// Setup:  npm install      then copy .env.example to .env, fill in SMTP settings, then  node server.js
// Needs Node 22.5+ (uses the built-in node:sqlite).

const express = require('express');
const { DatabaseSync } = require('node:sqlite');
const crypto = require('crypto');
const path = require('path');

// Load .env (Node 20.12+). Silently ignored if the file doesn't exist.
try { process.loadEnvFile(path.join(__dirname, '.env')); } catch {}

const PORT = process.env.PORT || 3000;
const OTP_TTL_MS = 5 * 60 * 1000;          // code valid for 5 minutes
const RESEND_GAP_MS = 30 * 1000;           // wait 30s between codes
const MAX_ATTEMPTS = 5;                    // wrong OTP guesses allowed per code
const SESSION_MS = 30 * 24 * 3600 * 1000;  // stay logged in for 30 days
const LOGIN_MAX_FAILS = 5;                 // wrong passwords before temporary lock
const LOGIN_LOCK_MS = 15 * 60 * 1000;

// ---------- Database (creates users.db next to this file) ----------
const db = new DatabaseSync(path.join(__dirname, 'users.db'));
db.exec('PRAGMA journal_mode = WAL');

// If users.db was made by the old version (no "username" column), set the old tables aside
// (renamed to *_old_v1, nothing is deleted) so the new tables can be created cleanly.
const oldUsers = db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").get();
if (oldUsers && !db.prepare('PRAGMA table_info(users)').all().some((c) => c.name === 'username')) {
  db.exec('PRAGMA foreign_keys = OFF');
  for (const t of ['sessions', 'otps', 'users']) {
    if (db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(t)) db.exec(`ALTER TABLE ${t} RENAME TO ${t}_old_v1`);
  }
  console.log('\n  ℹ  Old database layout found — old tables were renamed to *_old_v1 and fresh ones created.');
}

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login    TEXT
  );
  -- A signup waits here until the email code is confirmed; only then a real user is created.
  CREATE TABLE IF NOT EXISTS pending (
    email         TEXT PRIMARY KEY,
    username      TEXT NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    code_hash     TEXT NOT NULL,
    expires_at    INTEGER NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_sent     INTEGER NOT NULL
  );
  CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    expires_at INTEGER NOT NULL
  );
`);

// ---------- Helpers ----------
const otpHash = (email, code) => crypto.createHash('sha256').update(`${email}:${code}`).digest('hex');

function hashPassword(pw) {
  const salt = crypto.randomBytes(16);
  const key = crypto.scryptSync(pw, salt, 64);
  return `${salt.toString('hex')}:${key.toString('hex')}`;
}
function checkPassword(pw, stored) {
  const [saltHex, keyHex] = stored.split(':');
  const key = crypto.scryptSync(pw, Buffer.from(saltHex, 'hex'), 64);
  return crypto.timingSafeEqual(key, Buffer.from(keyHex, 'hex'));
}
const DUMMY_HASH = hashPassword('dummy-password'); // keeps login timing similar for unknown usernames

const isEmail = (s) => typeof s === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(s) && s.length <= 254;
const USERNAME_RE = /^[A-Za-z0-9_.]{3,20}$/;
const usernameError = (u) => USERNAME_RE.test(u) ? null : 'Username must be 3–20 characters: letters, numbers, _ or .';
const passwordError = (p) => (typeof p === 'string' && p.length >= 8 && p.length <= 128) ? null : 'Password must be 8–128 characters.';

const getCookie = (req, key) =>
  (req.headers.cookie || '').split('; ').map((c) => c.split('=')).find(([k]) => k === key)?.[1];

function usernameTaken(username, exceptEmail = '') {
  if (db.prepare('SELECT 1 FROM users WHERE username = ?').get(username)) return true;
  return !!db.prepare('SELECT 1 FROM pending WHERE username = ? AND email != ? AND expires_at > ?')
    .get(username, exceptEmail, Date.now());
}

// Up to 3 free alternatives, e.g. asha -> asha42, asha_7, asha2026
function suggestUsernames(base, exceptEmail = '') {
  base = base.replace(/[^A-Za-z0-9_.]/g, '').slice(0, 14) || 'user';
  const out = new Set();
  const tries = [() => base + crypto.randomInt(10, 100), () => `${base}_${crypto.randomInt(1, 10)}`,
                 () => base + new Date().getFullYear(), () => base + crypto.randomInt(100, 1000)];
  for (let i = 0; out.size < 3 && i < 30; i++) {
    const c = tries[i % tries.length]();
    if (c.length <= 20 && !usernameTaken(c, exceptEmail)) out.add(c);
  }
  return [...out];
}

// ---------- Email ----------
const smtpConfigured = () => !!(process.env.SMTP_HOST && process.env.SMTP_USER && process.env.SMTP_PASS);
let transport;
function getTransport() {
  if (!transport) {
    const port = Number(process.env.SMTP_PORT || 587);
    transport = require('nodemailer').createTransport({
      host: process.env.SMTP_HOST,
      port,
      secure: port === 465,                       // 465 = SSL, 587 = STARTTLS
      auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS },
    });
  }
  return transport;
}

// Returns true if a real email was sent; false if SMTP isn't configured (code is printed in this terminal instead).
async function deliverCode(email, code) {
  if (!smtpConfigured()) {
    console.log(`\n  ┌─ OTP for ${email}  (SMTP not configured — NOT emailed)\n  └─ ${code}   (valid 5 min)\n`);
    return false;
  }
  await getTransport().sendMail({
    from: process.env.SMTP_FROM || process.env.SMTP_USER,
    to: email,
    subject: `Your verification code: ${code}`,
    text: `Your verification code is ${code}. It expires in 5 minutes.\n\nIf you didn't request this, ignore this email.`,
  });
  return true;
}

// Create/replace the OTP for a pending signup and send it.
async function issueCode(res, email) {
  const code = String(crypto.randomInt(100000, 1000000));
  db.prepare('UPDATE pending SET code_hash = ?, expires_at = ?, attempts = 0, last_sent = ? WHERE email = ?')
    .run(otpHash(email, code), Date.now() + OTP_TTL_MS, Date.now(), email);
  try {
    const emailed = await deliverCode(email, code);
    res.json({ ok: true, emailed, resendIn: RESEND_GAP_MS / 1000 });
  } catch (err) {
    console.error('Email failed:', err.message);
    res.status(502).json({ error: 'Could not send the email. Check the SMTP settings in .env (see server terminal).' });
  }
}

function startSession(res, userId) {
  const token = crypto.randomBytes(32).toString('hex');
  db.prepare('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)').run(token, userId, Date.now() + SESSION_MS);
  res.setHeader('Set-Cookie', `sid=${token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${SESSION_MS / 1000}`);
}

// ---------- App ----------
const app = express();
app.use(express.json({ limit: '10kb' }));
// Makes errors inside async routes return a JSON error instead of crashing the whole server.
const wrap = (fn) => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);

app.get('/', (_req, res) => res.sendFile(path.join(__dirname, 'index.html')));

// Live "is this username free?" check
app.get('/api/check-username', (req, res) => {
  const username = String(req.query.u || '').trim();
  const bad = usernameError(username);
  if (bad) return res.json({ available: false, error: bad, suggestions: [] });
  if (!usernameTaken(username)) return res.json({ available: true });
  res.json({ available: false, error: 'That username is taken.', suggestions: suggestUsernames(username) });
});

// Signup step 1: validate, then email a code
app.post('/api/signup', wrap(async (req, res) => {
  const username = String(req.body.username || '').trim();
  const email = String(req.body.email || '').trim().toLowerCase();
  const password = req.body.password;

  const bad = usernameError(username) || (!isEmail(email) && 'Enter a valid email address.') || passwordError(password);
  if (bad) return res.status(400).json({ error: bad });

  if (db.prepare('SELECT 1 FROM users WHERE email = ?').get(email))
    return res.status(409).json({ error: 'This email is already registered. Log in instead.' });
  if (usernameTaken(username, email))
    return res.status(409).json({ error: `The username "${username}" is already taken.`, suggestions: suggestUsernames(username, email) });

  const prev = db.prepare('SELECT last_sent FROM pending WHERE email = ?').get(email);
  const wait = prev ? prev.last_sent + RESEND_GAP_MS - Date.now() : 0;
  if (wait > 0) return res.status(429).json({ error: `Wait ${Math.ceil(wait / 1000)}s before requesting another code.` });

  db.prepare(`
    INSERT INTO pending (email, username, password_hash, code_hash, expires_at, attempts, last_sent) VALUES (?, ?, ?, '', 0, 0, 0)
    ON CONFLICT(email) DO UPDATE SET username = excluded.username, password_hash = excluded.password_hash
  `).run(email, username, hashPassword(password));
  await issueCode(res, email);
}));

// Resend the code for a signup in progress
app.post('/api/resend-otp', wrap(async (req, res) => {
  const email = String(req.body.email || '').trim().toLowerCase();
  const row = db.prepare('SELECT last_sent FROM pending WHERE email = ?').get(email);
  if (!row) return res.status(400).json({ error: 'Start the signup again.' });
  const wait = row.last_sent + RESEND_GAP_MS - Date.now();
  if (wait > 0) return res.status(429).json({ error: `Wait ${Math.ceil(wait / 1000)}s before requesting another code.` });
  await issueCode(res, email);
}));

// Signup step 2: check the code, create the account, log in
app.post('/api/verify-otp', (req, res) => {
  const email = String(req.body.email || '').trim().toLowerCase();
  const code = String(req.body.code || '').trim();

  const row = db.prepare('SELECT * FROM pending WHERE email = ?').get(email);
  if (!row || row.expires_at < Date.now()) return res.status(400).json({ error: 'This code has expired. Request a new one.' });
  if (row.attempts >= MAX_ATTEMPTS) return res.status(429).json({ error: 'Too many wrong attempts. Request a new code.' });

  const good = crypto.timingSafeEqual(Buffer.from(otpHash(email, code)), Buffer.from(row.code_hash));
  if (!good) {
    db.prepare('UPDATE pending SET attempts = attempts + 1 WHERE email = ?').run(email);
    const left = MAX_ATTEMPTS - row.attempts - 1;
    return res.status(400).json({ error: left > 0 ? `Wrong code. ${left} ${left === 1 ? 'try' : 'tries'} left.` : 'Too many wrong attempts. Request a new code.' });
  }

  let userId;
  try {
    userId = db.prepare("INSERT INTO users (username, email, password_hash, last_login) VALUES (?, ?, ?, CURRENT_TIMESTAMP)")
      .run(row.username, email, row.password_hash).lastInsertRowid;
  } catch {
    // someone grabbed the username/email in the meantime
    return res.status(409).json({ error: 'That username was just taken. Go back and pick another.', suggestions: suggestUsernames(row.username, email) });
  }
  db.prepare('DELETE FROM pending WHERE email = ?').run(email);
  startSession(res, userId);
  res.json({ ok: true, user: { username: row.username, email } });
});

// Login: username + password only
const fails = new Map(); // username(lowercase) -> { n, until }
app.post('/api/login', (req, res) => {
  const username = String(req.body.username || '').trim();
  const password = String(req.body.password || '');
  const key = username.toLowerCase();

  const f = fails.get(key);
  if (f && f.until > Date.now()) return res.status(429).json({ error: `Too many failed attempts. Try again in ${Math.ceil((f.until - Date.now()) / 60000)} min.` });

  const user = db.prepare('SELECT id, username, email, password_hash FROM users WHERE username = ?').get(username);
  let ok = false;
  try { ok = checkPassword(password, user ? user.password_hash : DUMMY_HASH) && !!user; } catch {}
  if (!ok) {
    const n = (f && f.until <= Date.now() ? 0 : f?.n || 0) + 1;
    fails.set(key, { n, until: n >= LOGIN_MAX_FAILS ? Date.now() + LOGIN_LOCK_MS : 0 });
    return res.status(401).json({ error: 'Wrong username or password.' });
  }
  fails.delete(key);
  db.prepare('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?').run(user.id);
  startSession(res, user.id);
  res.json({ ok: true, user: { username: user.username, email: user.email } });
});

app.get('/api/me', (req, res) => {
  const user = db.prepare(`
    SELECT u.username, u.email FROM sessions s JOIN users u ON u.id = s.user_id
    WHERE s.token = ? AND s.expires_at > ?
  `).get(getCookie(req, 'sid') || '', Date.now());
  res.json({ user: user || null });
});

app.post('/api/logout', (req, res) => {
  db.prepare('DELETE FROM sessions WHERE token = ?').run(getCookie(req, 'sid') || '');
  res.setHeader('Set-Cookie', 'sid=; HttpOnly; Path=/; Max-Age=0');
  res.json({ ok: true });
});

// Any uncaught route error: log it, answer with JSON, keep the server running
app.use((err, _req, res, _next) => {
  console.error('Server error:', err.message);
  res.status(500).json({ error: 'Server error. Check the terminal for details.' });
});

// Clean up expired rows once an hour
setInterval(() => {
  db.prepare('DELETE FROM pending WHERE expires_at < ?').run(Date.now() - 3600e3);
  db.prepare('DELETE FROM sessions WHERE expires_at < ?').run(Date.now());
}, 3600e3).unref();

app.listen(PORT, '127.0.0.1', async () => {
  console.log(`\n  Running at http://localhost:${PORT}`);
  if (!smtpConfigured()) {
    console.log('  ⚠  SMTP is NOT configured — OTP codes will only print in this terminal, no email is sent.');
    console.log('     Copy .env.example to .env and fill it in to send real emails.\n');
  } else {
    try { await getTransport().verify(); console.log(`  ✔ Email ready via ${process.env.SMTP_HOST}\n`); }
    catch (e) {
      const pass = process.env.SMTP_PASS || '';
      console.log(`  ✖ SMTP login failed: ${e.message}`);
      console.log(`    Read from .env →  SMTP_USER="${process.env.SMTP_USER}"  SMTP_PASS length=${pass.length} (a Gmail App password is exactly 16)`);
      if (pass.length !== 16) console.log('    ⚠ SMTP_PASS is not 16 characters: remove spaces and quotes, and paste the App password only.');
      console.log('    Also check: SMTP_USER is the same Gmail account that created the App password, and 2-Step Verification is on.\n');
    }
  }
});