#!/usr/bin/env python3
"""Parche idempotente de /opt/sahjony-packages/app/main.py — seguridad Supabase.

Uso en el VPS:
  python3 patch_main.py --check    # solo reporta qué parches aplicarían
  python3 patch_main.py --apply    # aplica, con respaldo previo

Cada parche exige un número exacto de coincidencias; si alguno falla,
no se escribe nada.
"""
import re
import shutil
import sys
import time

MAIN = "/opt/sahjony-packages/app/main.py"

PATCHES = []

# ---------------------------------------------------------------- P-A: throttle + _login_user al inicio de staff_login
PATCHES.append({
    "name": "P-A staff_login throttle",
    "regex": r"(?m)^[ \t]*ok = False[ \t]*$",
    "count": 1,
    "new": """    ok = False
    _login_user = None
    try:
        import supa as _supa
        _ip = request.client.host if request.client else "?"
        if not _supa.throttle_ok("staff-login:%s" % _ip, 10, 300):
            return templates.TemplateResponse(
                "login.html",
                {"request": request,
                 "error": "Demasiados intentos. Espera 5 minutos.",
                 "configured": True},
                status_code=429,
            )
        _supa.throttle_hit("staff-login:%s" % _ip)
    except Exception as _e:
        print("[staff] throttle: %s" % _e, flush=True)""",
})

# ---------------------------------------------------------------- P-B: usuarios Supabase tras el check de env
PATCHES.append({
    "name": "P-B staff_login usuarios supabase",
    "old": '''    if not ok:
        return templates.TemplateResponse(
            "login.html",
''',
    "count": 1,
    "new": '''    if not ok:
        try:
            import supa as _supa
            if _supa.sb_enabled():
                _r = _supa.staff_user_get(username)
                if _r and _supa.verify_password(password, _r["pw_hash"]):
                    ok = True
                    _login_user = _r["username"]
        except Exception as _e:
            print("[staff] users: %s" % _e, flush=True)
    if not ok:
        return templates.TemplateResponse(
            "login.html",
''',
})

# ---------------------------------------------------------------- P-C: sesión Supabase al entrar
PATCHES.append({
    "name": "P-C staff_login sesion supabase",
    "old": '''    resp = RedirectResponse("/staff/dashboard", status_code=303)
    resp.set_cookie(_SESSION_COOKIE, _session_value(STAFF_USER),
                    httponly=True, samesite="lax", max_age=SESSION_TTL, path="/")
    return resp
''',
    "count": 1,
    "new": '''    resp = RedirectResponse("/staff/dashboard", status_code=303)
    _sess = None
    try:
        import supa as _supa
        if _supa.sb_enabled():
            _sess = _supa.staff_session_create(_login_user or STAFF_USER)
    except Exception as _e:
        print("[staff] session: %s" % _e, flush=True)
    resp.set_cookie(_SESSION_COOKIE, _sess or _session_value(STAFF_USER),
                    httponly=True, samesite="lax", max_age=SESSION_TTL, path="/")
    return resp
''',
})

# ---------------------------------------------------------------- P-D: _valid_session con Supabase + respaldo HMAC
PATCHES.append({
    "name": "P-D _valid_session supabase",
    "old": '''def _valid_session(request: Request) -> bool:
    if not (STAFF_USER and SESSION_SECRET):
        return False
    raw = request.cookies.get(_SESSION_COOKIE, "")
    try:
        username, exp, sig = raw.split(":")
    except ValueError:
        return False
    if username != STAFF_USER:
        return False
    try:
        if int(exp) < int(time.time()):
            return False
    except ValueError:
        return False
    want = _hmac.new(SESSION_SECRET.encode(), f"{username}:{exp}".encode(),
                     _hashlib.sha256).hexdigest()
    return _hmac.compare_digest(want, sig)
''',
    "count": 1,
    "new": '''def _valid_session_hmac(raw: str):
    """Valida el formato anterior de cookie firmada (respaldo)."""
    if not (STAFF_USER and SESSION_SECRET):
        return None
    try:
        username, exp, sig = raw.split(":")
    except ValueError:
        return None
    if username != STAFF_USER:
        return None
    try:
        if int(exp) < int(time.time()):
            return None
    except ValueError:
        return None
    want = _hmac.new(SESSION_SECRET.encode(), f"{username}:{exp}".encode(),
                     _hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(want, sig):
        return None
    return username


def _valid_session(request: Request):
    """Sesión de staff: Supabase primero (staff_sessions), respaldo HMAC.

    Devuelve el username si es válida, None si no. Si Supabase no responde,
    se usa el formato anterior para no bloquear al personal."""
    raw = request.cookies.get(_SESSION_COOKIE, "")
    if not raw:
        return None
    try:
        import supa as _supa
    except ImportError:
        return _valid_session_hmac(raw)
    try:
        user = _supa.staff_session_check(raw)
        if user:
            return user
    except Exception as e:
        print("[staff] supabase no responde, respaldo HMAC: %s" % e, flush=True)
    return _valid_session_hmac(raw)
''',
})

# ---------------------------------------------------------------- P-E: exponer staff_user en el middleware
PATCHES.append({
    "name": "P-E middleware staff_user",
    "old": "    request.state.staff_session = _valid_session(request)\n",
    "count": 1,
    "new": ("    request.state.staff_session = _valid_session(request)\n"
            "    request.state.staff_user = request.state.staff_session or None\n"),
})

# ---------------------------------------------------------------- P-F: middleware CSRF por origen
PATCHES.append({
    "name": "P-F csrf middleware",
    "old": "# ---------------------------------------------------------------- auth/throttle\n",
    "count": 1,
    "new": '''# ---------------------------------------------------------------- CSRF por origen
# Los navegadores mandan Origin/Referer en los POST. Si el origen no es el
# nuestro, se bloquea (segunda capa además de SameSite=Lax).


@app.middleware("http")
async def _csrf_origin_mw(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        path = request.url.path or ""
        if path.startswith(("/staff/", "/agencia/", "/portal/")):
            import urllib.parse as _up
            host = (request.headers.get("host") or "").split(":")[0].lower()
            origin = request.headers.get("origin") or ""
            referer = request.headers.get("referer") or ""
            ok = True
            if origin:
                ok = (_up.urlparse(origin).hostname or "").lower() == host
            elif referer:
                ok = (_up.urlparse(referer).hostname or "").lower() == host
            if not ok:
                return HTMLResponse("Petición bloqueada: origen no válido.",
                                    status_code=403)
    return await call_next(request)


# ---------------------------------------------------------------- auth/throttle
''',
})

# ---------------------------------------------------------------- P-G: revocar sesión al salir
PATCHES.append({
    "name": "P-G staff_logout revoke",
    "old": '''@app.get("/staff/logout")
def staff_logout(request: Request):
    resp = RedirectResponse("/staff/login", status_code=303)
    resp.delete_cookie(_SESSION_COOKIE, path="/")
    return resp
''',
    "count": 1,
    "new": '''@app.get("/staff/logout")
def staff_logout(request: Request):
    try:
        import supa as _supa
        _supa.staff_session_revoke(request.cookies.get(_SESSION_COOKIE, ""))
    except Exception:
        pass
    resp = RedirectResponse("/staff/login", status_code=303)
    resp.delete_cookie(_SESSION_COOKIE, path="/")
    return resp
''',
})

# ---------------------------------------------------------------- P-H: rutas staff usuarios + recuperación
PATCHES.append({
    "name": "P-H staff usuarios/recuperacion",
    "old": "# ---------------------------------------------------------------- portal de clientes (Juan, 2026-09-22)\n",
    "count": 1,
    "new": '''# ---------------------------------------------------------------- staff: usuarios y recuperación (2026-09-24)
# Cuentas individuales de staff en Supabase (staff_users); sesiones en
# staff_sessions (se sabe quién hizo qué). Recuperación de agencias con
# enlace de un solo uso (agency_resets).


def _staff_html(title: str, body: str) -> str:
    from html import escape as _he
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>"
            "body{font-family:system-ui,sans-serif;max-width:720px;margin:0 auto;"
            "padding:12px;background:#f6f4ee;color:#222}"
            ".card{background:#fff;border-radius:12px;padding:14px;margin:12px 0}"
            ".btn{display:inline-block;background:#0d3b66;color:#fff;border:0;"
            "border-radius:10px;padding:12px 18px;font-size:16px;cursor:pointer}"
            "input{width:100%;padding:12px;border:1px solid #ccc;border-radius:10px;"
            "font-size:16px;margin:6px 0}table{width:100%;border-collapse:collapse}"
            "td,th{padding:8px;border-bottom:1px solid #eee;text-align:left}"
            ".err{background:#fdecea;border:1px solid #c00;border-radius:10px;padding:12px}"
            ".okmsg{background:#e6f4ea;border:1px solid #1a7a3a;border-radius:10px;padding:12px}"
            ".muted{color:#777;font-size:13px}"
            "</style></head><body><div class='card'><h2>%s</h2>%s</div>"
            "<p><a href='/staff/dashboard'>&larr; Panel</a></p></body></html>"
            % (_he(title), _he(title), body))


@app.get("/staff/usuarios", response_class=HTMLResponse)
def staff_users_page(request: Request, token: str = Depends(require_staff)):
    import supa as _supa
    from html import escape as _he
    err, users = "", []
    if _supa.sb_enabled():
        try:
            users = _supa.staff_users_list()
        except Exception as e:
            err = "Supabase no responde: %s" % e
    else:
        err = "Supabase no está configurado en este servidor."
    rows = "".join(
        "<tr><td>%s</td><td>%s</td></tr>"
        % (_he(u.get("username", "")), _he(str(u.get("created_at", ""))))
        for u in users)
    body = (("<div class='err'>%s</div>" % _he(err)) if err else "")
    body += ("<table><tr><th>Usuario</th><th>Creado</th></tr>%s</table>" % rows
             + "<h3>Crear usuario</h3>"
             "<form method='post'>"
             "<input name='username' placeholder='usuario' required autocomplete='off'>"
             "<input name='password' type='password' placeholder='contraseña (mín 8)' "
             "required autocomplete='new-password'>"
             "<button class='btn'>Crear</button></form>"
             "<p class='muted'>Cada persona del staff entra con su propio usuario en "
             "/staff/login. Las sesiones quedan registradas en Supabase.</p>")
    return HTMLResponse(_staff_html("Usuarios de staff", body))


@app.post("/staff/usuarios", response_class=HTMLResponse)
async def staff_user_add(request: Request, token: str = Depends(require_staff)):
    import supa as _supa
    from html import escape as _he
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    err = ""
    if not _supa.sb_enabled():
        err = "Supabase no está configurado."
    elif len(username) < 3 or len(password) < 8:
        err = "Usuario mínimo 3 caracteres, contraseña mínimo 8."
    else:
        try:
            _supa.staff_user_create(username, password)
        except Exception as e:
            err = "No se pudo crear: %s" % e
    if err:
        return HTMLResponse(_staff_html(
            "Usuarios de staff",
            "<div class='err'>%s</div><p><a href='/staff/usuarios'>Volver</a></p>"
            % _he(err)))
    return RedirectResponse("/staff/usuarios", status_code=303)


@app.get("/staff/recuperacion", response_class=HTMLResponse)
def staff_reset_page(request: Request, token: str = Depends(require_staff)):
    body = ("<p>Genera un enlace de <b>un solo uso</b> (válido 1 hora) para que "
            "una agencia cree su contraseña. Compártelo por WhatsApp.</p>"
            "<form method='post'>"
            "<input name='email' type='email' placeholder='correo del dueño' required>"
            "<button class='btn'>Generar enlace</button></form>")
    return HTMLResponse(_staff_html("Recuperación de agencia", body))


@app.post("/staff/recuperacion", response_class=HTMLResponse)
async def staff_reset_make(request: Request,
                           token: str = Depends(require_staff)):
    import supa as _supa
    from html import escape as _he
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    err, link = "", ""
    if not _supa.sb_enabled():
        err = "Supabase no está configurado."
    else:
        try:
            tok = _supa.reset_create(email)
            link = ("https://paquetes.sahjony.com/agencia/recuperar?token=" + tok)
        except Exception as e:
            err = "No se pudo generar: %s" % e
    if err:
        body = "<div class='err'>%s</div>" % _he(err)
    else:
        body = ("<div class='okmsg'>Enlace válido por 1 hora, un solo uso:</div>"
                "<p style='word-break:break-all'><b>%s</b></p>"
                "<p class='muted'>Se muestra una sola vez. Cópialo y mándalo "
                "por WhatsApp.</p>" % _he(link))
    body += "<p><a href='/staff/recuperacion'>Generar otro</a></p>"
    return HTMLResponse(_staff_html("Recuperación de agencia", body))


# ---------------------------------------------------------------- portal de clientes (Juan, 2026-09-22)
''',
})

# ---------------------------------------------------------------- P-I: throttle del portal a Supabase
PATCHES.append({
    "name": "P-I portal throttle supabase",
    "old": '''def _portal_throttle_ok(key: str) -> bool:
    now = time.time()
    hits = [t for t in _PORTAL_ATTEMPTS.get(key, []) if now - t < 300]
    _PORTAL_ATTEMPTS[key] = hits
    return len(hits) < 10


def _portal_throttle_hit(key: str) -> None:
    _PORTAL_ATTEMPTS.setdefault(key, []).append(time.time())
''',
    "count": 1,
    "new": '''def _portal_throttle_ok(key: str) -> bool:
    try:
        import supa as _supa
        return _supa.throttle_ok("portal:" + key, 10, 300)
    except Exception:
        pass
    now = time.time()
    hits = [t for t in _PORTAL_ATTEMPTS.get(key, []) if now - t < 300]
    _PORTAL_ATTEMPTS[key] = hits
    return len(hits) < 10


def _portal_throttle_hit(key: str) -> None:
    try:
        import supa as _supa
        _supa.throttle_hit("portal:" + key)
    except Exception:
        pass
    _PORTAL_ATTEMPTS.setdefault(key, []).append(time.time())
''',
})

# ---------------------------------------------------------------- P-J: validación del registro público
PATCHES.append({
    "name": "P-Ja onboarding email valido",
    "old": '''    elif _has_placeholders(legal_name, brand, contact_name, phone, email,
                            address, city, state):
        error = ("Detectamos texto de ejemplo sin completar en el formulario. "
                 "Revísalo y envíalo con tus datos reales.")
''',
    "count": 1,
    "new": '''    elif _has_placeholders(legal_name, brand, contact_name, phone, email,
                            address, city, state):
        error = ("Detectamos texto de ejemplo sin completar en el formulario. "
                 "Revísalo y envíalo con tus datos reales.")
    elif not _re.match(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]{2,}$", (email or "").strip()):
        error = "Ese correo no parece válido. Revísalo (ejemplo: nombre@correo.com)."
''',
})

PATCHES.append({
    "name": "P-Jb onboarding duplicados",
    "old": '''    conn = dbmod.get_db()
    try:
        conn.execute(
            """INSERT INTO agencies (legal_name, brand, contact_name, phone, email,
''',
    "count": 1,
    "new": '''    conn = dbmod.get_db()
    _dup = conn.execute(
        "SELECT legal_name FROM agencies WHERE lower(legal_name)=lower(?) OR "
        "(? <> '' AND lower(email)=lower(?))",
        (legal_name.strip(), email.strip(), email.strip())).fetchone()
    if _dup:
        conn.close()
        return templates.TemplateResponse(
            "onboarding.html",
            {"request": request,
             "error": "Ya tenemos una solicitud o cuenta con ese nombre o correo. "
                      "Si eres tú, escríbenos y la revisamos juntos.",
             "terms": ONBOARDING_TERMS, "form": form},
            status_code=400,
        )
    try:
        conn.execute(
            """INSERT INTO agencies (legal_name, brand, contact_name, phone, email,
''',
})


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    src = open(MAIN, encoding="utf-8").read()
    problems = []
    for p in PATCHES:
        if "regex" in p:
            n = len(re.findall(p["regex"], src))
        else:
            n = src.count(p["old"])
        ok = (n == p["count"])
        print("%s %s: %d/%d" % ("OK " if ok else "FALLA", p["name"], n, p["count"]))
        if not ok:
            problems.append(p["name"])
    if problems:
        print("ABORTADO: %d parches sin ancla exacta." % len(problems))
        sys.exit(1)
    if mode == "--check":
        print("CHECK: todos los parches aplicarían limpio.")
        return
    if mode != "--apply":
        print("uso: patch_main.py --check | --apply")
        sys.exit(2)
    # ya aplicados antes: si aparece la marca, no hacer nada
    if "_valid_session_hmac" in src and "staff_users_page" in src:
        print("APPLY: parches ya presentes, nada que hacer.")
        return
    bak = "%s.pre-supabase-%s" % (MAIN, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(MAIN, bak)
    print("respaldo: %s" % bak)
    for p in PATCHES:
        if "regex" in p:
            src = re.sub(p["regex"], lambda m: p["new"], src, count=1)
        else:
            src = src.replace(p["old"], p["new"], 1)
    open(MAIN, "w", encoding="utf-8").write(src)
    print("APPLY: %d parches aplicados." % len(PATCHES))


if __name__ == "__main__":
    main()
