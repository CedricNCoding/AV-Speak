import os
import sqlite3
import subprocess
import secrets
import smtplib
import threading
import hmac
import hashlib
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import bcrypt as _bcrypt
from pydantic import BaseModel

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "av_speak.db"

# --- License ---
# Cle HMAC pour signer les codes de licence.
# Le depot Git etant prive, la cle est directement dans le code pour simplifier
# le deploiement. Cette meme cle doit etre utilisee par generate-license.py.
LICENSE_SECRET = b"5ed1966ecbfabb763c5bf26a54d6d7009804138ebb61dfc032e46ede38a84e1e"
TRIAL_DAYS = 30
EXPIRY_WARNING_DAYS = 7
TTS_CACHE_DIR = BASE_DIR / "tts_cache"
PIPER_BIN = BASE_DIR / "piper" / "piper"
PIPER_MODEL = BASE_DIR / "piper" / "fr_FR-siwis-medium.onnx"

TTS_CACHE_DIR.mkdir(exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Simple session store (in-memory, single PC).
# sessions maps session_id -> {"username": str, "cgu_accepted": bool,
#                              "must_change_password": bool, "created_at": float, "last_used": float}
sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()
# Enable Secure cookie only if the deployment serves over HTTPS (env var).
_COOKIE_SECURE = os.environ.get("AVSPEAK_HTTPS", "").lower() in ("1", "true", "yes")

# --- Database ---

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            prenom TEXT NOT NULL,
            civilite TEXT DEFAULT 'X' NOT NULL,
            email TEXT DEFAULT '',
            telephone TEXT DEFAULT '',
            call_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS used_licenses (
            serial TEXT PRIMARY KEY,
            days INTEGER NOT NULL,
            activated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            prenom TEXT NOT NULL,
            entreprise TEXT DEFAULT '',
            contact_id INTEGER,
            arrived_at TEXT NOT NULL,
            left_at TEXT,
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS evac_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            triggered_at TEXT NOT NULL,
            success INTEGER NOT NULL,
            recipients TEXT NOT NULL,
            visitors_count INTEGER NOT NULL,
            error TEXT DEFAULT '',
            source_ip TEXT DEFAULT '',
            user_agent TEXT DEFAULT ''
        );
    """)
    # Migration: add civilite column if missing
    columns = [row[1] for row in conn.execute("PRAGMA table_info(contacts)").fetchall()]
    if "civilite" not in columns:
        conn.execute("ALTER TABLE contacts ADD COLUMN civilite TEXT DEFAULT 'X' NOT NULL")
    # Migration: add audit columns on evac_log if upgrading from an earlier schema
    evac_cols = [row[1] for row in conn.execute("PRAGMA table_info(evac_log)").fetchall()]
    if "source_ip" not in evac_cols:
        conn.execute("ALTER TABLE evac_log ADD COLUMN source_ip TEXT DEFAULT ''")
    if "user_agent" not in evac_cols:
        conn.execute("ALTER TABLE evac_log ADD COLUMN user_agent TEXT DEFAULT ''")
    # Migration: add must_change_password flag on users
    user_cols = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "must_change_password" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")
    # Migration: SMS provider switched from OVH to Conexteo — drop unused legacy keys.
    conn.execute(
        "DELETE FROM settings WHERE key IN "
        "('ovh_endpoint','ovh_app_key','ovh_app_secret','ovh_consumer_key',"
        "'ovh_sms_service','ovh_sms_sender')"
    )
    # Create default admin if not exists. The default password 'admin' is intentionally
    # weak — we flag the account so the very next login forces a password change.
    existing = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    if not existing:
        pw_hash = _bcrypt.hashpw("admin".encode(), _bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO users (username, password_hash, must_change_password) VALUES (?, ?, 1)",
            ("admin", pw_hash),
        )
    # Default color settings
    defaults = {
        "color_primary": "#1a73e8",
        "color_secondary": "#ffffff",
        "color_background": "#f5f5f5",
        "color_text": "#333333",
        "color_button": "#1a73e8",
        "color_button_text": "#ffffff",
        "entreprise_nom": "Accueil",
        "phrase_accueil": "{civilite} {prenom} {nom} est demande a l'accueil",
        "logo_url": "",
        # SMTP
        "smtp_enabled": "0",
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_password": "",
        "smtp_from": "",
        "smtp_tls": "1",
        "email_subject": "Visite de {civilite} {prenom} {nom}",
        "email_body": "Bonjour,\n\n{civilite} {prenom} {nom} vous attend a l'accueil.\n\nVisiteur : {visiteur_nom}\nEmail visiteur : {visiteur_email}\n\nCordialement,\n{entreprise}",
        # Conexteo SMS (replaces OVH)
        "sms_enabled": "0",
        "conexteo_api_key": "",
        "conexteo_sender": "",  # alphanumeric sender ID (TPOA), up to 11 chars
        "sms_body": "{civilite} {prenom} {nom} vous attend a l'accueil. Visiteur: {visiteur_nom}",
        # Notifications
        "notif_on_announce": "1",
        # Repeat / diffusion
        "repeat_count": "1",
        "repeat_delay": "20",
        # Visitor contact fields
        "contact_fields_enabled": "1",
        # Kiosk instruction text/image
        "kiosk_instruction": "",
        "kiosk_image_url": "",
        # Virtual keyboard
        "keyboard_size": "M",
        # Kiosk content size
        "kiosk_font_size": "classique",
        # License
        "license_expiry": (date.today() + timedelta(days=TRIAL_DAYS)).isoformat(),
        "license_last_seen": date.today().isoformat(),
        # Security register
        "security_register_enabled": "0",
        "security_register_history": "1",
        # Evacuation alert
        "evac_enabled": "0",
        "evac_code_hash": "",
        "evac_recipients": "",
        "evac_subject": "[ALERTE EVACUATION] Liste des visiteurs presents - {entreprise}",
        "evac_body_header": "Liste des visiteurs presents dans l'etablissement au moment du declenchement de l'alerte.",
    }
    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
    conn.commit()
    conn.close()


init_db()


# --- Helpers ---

def get_settings(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


# --- License management ---

def verify_license_code(code: str) -> tuple[bool, str, int]:
    """Verifies a license code. Returns (is_valid, serial, days_to_add)."""
    try:
        parts = code.strip().upper().replace(" ", "").split("-")
        if len(parts) != 4 or parts[0] != "AVSP":
            return False, "", 0
        serial, days_str, sig = parts[1], parts[2], parts[3]
        days = int(days_str)
        if days <= 0 or days > 36500:
            return False, "", 0
        payload = f"{serial}-{days}".encode()
        expected = hmac.new(LICENSE_SECRET, payload, hashlib.sha256).hexdigest()[:8].upper()
        if not hmac.compare_digest(expected, sig):
            return False, "", 0
        return True, serial, days
    except Exception:
        return False, "", 0


def get_license_status(conn: sqlite3.Connection) -> dict:
    """Returns {expiry, days_left, expired, warning}."""
    settings = get_settings(conn)
    expiry_str = settings.get("license_expiry")
    try:
        expiry = date.fromisoformat(expiry_str) if expiry_str else date.today()
    except Exception:
        expiry = date.today()
    today = date.today()
    # Anti-rollback: if today is before last_seen by more than 1 day, use last_seen as reference
    last_seen_str = settings.get("license_last_seen")
    try:
        last_seen = date.fromisoformat(last_seen_str) if last_seen_str else today
    except Exception:
        last_seen = today
    reference = max(today, last_seen)
    # Update last_seen if today is more recent
    if today > last_seen:
        conn.execute("UPDATE settings SET value = ? WHERE key = ?",
                     (today.isoformat(), "license_last_seen"))
        conn.commit()
    days_left = (expiry - reference).days
    return {
        "expiry": expiry.isoformat(),
        "days_left": days_left,
        "expired": days_left < 0,
        "warning": 0 <= days_left <= EXPIRY_WARNING_DAYS,
    }


def _is_json_request(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    ctype = request.headers.get("content-type", "")
    return "application/json" in accept or "application/json" in ctype


def require_auth(request: Request, *, allow_force_change: bool = False):
    """Validate session, enforce TTL, CGU acceptance, and forced password change.

    If `allow_force_change` is True (only for the /admin/password route), the
    must_change_password gate is skipped — so the user can actually change it.
    """
    session_id = request.cookies.get("session_id")
    now = _time.monotonic()
    json_req = _is_json_request(request)

    def deny_redirect(location: str):
        if json_req:
            raise HTTPException(status_code=401, detail="Session expiree ou non authentifiee")
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": location})

    with _sessions_lock:
        session = sessions.get(session_id) if session_id else None
        if session:
            age = now - session.get("created_at", now)
            idle = now - session.get("last_used", now)
            if age > SESSION_TTL_S or idle > SESSION_TTL_S:
                sessions.pop(session_id, None)
                session = None
        if not session:
            deny_redirect("/admin/login")
        session["last_used"] = now
        cgu_ok = session.get("cgu_accepted", False)
        must_change = session.get("must_change_password", False)
        username = session["username"]

    if not cgu_ok:
        deny_redirect("/admin/cgu")
    if must_change and not allow_force_change:
        deny_redirect("/admin/password?force=1")
    return username


# --- TTS generation ---

def generate_tts(texte: str) -> str | None:
    """Generate TTS with Piper and return the filename."""
    import hashlib
    filename = hashlib.md5(texte.encode()).hexdigest() + ".wav"
    filepath = TTS_CACHE_DIR / filename

    if not filepath.exists():
        try:
            result = subprocess.run(
                [str(PIPER_BIN), "--model", str(PIPER_MODEL), "--output_file", str(filepath)],
                input=texte,
                text=True,
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0:
                print(f"Erreur Piper TTS: {result.stderr}")
                return None
        except FileNotFoundError:
            print(f"Piper non trouvé: {PIPER_BIN}")
            return None
        except Exception as e:
            print(f"Erreur TTS: {e}")
            return None

    return filename


# --- Email sending ---

def send_email(settings: dict, contact: dict, civilite: str,
               visitor_name: str = "", visitor_email: str = "",
               raise_on_error: bool = False):
    """Send notification email to the contact."""
    if settings.get("smtp_enabled") != "1":
        if raise_on_error:
            raise ValueError("SMTP désactivé dans les paramètres")
        return
    email_to = contact["email"]
    if not email_to:
        if raise_on_error:
            raise ValueError("Pas d'adresse email pour ce contact")
        return

    try:
        tpl_vars = dict(
            civilite=civilite, prenom=contact["prenom"],
            nom=contact["nom"], entreprise=settings.get("entreprise_nom", ""),
            visiteur_nom=visitor_name or "Non renseigné",
            visiteur_email=visitor_email or "Non renseigné",
        )
        subject = settings["email_subject"].format(**tpl_vars).strip()
        body = settings["email_body"].format(**tpl_vars).strip()

        msg = MIMEMultipart()
        msg["From"] = settings["smtp_from"]
        msg["To"] = email_to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        port = int(settings.get("smtp_port", 587))
        if settings.get("smtp_tls") == "1":
            server = smtplib.SMTP(settings["smtp_host"], port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP(settings["smtp_host"], port, timeout=10)

        if settings.get("smtp_user"):
            server.login(settings["smtp_user"], settings["smtp_password"])
        server.send_message(msg)
        server.quit()
        print(f"Email envoyé à {email_to}")
    except Exception as e:
        print(f"Erreur envoi email: {e}")
        if raise_on_error:
            raise


# --- Conexteo SMS sending ---

CONEXTEO_API_BASE = "https://api.conexteo.com"
CONEXTEO_SMS_ENDPOINT = "/messages/sms"


def _normalize_phone(phone: str) -> str:
    """Best-effort normalization to E.164. Accepts '+33...', '0033...', '06...' (assumed FR).
    Conexteo accepts both national (0606...) and international (+33606...) — we normalize
    to international for consistency and to avoid ambiguity with non-FR numbers."""
    import re
    if not phone:
        return ""
    raw = re.sub(r"[\s.\-()]", "", phone.strip())
    if raw.startswith("+"):
        return raw
    if raw.startswith("00"):
        return "+" + raw[2:]
    if raw.startswith("0") and len(raw) == 10:
        # French national format -> +33
        return "+33" + raw[1:]
    if raw.isdigit():
        return "+" + raw
    return raw


def send_sms(settings: dict, contact: dict, civilite: str,
             visitor_name: str = "", visitor_email: str = "",
             raise_on_error: bool = False):
    """Send notification SMS via the Conexteo HTTP API.

    Endpoint : POST https://api.conexteo.com/messages/sms
    Auth     : X-APP-ID + X-API-KEY headers (both set to the API key value)
    Body     : {"recipients": ["+33..."], "content": "...", "sender": "<alias>",
                "external_id": "<uuid>"}
    Success  : HTTP 2xx. HTTP 409 means the message was already submitted with
               the same external_id and is treated as success.
    """
    if settings.get("sms_enabled") != "1":
        if raise_on_error:
            raise ValueError("SMS desactive dans les parametres")
        return

    phone = _normalize_phone(contact.get("telephone", ""))
    if not phone:
        if raise_on_error:
            raise ValueError("Pas de numero de telephone pour ce contact")
        return

    api_key = settings.get("conexteo_api_key", "").strip()
    if not api_key:
        err = "Cle API Conexteo manquante"
        if raise_on_error:
            raise ValueError(err)
        print(f"Erreur SMS: {err}")
        return

    try:
        import requests
        import uuid as _uuid

        tpl_vars = dict(
            civilite=civilite, prenom=contact["prenom"],
            nom=contact["nom"], entreprise=settings.get("entreprise_nom", ""),
            visiteur_nom=visitor_name or "Non renseigne",
            visiteur_email=visitor_email or "Non renseigne",
        )
        body = settings["sms_body"].format(**tpl_vars).strip()
        # SMS hard limit: 1530 chars (10 concatenated parts) — well above realistic announce text.
        body = body[:1530]

        payload = {
            "recipients": [phone],
            "content": body,
            # Idempotency key — Conexteo replies 409 if a request with the same
            # external_id was already accepted (treated as success below).
            "external_id": f"avspeak-{_uuid.uuid4()}",
        }
        sender = settings.get("conexteo_sender", "").strip()
        if sender:
            payload["sender"] = sender[:11]  # TPOA alphanumeric limit

        headers = {
            "X-APP-ID": api_key,
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        url = CONEXTEO_API_BASE + CONEXTEO_SMS_ENDPOINT
        resp = requests.post(url, headers=headers, json=payload, timeout=15)

        if resp.status_code == 409:
            # Treated as success: the message was already submitted.
            print(f"SMS deja envoye (dedup external_id) a {phone}")
            return

        if resp.status_code >= 400:
            try:
                err_json = resp.json()
            except Exception:
                err_json = {"raw": resp.text[:300]}
            err = f"HTTP {resp.status_code} : {err_json}"
            print(f"Erreur SMS Conexteo: {err}")
            if raise_on_error:
                raise ValueError(err)
            return

        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text[:300]}
        print(f"SMS envoye a {phone} — reponse Conexteo: {data}")
    except Exception as e:
        print(f"Erreur envoi SMS: {e}")
        if raise_on_error:
            raise


# --- Evacuation alert ---

import time as _time

EVAC_CODE_REGEX = "^[0-9]{6}$"
# Server-side pepper combined with the PIN before bcrypt. Defends offline brute-force
# of a stolen database — the attacker would need the source code too.
EVAC_PEPPER = b"f3a91c2b8e7d6549a0b4c2d8e1f9a7b3c5d6e8f0a2b4c6d8e0f1a3b5c7d9e2f4"
EVAC_TRIGGER_COOLDOWN_S = 60
EVAC_FAIL_WINDOW_S = 900
EVAC_FAIL_MAX_PER_IP = 5
EVAC_FAIL_MAX_GLOBAL = 30
EVAC_LOG_RETENTION_DAYS = 90
SESSION_TTL_S = 8 * 3600

# Keys that must never be exposed by the public /api/settings endpoint.
SENSITIVE_SETTING_KEYS = {
    "smtp_password", "smtp_user", "smtp_host", "smtp_port", "smtp_from",
    "conexteo_api_key", "conexteo_sender",
    "evac_code_hash", "evac_recipients", "email_subject", "email_body",
    "sms_body", "evac_subject", "evac_body_header",
}

# In-memory rate-limit state for /api/evac/trigger.
_evac_fail_log: dict[str, list[float]] = {}
_evac_last_success_ts: float = 0.0
_evac_global_fails: list[float] = []
_evac_state_lock = threading.Lock()
_evac_dummy_hash_cache: str | None = None
# Per-IP soft burst-limit for /api/visitors/present: list of recent timestamps.
_visitors_last_call: dict[str, list[float]] = {}
_visitors_lock = threading.Lock()


def _peppered(code: str) -> bytes:
    """HMAC-SHA256 the PIN with the server pepper before bcrypt — defense in depth."""
    return hmac.new(EVAC_PEPPER, code.encode("utf-8"), hashlib.sha256).digest()


def _evac_dummy_hash() -> str:
    """Pre-computed bcrypt hash for constant-time-ish dummy comparisons."""
    global _evac_dummy_hash_cache
    if _evac_dummy_hash_cache is None:
        _evac_dummy_hash_cache = _bcrypt.hashpw(
            _peppered("000000"), _bcrypt.gensalt(rounds=12)
        ).decode("ascii")
    return _evac_dummy_hash_cache


def hash_evac_code(code: str) -> str:
    return _bcrypt.hashpw(_peppered(code), _bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_evac_code(code: str, stored_hash: str) -> bool:
    """Always performs a bcrypt operation to avoid timing oracle on disabled / no-code states."""
    if not code:
        # Still run a dummy check to equalize timing.
        try:
            _bcrypt.checkpw(_peppered("000000"), _evac_dummy_hash().encode("ascii"))
        except Exception:
            pass
        return False
    target = stored_hash or _evac_dummy_hash()
    try:
        ok = _bcrypt.checkpw(_peppered(code), target.encode("ascii"))
    except (ValueError, TypeError):
        ok = False
    # If we ran against the dummy, force False regardless of result (paranoid).
    if not stored_hash:
        return False
    return ok


def _safe_subject_format(tpl: str, entreprise: str, date_str: str) -> str:
    """Whitelist-only placeholder substitution — avoids str.format SSTI / attribute traversal."""
    out = (tpl or "").replace("{entreprise}", entreprise).replace("{date}", date_str)
    return out


def _strip_header_value(s: str) -> str:
    """Remove CR/LF/NUL to defeat SMTP/email header injection."""
    if not s:
        return ""
    return "".join(c for c in s if c not in ("\r", "\n", "\x00"))[:998]


def _smtp_host_safe(host: str) -> bool:
    """Block obvious SSRF targets via configurable SMTP host (loopback, metadata services)."""
    import ipaddress
    h = (host or "").strip().lower()
    if not h or len(h) > 253:
        return False
    blocked_names = {"localhost", "ip6-localhost", "ip6-loopback",
                     "metadata.google.internal", "metadata.azure.com"}
    if h in blocked_names:
        return False
    try:
        ip = ipaddress.ip_address(h)
        if (ip.is_loopback or ip.is_link_local or ip.is_unspecified or
                ip.is_multicast or ip.is_reserved):
            return False
    except ValueError:
        pass  # Hostname — allow (LAN deployments may legitimately use private SMTP relays)
    return True


def _client_ip(request: Request) -> str:
    # Direct connection IP. We deliberately ignore X-Forwarded-For (no trusted proxy in this app).
    return (request.client.host if request and request.client else "?") or "?"


def _evac_rate_limit_check(ip: str) -> tuple[bool, str]:
    """Returns (allowed, error_message)."""
    now = _time.monotonic()
    with _evac_state_lock:
        # Trim global fail log
        cutoff = now - EVAC_FAIL_WINDOW_S
        _evac_global_fails[:] = [t for t in _evac_global_fails if t >= cutoff]
        if len(_evac_global_fails) >= EVAC_FAIL_MAX_GLOBAL:
            return False, "Trop de tentatives, reessayez plus tard"
        # Per-IP
        recent = [t for t in _evac_fail_log.get(ip, []) if t >= cutoff]
        _evac_fail_log[ip] = recent
        if len(recent) >= EVAC_FAIL_MAX_PER_IP:
            return False, "Trop de tentatives, reessayez plus tard"
        # Global cooldown after a successful trigger
        global _evac_last_success_ts
        if _evac_last_success_ts and (now - _evac_last_success_ts) < EVAC_TRIGGER_COOLDOWN_S:
            wait = int(EVAC_TRIGGER_COOLDOWN_S - (now - _evac_last_success_ts))
            return False, f"Patientez {wait}s avant un nouveau declenchement"
    return True, ""


def _evac_record_fail(ip: str):
    now = _time.monotonic()
    with _evac_state_lock:
        _evac_fail_log.setdefault(ip, []).append(now)
        _evac_global_fails.append(now)


def _evac_record_success():
    global _evac_last_success_ts
    with _evac_state_lock:
        _evac_last_success_ts = _time.monotonic()


def parse_recipients(raw: str) -> list[str]:
    """Parse a recipients string (comma/newline separated) into a deduped list of valid-looking emails."""
    import re
    if not raw:
        return []
    tokens = [t.strip() for t in re.split(r"[,;\n\r]+", raw) if t.strip()]
    seen = set()
    out = []
    email_re = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
    for t in tokens:
        if len(t) > 254:
            continue
        if not email_re.match(t):
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
    return out


def send_evac_email(settings: dict, recipients: list[str], visitors: list[dict]) -> tuple[bool, str]:
    """Send the evacuation list email. Returns (success, error_message)."""
    if settings.get("smtp_enabled") != "1":
        return False, "SMTP desactive dans les parametres"
    if not recipients:
        return False, "Aucun destinataire configure"
    if not settings.get("smtp_host") or not settings.get("smtp_from"):
        return False, "Configuration SMTP incomplete"
    if not _smtp_host_safe(settings.get("smtp_host", "")):
        return False, "Hote SMTP refuse (loopback/metadata interdit)"

    try:
        now = datetime.now()
        date_str = now.strftime("%d/%m/%Y a %H:%M")
        entreprise = _strip_header_value(settings.get("entreprise_nom", ""))
        subject_tpl = settings.get("evac_subject",
            "[ALERTE EVACUATION] Liste des visiteurs presents - {entreprise}")
        subject = _strip_header_value(_safe_subject_format(subject_tpl, entreprise, date_str)).strip()
        if not subject:
            subject = f"[ALERTE EVACUATION] Liste des visiteurs presents - {entreprise}"

        header = (settings.get("evac_body_header", "") or "").strip()
        lines = [
            f"ALERTE EVACUATION - {entreprise}",
            f"Declenchee le {date_str}",
            "",
        ]
        if header:
            lines.append(header)
            lines.append("")
        lines.append(f"Nombre de visiteurs presents : {len(visitors)}")
        lines.append("")
        if visitors:
            for i, v in enumerate(visitors, 1):
                lines.append(f"{i}. {v.get('prenom','')} {v.get('nom','')}".rstrip())
                if v.get("entreprise"):
                    lines.append(f"   Entreprise : {v['entreprise']}")
                contact_full = f"{v.get('contact_prenom') or ''} {v.get('contact_nom') or ''}".strip()
                if contact_full:
                    lines.append(f"   RDV avec : {contact_full}")
                arrived = v.get("arrived_at", "")
                if arrived:
                    arrived_hm = arrived[11:16] if len(arrived) >= 16 else arrived
                    lines.append(f"   Arrive a : {arrived_hm}")
                lines.append("")
        else:
            lines.append("Aucun visiteur enregistre au moment du declenchement.")
            lines.append("")
        lines.append("---")
        lines.append(f"Message envoye automatiquement par AV-Speak ({entreprise}).")
        body = "\n".join(lines)

        msg = MIMEMultipart()
        msg["From"] = _strip_header_value(settings["smtp_from"])
        # Recipients in the envelope (sendmail) only; To header set to From so addresses
        # are not disclosed between recipients (Bcc-like behaviour).
        msg["To"] = _strip_header_value(settings["smtp_from"])
        msg["Subject"] = subject
        msg["Auto-Submitted"] = "auto-generated"
        msg["X-Priority"] = "1"
        msg.attach(MIMEText(body, "plain", "utf-8"))

        port = int(settings.get("smtp_port", 587))
        if settings.get("smtp_tls") == "1":
            server = smtplib.SMTP(settings["smtp_host"], port, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP(settings["smtp_host"], port, timeout=15)
        if settings.get("smtp_user"):
            server.login(settings["smtp_user"], settings["smtp_password"])
        server.sendmail(settings["smtp_from"], recipients, msg.as_string())
        server.quit()
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def send_notifications(settings: dict, contact: dict, civilite: str,
                       visitor_name: str = "", visitor_email: str = ""):
    """Send email and SMS in background threads."""
    if settings.get("notif_on_announce") != "1":
        return
    contact_dict = dict(contact)
    threading.Thread(target=send_email, args=(settings, contact_dict, civilite, visitor_name, visitor_email)).start()
    threading.Thread(target=send_sms, args=(settings, contact_dict, civilite, visitor_name, visitor_email)).start()


# --- Routes: Kiosk (Frontend tactile) ---

@app.get("/", response_class=HTMLResponse)
async def kiosk(request: Request):
    conn = get_db()
    settings = get_settings(conn)
    top_contacts = conn.execute(
        "SELECT * FROM contacts ORDER BY call_count DESC LIMIT 6"
    ).fetchall()
    license_status = get_license_status(conn)
    conn.close()
    return templates.TemplateResponse("kiosk.html", {
        "request": request,
        "settings": settings,
        "top_contacts": top_contacts,
        "license_status": license_status,
    })


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    # Strict allowlist: only md5-hex .wav filenames produced by our TTS cache.
    import re
    if not re.fullmatch(r"[a-f0-9]{32}\.wav", filename):
        raise HTTPException(status_code=404)
    cache_root = TTS_CACHE_DIR.resolve()
    try:
        filepath = (cache_root / filename).resolve()
    except (OSError, ValueError):
        raise HTTPException(status_code=404)
    # Defense-in-depth: ensure the resolved path is still inside the cache directory.
    try:
        filepath.relative_to(cache_root)
    except ValueError:
        raise HTTPException(status_code=404)
    if not filepath.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(str(filepath), media_type="audio/wav")


@app.get("/api/contacts/search")
async def search_contacts(q: str = ""):
    if not q or len(q) < 1:
        return []
    conn = get_db()
    contacts = conn.execute(
        "SELECT * FROM contacts WHERE nom LIKE ? OR prenom LIKE ? ORDER BY nom, prenom LIMIT 20",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    conn.close()
    return [dict(c) for c in contacts]


@app.get("/api/contacts/top")
async def top_contacts():
    conn = get_db()
    contacts = conn.execute(
        "SELECT * FROM contacts ORDER BY call_count DESC LIMIT 6"
    ).fetchall()
    conn.close()
    return [dict(c) for c in contacts]


@app.post("/api/announce/{contact_id}")
async def announce(contact_id: int, visitor_name: str = "", visitor_email: str = "",
                   visitor_prenom: str = "", visitor_entreprise: str = ""):
    conn = get_db()
    # License check
    lic = get_license_status(conn)
    if lic["expired"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Licence expirée")
    contact = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    if not contact:
        conn.close()
        raise HTTPException(status_code=404, detail="Contact non trouvé")

    conn.execute("UPDATE contacts SET call_count = call_count + 1 WHERE id = ?", (contact_id,))

    settings = get_settings(conn)

    # Security register: create visitor entry
    visitor_id = None
    if settings.get("security_register_enabled") == "1" and visitor_name.strip():
        from datetime import datetime
        cursor = conn.execute(
            "INSERT INTO visitors (nom, prenom, entreprise, contact_id, arrived_at) VALUES (?, ?, ?, ?, ?)",
            (visitor_name.strip(), visitor_prenom.strip(), visitor_entreprise.strip(),
             contact_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        visitor_id = cursor.lastrowid

    conn.commit()
    conn.close()

    civilite_map = {"M": "Monsieur", "Mme": "Madame", "X": ""}
    civilite = civilite_map.get(contact["civilite"], "")

    phrase_template = settings.get("phrase_accueil", "{civilite} {prenom} {nom} est demande a l'accueil")
    texte = phrase_template.format(
        civilite=civilite,
        prenom=contact["prenom"],
        nom=contact["nom"],
    ).strip()
    # Clean up double spaces if civilite is empty
    while "  " in texte:
        texte = texte.replace("  ", " ")

    audio_file = generate_tts(texte)

    send_notifications(settings, contact, civilite, visitor_name.strip(), visitor_email.strip())

    return {
        "status": "ok",
        "message": texte,
        "audio_url": f"/audio/{audio_file}" if audio_file else None,
        "repeat_count": int(settings.get("repeat_count", "1")),
        "repeat_delay": int(settings.get("repeat_delay", "20")),
        "visitor_id": visitor_id,
    }


def _same_origin_request(request: Request) -> bool:
    """Block off-origin polling/recon: require a Referer/Origin pointing at our own host."""
    host = (request.headers.get("host") or "").lower()
    if not host:
        return False
    ref = (request.headers.get("referer") or request.headers.get("origin") or "").lower()
    if not ref:
        return False
    # ref starts with scheme://host[:port]/...
    try:
        ref_host = ref.split("://", 1)[1].split("/", 1)[0]
    except IndexError:
        return False
    return ref_host == host


@app.get("/api/visitors/present")
async def visitors_present(request: Request):
    """Return list of currently present visitors. Restricted to same-origin to
    prevent off-kiosk recon (the kiosk page itself sends a same-origin Referer).
    No hard throttle: it collided with legitimate page refreshes; same-origin
    is the actual access-control gate."""
    if not _same_origin_request(request):
        raise HTTPException(status_code=403, detail="Origine non autorisee")
    # Soft rate-limit: only block obvious bursts (>10 calls in 10s per IP).
    ip = _client_ip(request)
    now = _time.monotonic()
    with _visitors_lock:
        log = _visitors_last_call.get(ip, [])
        if not isinstance(log, list):
            log = []  # migrate from previous (timestamp-float) shape if any
        log = [t for t in log if now - t < 10.0]
        if len(log) >= 10:
            raise HTTPException(status_code=429, detail="Trop de requetes")
        log.append(now)
        _visitors_last_call[ip] = log
        # Opportunistic cleanup
        if len(_visitors_last_call) > 200:
            stale = [k for k, v in _visitors_last_call.items()
                     if not v or (isinstance(v, list) and (not v or now - v[-1] > 60))]
            for k in stale:
                _visitors_last_call.pop(k, None)
    conn = get_db()
    visitors = conn.execute(
        """SELECT v.id, v.nom, v.prenom, v.entreprise, v.arrived_at,
                  c.prenom AS contact_prenom, c.nom AS contact_nom
           FROM visitors v LEFT JOIN contacts c ON v.contact_id = c.id
           WHERE v.left_at IS NULL ORDER BY v.arrived_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(v) for v in visitors]


@app.post("/api/visitors/{visitor_id}/leave")
async def visitor_leave(visitor_id: int):
    """Mark a visitor as departed."""
    from datetime import datetime
    conn = get_db()
    visitor = conn.execute("SELECT * FROM visitors WHERE id = ? AND left_at IS NULL", (visitor_id,)).fetchone()
    if not visitor:
        conn.close()
        raise HTTPException(status_code=404, detail="Visiteur non trouvé")
    conn.execute("UPDATE visitors SET left_at = ? WHERE id = ?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), visitor_id))
    settings = get_settings(conn)
    # If history disabled, delete the record
    if settings.get("security_register_history") != "1":
        conn.execute("DELETE FROM visitors WHERE id = ?", (visitor_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/api/license")
async def api_license_status():
    """Public endpoint - returns license status for kiosk display."""
    conn = get_db()
    status = get_license_status(conn)
    conn.close()
    return status


@app.get("/api/settings")
async def api_get_settings():
    conn = get_db()
    settings = get_settings(conn)
    conn.close()
    # Strip secrets and config-only values before exposing publicly.
    return {k: v for k, v in settings.items() if k not in SENSITIVE_SETTING_KEYS}


class EvacTriggerRequest(BaseModel):
    code: str


def _log_evac(conn, success: int, recipients_str: str, visitors_count: int,
              error: str, source_ip: str, user_agent: str):
    from datetime import datetime
    conn.execute(
        """INSERT INTO evac_log
           (triggered_at, success, recipients, visitors_count, error, source_ip, user_agent)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         success, recipients_str, visitors_count,
         (error or "")[:300], source_ip[:64], (user_agent or "")[:200]),
    )
    # Auto-purge rows older than retention window.
    conn.execute(
        "DELETE FROM evac_log WHERE triggered_at < datetime('now', ?)",
        (f"-{EVAC_LOG_RETENTION_DAYS} days",),
    )


@app.post("/api/evac/trigger")
async def api_evac_trigger(request: Request, payload: EvacTriggerRequest):
    """Public endpoint: triggers the evacuation email when the 6-digit code is correct."""
    import re
    ip = _client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:200]
    GENERIC_ERR = "Code incorrect ou fonction indisponible"

    code = (payload.code or "").strip()

    # 1. Rate-limit before any crypto / DB work (also defeats lockout/timing recon).
    allowed, lockout_msg = _evac_rate_limit_check(ip)
    if not allowed:
        return JSONResponse({"ok": False, "error": lockout_msg}, status_code=429)

    # 2. Strict format check. Run a dummy bcrypt to equalize timing with the real path.
    if not re.match(EVAC_CODE_REGEX, code):
        verify_evac_code("000000", "")  # constant-time dummy
        _evac_record_fail(ip)
        return JSONResponse({"ok": False, "error": GENERIC_ERR}, status_code=400)

    conn = get_db()
    settings = get_settings(conn)
    enabled = settings.get("evac_enabled") == "1"
    stored = settings.get("evac_code_hash", "")

    # Always perform a bcrypt check (against dummy if disabled or no code) to
    # avoid a timing oracle that reveals system state to an unauthenticated caller.
    code_ok = verify_evac_code(code, stored)

    if not enabled or not stored or not code_ok:
        _log_evac(conn, 0, "", 0,
                  "Code incorrect" if (enabled and stored) else
                  ("Fonction desactivee" if not enabled else "Pas de code defini"),
                  ip, ua)
        conn.commit()
        conn.close()
        _evac_record_fail(ip)
        return JSONResponse({"ok": False, "error": GENERIC_ERR}, status_code=401)

    # 3. Send.
    recipients = parse_recipients(settings.get("evac_recipients", ""))
    visitors_rows = conn.execute(
        """SELECT v.id, v.nom, v.prenom, v.entreprise, v.arrived_at,
                  c.prenom AS contact_prenom, c.nom AS contact_nom
           FROM visitors v LEFT JOIN contacts c ON v.contact_id = c.id
           WHERE v.left_at IS NULL ORDER BY v.arrived_at ASC"""
    ).fetchall()
    visitors = [dict(v) for v in visitors_rows]
    success, err = send_evac_email(settings, recipients, visitors)

    _log_evac(conn,
              1 if success else 0,
              ", ".join(recipients),
              len(visitors),
              "" if success else err,
              ip, ua)
    conn.commit()
    conn.close()

    if not success:
        # Do NOT expose SMTP error details to the public caller.
        return JSONResponse(
            {"ok": False, "error": "Envoi indisponible (voir journal admin)"},
            status_code=500,
        )

    _evac_record_success()
    return {"ok": True, "sent_to": len(recipients), "visitors_count": len(visitors)}


# --- Routes: Admin ---

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    conn = get_db()
    settings = get_settings(conn)
    conn.close()
    return templates.TemplateResponse("login.html", {"request": request, "settings": settings, "error": None})


@app.post("/admin/login")
async def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_db()
    settings = get_settings(conn)
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not user or not _bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return templates.TemplateResponse("login.html", {
            "request": request, "settings": settings, "error": "Identifiants incorrects"
        })
    session_id = secrets.token_hex(32)
    now = _time.monotonic()
    with _sessions_lock:
        sessions[session_id] = {
            "username": username,
            "cgu_accepted": False,
            "must_change_password": bool(user["must_change_password"]) if "must_change_password" in user.keys() else False,
            "created_at": now,
            "last_used": now,
        }
    response = RedirectResponse(url="/admin/cgu", status_code=303)
    response.set_cookie(
        "session_id", session_id,
        httponly=True,
        samesite="strict",
        secure=_COOKIE_SECURE,
        max_age=SESSION_TTL_S,
    )
    return response


@app.get("/admin/logout")
async def admin_logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id:
        with _sessions_lock:
            sessions.pop(session_id, None)
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("session_id")
    return response


CGU_TEXT = """
<h2>Conditions G&eacute;n&eacute;rales d'Utilisation — AV-Speak</h2>
<p><em>Derni&egrave;re mise &agrave; jour : avril 2026</em></p>

<h3>1. Objet</h3>
<p>AV-Speak est un syst&egrave;me d'annonce de visiteurs destin&eacute; &agrave; faciliter l'accueil au sein d'un
&eacute;tablissement. Le logiciel est fourni <strong>en l'&eacute;tat</strong>, sans garantie d'aucune sorte.</p>

<h3>2. Responsabilit&eacute; du client</h3>
<p>Le client (personne physique ou morale utilisant le logiciel) est <strong>seul responsable</strong> :</p>
<ul>
    <li>De la <strong>collecte, du stockage et de la conservation</strong> des donn&eacute;es personnelles
        saisies dans le syst&egrave;me (noms, pr&eacute;noms, emails, num&eacute;ros de t&eacute;l&eacute;phone, donn&eacute;es visiteurs).</li>
    <li>Du <strong>respect de la r&eacute;glementation</strong> applicable en mati&egrave;re de protection des donn&eacute;es
        personnelles (notamment le RGPD en Europe) : d&eacute;clarations, consentements, dur&eacute;es de conservation,
        droits des personnes concern&eacute;es.</li>
    <li>De la <strong>sauvegarde</strong> r&eacute;guli&egrave;re de la base de donn&eacute;es et de la s&eacute;curit&eacute; d'acc&egrave;s au syst&egrave;me.</li>
    <li>De la configuration et de la maintenance du mat&eacute;riel et du r&eacute;seau sur lequel le logiciel est d&eacute;ploy&eacute;.</li>
</ul>

<h3>3. Registre de s&eacute;curit&eacute;</h3>
<p>La fonctionnalit&eacute; &laquo; Registre de s&eacute;curit&eacute; &raquo; propos&eacute;e par AV-Speak est un <strong>outil
d'aide au suivi des visiteurs</strong>. Elle <strong>ne constitue en aucun cas un registre de s&eacute;curit&eacute;
conforme</strong> aux normes r&eacute;glementaires en vigueur (Code du travail, r&egrave;glements ERP, normes de s&ucirc;ret&eacute;, etc.).</p>
<p>Le client ne peut en aucun cas se pr&eacute;valoir de l'utilisation de cette fonctionnalit&eacute; pour
justifier de sa conformit&eacute; aux obligations l&eacute;gales en mati&egrave;re de s&eacute;curit&eacute; et de s&ucirc;ret&eacute;.</p>

<h3>3-bis. Fonction d'alerte &eacute;vacuation</h3>
<p>La fonctionnalit&eacute; &laquo; Alerte &eacute;vacuation &raquo; permet, sur saisie d'un code &agrave; 6 chiffres,
l'envoi automatique par email de la liste des visiteurs alors enregistr&eacute;s comme pr&eacute;sents.
Cette fonctionnalit&eacute; est un <strong>outil de communication d'appoint</strong> et
<strong>ne se substitue &agrave; aucun dispositif r&eacute;glementaire</strong> (PPMS, SSI, registre de
s&eacute;curit&eacute;, consignes ERP, exercices d'&eacute;vacuation, etc.).</p>
<p>Son fonctionnement d&eacute;pend enti&egrave;rement de l'infrastructure du client :
disponibilit&eacute; du r&eacute;seau et de l'alimentation &eacute;lectrique du poste, accessibilit&eacute;
du serveur SMTP configur&eacute;, validit&eacute; des identifiants, capacit&eacute; des destinataires
&agrave; recevoir et traiter le message. <strong>L'&eacute;diteur ne garantit pas la
disponibilit&eacute; de cette fonction au moment d'un incident</strong>.</p>
<p>Le client s'engage &agrave; :</p>
<ul>
    <li>tester mensuellement l'envoi (bouton de test int&eacute;gr&eacute;) ;</li>
    <li>informer les visiteurs que leurs donn&eacute;es peuvent &ecirc;tre transmises aux destinataires d&eacute;sign&eacute;s en cas d'incident ;</li>
    <li>configurer des destinataires de confiance, internes de pr&eacute;f&eacute;rence ;</li>
    <li>renouveler r&eacute;guli&egrave;rement le code d'acc&egrave;s ;</li>
    <li>ne pas pr&eacute;senter cette fonction comme un dispositif r&eacute;glementaire aupr&egrave;s de tiers
        (commissions de s&eacute;curit&eacute;, assureurs, autorit&eacute;s).</li>
</ul>

<h3>4. Limitation de responsabilit&eacute;</h3>
<p>L'&eacute;diteur du logiciel ne pourra &ecirc;tre tenu responsable :</p>
<ul>
    <li>De toute <strong>perte, alt&eacute;ration ou fuite de donn&eacute;es</strong> quelle qu'en soit la cause.</li>
    <li>De tout <strong>dommage direct ou indirect</strong> r&eacute;sultant de l'utilisation ou de l'impossibilit&eacute;
        d'utiliser le logiciel.</li>
    <li>Du <strong>non-respect par le client</strong> de ses obligations l&eacute;gales et r&eacute;glementaires.</li>
</ul>

<h3>5. Donn&eacute;es personnelles</h3>
<p>Les donn&eacute;es sont stock&eacute;es <strong>localement</strong> sur le poste du client (base SQLite). Aucune donn&eacute;e
n'est transmise &agrave; l'&eacute;diteur. Le client est le <strong>responsable de traitement</strong> au sens du RGPD
et doit mettre en &oelig;uvre les mesures techniques et organisationnelles appropri&eacute;es.</p>

<h3>6. Acceptation</h3>
<p>L'utilisation du logiciel implique l'acceptation pleine et enti&egrave;re des pr&eacute;sentes conditions.
&Agrave; chaque connexion &agrave; l'interface d'administration, l'utilisateur devra confirmer avoir pris
connaissance de ces conditions.</p>
"""


@app.get("/admin/cgu", response_class=HTMLResponse)
async def admin_cgu_page(request: Request):
    session_id = request.cookies.get("session_id")
    with _sessions_lock:
        if not session_id or session_id not in sessions:
            return RedirectResponse(url="/admin/login", status_code=303)
    conn = get_db()
    settings = get_settings(conn)
    conn.close()
    return templates.TemplateResponse("cgu.html", {
        "request": request, "settings": settings, "cgu_text": CGU_TEXT,
    })


@app.post("/admin/cgu/accept")
async def admin_cgu_accept(request: Request):
    session_id = request.cookies.get("session_id")
    with _sessions_lock:
        if not session_id or session_id not in sessions:
            return RedirectResponse(url="/admin/login", status_code=303)
        sessions[session_id]["cgu_accepted"] = True
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, evac_error: str = ""):
    username = require_auth(request)
    conn = get_db()
    settings = get_settings(conn)
    contacts = conn.execute("SELECT * FROM contacts ORDER BY nom, prenom").fetchall()
    visitors_present = conn.execute(
        """SELECT v.id, v.nom, v.prenom, v.entreprise, v.arrived_at,
                  c.prenom AS contact_prenom, c.nom AS contact_nom
           FROM visitors v LEFT JOIN contacts c ON v.contact_id = c.id
           WHERE v.left_at IS NULL ORDER BY v.arrived_at DESC"""
    ).fetchall()
    visitors_history = conn.execute(
        """SELECT v.id, v.nom, v.prenom, v.entreprise, v.arrived_at, v.left_at,
                  c.prenom AS contact_prenom, c.nom AS contact_nom
           FROM visitors v LEFT JOIN contacts c ON v.contact_id = c.id
           WHERE v.left_at IS NOT NULL ORDER BY v.left_at DESC LIMIT 100"""
    ).fetchall()
    license_status = get_license_status(conn)
    evac_log = conn.execute(
        """SELECT triggered_at, success, recipients, visitors_count, error, source_ip, user_agent
           FROM evac_log ORDER BY id DESC LIMIT 20"""
    ).fetchall()
    fresh_settings = get_settings(conn)
    evac_code_set = bool(fresh_settings.get("evac_code_hash"))
    user_row = conn.execute(
        "SELECT must_change_password FROM users WHERE username = ?", (username,)
    ).fetchone()
    must_change_pw = bool(user_row and user_row["must_change_password"])
    smtp_ready = (fresh_settings.get("smtp_enabled") == "1"
                  and bool(fresh_settings.get("smtp_host"))
                  and bool(fresh_settings.get("smtp_from")))
    conn.close()
    # Filter sensitive values out of the dict passed to the template — any future
    # rendering bug (e.g. dumping settings) shouldn't leak credentials.
    safe_settings = {k: v for k, v in settings.items() if k not in SENSITIVE_SETTING_KEYS}
    # Re-inject only the non-secret fields needed by the admin UI (passwords stay out).
    for k in ("smtp_enabled", "smtp_host", "smtp_port", "smtp_user", "smtp_from",
              "smtp_tls", "email_subject", "email_body",
              "conexteo_sender",
              "sms_body", "evac_subject", "evac_body_header", "evac_recipients"):
        if k in settings:
            safe_settings[k] = settings[k]
    # smtp_password / conexteo_api_key / evac_code_hash stay hidden.
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "settings": safe_settings,
        "contacts": contacts,
        "visitors_present": visitors_present,
        "visitors_history": visitors_history,
        "cgu_text": CGU_TEXT,
        "license_status": license_status,
        "evac_log": evac_log,
        "evac_code_set": evac_code_set,
        "must_change_pw": must_change_pw,
        "smtp_ready": smtp_ready,
        "username": username,
        "evac_error": evac_error[:500] if evac_error else "",
    })


@app.post("/admin/contacts/add")
async def admin_add_contact(
    request: Request,
    nom: str = Form(...),
    prenom: str = Form(...),
    civilite: str = Form("X"),
    email: str = Form(""),
    telephone: str = Form(""),
):
    require_auth(request)
    conn = get_db()
    conn.execute(
        "INSERT INTO contacts (nom, prenom, civilite, email, telephone) VALUES (?, ?, ?, ?, ?)",
        (nom.strip(), prenom.strip(), civilite.strip(), email.strip(), telephone.strip()),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/contacts/edit/{contact_id}")
async def admin_edit_contact(
    request: Request,
    contact_id: int,
    nom: str = Form(...),
    prenom: str = Form(...),
    civilite: str = Form("X"),
    email: str = Form(""),
    telephone: str = Form(""),
):
    require_auth(request)
    conn = get_db()
    conn.execute(
        "UPDATE contacts SET nom=?, prenom=?, civilite=?, email=?, telephone=? WHERE id=?",
        (nom.strip(), prenom.strip(), civilite.strip(), email.strip(), telephone.strip(), contact_id),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/contacts/delete/{contact_id}")
async def admin_delete_contact(request: Request, contact_id: int):
    require_auth(request)
    conn = get_db()
    conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


_SECRET_SETTING_FIELDS = {"smtp_password", "conexteo_api_key"}


@app.post("/admin/settings")
async def admin_update_settings(request: Request):
    require_auth(request)
    form = await request.form()
    conn = get_db()
    for key in ("color_primary", "color_secondary", "color_background", "color_text",
                "color_button", "color_button_text", "entreprise_nom", "phrase_accueil",
                "smtp_enabled", "smtp_host", "smtp_port", "smtp_user", "smtp_password",
                "smtp_from", "smtp_tls", "email_subject", "email_body",
                "sms_enabled", "conexteo_api_key", "conexteo_sender", "sms_body",
                "notif_on_announce",
                "repeat_count", "repeat_delay",
                "contact_fields_enabled", "kiosk_instruction", "keyboard_size", "kiosk_font_size",
                "security_register_enabled", "security_register_history"):
        value = form.get(key)
        if value is None:
            continue
        cleaned = value.strip()
        # Never overwrite a stored secret with an empty value (form fields are not pre-filled).
        if key in _SECRET_SETTING_FIELDS and cleaned == "":
            continue
        # Lightweight validation on color fields (defense vs CSS injection).
        if key.startswith("color_"):
            import re
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", cleaned):
                continue
        # Strip CR/LF from any field that ends up in email headers.
        if key in ("smtp_from", "smtp_user", "email_subject", "conexteo_sender", "entreprise_nom"):
            cleaned = _strip_header_value(cleaned)
        conn.execute("UPDATE settings SET value = ? WHERE key = ?", (cleaned, key))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/logo")
async def admin_upload_logo(request: Request):
    require_auth(request)
    form = await request.form()
    file = form.get("logo_file")
    if not file or not file.filename:
        return RedirectResponse(url="/admin", status_code=303)

    ext = Path(file.filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
        raise HTTPException(status_code=400, detail="Format non supporte (png, jpg, svg, webp)")

    content = await file.read()
    logo_path = BASE_DIR / "static" / f"logo{ext}"
    # Remove old logos
    for old in (BASE_DIR / "static").glob("logo.*"):
        old.unlink()
    logo_path.write_bytes(content)

    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                 ("logo_url", f"/static/logo{ext}"))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/logo/delete")
async def admin_delete_logo(request: Request):
    require_auth(request)
    for old in (BASE_DIR / "static").glob("logo.*"):
        old.unlink()
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                 ("logo_url", ""))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/kiosk-image")
async def admin_upload_kiosk_image(request: Request):
    require_auth(request)
    form = await request.form()
    file = form.get("kiosk_image_file")
    if not file or not file.filename:
        return RedirectResponse(url="/admin", status_code=303)

    ext = Path(file.filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"):
        raise HTTPException(status_code=400, detail="Format non supporte (png, jpg, svg, webp, gif)")

    content = await file.read()
    img_path = BASE_DIR / "static" / f"kiosk_instruction{ext}"
    for old in (BASE_DIR / "static").glob("kiosk_instruction.*"):
        old.unlink()
    img_path.write_bytes(content)

    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                 ("kiosk_image_url", f"/static/kiosk_instruction{ext}"))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/kiosk-image/delete")
async def admin_delete_kiosk_image(request: Request):
    require_auth(request)
    for old in (BASE_DIR / "static").glob("kiosk_instruction.*"):
        old.unlink()
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                 ("kiosk_image_url", ""))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/admin/password", response_class=HTMLResponse)
async def admin_password_page(request: Request, force: str = ""):
    """Standalone change-password page used when must_change_password is enforced."""
    username = require_auth(request, allow_force_change=True)
    conn = get_db()
    settings = get_settings(conn)
    user = conn.execute(
        "SELECT must_change_password FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    forced = bool(user and user["must_change_password"]) or force == "1"
    safe_settings = {k: v for k, v in settings.items() if k not in SENSITIVE_SETTING_KEYS}
    return templates.TemplateResponse("password.html", {
        "request": request, "settings": safe_settings,
        "username": username, "forced": forced, "error": None,
    })


def _render_password_error(request: Request, username: str, message: str, forced: bool):
    conn = get_db()
    settings = get_settings(conn)
    conn.close()
    safe_settings = {k: v for k, v in settings.items() if k not in SENSITIVE_SETTING_KEYS}
    return templates.TemplateResponse("password.html", {
        "request": request, "settings": safe_settings,
        "username": username, "forced": forced, "error": message,
    }, status_code=400)


@app.post("/admin/password")
async def admin_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
):
    username = require_auth(request, allow_force_change=True)
    # Determine whether the user is in forced-change mode (drives back-link rendering).
    conn = get_db()
    user_row = conn.execute(
        "SELECT must_change_password, password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    forced = bool(user_row and user_row["must_change_password"])
    if len(new_password) < 8:
        conn.close()
        return _render_password_error(request, username,
            "Le nouveau mot de passe doit faire au moins 8 caracteres.", forced)
    if new_password == "admin":
        conn.close()
        return _render_password_error(request, username,
            "Le mot de passe ne peut pas etre 'admin'.", forced)
    if not _bcrypt.checkpw(current_password.encode(), user_row["password_hash"].encode()):
        conn.close()
        return _render_password_error(request, username,
            "Mot de passe actuel incorrect.", forced)
    new_hash = _bcrypt.hashpw(new_password.encode(), _bcrypt.gensalt()).decode()
    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE username = ?",
        (new_hash, username),
    )
    conn.commit()
    conn.close()
    # Clear the must_change_password flag on the active session.
    session_id = request.cookies.get("session_id")
    with _sessions_lock:
        if session_id and session_id in sessions:
            sessions[session_id]["must_change_password"] = False
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/license/activate")
async def admin_license_activate(request: Request, code: str = Form(...)):
    require_auth(request)
    valid, serial, days = verify_license_code(code)
    if not valid:
        return JSONResponse({"status": "error", "message": "Code invalide"}, status_code=400)
    conn = get_db()
    # Check if already used
    existing = conn.execute("SELECT serial FROM used_licenses WHERE serial = ?", (serial,)).fetchone()
    if existing:
        conn.close()
        return JSONResponse({"status": "error", "message": "Ce code a deja ete utilise"}, status_code=400)
    # Compute new expiry: start from today or current expiry (whichever is later)
    status = get_license_status(conn)
    current_expiry = date.fromisoformat(status["expiry"])
    base = max(date.today(), current_expiry) if not status["expired"] else date.today()
    new_expiry = base + timedelta(days=days)
    conn.execute("UPDATE settings SET value = ? WHERE key = ?",
                 (new_expiry.isoformat(), "license_expiry"))
    conn.execute("INSERT INTO used_licenses (serial, days, activated_at) VALUES (?, ?, ?)",
                 (serial, days, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return JSONResponse({"status": "ok", "message": f"Licence etendue de {days} jours",
                        "new_expiry": new_expiry.isoformat()})


@app.post("/admin/visitors/purge")
async def admin_purge_visitors(request: Request):
    require_auth(request)
    conn = get_db()
    conn.execute("DELETE FROM visitors WHERE left_at IS NOT NULL")
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


_EVAC_SUBJECT_VALID_RE = None

def _is_evac_subject_valid(s: str) -> bool:
    """Allow only printable text with the two whitelisted placeholders {entreprise} and {date}.
    Any other {…} placeholder is rejected (defense vs SSTI / config-poisoning typos)."""
    import re
    global _EVAC_SUBJECT_VALID_RE
    if _EVAC_SUBJECT_VALID_RE is None:
        # Find any {placeholder} that is NOT {entreprise} or {date}.
        _EVAC_SUBJECT_VALID_RE = re.compile(r"\{(?!entreprise\}|date\})[^}]*\}")
    if not s or "\r" in s or "\n" in s:
        return False
    if _EVAC_SUBJECT_VALID_RE.search(s):
        return False
    return True


def _redirect_admin_evac_error(conn, msg: str) -> RedirectResponse:
    """Close the DB and bounce back to the Evacuation panel with a flash message."""
    from urllib.parse import quote
    conn.close()
    return RedirectResponse(url=f"/admin?evac_error={quote(msg)}#panel-evac", status_code=303)


@app.post("/admin/evac/settings")
async def admin_evac_settings(
    request: Request,
    evac_enabled: str = Form("0"),
    evac_recipients: str = Form(""),
    evac_subject: str = Form(""),
    evac_body_header: str = Form(""),
):
    require_auth(request)
    conn = get_db()
    settings = get_settings(conn)
    want_enabled = (evac_enabled == "1")

    # Always persist the editable fields first — the user shouldn't lose their
    # input just because they ticked "activer" too early.
    subject_clean = (evac_subject or "").strip()[:500]
    if subject_clean and not _is_evac_subject_valid(subject_clean):
        return _redirect_admin_evac_error(
            conn, "Sujet invalide. Seuls les blocs {entreprise} et {date} sont autorises, pas de retour a la ligne.")

    conn.execute("UPDATE settings SET value = ? WHERE key = ?",
                 ((evac_recipients or "").strip()[:2000], "evac_recipients"))
    if subject_clean:
        conn.execute("UPDATE settings SET value = ? WHERE key = ?",
                     (subject_clean, "evac_subject"))
    conn.execute("UPDATE settings SET value = ? WHERE key = ?",
                 ((evac_body_header or "").strip()[:2000], "evac_body_header"))

    # Now, if the user asked to enable, verify prerequisites — saved values
    # are kept; only the enable flag is rejected.
    if want_enabled:
        # Refresh after our writes.
        settings = get_settings(conn)
        has_code = bool(settings.get("evac_code_hash", ""))
        smtp_ok = (settings.get("smtp_enabled") == "1"
                   and settings.get("smtp_host") and settings.get("smtp_from"))
        rcpts = parse_recipients(settings.get("evac_recipients", ""))
        host_ok = _smtp_host_safe(settings.get("smtp_host", ""))
        if not has_code:
            conn.commit()
            return _redirect_admin_evac_error(
                conn, "Definissez d'abord un code a 6 chiffres avant d'activer la fonction.")
        if not smtp_ok:
            conn.commit()
            return _redirect_admin_evac_error(
                conn, "Activez et configurez d'abord le SMTP dans l'onglet Notifications.")
        if not host_ok:
            conn.commit()
            return _redirect_admin_evac_error(
                conn, "Hote SMTP refuse (loopback ou service metadata interdit).")
        if not rcpts:
            conn.commit()
            return _redirect_admin_evac_error(
                conn, "Configurez au moins un destinataire valide avant d'activer.")

    conn.execute("UPDATE settings SET value = ? WHERE key = ?",
                 ("1" if want_enabled else "0", "evac_enabled"))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin#panel-evac", status_code=303)


@app.post("/admin/evac/purge")
async def admin_evac_purge(request: Request):
    require_auth(request)
    conn = get_db()
    conn.execute("DELETE FROM evac_log")
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/evac/code")
async def admin_evac_set_code(request: Request, new_code: str = Form(...)):
    require_auth(request)
    import re
    code = (new_code or "").strip()
    if not re.match(EVAC_CODE_REGEX, code):
        return JSONResponse({"status": "error", "message": "Le code doit comporter exactement 6 chiffres"},
                            status_code=400)
    h = hash_evac_code(code)
    conn = get_db()
    conn.execute("UPDATE settings SET value = ? WHERE key = ?", (h, "evac_code_hash"))
    conn.commit()
    conn.close()
    return JSONResponse({"status": "ok", "message": "Code mis a jour"})


@app.post("/admin/evac/test")
async def admin_evac_test(request: Request):
    """Admin-only: test sending the evacuation email with current present visitors."""
    require_auth(request)
    conn = get_db()
    settings = get_settings(conn)
    recipients = parse_recipients(settings.get("evac_recipients", ""))
    visitors_rows = conn.execute(
        """SELECT v.id, v.nom, v.prenom, v.entreprise, v.arrived_at,
                  c.prenom AS contact_prenom, c.nom AS contact_nom
           FROM visitors v LEFT JOIN contacts c ON v.contact_id = c.id
           WHERE v.left_at IS NULL ORDER BY v.arrived_at ASC"""
    ).fetchall()
    conn.close()
    if not recipients:
        return JSONResponse({"status": "error", "message": "Aucun destinataire valide configure"},
                            status_code=400)
    visitors = [dict(v) for v in visitors_rows]
    ok, err = send_evac_email(settings, recipients, visitors)
    if not ok:
        return JSONResponse({"status": "error", "message": f"Erreur: {err}"}, status_code=500)
    return JSONResponse({"status": "ok",
                         "message": f"Email de test envoye a {len(recipients)} destinataire(s) ({len(visitors)} visiteur(s))"})


@app.post("/admin/test-email")
async def admin_test_email(request: Request):
    require_auth(request)
    conn = get_db()
    settings = get_settings(conn)
    conn.close()
    test_contact = {"prenom": "Test", "nom": "Utilisateur", "civilite": "M",
                    "email": settings.get("smtp_from", ""), "telephone": ""}
    try:
        send_email(settings, test_contact, "Monsieur", raise_on_error=True)
        return JSONResponse({"status": "ok", "message": "Email de test envoyé à " + test_contact["email"]})
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Erreur: {type(e).__name__}: {e}"})


@app.post("/admin/test-sms")
async def admin_test_sms(request: Request):
    require_auth(request)
    form = await request.form()
    phone = form.get("test_phone", "")
    if not phone:
        return JSONResponse({"status": "error", "message": "Numero de telephone requis"}, status_code=400)
    conn = get_db()
    settings = get_settings(conn)
    conn.close()
    test_contact = {"prenom": "Test", "nom": "Utilisateur", "civilite": "M",
                    "email": "", "telephone": phone}
    try:
        send_sms(settings, test_contact, "Monsieur", raise_on_error=True)
        return JSONResponse({"status": "ok", "message": "SMS de test envoyé à " + phone})
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Erreur: {type(e).__name__}: {e}"})


# --- CSV Import ---

@app.post("/admin/contacts/import")
async def admin_import_contacts(request: Request):
    require_auth(request)
    form = await request.form()
    file = form.get("csv_file")
    if not file:
        raise HTTPException(status_code=400, detail="Aucun fichier")

    import csv
    import io
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")

    conn = get_db()
    count = 0
    for row in reader:
        nom = row.get("nom", row.get("Nom", "")).strip()
        prenom = row.get("prenom", row.get("Prenom", row.get("Prénom", ""))).strip()
        email = row.get("email", row.get("Email", row.get("Mail", ""))).strip()
        telephone = row.get("telephone", row.get("Telephone", row.get("Téléphone", row.get("Tel", "")))).strip()
        civilite = row.get("civilite", row.get("Civilite", row.get("Civilité", row.get("Genre", "M")))).strip()
        if civilite not in ("M", "Mme", "X"):
            civilite = "M"
        if nom and prenom:
            conn.execute(
                "INSERT INTO contacts (nom, prenom, civilite, email, telephone) VALUES (?, ?, ?, ?, ?)",
                (nom, prenom, civilite, email, telephone),
            )
            count += 1
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
