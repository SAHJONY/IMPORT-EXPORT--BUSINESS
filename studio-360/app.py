#!/usr/bin/env python3
"""Voice Clone Studio — tiny web UI over the voice-clone engine.

Backend contract (engine lives at ~/workspace/skills/voice-clone/):
  scripts/clone.py --list-voices                       -> JSON list
  scripts/clone.py --voice NAME --text T --language es --output F -> JSON

Saving a voice uses the engine's own on-disk convention
(voices/<name>/reference.<ext> + meta.json), exactly as clone.py's
--save-voice writes it, so the engine picks it up with zero changes.
If the engine is missing/broken, /api/status reports it and the UI
shows a clear banner instead of crashing.

Run:  python3 app.py            (port 8099)
      PORT=8100 python3 app.py  (custom port)
"""

import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import uuid
from datetime import timedelta

from flask import Flask, jsonify, redirect, request, send_file, render_template, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------- config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.expanduser("~/workspace/skills/voice-clone")
CLONE_PY = os.path.join(SKILL_DIR, "scripts", "clone.py")
VOICES_DIR = os.path.join(SKILL_DIR, "voices")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
PORT = int(os.environ.get("PORT", "8099"))

ALLOWED_EXTS = {".mp3", ".wav", ".m4a"}
ALLOWED_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_RE = re.compile(r"^[a-f0-9-]{8,64}\.(mp3|wav)$")
PHOTO_FILE_RE = re.compile(r"^photo\.(jpg|jpeg|png|webp)$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_TEXT = 600          # keeps CPU synthesis time sane
SYNTH_TIMEOUT = 1200    # seconds; model load ~1-2 min + synth on CPU
SUPPORTED_LANGUAGES = {"es", "en", "pt", "fr", "de", "it"}  # "Español (Cuba)" maps to es

# Known engine failure modes -> plain-Spanish explanation for the user.
def friendly_engine_error(raw):
    low = (raw or "").lower()
    if "add_safe_globals" in low or "was not an allowed global" in low:
        return ("El motor de voz tiene un problema interno con la versión de "
                "PyTorch y no pudo arrancar. Ya está reportado a quien lo está "
                "armando; inténtalo de nuevo más tarde.")
    if "out of memory" in low or "cuda out of memory" in low or "killed" in low:
        return ("El motor se quedó sin memoria. Prueba con un texto más corto.")
    if "unknown saved voice" in low:
        return "Esa voz no existe. Clónala primero arriba."
    return raw

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)

# ---- account login: signup on first run, then username+password ----
AUTH_FILE = os.path.join(BASE_DIR, ".auth.json")
SECRET_FILE = os.path.join(BASE_DIR, ".flask_secret")


def _flask_secret():
    if os.path.isfile(SECRET_FILE):
        with open(SECRET_FILE, "rb") as fh:
            return fh.read().strip()
    key = secrets.token_hex(32).encode()
    with open(SECRET_FILE, "wb") as fh:
        fh.write(key)
    os.chmod(SECRET_FILE, 0o600)
    return key


app.secret_key = _flask_secret()
app.permanent_session_lifetime = timedelta(days=30)


def _account():
    """Saved account dict or None (nobody signed up yet). Never raises."""
    try:
        with open(AUTH_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _save_account(user, password):
    with open(AUTH_FILE, "w", encoding="utf-8") as fh:
        json.dump({"user": user,
                   "password_hash": generate_password_hash(password)}, fh)
    os.chmod(AUTH_FILE, 0o600)


@app.get("/setup")
def setup():
    """First-run signup: create the studio's username + password."""
    if _account() is not None or session.get("authed"):
        return redirect(url_for("index"))
    return render_template("setup.html", error=None)


@app.post("/setup")
def do_setup():
    if _account() is not None:
        return redirect(url_for("login"))
    user = (request.form.get("user") or "").strip().lower() or "juan"
    pwd = request.form.get("password") or ""
    pwd2 = request.form.get("password2") or ""
    if not re.match(r"^[a-z0-9_.-]{1,40}$", user):
        return render_template("setup.html",
                               error="Usuario no válido (letras, números, . _ -)."), 400
    if len(pwd) < 6:
        return render_template("setup.html",
                               error="La contraseña debe tener al menos 6 caracteres."), 400
    if pwd != pwd2:
        return render_template("setup.html",
                               error="Las contraseñas no coinciden."), 400
    _save_account(user, pwd)
    session["authed"] = True
    session.permanent = True
    return redirect(url_for("index"))


@app.get("/login")
def login():
    if session.get("authed"):
        return redirect(url_for("index"))
    if _account() is None:
        return redirect(url_for("setup"))
    return render_template("login.html", error=None)


@app.post("/login")
def do_login():
    acct = _account()
    user = (request.form.get("user") or "").strip().lower()
    pwd = request.form.get("password") or ""
    if acct and user == acct.get("user") \
            and check_password_hash(acct.get("password_hash", ""), pwd):
        session["authed"] = True
        session.permanent = True
        return redirect(url_for("index"))
    return render_template("login.html",
                           error="Usuario o contraseña incorrectos."), 401


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.before_request
def _require_login():
    public = {"setup", "do_setup", "login", "do_login", "static", "serve_media"}
    if request.endpoint in public or session.get("authed"):
        return None
    if _account() is None:
        return redirect(url_for("setup"))
    return redirect(url_for("login"))


_synth_lock = threading.Lock()  # one synthesis at a time: tiny RAM box


# ------------------------------------------------------- engine helpers
def _model_path():
    tts_home = os.environ.get("TTS_HOME", os.path.expanduser("~/.local/share/tts"))
    # Model-dir nesting differs between TTS builds (some nest under an
    # extra "tts/"), so check both layouts.
    for sub in ("tts_models--multilingual--multi-dataset--xtts_v2",
                os.path.join("tts", "tts_models--multilingual--multi-dataset--xtts_v2")):
        p = os.path.join(tts_home, sub, "model.pth")
        if os.path.isfile(p):
            return p
    return os.path.join(
        tts_home, "tts_models--multilingual--multi-dataset--xtts_v2", "model.pth")


def engine_status():
    """(ready: bool, detail: str) — never raises."""
    if not os.path.isfile(CLONE_PY):
        return False, "Falta el motor (scripts/clone.py). La herramienta de clonación aún no está instalada."
    if importlib.util.find_spec("TTS") is None:
        return False, "Falta la librería TTS de Python. El motor aún no está instalado."
    if not os.path.isfile(_model_path()):
        return False, "El modelo de voz aún se está descargando. Inténtalo en unos minutos."
    return True, "Motor listo (XTTS v2)"


def _run_clone(args, timeout=60):
    """Run clone.py, return (ok, payload|error). Never raises."""
    try:
        proc = subprocess.run(
            [sys.executable, CLONE_PY] + args,
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "El motor tardó demasiado y se detuvo. Prueba con un texto más corto."
    except Exception as exc:  # noqa: BLE001
        return False, f"No se pudo arrancar el motor: {exc}"
    out = (proc.stdout or "").strip()
    if proc.returncode == 0 and out:
        try:
            start = out.index("{")
            return True, json.loads(out[start:])
        except (ValueError, json.JSONDecodeError):
            pass
    err = (proc.stderr or "").strip().splitlines()
    tail = " ".join(err[-3:]) if err else "error desconocido del motor"
    return False, tail[-500:]


def list_voices():
    ok, payload = _run_clone(["--list-voices"])
    if ok and isinstance(payload, dict):
        voices = payload.get("voices", [])
    else:
        # Fallback: read the voices dir directly with the engine's convention.
        voices = []
        if os.path.isdir(VOICES_DIR):
            for name in sorted(os.listdir(VOICES_DIR)):
                meta = os.path.join(VOICES_DIR, name, "meta.json")
                if os.path.isfile(meta):
                    try:
                        with open(meta, encoding="utf-8") as fh:
                            voices.append({"name": name, **json.load(fh)})
                    except (OSError, json.JSONDecodeError):
                        continue
    for v in voices:
        if v.get("photo"):
            v["photo_url"] = f"/persona-photo/{v['name']}"
        if v.get("movements"):
            v["movements_url"] = f"/persona-movements/{v['name']}"
        if v.get("body"):
            v["body_url"] = f"/persona-body/{v['name']}"
    return voices


def probe_duration(path):
    """Seconds of audio, or None. Never raises."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30)
        return round(float(proc.stdout.strip()), 1)
    except Exception:  # noqa: BLE001
        return None


def sanitize_name(raw):
    name = (raw or "").strip().lower().replace(" ", "-")
    name = re.sub(r"[^a-z0-9_-]", "", name)
    return name if NAME_RE.match(name) else ""


# ---------------------------------------------------------------- routes
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def api_status():
    ready, detail = engine_status()
    return jsonify({"engine_ready": ready, "detail": detail,
                    "voices_count": len(list_voices())})


@app.get("/api/voices")
def api_voices():
    return jsonify({"ok": True, "voices": list_voices()})


@app.post("/api/voices")
def api_save_voice():
    """Upload reference audio + name -> staged as an engine voice."""
    ready, detail = engine_status()
    if not ready:
        return jsonify({"ok": False, "error": detail}), 503

    upload = request.files.get("audio")
    if upload is None or not upload.filename:
        return jsonify({"ok": False,
                        "error": "Sube un archivo de audio primero."}), 400
    name = sanitize_name(request.form.get("name", ""))
    if not name:
        return jsonify({"ok": False, "error":
                        "Ponle un nombre válido a la voz (letras, números, - y _)."}), 400

    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        return jsonify({"ok": False, "error":
                        "Formato no válido. Usa mp3, wav o m4a."}), 400

    vdir = os.path.join(VOICES_DIR, name)
    if os.path.isfile(os.path.join(vdir, "meta.json")) \
            and request.form.get("overwrite") != "1":
        return jsonify({"ok": False, "error": "exists",
                        "message": f'La voz "{name}" ya existe. ¿La quieres reemplazar?'}), 409

    tmp_name = f"{uuid.uuid4().hex}{ext}"
    tmp_path = os.path.join(UPLOAD_DIR, tmp_name)
    try:
        upload.save(tmp_path)
    except OSError as exc:
        return jsonify({"ok": False,
                        "error": f"No se pudo guardar el audio: {exc}"}), 500

    photo_tmp, photo_ext, photo_err = _stage_photo_upload(request.files.get("photo"))
    if photo_err:
        return jsonify({"ok": False, "error": photo_err}), 400

    return _stage_reference(tmp_path, name, ext,
                            request.form.get("overwrite") == "1",
                            photo_tmp, photo_ext)


URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
CLIP_START = 10   # seconds into the video where the voice sample starts
CLIP_LEN = 30     # seconds of audio taken for the reference clip
MOV_FILE_RE = re.compile(r"^movements\.mp4$")
BODY_FILE_RE = re.compile(r"^body\.(jpg|jpeg|png|webp)$")


def _stage_reference(tmp_path, name, ext, overwrite, photo_tmp=None, photo_ext=None,
                      mov_tmp=None, body_tmp=None):
    """Validate + stage an audio file as an engine voice. Shared by
    the upload flow and the from-URL flow. photo_tmp is an optional
    staged image file that becomes the persona's face reference.
    mov_tmp is an optional staged mp4 with the persona's movement
    reference (gestures/way of moving), and body_tmp an optional
    staged full-body reference frame — both saved for future phase-2
    digital-character video generation."""
    vdir = os.path.join(VOICES_DIR, name)
    if os.path.isfile(os.path.join(vdir, "meta.json")) and not overwrite:
        return jsonify({"ok": False, "error": "exists",
                        "message": f'La voz "{name}" ya existe. ¿La quieres reemplazar?'}), 409

    duration = probe_duration(tmp_path)
    note = None
    if duration is not None and (duration < 6 or duration > 60):
        note = (f"El audio dura {duration}s. Lo ideal es de 6 a 30 segundos "
                "de voz clara; igual la guardé, pero puede clonar mejor con otro pedazo.")

    try:
        os.makedirs(vdir, exist_ok=True)
        dest = os.path.join(vdir, f"reference{ext}")
        with open(tmp_path, "rb") as src, open(dest, "wb") as fh:
            fh.write(src.read())
        meta = {"reference": dest, "language": "es", "source": tmp_path}
        if photo_tmp and photo_ext in ALLOWED_PHOTO_EXTS:
            photo_dest = os.path.join(vdir, f"photo{photo_ext}")
            with open(photo_tmp, "rb") as src, open(photo_dest, "wb") as fh:
                fh.write(src.read())
            meta["photo"] = f"photo{photo_ext}"
        if mov_tmp and os.path.isfile(mov_tmp):
            mov_dest = os.path.join(vdir, "movements.mp4")
            with open(mov_tmp, "rb") as src, open(mov_dest, "wb") as fh:
                fh.write(src.read())
            meta["movements"] = "movements.mp4"
        if body_tmp and os.path.isfile(body_tmp):
            body_ext = os.path.splitext(body_tmp)[1].lower()
            if body_ext in ALLOWED_PHOTO_EXTS:
                body_dest = os.path.join(vdir, f"body{body_ext}")
                with open(body_tmp, "rb") as src, open(body_dest, "wb") as fh:
                    fh.write(src.read())
                meta["body"] = f"body{body_ext}"
        with open(os.path.join(vdir, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        return jsonify({"ok": False,
                        "error": f"No se pudo guardar la voz: {exc}"}), 500

    return jsonify({"ok": True,
                    "voice": {"name": name, **meta},
                    "duration_secs": duration, "note": note})


def _stage_photo_upload(file_storage):
    """Stage an uploaded persona photo into UPLOAD_DIR. Returns
    (tmp_path, ext, error) — error is None on success or when no
    photo was provided."""
    if file_storage is None or not file_storage.filename:
        return None, None, None
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ALLOWED_PHOTO_EXTS:
        return None, None, "La foto debe ser jpg, jpeg, png o webp."
    tmp_name = f"photo-{uuid.uuid4().hex}{ext}"
    tmp_path = os.path.join(UPLOAD_DIR, tmp_name)
    try:
        file_storage.save(tmp_path)
    except OSError as exc:
        return None, None, f"No se pudo guardar la foto: {exc}"
    return tmp_path, ext, None


@app.post("/api/voices/from-url")
def api_voice_from_url():
    """Paste a video link (YouTube, Instagram, Facebook, TikTok...) ->
    download its audio, take a {CLIP_LEN}s slice, stage it as a voice."""
    ready, detail = engine_status()
    if not ready:
        return jsonify({"ok": False, "error": detail}), 503

    data = request.get_json(silent=True) or {}
    if request.form:  # multipart (URL flow with optional photo)
        data = {"url": request.form.get("url", ""),
                "name": request.form.get("name", ""),
                "overwrite": request.form.get("overwrite", "")}
    url = (data.get("url") or "").strip()
    name = sanitize_name(data.get("name", ""))
    overwrite = data.get("overwrite") == "1" or data.get("overwrite") is True
    if not url or not URL_RE.match(url) or len(url) > 500:
        return jsonify({"ok": False, "error":
                        "Ese enlace no parece válido. Pega la dirección completa del video."}), 400
    if "@" in url.split("://", 1)[1].split("/", 1)[0]:
        return jsonify({"ok": False, "error":
                        "El enlace no puede traer usuario o contraseña."}), 400
    if not name:
        return jsonify({"ok": False, "error":
                        "Ponle un nombre válido a la voz (letras, números, - y _)."}), 400

    vdir = os.path.join(VOICES_DIR, name)
    if os.path.isfile(os.path.join(vdir, "meta.json")) and not overwrite:
        return jsonify({"ok": False, "error": "exists",
                        "message": f'La voz "{name}" ya existe. ¿La quieres reemplazar?'}), 409

    tmp_base = os.path.join(UPLOAD_DIR, f"url-{uuid.uuid4().hex}")
    # Download the FULL audio, then cut the 10s-40s window locally with
    # ffmpeg. (yt-dlp --download-sections is unreliable on direct media
    # URLs, so we do the precise trim ourselves — bulletproof everywhere.)
    full_audio = tmp_base + "-full.mp3"
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings",
           "-x", "--audio-format", "mp3", "--audio-quality", "5",
           "-o", tmp_base + "-full.%(ext)s", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error":
                        "Tardó demasiado en bajar el video. Prueba con otro enlace."}), 504
    if proc.returncode != 0 or not os.path.isfile(full_audio):
        err = (proc.stderr or "")[-300:]
        if "unsupported url" in err.lower() or "unsupported" in err.lower():
            msg = "No pude leer ese enlace. Revisa que sea un video público."
        elif "private" in err.lower() or "login" in err.lower():
            msg = "Ese video es privado o pide iniciar sesión; usa uno público."
        else:
            msg = "No pude bajar el audio de ese enlace. Prueba con otro."
        return jsonify({"ok": False, "error": msg}), 422
    tmp_path = tmp_base + ".mp3"
    cut = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-ss", str(CLIP_START), "-t", str(CLIP_LEN),
         "-i", full_audio, "-c:a", "libmp3lame", "-q:a", "5", tmp_path],
        capture_output=True, timeout=300)
    try:
        os.remove(full_audio)
    except OSError:
        pass
    if cut.returncode != 0 or not os.path.isfile(tmp_path):
        return jsonify({"ok": False, "error":
                        "El video es muy corto; necesito al menos unos segundos de audio."}), 422

    # Movement reference clip: same 30s window, 720p mp4 — saved for
    # future phase-2 full-character video generation. Video download is
    # capped at 500MB and is non-fatal: the persona is still created
    # with its voice even if the clip can't be fetched.
    mov_path = tmp_base + "-mov.mp4"
    mov_ok = False
    full_video = tmp_base + "-fullvideo.mp4"
    mov_cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings",
               "-f", "b[height<=720]/b",
               "--merge-output-format", "mp4", "--max-filesize", "500M",
               "-o", tmp_base + "-fullvideo.%(ext)s", url]
    try:
        mov_proc = subprocess.run(mov_cmd, capture_output=True, text=True, timeout=600)
        if mov_proc.returncode == 0 and os.path.isfile(full_video):
            mv = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-ss", str(CLIP_START), "-t", str(CLIP_LEN),
                 "-i", full_video, "-vf", "scale=-2:720",
                 "-c:v", "libx264", "-preset", "veryfast",
                 "-c:a", "aac", mov_path],
                capture_output=True, timeout=600)
            mov_ok = mv.returncode == 0 and os.path.isfile(mov_path)
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:
            if os.path.isfile(full_video):
                os.remove(full_video)
        except OSError:
            pass

    # Full-body reference frame (middle of the movement clip) — saved
    # for future phase-2 full-character video generation.
    body_tmp = None
    if mov_ok:
        cand = tmp_base + "-body.jpg"
        bp = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(CLIP_LEN // 2),
             "-i", mov_path, "-frames:v", "1", cand],
            capture_output=True, timeout=120)
        if bp.returncode == 0 and os.path.isfile(cand):
            body_tmp = cand

    photo_tmp, photo_ext, photo_err = _stage_photo_upload(request.files.get("photo"))
    if photo_err:
        return jsonify({"ok": False, "error": photo_err}), 400

    return _stage_reference(tmp_path, name, ".mp3", overwrite, photo_tmp, photo_ext,
                            mov_path if mov_ok else None, body_tmp)


@app.post("/api/speak")
def api_speak():
    """{voice, text} -> synthesize Spanish audio with the cloned voice."""
    ready, detail = engine_status()
    if not ready:
        return jsonify({"ok": False, "error": detail}), 503

    data = request.get_json(silent=True) or {}
    name = sanitize_name(data.get("voice", ""))
    text = (data.get("text", "") or "").strip()
    lang = (data.get("language") or "es").strip().lower()
    if not name or not os.path.isfile(os.path.join(VOICES_DIR, name, "meta.json")):
        return jsonify({"ok": False,
                        "error": "Esa voz no existe. Clónala primero arriba."}), 400
    if lang not in SUPPORTED_LANGUAGES:
        return jsonify({"ok": False,
                        "error": "Ese idioma no está soportado por el motor."}), 400
    if not text:
        return jsonify({"ok": False, "error": "Escribe el texto primero."}), 400
    if len(text) > MAX_TEXT:
        return jsonify({"ok": False, "error":
                        f"El texto es muy largo ({len(text)} caracteres, máximo {MAX_TEXT}). "
                        "Pártelo en pedazos."}), 400

    out_name = f"{uuid.uuid4().hex}.mp3"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    with _synth_lock:  # one at a time — the box has little RAM
        ok, payload = _run_clone(
            ["--voice", name, "--text", text,
             "--language", lang, "--output", out_path],
            timeout=SYNTH_TIMEOUT)
    if not ok:
        return jsonify({"ok": False,
                        "error": friendly_engine_error(payload)}), 502
    if not os.path.isfile(out_path):
        return jsonify({"ok": False,
                        "error": "El motor no devolvió audio. Inténtalo de nuevo."}), 502
    return jsonify({"ok": True, "audio_url": f"/audio/{out_name}",
                    "duration_secs": payload.get("duration_secs"),
                    "bytes": payload.get("bytes")})


@app.get("/persona-photo/<name>")
def persona_photo(name):
    """Serve a persona's face-reference photo (thumbnail in the UI)."""
    if not NAME_RE.match(name):
        return jsonify({"ok": False, "error": "Persona no válida."}), 404
    vdir = os.path.join(VOICES_DIR, name)
    try:
        with open(os.path.join(vdir, "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return jsonify({"ok": False, "error": "No existe esa persona."}), 404
    photo = meta.get("photo", "")
    if not PHOTO_FILE_RE.match(photo):
        return jsonify({"ok": False, "error": "Esa persona no tiene foto."}), 404
    path = os.path.join(vdir, photo)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "Esa persona no tiene foto."}), 404
    mimetype = "image/png" if photo.endswith(".png") else \
               "image/webp" if photo.endswith(".webp") else "image/jpeg"
    return send_file(path, mimetype=mimetype)


@app.get("/persona-movements/<name>")
def persona_movements(name):
    """Serve a persona's movement-reference clip (saved for future
    phase-2 motion retargeting; not animated yet)."""
    if not NAME_RE.match(name):
        return jsonify({"ok": False, "error": "Persona no válida."}), 404
    vdir = os.path.join(VOICES_DIR, name)
    try:
        with open(os.path.join(vdir, "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return jsonify({"ok": False, "error": "No existe esa persona."}), 404
    mov = meta.get("movements", "")
    if not MOV_FILE_RE.match(mov):
        return jsonify({"ok": False, "error": "Esa persona no tiene clip de movimientos."}), 404
    path = os.path.join(vdir, mov)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "Esa persona no tiene clip de movimientos."}), 404
    return send_file(path, mimetype="video/mp4")


@app.get("/persona-body/<name>")
def persona_body(name):
    """Serve a persona's full-body reference frame (saved for future
    phase-2 full-character video generation)."""
    if not NAME_RE.match(name):
        return jsonify({"ok": False, "error": "Persona no válida."}), 404
    vdir = os.path.join(VOICES_DIR, name)
    try:
        with open(os.path.join(vdir, "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return jsonify({"ok": False, "error": "No existe esa persona."}), 404
    body = meta.get("body", "")
    if not BODY_FILE_RE.match(body):
        return jsonify({"ok": False, "error": "Esa persona no tiene referencia de cuerpo."}), 404
    path = os.path.join(vdir, body)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "Esa persona no tiene referencia de cuerpo."}), 404
    mimetype = "image/png" if body.endswith(".png") else \
               "image/webp" if body.endswith(".webp") else "image/jpeg"
    return send_file(path, mimetype=mimetype)


@app.get("/audio/<fname>")
def serve_audio(fname):
    if not AUDIO_RE.match(fname):
        return jsonify({"ok": False, "error": "Archivo no válido."}), 404
    path = os.path.join(OUTPUT_DIR, fname)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "No existe ese audio."}), 404
    return send_file(path, mimetype="audio/mpeg",
                     download_name=fname, as_attachment=False)


@app.errorhandler(Exception)
def _json_errors(exc):  # noqa: BLE001 - never crash on the user
    code = getattr(exc, "code", 500)
    return jsonify({"ok": False, "error": f"Error interno ({code}). Inténtalo de nuevo."}), code


# ================================================================
# SAHJONY Studio 360 — Music · Video · Produce · Publish · Settings
# Added 2026-09-24. The voice studio above is untouched.
# External providers (ElevenLabs music, fal.ai video) need API keys
# that Juan pastes himself in the Ajustes tab. Keys live in
# .studio_keys.json (mode 600) — never in source, chat or logs.
# Nothing is generated or published without his tap in the UI, and
# every paid generation shows its estimated cost first.
# ================================================================

import time as _time
import urllib.request as _ureq
import urllib.error as _uerr

STUDIO_PUBLIC = os.environ.get("STUDIO_PUBLIC", "https://studio.sahjony.com")
JOBS_DIR = os.path.join(BASE_DIR, "jobs")
KEYS_FILE = os.path.join(BASE_DIR, ".studio_keys.json")
MEDIA_TOKENS_FILE = os.path.join(BASE_DIR, ".media_tokens.json")
PUBLISH_FILE = os.path.join(JOBS_DIR, "publish.json")
os.makedirs(JOBS_DIR, exist_ok=True)

_jobs_lock = threading.Lock()

JOB_RE = re.compile(r"^[a-f0-9]{32}$")
VIDEO_RE = re.compile(r"^[a-f0-9-]{8,64}\.(mp4|mov)$")
SAFE_MEDIA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,80}$")

ELEVENLABS_MUSIC_URL = "https://api.elevenlabs.io/v1/music"
FAL_QUEUE_BASE = "https://queue.fal.run"
MUSIC_USD_PER_MIN = 0.75  # aproximado; verificar en elevenlabs.io/pricing

VIDEO_MODELS = {
    "veo3": {
        "label": "Veo 3 Fast — video CON audio 🎙️",
        "text_id": "fal-ai/veo3/fast",
        "image_id": "fal-ai/veo3/fast/image-to-video",
        "usd_s": 0.40, "max_s": 8, "def_s": 8,
        "note": "El mejor para personajes que hablan. ~8 s por clip. Precio aprox.",
    },
    "kling": {
        "label": "Kling 2.5 Turbo — b-roll barato 💸",
        "text_id": "fal-ai/kling-video/v2.5-turbo/standard/text-to-video",
        "image_id": "fal-ai/kling-video/v2.5-turbo/standard/image-to-video",
        "usd_s": 0.07, "max_s": 10, "def_s": 5,
        "note": "Sin audio; ideal para fondos y escenas. Precio aprox.",
    },
    "hailuo": {
        "label": "Hailuo MiniMax — económico 💸",
        "text_id": "minimax/h3/text-to-video",
        "image_id": "minimax/h3/image-to-video",
        "usd_s": 0.055, "max_s": 10, "def_s": 6,
        "note": "Texto→video barato. Precio aprox.",
    },
}


# ---------------------------------------------------------- key storage
def _get_keys():
    try:
        with open(KEYS_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        return {"elevenlabs": d.get("elevenlabs", ""),
                "fal": d.get("fal", "")}
    except (OSError, ValueError):
        return {"elevenlabs": "", "fal": ""}


def _set_keys(updates):
    keys = _get_keys()
    for k in ("elevenlabs", "fal"):
        v = (updates.get(k) or "").strip()
        if v:
            keys[k] = v
    with open(KEYS_FILE, "w", encoding="utf-8") as fh:
        json.dump(keys, fh)
    os.chmod(KEYS_FILE, 0o600)
    return keys


# ---------------------------------------------------------- job storage
def _job_new(kind, label, params, cost_est=None):
    jid = uuid.uuid4().hex
    job = {"id": jid, "kind": kind, "label": label, "params": params,
           "status": "queued", "progress": "En cola…",
           "created": _time.time(), "cost_est": cost_est,
           "result": None, "error": None}
    with _jobs_lock:
        with open(os.path.join(JOBS_DIR, jid + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump(job, fh, ensure_ascii=False)
    return job


def _job_get(jid):
    if not JOB_RE.match(jid or ""):
        return None
    try:
        with open(os.path.join(JOBS_DIR, jid + ".json"),
                  encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _job_update(jid, **kw):
    with _jobs_lock:
        job = _job_get(jid)
        if not job:
            return
        job.update(kw)
        try:
            with open(os.path.join(JOBS_DIR, jid + ".json"), "w",
                      encoding="utf-8") as fh:
                json.dump(job, fh, ensure_ascii=False)
        except OSError:
            pass


def _job_fail(jid, msg):
    _job_update(jid, status="error", error=msg,
                progress="Falló 😞")


def _jobs_list(kind, limit=20):
    out = []
    try:
        names = os.listdir(JOBS_DIR)
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json") or n == "publish.json":
            continue
        job = _job_get(n[:-5])
        if job and job.get("kind") == kind:
            out.append(job)
    out.sort(key=lambda j: j.get("created", 0), reverse=True)
    return out[:limit]


# ---------------------------------------------------------- http helper
def _http(method, url, headers=None, body=None, timeout=120):
    """(status, content_type, data_bytes|json, error). Never raises."""
    req = _ureq.Request(url, data=body, headers=headers or {},
                        method=method)
    try:
        with _ureq.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "application/json" in ctype:
                try:
                    return resp.status, ctype, json.loads(raw.decode("utf-8",
                                                                     "replace")), None
                except ValueError:
                    return resp.status, ctype, raw, None
            return resp.status, ctype, raw, None
    except _uerr.HTTPError as e:
        try:
            detail = e.read()[:400].decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            detail = ""
        return e.code, "", None, f"HTTP {e.code}: {detail}"
    except Exception as exc:  # noqa: BLE001
        return 0, "", None, f"Error de conexión: {exc}"


# ================================================================ MUSIC
@app.post("/api/music")
def api_music_create():
    keys = _get_keys()
    if not keys["elevenlabs"]:
        return jsonify({"ok": False, "error":
                        "Falta la llave de ElevenLabs. Ponla en la pestaña ⚙️ Ajustes."}), 400
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    instrumental = bool(data.get("instrumental"))
    model = data.get("model") or "music_v1"
    try:
        secs = int(data.get("secs") or 60)
    except (TypeError, ValueError):
        secs = 60
    if not prompt:
        return jsonify({"ok": False, "error":
                        "Describe el estilo y la letra de la canción primero. 🎵"}), 400
    if len(prompt) > 4100:
        return jsonify({"ok": False, "error":
                        "El texto es muy largo (máximo 4100 caracteres)."}), 400
    if model not in ("music_v1", "music_v2"):
        model = "music_v1"
    secs = max(15, min(600, secs))
    cost_est = ((secs + 59) // 60) * MUSIC_USD_PER_MIN
    job = _job_new("music", prompt[:60], {"prompt": prompt, "secs": secs,
                                         "model": model,
                                         "instrumental": instrumental},
                   cost_est=cost_est)
    t = threading.Thread(target=_music_worker,
                         args=(job["id"], keys["elevenlabs"], prompt,
                               secs * 1000, model, instrumental),
                         daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job["id"],
                    "cost_est": cost_est})


def _music_worker(jid, key, prompt, length_ms, model, instrumental):
    _job_update(jid, status="working",
                progress="Componiendo la música… 🎼 (puede tardar unos minutos)")
    body = {"prompt": prompt, "music_length_ms": length_ms,
            "model_id": model}
    if instrumental:
        body["force_instrumental"] = True
    headers = {"xi-api-key": key, "Content-Type": "application/json"}
    url = ELEVENLABS_MUSIC_URL + "?output_format=mp3_44100_128"
    status, ctype, data, err = _http(
        "POST", url, headers, json.dumps(body).encode(), timeout=900)
    if err:
        _job_fail(jid, f"ElevenLabs: {err}")
        return
    audio = None
    if isinstance(data, bytes) and ctype.startswith("audio"):
        audio = data
    elif isinstance(data, dict) and data.get("job_id"):
        # Async variant: poll until the audio is ready.
        audio = _music_poll_async(jid, key, data["job_id"], headers)
        if audio is None:
            return  # _music_poll_async already failed the job
    else:
        _job_fail(jid, "ElevenLabs devolvió algo inesperado. Inténtalo de nuevo.")
        return
    fname = f"music-{jid}.mp3"
    try:
        with open(os.path.join(OUTPUT_DIR, fname), "wb") as fh:
            fh.write(audio)
    except OSError as exc:
        _job_fail(jid, f"No se pudo guardar el audio: {exc}")
        return
    _job_update(jid, status="done", progress="¡Lista! 🎉",
                result={"file": fname, "url": f"/audio/{fname}",
                        "secs": probe_duration(os.path.join(OUTPUT_DIR,
                                                             fname))})


def _music_poll_async(jid, key, remote_id, headers):
    """Poll GET /v1/music/{job_id}; returns audio bytes or None (fails job)."""
    url = f"{ELEVENLABS_MUSIC_URL}/{remote_id}"
    for _ in range(40):
        if (_job_get(jid) or {}).get("status") == "cancelled":
            return None
        _time.sleep(15)
        status, ctype, data, err = _http("GET", url, headers, timeout=60)
        if err:
            continue
        if isinstance(data, bytes) and ctype.startswith("audio"):
            return data
        if isinstance(data, dict):
            st = str(data.get("status", "")).lower()
            if st in ("done", "completed", "succeeded"):
                aud = data.get("audio") or data.get("audio_base64")
                if aud:
                    import base64 as _b64
                    try:
                        return _b64.b64decode(aud)
                    except Exception:  # noqa: BLE001
                        pass
                _job_fail(jid, "La música terminó pero no trajo audio.")
                return None
            if st in ("failed", "error"):
                _job_fail(jid, f"ElevenLabs: {data.get('error', 'falló la generación')}")
                return None
    _job_fail(jid, "Se acabó el tiempo esperando la música. Inténtalo de nuevo.")
    return None


# ================================================================ VIDEO
@app.post("/api/video")
def api_video_create():
    keys = _get_keys()
    if not keys["fal"]:
        return jsonify({"ok": False, "error":
                        "Falta la llave de fal.ai. Ponla en la pestaña ⚙️ Ajustes."}), 400
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    mode = data.get("mode") or "text"
    model_key = data.get("model") or "veo3"
    image_url = (data.get("image_url") or "").strip()
    model = VIDEO_MODELS.get(model_key)
    if not model:
        return jsonify({"ok": False, "error": "Modelo no válido."}), 400
    if not prompt:
        return jsonify({"ok": False, "error":
                        "Describe la escena del video primero. 🎬"}), 400
    if len(prompt) > 2000:
        return jsonify({"ok": False, "error":
                        "La descripción es muy larga (máximo 2000 caracteres)."}), 400
    if mode not in ("text", "image"):
        mode = "text"
    if mode == "image":
        if not image_url or not URL_RE.match(image_url):
            return jsonify({"ok": False, "error":
                            "Para imagen→video necesito la URL pública de la imagen."}), 400
    try:
        secs = int(data.get("secs") or model["def_s"])
    except (TypeError, ValueError):
        secs = model["def_s"]
    secs = max(2, min(model["max_s"], secs))
    cost_est = round(secs * model["usd_s"], 2)
    endpoint = model["image_id"] if mode == "image" else model["text_id"]
    job = _job_new("video", prompt[:60],
                   {"prompt": prompt, "mode": mode, "model": model_key,
                    "endpoint": endpoint, "image_url": image_url,
                    "secs": secs}, cost_est=cost_est)
    t = threading.Thread(target=_video_worker,
                         args=(job["id"], keys["fal"]), daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job["id"], "cost_est": cost_est})


def _fal_payload(model_key, mode, prompt, image_url, secs):
    full = {"prompt": prompt, "aspect_ratio": "9:16"}
    if mode == "image":
        full["image_url"] = image_url
    if model_key == "kling":
        full["duration"] = str(secs)
    minimal = {"prompt": prompt}
    if mode == "image":
        minimal["image_url"] = image_url
    return full, minimal


def _video_worker(jid, key):
    job = _job_get(jid)
    if not job:
        return
    p = job["params"]
    headers = {"Authorization": "Key " + key,
               "Content-Type": "application/json"}
    submit_url = f"{FAL_QUEUE_BASE}/{p['endpoint']}"
    full, minimal = _fal_payload(p["model"], p["mode"], p["prompt"],
                                p["image_url"], p["secs"])
    _job_update(jid, status="working", progress="Mandando el pedido a fal.ai… 📤")
    st, _, data, err = _http("POST", submit_url, headers,
                             json.dumps(full).encode(), timeout=120)
    if err and st in (400, 422):
        # Retry once with the minimal payload (some models are picky).
        st, _, data, err = _http("POST", submit_url, headers,
                                 json.dumps(minimal).encode(), timeout=120)
    if err or not isinstance(data, dict) or not data.get("request_id"):
        _job_fail(jid, f"fal.ai: {err or 'no devolvió request_id'}")
        return
    rid = data["request_id"]
    status_url = data.get("status_url",
                          f"{submit_url}/requests/{rid}/status")
    response_url = data.get("response_url",
                            f"{submit_url}/requests/{rid}/response")
    cancel_url = data.get("cancel_url",
                          f"{submit_url}/requests/{rid}/cancel")
    _job_update(jid, params={**p, "request_id": rid,
                             "cancel_url": cancel_url})
    deadline = _time.time() + 30 * 60
    while _time.time() < deadline:
        if (_job_get(jid) or {}).get("status") == "cancelled":
            return
        st, _, sdata, serr = _http("GET", status_url, headers, timeout=60)
        if serr or not isinstance(sdata, dict):
            _time.sleep(5)
            continue
        status = sdata.get("status")
        if status == "COMPLETED":
            break
        if status in ("FAILED",):
            _job_fail(jid, f"fal.ai: {sdata.get('error', 'falló la generación')}")
            return
        qp = sdata.get("queue_position")
        prog = ("En la cola… ⏳" if status == "IN_QUEUE"
                else "Generando el video… 🎥")
        if isinstance(qp, int) and qp > 0:
            prog += f" (posición {qp})"
        _job_update(jid, progress=prog)
        _time.sleep(5)
    else:
        _job_fail(jid, "Se acabó el tiempo esperando el video.")
        return
    if (_job_get(jid) or {}).get("status") == "cancelled":
        return
    _job_update(jid, progress="Bajando el video… ⬇️")
    st, _, rdata, rerr = _http("GET", response_url, headers, timeout=120)
    if rerr or not isinstance(rdata, dict):
        _job_fail(jid, f"fal.ai: {rerr or 'sin resultado'}")
        return
    vurl = None
    v = rdata.get("video")
    if isinstance(v, dict):
        vurl = v.get("url")
    elif isinstance(v, str):
        vurl = v
    vurl = vurl or rdata.get("video_url")
    if not vurl:
        _job_fail(jid, "fal.ai no devolvió URL de video.")
        return
    fname = f"video-{jid}.mp4"
    dest = os.path.join(OUTPUT_DIR, fname)
    try:
        req = _ureq.Request(vurl, headers={"User-Agent": "SAHJONY-Studio/1.0"})
        with _ureq.urlopen(req, timeout=600) as resp, \
                open(dest, "wb") as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
    except Exception as exc:  # noqa: BLE001
        _job_fail(jid, f"No se pudo bajar el video: {exc}")
        return
    _job_update(jid, status="done", progress="¡Listo! 🎉",
                result={"file": fname, "url": f"/video/{fname}",
                        "secs": probe_duration(dest)})


@app.post("/api/jobs/<jid>/cancel")
def api_job_cancel(jid):
    job = _job_get(jid)
    if not job:
        return jsonify({"ok": False, "error": "Trabajo no válido."}), 404
    if job.get("status") in ("done", "error", "cancelled"):
        return jsonify({"ok": True})
    if job.get("kind") == "video":
        curl = (job.get("params") or {}).get("cancel_url")
        key = _get_keys()["fal"]
        if curl and key:
            _http("POST", curl, {"Authorization": "Key " + key},
                  timeout=30)
    _job_update(jid, status="cancelled", progress="Cancelado.")
    return jsonify({"ok": True})


@app.get("/api/jobs")
def api_jobs():
    kind = request.args.get("kind") or "music"
    if kind not in ("music", "video", "produce"):
        kind = "music"
    return jsonify({"ok": True, "jobs": _jobs_list(kind)})


@app.get("/api/jobs/<jid>")
def api_job_get(jid):
    job = _job_get(jid)
    if not job:
        return jsonify({"ok": False, "error": "Trabajo no válido."}), 404
    return jsonify({"ok": True, "job": job})


# ============================================================== PRODUCE
def _resolve_media(fname):
    """Safe path for a studio file (outputs or uploads). None if invalid."""
    if not fname or "/" in fname or "\\" in fname:
        return None
    if not (AUDIO_RE.match(fname) or VIDEO_RE.match(fname)
            or SAFE_MEDIA_RE.match(fname)):
        return None
    for d in (OUTPUT_DIR, UPLOAD_DIR):
        p = os.path.join(d, fname)
        if os.path.isfile(p):
            return p
    return None


def _fmt_srt(secs):
    ms = int(round(max(0, secs) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _make_srt(text, total_s, path):
    words = (text or "").split()
    if not words:
        return False
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 7:
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        chunks.append(" ".join(cur))
    per = total_s / len(chunks)
    with open(path, "w", encoding="utf-8") as fh:
        for i, ch in enumerate(chunks):
            fh.write(f"{i + 1}\n{_fmt_srt(i * per)} --> "
                     f"{_fmt_srt((i + 1) * per)}\n{ch}\n\n")
    return True


def _find_font():
    try:
        proc = subprocess.run(["fc-match", "-f", "%{file}\n", "DejaVu Sans"],
                              capture_output=True, text=True, timeout=15)
        p = (proc.stdout or "").strip().splitlines()
        if p and os.path.isfile(p[0]):
            return p[0]
    except Exception:  # noqa: BLE001
        pass
    return None


@app.post("/api/produce")
def api_produce():
    voice = _resolve_media((request.form.get("voice") or "").strip())
    if not voice:
        return jsonify({"ok": False, "error":
                        "Escoge el audio de la voz primero. 🎙️"}), 400
    music = _resolve_media((request.form.get("music") or "").strip())
    bg = _resolve_media((request.form.get("bg") or "").strip())
    if not bg:
        return jsonify({"ok": False, "error":
                        "Sube una imagen o video de fondo primero. 🖼️"}), 400
    logo = _resolve_media((request.form.get("logo") or "").strip())
    script = (request.form.get("script") or "").strip()
    brand = (request.form.get("brand") or "SAHJONY").strip()[:40] or "SAHJONY"
    if not script:
        return jsonify({"ok": False, "error":
                        "Escribe el guion para los subtítulos. ✍️"}), 400
    dur = probe_duration(voice) or 10
    dur = max(3, min(300, dur))
    job = _job_new("produce", script[:60],
                   {"voice": os.path.basename(voice),
                    "music": os.path.basename(music) if music else None,
                    "bg": os.path.basename(bg),
                    "logo": os.path.basename(logo) if logo else None,
                    "script": script, "brand": brand, "dur": dur})
    t = threading.Thread(target=_produce_worker, args=(job["id"],),
                         daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job["id"]})


def _produce_worker(jid):
    job = _job_get(jid)
    p = job["params"]
    voice = _resolve_media(p["voice"])
    music = _resolve_media(p["music"]) if p.get("music") else None
    bg = _resolve_media(p["bg"])
    logo = _resolve_media(p["logo"]) if p.get("logo") else None
    if not voice or not bg:
        _job_fail(jid, "Faltan archivos. Inténtalo de nuevo.")
        return
    dur = p["dur"]
    srt = os.path.join(JOBS_DIR, f"{jid}.srt")
    out = os.path.join(OUTPUT_DIR, f"final-{jid}.mp4")
    _job_update(jid, status="working", progress="Armando los subtítulos… ✍️")
    _make_srt(p["script"], dur, srt)

    is_video_bg = os.path.splitext(bg)[1].lower() in (".mp4", ".mov")
    frames = int(dur * 30)
    font = _find_font()
    style = ("FontSize=26,PrimaryColour=&HFFFFFF,OutlineColour=&H90000000,"
             "BorderStyle=1,Outline=2,Shadow=0,MarginV=140,Alignment=2,Bold=1")

    inputs = []
    if is_video_bg:
        inputs += ["-stream_loop", "-1", "-i", bg]
    else:
        inputs += ["-loop", "1", "-framerate", "30", "-t", str(dur),
                   "-i", bg]
    inputs += ["-i", voice]
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]
    if logo:
        inputs += ["-i", logo]

    # --- video filter chain
    if is_video_bg:
        vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
              "crop=1080:1920,setsar=1,fps=30,format=yuv420p[vbase]")
    else:
        vf = (f"[0:v]scale=2160:3840,zoompan=z='min(max(zoom,pzoom)+0.0015,1.25)':"
              f"d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"s=1080x1920:fps=30,format=yuv420p[vbase]")
    last_v = "[vbase]"
    a_idx, next_i = 1, 2
    if music:
        next_i = 3
    if logo:
        # scale logo to a sane width, overlay it sliding gently at the top
        vf += (f";[{next_i}:v]scale=420:-1[logo];{last_v}[logo]overlay="
               f"x='(W-w)/2+40*sin(2*PI*t/8)':y=64:format=auto[vlogo]")
        last_v = "[vlogo]"
        next_i += 1
    vf += f";{last_v}subtitles='{srt}':force_style='{style}'[vsub]"
    last_v = "[vsub]"
    if font and not logo:
        # moving text brand when there is no logo image
        brand = p["brand"].replace("'", "").replace(":", "")
        vf += (f";{last_v}drawtext=fontfile='{font}':text='{brand}':"
               f"fontsize=46:fontcolor=white@0.88:borderw=2:bordercolor=black@0.55:"
               f"x='(w-text_w)/2+50*sin(2*PI*t/8)':y=84[vout]")
        last_v = "[vout]"

    # --- audio: voice always clear, music ducked underneath
    if music:
        af = (f"[{a_idx}:a][{a_idx + 1}:a]amix=inputs=2:duration=first:"
              f"weights='1 0.12',aformat=sample_fmts=fltp:channel_layouts=stereo[aout]")
    else:
        af = f"[{a_idx}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[aout]"

    cmd = (["ffmpeg", "-y", "-loglevel", "error"] + inputs +
           ["-filter_complex", vf + ";" + af,
            "-map", last_v, "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", "-shortest", out])
    _job_update(jid, progress="Mezclando voz, música y video… 🎥 (tarda unos minutos)")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=1500)
    except subprocess.TimeoutExpired:
        _job_fail(jid, "Tardó demasiado armando el video.")
        return
    try:
        os.remove(srt)
    except OSError:
        pass
    if proc.returncode != 0 or not os.path.isfile(out):
        _job_fail(jid, "No se pudo armar el video. Inténtalo de nuevo.")
        return
    fname = os.path.basename(out)
    note = None if font or logo else " (sin marca de texto: falta fuente)"
    _job_update(jid, status="done",
                progress=f"¡Video listo! 🎉{note or ''}",
                result={"file": fname, "url": f"/video/{fname}",
                        "secs": probe_duration(out)})


@app.get("/video/<fname>")
def serve_video(fname):
    if not VIDEO_RE.match(fname):
        return jsonify({"ok": False, "error": "Archivo no válido."}), 404
    path = os.path.join(OUTPUT_DIR, fname)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "No existe ese video."}), 404
    return send_file(path, mimetype="video/mp4",
                     download_name=fname, as_attachment=False)


@app.get("/api/outputs")
def api_outputs():
    audios, videos = [], []
    try:
        names = sorted(os.listdir(OUTPUT_DIR))
    except OSError:
        names = []
    for n in names:
        full = os.path.join(OUTPUT_DIR, n)
        if AUDIO_RE.match(n):
            kind = ("musica" if n.startswith("music-")
                    else "voz")
            audios.append({"name": n, "url": f"/audio/{n}",
                           "kind": kind, "secs": probe_duration(full)})
        elif VIDEO_RE.match(n):
            kind = ("final" if n.startswith("final-")
                    else "video")
            videos.append({"name": n, "url": f"/video/{n}",
                           "kind": kind, "secs": probe_duration(full)})
    return jsonify({"ok": True, "audios": audios, "videos": videos})


# ==================================================== public media (fal.ai)
def _media_tokens():
    try:
        with open(MEDIA_TOKENS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _media_tokens_save(d):
    with open(MEDIA_TOKENS_FILE, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    os.chmod(MEDIA_TOKENS_FILE, 0o600)


@app.post("/api/upload")
def api_upload():
    """Upload image/video/audio -> local file + public URL (for fal.ai)."""
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"ok": False, "error": "Escoge un archivo."}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXTS | ALLOWED_PHOTO_EXTS | {".mp4", ".mov"}:
        return jsonify({"ok": False, "error":
                        "Formato no válido (audio, imagen o mp4)."}), 400
    fname = f"up-{uuid.uuid4().hex}{ext}"
    dest = os.path.join(UPLOAD_DIR, fname)
    try:
        f.save(dest)
    except OSError as exc:
        return jsonify({"ok": False, "error": f"No se pudo subir: {exc}"}), 500
    token = uuid.uuid4().hex
    toks = _media_tokens()
    toks[token] = fname
    _media_tokens_save(toks)
    public_url = f"{STUDIO_PUBLIC}/media/{token}/{fname}"
    return jsonify({"ok": True, "file": fname,
                    "local_url": f"/uploads-file/{fname}",
                    "public_url": public_url})


@app.get("/uploads-file/<fname>")
def serve_upload(fname):
    if not SAFE_MEDIA_RE.match(fname):
        return jsonify({"ok": False, "error": "Archivo no válido."}), 404
    path = os.path.join(UPLOAD_DIR, fname)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "No existe."}), 404
    ext = os.path.splitext(fname)[1].lower()
    mt = {"mp4": "video/mp4", "mov": "video/mp4",
          "mp3": "audio/mpeg", "wav": "audio/wav",
          "m4a": "audio/mp4", "png": "image/png",
          "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")
    return send_file(path, mimetype=mt)


@app.get("/media/<token>/<fname>")
def serve_media(token, fname):
    """Public signed URL so fal.ai can fetch an uploaded image."""
    toks = _media_tokens()
    if not JOB_RE.match(token or "") or toks.get(token) != fname:
        return jsonify({"ok": False, "error": "No válido."}), 404
    return serve_upload(fname)


# ============================================================== PUBLISH
def _publish_list():
    try:
        with open(PUBLISH_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def _publish_save(items):
    with open(PUBLISH_FILE, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)


PLATFORMS = ["TikTok", "Instagram", "Facebook", "YouTube", "Threads"]


@app.get("/api/publish")
def api_publish_list():
    return jsonify({"ok": True, "items": _publish_list(),
                    "platforms": PLATFORMS})


@app.post("/api/publish")
def api_publish_add():
    data = request.get_json(silent=True) or {}
    fname = (data.get("file") or "").strip()
    caption = (data.get("caption") or "").strip()
    platforms = [p for p in (data.get("platforms") or [])
                 if p in PLATFORMS]
    if not VIDEO_RE.match(fname) or not os.path.isfile(
            os.path.join(OUTPUT_DIR, fname)):
        return jsonify({"ok": False, "error":
                        "Escoge un video final primero. 🎥"}), 400
    if not caption:
        return jsonify({"ok": False, "error":
                        "Escribe el texto que acompaña al video. ✍️"}), 400
    if not platforms:
        return jsonify({"ok": False, "error":
                        "Marca al menos una red social."}), 400
    items = _publish_list()
    items.append({"id": uuid.uuid4().hex, "file": fname,
                  "url": f"/video/{fname}", "caption": caption,
                  "platforms": platforms, "status": "borrador",
                  "created": _time.time()})
    _publish_save(items)
    return jsonify({"ok": True})


@app.post("/api/publish/<pid>/approve")
def api_publish_approve(pid):
    items = _publish_list()
    for it in items:
        if it["id"] == pid:
            it["status"] = "aprobado"
    _publish_save(items)
    return jsonify({"ok": True})


@app.post("/api/publish/<pid>/unapprove")
def api_publish_unapprove(pid):
    items = _publish_list()
    for it in items:
        if it["id"] == pid:
            it["status"] = "borrador"
    _publish_save(items)
    return jsonify({"ok": True})


@app.delete("/api/publish/<pid>")
def api_publish_delete(pid):
    _publish_save([it for it in _publish_list() if it["id"] != pid])
    return jsonify({"ok": True})


# ============================================================== SETTINGS
@app.get("/api/settings")
def api_settings():
    keys = _get_keys()
    return jsonify({"ok": True,
                    "elevenlabs_set": bool(keys["elevenlabs"]),
                    "fal_set": bool(keys["fal"]),
                    "music_note": (f"Canción con letra o instrumental. "
                                   f"Costo aprox. ${MUSIC_USD_PER_MIN:.2f} por minuto "
                                   f"(redondeado al minuto). Verifica precios en elevenlabs.io/pricing."),
                    "video_note": ("Clips de 2 a 10 s según el modelo. "
                                   "Veo 3 Fast ~$0.40/s · Kling ~$0.07/s · Hailuo ~$0.055/s "
                                   "(aprox., verifica en fal.ai)."),
                    "license_note": ("Ojo: las voces clonadas aquí (XTTS v2) no tienen "
                                     "licencia comercial. No las uses en contenido "
                                     "monetizado ni para clientes sin revisar licencias.")})


@app.post("/api/settings")
def api_settings_save():
    data = request.get_json(silent=True) or {}
    _set_keys(data)
    return jsonify({"ok": True,
                    "msg": "Llaves guardadas. 🔐"})


# --- end SAHJONY Studio 360 ---


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)