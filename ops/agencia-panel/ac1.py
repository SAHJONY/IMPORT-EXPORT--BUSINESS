"""Centro de comando — parte 1: acceso multi-locación, checklist, "más"."""
from __future__ import annotations

from ac_shared import *

router = APIRouter()


@router.get("/agencia/login", response_class=HTMLResponse)
def agencia_login_form(request: Request, error: str = ""):
    if _owner_ctx(request):
        return RedirectResponse("/agencia/panel", status_code=303)
    body = ('<div class="card"><h2>Entrar a mi agencia</h2>'
            + (('<div class="err">%s</div>' % _e(error)) if error else "") +
            '<form method="post"><label>Correo<input name="email" type="email" required '
            'autocomplete="username"></label>'
            '<label>Contraseña<input name="password" type="password" required '
            'autocomplete="current-password"></label>'
            '<button class="btn" style="width:100%">Entrar</button></form></div>')
    return HTMLResponse(_layout("Entrar",
                               {"email": "", "agencies": [], "multi": False, "unread": 0},
                               body))


@router.post("/agencia/login", response_class=HTMLResponse)
async def agencia_login(request: Request):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    ip = request.client.host if request.client else "?"
    key = "login:%s:%s" % (ip, email)
    if not _throttle_ok(key, 10, 300):
        return HTMLResponse(_layout(
            "Entrar", {"email": "", "agencies": [], "multi": False, "unread": 0},
            '<div class="card"><div class="err">Demasiados intentos. Espera 5 minutos.</div>'
            '<a class="btn sec" href="/agencia/login">Reintentar</a></div>'), status_code=429)
    _throttle_hit(key)
    conn = dbmod.get_db()
    try:
        rows = adb.owner_login(conn, email, password)
    finally:
        conn.close()
    if not rows:
        return HTMLResponse(_layout(
            "Entrar", {"email": "", "agencies": [], "multi": False, "unread": 0},
            '<div class="card"><div class="err">Correo o contraseña inválidos.</div>'
            '<a class="btn sec" href="/agencia/login">Reintentar</a></div>'), status_code=401)
    conn = dbmod.get_db()
    try:
        adb.audit(conn, rows[0]["id"], "owner", "login",
                  detail="email=%s locaciones=%d" % (email, len(rows)), actor_id=email)
        must = adb.owner_must_change(conn, email)
    finally:
        conn.close()
    resp = RedirectResponse("/agencia/password" if must else "/agencia/panel",
                            status_code=303)
    resp.set_cookie(_AGENCY_COOKIE, _new_session_value(email), httponly=True,
                    samesite="Lax", secure=_COOKIE_SECURE,
                    max_age=SESSION_TTL, path="/")
    return resp


@router.post("/agencia/logout")
def agencia_logout(request: Request):
    resp = RedirectResponse("/agencia/login", status_code=303)
    resp.delete_cookie(_AGENCY_COOKIE, path="/")
    return resp


@router.get("/agencia/password", response_class=HTMLResponse)
def agencia_password_form(request: Request):
    ctx, redir = _guard(request)
    if redir:
        return redir
    body = ('<div class="card"><h2>Crea tu contraseña</h2>'
            '<p class="muted">Es la misma para todas tus locaciones.</p>'
            '<form method="post">'
            '<label>Nueva contraseña (mínimo 8 caracteres)'
            '<input name="p1" type="password" required autocomplete="new-password"></label>'
            '<label>Repite la contraseña<input name="p2" type="password" required '
            'autocomplete="new-password"></label>'
            '<button class="btn ok" style="width:100%">Guardar</button></form></div>')
    return HTMLResponse(_layout("Contraseña", ctx, body))


@router.post("/agencia/password")
async def agencia_password(request: Request):
    ctx, redir = _guard(request)
    if redir:
        return redir
    form = await request.form()
    p1, p2 = form.get("p1") or "", form.get("p2") or ""
    if p1 != p2 or len(p1) < 8:
        raise HTTPException(400, "Las contraseñas no coinciden o son muy cortas (mínimo 8).")
    conn = dbmod.get_db()
    try:
        adb.owner_set_password(conn, ctx["email"], p1)
    finally:
        conn.close()
    return RedirectResponse("/agencia/panel", status_code=303)


@router.get("/agencia/mas", response_class=HTMLResponse)
def agencia_more(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    items = [("📦", "Paquetes", "/agencia/paquetes"),
             ("👥", "Clientes", "/agencia/clientes"),
             ("💲", "Mi lista de precios", "/agencia/precios"),
             ("🚚", "Embarques", "/agencia/embarques"),
             ("🧾", "Facturas", "/agencia/facturas"),
             ("💵", "Cobros", "/agencia/pagos"),
             ("🧮", "Gastos", "/agencia/gastos"),
             ("💳", "Cómo me pagan", "/agencia/metodos"),
             ("📊", "Mi economía", "/agencia/economia"),
             ("🤝", "Mi liquidación", "/agencia/liquidacion"),
             ("📎", "Documentos", "/agencia/documentos"),
             ("📷", "Escanear", "/agencia/escanear"),
             ("📍", "Rastreo interno", "/agencia/rastreo"),
             ("👤", "Mi perfil", "/agencia/perfil"),
             ("📜", "Términos", "/agencia/terminos"),
             ("🏪", "Nueva locación", "/agencia/nueva-locacion"),
             ("🔔", "Notificaciones", "/agencia/notificaciones"),
             ("✉️", "Plantillas", "/agencia/plantillas"),
             ("🧾", "Actividad", "/agencia/auditoria")]
    cards = "".join(
        '<a class="card" style="display:block;text-decoration:none;color:#222" href="%s">'
        '<b>%s %s</b></a>' % (u, ic, _e(t)) for ic, t, u in items)
    cards += ('<div class="card"><form method="post" action="/agencia/logout">'
              '<b>🚪</b> <button class="btn sm sec">Salir</button></form></div>')
    return HTMLResponse(_layout("Más", ctx, cards, active="mas"))


@router.get("/agencia/checklist", response_class=HTMLResponse)
def agencia_checklist(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        cl = adb.checklist(conn, ctx["agency_ids"])
    finally:
        conn.close()
    items = "".join(
        '<div class="card">%s <b>%s</b><br><a class="btn sm" href="%s">Hacerlo</a></div>'
        % ("✅" if done else "⬜", _e(label), url)
        for _key, label, url, done in cl["items"])
    body = ('<h2>Para empezar (%d de %d)</h2>' % (cl["done"], cl["total"]) + items +
            '<a class="btn" href="/agencia/panel">Ir al panel</a>')
    return HTMLResponse(_layout("Primeros pasos", ctx, body))
