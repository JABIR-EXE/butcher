"""Account and per-business workspace management for CutPilot hosted pilot.

Each organization receives a separate SQLite database file. This is suitable for
an invite-only, single-instance beta on persistent storage; migrate to PostgreSQL
before horizontal scaling or a larger production launch.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
import sqlite3
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CUTPILOT_DATA_DIR", BASE_DIR / "data")).resolve()
TENANT_DIR = DATA_DIR / "tenants"
AUTH_DB = DATA_DIR / "auth.sqlite3"
SESSION_COOKIE = "cutpilot_session"
SESSION_DAYS = int(os.environ.get("CUTPILOT_SESSION_DAYS", "7"))

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  full_name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  email_verified INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS organizations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  country TEXT NOT NULL DEFAULT '',
  currency TEXT NOT NULL DEFAULT 'USD',
  owner_user_id TEXT NOT NULL REFERENCES users(id),
  plan TEXT NOT NULL DEFAULT 'starter',
  subscription_status TEXT NOT NULL DEFAULT 'pilot',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'owner',
  created_at TEXT NOT NULL,
  PRIMARY KEY(user_id, organization_id)
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS email_tokens (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_type TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS billing_events (
  id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  event_type TEXT NOT NULL,
  provider_event_id TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'recorded',
  created_at TEXT NOT NULL
);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def stamp(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(AUTH_DB, timeout=20, factory=ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def init_db() -> None:
    TENANT_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)
    try:
        os.chmod(AUTH_DB, 0o600)
    except OSError:
        pass


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    # scrypt is deliberately used from Python's standard library; no plaintext passwords are stored.
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + salt.hex() + "$" + derived.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(digest_hex)))
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tenant_db_path(organization_id: str) -> Path:
    # Organization IDs are generated UUIDs, never user-supplied file paths.
    parsed = uuid.UUID(organization_id)
    return TENANT_DIR / f"{parsed}.sqlite3"


def create_account(*, full_name: str, email: str, password: str, business_name: str,
                   country: str = "", currency: str = "USD", plan: str = "starter") -> dict[str, Any]:
    full_name = " ".join(full_name.split())[:100]
    email = email.strip().lower()[:254]
    business_name = " ".join(business_name.split())[:120]
    currency = currency.upper().strip()
    plan = plan.lower().strip()
    if len(full_name) < 2:
        raise ValueError("Enter your name.")
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise ValueError("Enter a valid email address.")
    if len(password) < 12:
        raise ValueError("Use a password with at least 12 characters.")
    if not business_name:
        raise ValueError("Enter your butcher shop or business name.")
    if currency not in {"USD", "EUR", "GBP", "AED", "MAD", "CAD", "AUD"}:
        raise ValueError("Choose a supported business currency.")
    if plan not in {"starter", "professional", "multi-location"}:
        plan = "starter"

    user_id = str(uuid.uuid4())
    organization_id = str(uuid.uuid4())
    now = stamp()
    encoded = password_hash(password)
    with connect() as con:
        try:
            con.execute("INSERT INTO users(id,full_name,email,password_hash,email_verified,created_at) VALUES(?,?,?,?,0,?)",
                        (user_id, full_name, email, encoded, now))
        except sqlite3.IntegrityError:
            raise ValueError("An account with this email already exists. Sign in instead.")
        con.execute("INSERT INTO organizations(id,name,country,currency,owner_user_id,plan,subscription_status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (organization_id, business_name, country[:80], currency, user_id, plan, "pilot", now))
        con.execute("INSERT INTO memberships(user_id,organization_id,role,created_at) VALUES(?,?,?,?)",
                    (user_id, organization_id, "owner", now))
    path = tenant_db_path(organization_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    return {"user_id": user_id, "organization_id": organization_id, "db_path": str(path),
            "full_name": full_name, "email": email, "business_name": business_name, "plan": plan}


def mark_email_verified(user_id: str) -> None:
    with connect() as con:
        con.execute("UPDATE users SET email_verified=1 WHERE id=?", (user_id,))


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    with connect() as con:
        user = con.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (email.strip().lower(),)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            return None
        if not user["email_verified"]:
            raise PermissionError("Please verify your email address before signing in.")
        membership = con.execute("""SELECT o.id AS organization_id,o.name AS business_name,o.country,o.currency,
            o.plan,o.subscription_status,m.role FROM memberships m JOIN organizations o ON o.id=m.organization_id
            WHERE m.user_id=? ORDER BY m.created_at LIMIT 1""", (user["id"],)).fetchone()
        if not membership:
            raise PermissionError("This account has no business workspace. Contact support.")
        return {"user_id": user["id"], "full_name": user["full_name"], "email": user["email"], **dict(membership),
                "db_path": str(tenant_db_path(membership["organization_id"]))}


def create_session(user_id: str, organization_id: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    now = utc_now()
    expires = now + timedelta(days=SESSION_DAYS)
    with connect() as con:
        con.execute("INSERT INTO sessions(token_hash,user_id,organization_id,expires_at,created_at) VALUES(?,?,?,?,?)",
                    (_token_hash(token), user_id, organization_id, stamp(expires), stamp(now)))
    return token, stamp(expires)


def get_session(token: str | None) -> dict[str, Any] | None:
    if not token or len(token) < 40:
        return None
    with connect() as con:
        row = con.execute("""SELECT s.user_id,s.organization_id,s.expires_at,u.full_name,u.email,u.email_verified,
            o.name AS business_name,o.country,o.currency,o.plan,o.subscription_status,m.role
            FROM sessions s JOIN users u ON u.id=s.user_id
            JOIN organizations o ON o.id=s.organization_id
            JOIN memberships m ON m.user_id=s.user_id AND m.organization_id=s.organization_id
            WHERE s.token_hash=?""", (_token_hash(token),)).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= utc_now():
            con.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
            return None
        result = dict(row)
        if not result.pop("email_verified"):
            return None
        result["db_path"] = str(tenant_db_path(result["organization_id"]))
        return result


def delete_session(token: str | None) -> None:
    if not token:
        return
    with connect() as con:
        con.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


def create_email_token(user_id: str, token_type: str, hours: int = 24) -> str:
    token = secrets.token_urlsafe(36)
    with connect() as con:
        con.execute("INSERT INTO email_tokens(token_hash,user_id,token_type,expires_at,created_at) VALUES(?,?,?,?,?)",
                    (_token_hash(token), user_id, token_type, stamp(utc_now()+timedelta(hours=hours)), stamp()))
    return token


def consume_email_token(token: str, token_type: str) -> str | None:
    with connect() as con:
        row = con.execute("SELECT user_id,expires_at,used_at FROM email_tokens WHERE token_hash=? AND token_type=?",
                          (_token_hash(token), token_type)).fetchone()
        if not row or row["used_at"] or datetime.fromisoformat(row["expires_at"]) <= utc_now():
            return None
        con.execute("UPDATE email_tokens SET used_at=? WHERE token_hash=?", (stamp(), _token_hash(token)))
        return row["user_id"]


def smtp_ready() -> bool:
    required = ["CUTPILOT_SMTP_HOST", "CUTPILOT_SMTP_USER", "CUTPILOT_SMTP_PASSWORD", "CUTPILOT_EMAIL_FROM"]
    return all(os.environ.get(k) for k in required)


def send_email(to_address: str, subject: str, body: str) -> None:
    if not smtp_ready():
        raise RuntimeError("Email delivery is not configured yet. Add the SMTP settings before enabling public registration.")
    host = os.environ["CUTPILOT_SMTP_HOST"]
    port = int(os.environ.get("CUTPILOT_SMTP_PORT", "587"))
    message = EmailMessage()
    message["From"] = os.environ["CUTPILOT_EMAIL_FROM"]
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.login(os.environ["CUTPILOT_SMTP_USER"], os.environ["CUTPILOT_SMTP_PASSWORD"])
        smtp.send_message(message)


def reset_password(user_id: str, new_password: str) -> None:
    if len(new_password) < 12:
        raise ValueError("Use a password with at least 12 characters.")
    encoded = password_hash(new_password)
    with connect() as con:
        con.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, user_id))
        con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
