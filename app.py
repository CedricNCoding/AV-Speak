import os
import sqlite3
import subprocess
import secrets
import threading
from pathlib import Path
from functools import wraps

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import bcrypt as _bcrypt
from pydantic import BaseModel

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "av_speak.db"
TTS_CACHE_DIR = BASE_DIR / "tts_cache"
PIPER_BIN = BASE_DIR / "piper" / "piper"
PIPER_MODEL = BASE_DIR / "piper" / "fr_FR-siwis-medium.onnx"

TTS_CACHE_DIR.mkdir(exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Simple session store (in-memory, single PC)
sessions: dict[str, str] = {}

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
            email TEXT DEFAULT '',
            telephone TEXT DEFAULT '',
            call_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    # Create default admin if not exists
    existing = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    if not existing:
        pw_hash = _bcrypt.hashpw("admin".encode(), _bcrypt.gensalt()).decode()
        conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("admin", pw_hash))
    # Default color settings
    defaults = {
        "color_primary": "#1a73e8",
        "color_secondary": "#ffffff",
        "color_background": "#f5f5f5",
        "color_text": "#333333",
        "color_button": "#1a73e8",
        "color_button_text": "#ffffff",
        "entreprise_nom": "Accueil",
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


def require_auth(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    return sessions[session_id]


# --- Audio playback ---

def play_audio(filepath: str):
    """Play a WAV file through the default audio output."""
    import platform
    try:
        system = platform.system()
        if system == "Linux":
            subprocess.run(["aplay", filepath], capture_output=True, timeout=30)
        elif system == "Darwin":
            subprocess.run(["afplay", filepath], capture_output=True, timeout=30)
        elif system == "Windows":
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)
            pygame.mixer.quit()
    except Exception as e:
        print(f"Erreur lecture audio: {e}")


def generate_and_play_tts(texte: str):
    """Generate TTS with Piper and play it."""
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
                return
        except FileNotFoundError:
            print(f"Piper non trouvé: {PIPER_BIN}")
            print("Installez Piper TTS. Voir DEPLOIEMENT.md")
            return
        except Exception as e:
            print(f"Erreur TTS: {e}")
            return

    play_audio(str(filepath))


# --- Routes: Kiosk (Frontend tactile) ---

@app.get("/", response_class=HTMLResponse)
async def kiosk(request: Request):
    conn = get_db()
    settings = get_settings(conn)
    top_contacts = conn.execute(
        "SELECT * FROM contacts ORDER BY call_count DESC LIMIT 6"
    ).fetchall()
    conn.close()
    return templates.TemplateResponse("kiosk.html", {
        "request": request,
        "settings": settings,
        "top_contacts": top_contacts,
    })


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
async def announce(contact_id: int):
    conn = get_db()
    contact = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    if not contact:
        conn.close()
        raise HTTPException(status_code=404, detail="Contact non trouvé")

    conn.execute("UPDATE contacts SET call_count = call_count + 1 WHERE id = ?", (contact_id,))
    conn.commit()

    settings = get_settings(conn)
    conn.close()

    civilite = "Monsieur" if not contact["prenom"].endswith(("a", "e", "ine", "elle", "ette")) else "Madame"
    texte = f"{civilite} {contact['prenom']} {contact['nom']} est demandé à l'accueil"

    # Play TTS in background thread to not block the response
    thread = threading.Thread(target=generate_and_play_tts, args=(texte,))
    thread.start()

    return {"status": "ok", "message": texte}


@app.get("/api/settings")
async def api_get_settings():
    conn = get_db()
    settings = get_settings(conn)
    conn.close()
    return settings


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
    sessions[session_id] = username
    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie("session_id", session_id, httponly=True)
    return response


@app.get("/admin/logout")
async def admin_logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id and session_id in sessions:
        del sessions[session_id]
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("session_id")
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    require_auth(request)
    conn = get_db()
    settings = get_settings(conn)
    contacts = conn.execute("SELECT * FROM contacts ORDER BY nom, prenom").fetchall()
    conn.close()
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "settings": settings,
        "contacts": contacts,
    })


@app.post("/admin/contacts/add")
async def admin_add_contact(
    request: Request,
    nom: str = Form(...),
    prenom: str = Form(...),
    email: str = Form(""),
    telephone: str = Form(""),
):
    require_auth(request)
    conn = get_db()
    conn.execute(
        "INSERT INTO contacts (nom, prenom, email, telephone) VALUES (?, ?, ?, ?)",
        (nom.strip(), prenom.strip(), email.strip(), telephone.strip()),
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
    email: str = Form(""),
    telephone: str = Form(""),
):
    require_auth(request)
    conn = get_db()
    conn.execute(
        "UPDATE contacts SET nom=?, prenom=?, email=?, telephone=? WHERE id=?",
        (nom.strip(), prenom.strip(), email.strip(), telephone.strip(), contact_id),
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


@app.post("/admin/settings")
async def admin_update_settings(request: Request):
    require_auth(request)
    form = await request.form()
    conn = get_db()
    for key in ("color_primary", "color_secondary", "color_background", "color_text",
                "color_button", "color_button_text", "entreprise_nom"):
        value = form.get(key)
        if value is not None:
            conn.execute("UPDATE settings SET value = ? WHERE key = ?", (value.strip(), key))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/password")
async def admin_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
):
    username = require_auth(request)
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not _bcrypt.checkpw(current_password.encode(), user["password_hash"].encode()):
        conn.close()
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    new_hash = _bcrypt.hashpw(new_password.encode(), _bcrypt.gensalt()).decode()
    conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hash, username))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


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
        if nom and prenom:
            conn.execute(
                "INSERT INTO contacts (nom, prenom, email, telephone) VALUES (?, ?, ?, ?)",
                (nom, prenom, email, telephone),
            )
            count += 1
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
