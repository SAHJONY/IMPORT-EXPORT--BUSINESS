"""Centro de comando de agencias — base compartida.

Sesión multi-locación: la cookie firma el email del dueño (no el agency_id).
Todas las agencias activas con ese owner_email y login habilitado entran en la
sesión. Compatibilidad: también acepta la cookie vieja firmada por agency_id
y la promueve a sesión por email.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac as _hmac
import io
import os
import time
from html import escape as _escape

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
except ImportError:  # solo para py_compile local sin fastapi
    APIRouter = HTTPException = Request = object  # type: ignore
    HTMLResponse = RedirectResponse = StreamingResponse = object  # type: ignore

try:
    import db as dbmod
except ImportError:
    dbmod = None  # type: ignore
import agency_db as adb
import agency_docs as adocs

__all__ = ["APIRouter", "HTTPException", "Request", "HTMLResponse",
           "RedirectResponse", "StreamingResponse", "dbmod", "adb", "adocs",
           "os", "io", "csv", "SESSION_SECRET", "SESSION_TTL", "_AGENCY_COOKIE",
           "_COOKIE_SECURE",
           "_throttle_ok", "_throttle_hit", "_new_session_value", "_owner_ctx",
           "_guard", "_guard_strict", "_staff_ok", "_e", "_brand", "_addr", "CSS",
           "_layout", "_write_agency", "_order_scope", "_loc_options", "_loc_selector"]

SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
SESSION_TTL = 12 * 3600
_AGENCY_COOKIE = "_sjn_agency"
# En producción (HTTPS) la cookie debe viajar solo por TLS. En pruebas locales
# (http) se desactiva con AGENCY_COOKIE_SECURE=0.
_COOKIE_SECURE = os.environ.get("AGENCY_COOKIE_SECURE", "1") == "1"

# Throttle: Supabase primero (persistente entre reinicios), memoria como respaldo.
try:
    import supa as _supa
except ImportError:
    _supa = None  # type: ignore

_ATTEMPTS: dict[str, list[float]] = {}


def _throttle_ok(key: str, limit: int = 10, window: int = 300) -> bool:
    if _supa is not None:
        try:
            return _supa.throttle_ok("agencia:" + key, limit, window)
        except Exception:
            pass
    now = time.time()
    hits = [t for t in _ATTEMPTS.get(key, []) if now - t < window]
    _ATTEMPTS[key] = hits
    return len(hits) < limit


def _throttle_hit(key: str) -> None:
    if _supa is not None:
        try:
            _supa.throttle_hit("agencia:" + key)
        except Exception:
            pass
    _ATTEMPTS.setdefault(key, []).append(time.time())


def _b64e(email: str) -> str:
    return base64.urlsafe_b64encode(email.encode()).decode().rstrip("=")


def _b64d(token: str) -> str:
    return base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()


def _new_session_value(email: str) -> str:
    exp = str(int(time.time()) + SESSION_TTL)
    tok = _b64e(email.strip().lower())
    sig = _hmac.new(SESSION_SECRET.encode(), f"ag2:{tok}:{exp}".encode(),
                    hashlib.sha256).hexdigest()
    return f"ag2:{tok}:{exp}:{sig}"


def _session_email(request: Request) -> str | None:
    """Email firmado de la sesión, o None. Acepta formato nuevo y viejo."""
    if not SESSION_SECRET:
        return None
    raw = request.cookies.get(_AGENCY_COOKIE, "")
    parts = (raw or "").split(":")
    try:
        if len(parts) == 4 and parts[0] == "ag2":
            _, tok, exp, sig = parts
            if int(exp) < int(time.time()):
                return None
            want = _hmac.new(SESSION_SECRET.encode(), f"ag2:{tok}:{exp}".encode(),
                             hashlib.sha256).hexdigest()
            if not _hmac.compare_digest(want, sig):
                return None
            return _b64d(tok).strip().lower()
        if len(parts) == 3:
            # Formato viejo: agency_id firmado. Se promueve a sesión por email.
            aid, exp, sig = parts
            aid = int(aid)
            if int(exp) < int(time.time()):
                return None
            want = _hmac.new(SESSION_SECRET.encode(), f"ag:{aid}:{exp}".encode(),
                             hashlib.sha256).hexdigest()
            if not _hmac.compare_digest(want, sig):
                return None
            if dbmod is None:
                return None
            conn = dbmod.get_db()
            try:
                r = conn.execute(
                    "SELECT owner_email FROM agencies WHERE id=? AND owner_login_enabled=1",
                    (aid,)).fetchone()
                return (r["owner_email"] or "").strip().lower() if r else None
            finally:
                conn.close()
    except (ValueError, AttributeError):
        return None
    return None


def _owner_ctx(request: Request) -> dict | None:
    """Contexto de sesión multi-locación, o None."""
    if dbmod is None:
        return None
    email = _session_email(request)
    if not email:
        return None
    conn = dbmod.get_db()
    try:
        agencies = adb.owner_agencies(conn, email)
        if not agencies:
            return None
        unread = 0
        try:
            for a in agencies:
                unread += dbmod.count_unread_agency_messages(conn, a["id"])
        except Exception:
            pass
        return {"email": email, "agencies": agencies,
                "agency_ids": [a["id"] for a in agencies],
                "multi": len(agencies) > 1, "unread": unread}
    finally:
        conn.close()


def _guard(request: Request):
    ctx = _owner_ctx(request)
    if not ctx:
        return None, RedirectResponse("/agencia/login", status_code=303)
    return ctx, None


def _needs_password(request: Request, ctx: dict) -> bool:
    conn = dbmod.get_db()
    try:
        return adb.owner_must_change(conn, ctx["email"])
    finally:
        conn.close()


def _guard_strict(request: Request):
    """Como _guard, pero exige contraseña definitiva (no temporal)."""
    ctx, redir = _guard(request)
    if redir:
        return None, redir
    if _needs_password(request, ctx):
        return None, RedirectResponse("/agencia/password", status_code=303)
    return ctx, None


def _staff_ok(request: Request) -> bool:
    return bool(getattr(request.state, "staff_session", False))


# ---------------------------------------------------------------- formato
def _e(s) -> str:
    return _escape("" if s is None else str(s))


def _brand(ag) -> str:
    return (ag["brand"] or ag["legal_name"] or "Mi agencia").strip()


def _addr(ag) -> str:
    bits = [ag["address"] or "", ag["city"] or "", ag["state"] or ""]
    return ", ".join(b for b in bits if b).strip(", ")


CSS = """
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
margin:0;background:#f6f4ee;color:#222;max-width:760px;margin:0 auto;padding:0 12px 90px}
header.top{background:#0d3b66;color:#fff;padding:10px 12px;margin:0 -12px 12px;
position:sticky;top:0;z-index:10}
header.top .row{display:flex;align-items:center;gap:8px}
header.top select{background:#fff;border:0;border-radius:8px;padding:10px;font-size:15px;max-width:60%}
.bell{background:#fff;color:#0d3b66;border-radius:20px;padding:8px 12px;text-decoration:none;font-weight:700}
nav.tabs{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #ddd;
display:flex;z-index:10;max-width:760px;margin:0 auto}
nav.tabs a{flex:1;text-align:center;padding:12px 4px;font-size:12px;color:#0d3b66;text-decoration:none}
nav.tabs a.on{background:#0d3b66;color:#fff}
.card{background:#fff;border-radius:12px;padding:14px;margin:12px 0;box-shadow:0 1px 3px #0001}
.btn{display:inline-block;background:#0d3b66;color:#fff;border:0;border-radius:10px;
padding:12px 18px;font-size:16px;text-decoration:none;min-height:44px;cursor:pointer}
.btn.sec{background:#e8e4d8;color:#0d3b66}.btn.ok{background:#1a7a3a}.btn.sm{padding:8px 12px;font-size:14px;min-height:36px}
label{display:block;margin:10px 0;font-weight:600}
input,select,textarea{width:100%;padding:12px;border:1px solid #ccc;border-radius:10px;font-size:16px;background:#fff}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;margin:12px 0}
td,th{padding:10px;border-bottom:1px solid #eee;text-align:left;font-size:14px}
.muted{color:#777;font-size:13px}.alert{background:#fff3cd;border:1px solid #e6c200;border-radius:10px;padding:12px;margin:12px 0}
.okmsg{background:#e6f4ea;border:1px solid #1a7a3a;border-radius:10px;padding:12px;margin:12px 0}
.err{background:#fdecea;border:1px solid #c00;border-radius:10px;padding:12px;margin:12px 0}
.badge{display:inline-block;background:#0d3b66;color:#fff;border-radius:12px;padding:2px 10px;font-size:12px}
.badge.red{background:#c0392b}.badge.green{background:#1a7a3a}.badge.amber{background:#b7791f}
.kpi{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.kpi .card{margin:0;text-align:center}.kpi b{font-size:22px;display:block}
footer{margin:30px 0;text-align:center;color:#999;font-size:12px}
.sug{display:block;background:#eef4ff;border:1px dashed #0d3b66;border-radius:10px;
padding:10px;margin:8px 0;width:100%;text-align:left;font-size:15px;cursor:pointer}
@media print{.noprint,nav.tabs,header.top .row .bell{display:none!important}body{max-width:none;padding:0}}
"""


def _layout(title: str, ctx: dict, body: str, active: str = "",
            printable: bool = False) -> str:
    ctx = ctx or {}
    email = ctx.get("email") or ""
    multi = ctx.get("multi") or False
    agencies = ctx.get("agencies") or []
    unread = ctx.get("unread") or 0
    if multi:
        opts = '<option value="">Todas las locaciones</option>' + "".join(
            '<option value="%d">%s</option>' % (a["id"], _e(_brand(a))) for a in agencies)
        switcher = ('<select aria-label="Locación" onchange="var u=new URL(location.href);'
                    'if(this.value){u.searchParams.set(\'loc\',this.value)}'
                    'else{u.searchParams.delete(\'loc\')};location.href=u.toString()">%s</select>' % opts)
        brand_label = "Mis locaciones (%d)" % len(agencies)
    else:
        switcher = ""
        brand_label = _e(_brand(agencies[0])) if agencies else "Mi agencia"
    bell = ('<a class="bell" href="/agencia/mensajes">🔔%s</a>'
            % (" " + str(unread) if unread else ""))
    tabs = [("panel", "🏠 Panel", "/agencia/panel"),
            ("ordenes", "📦 Órdenes", "/agencia/ordenes"),
            ("mensajes", "💬 Msjs", "/agencia/mensajes"),
            ("mas", "⋯ Más", "/agencia/mas")]
    nav = "".join('<a href="%s"%s>%s</a>' % (u, ' class="on"' if active == k else "", l)
                  for k, l, u in tabs)
    staff_link = ""
    return ("""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title><style>%s</style></head><body>
<header class="top"><div class="row"><div><b>%s</b><br>
<span class="muted" style="color:#cfe0f5">%s</span></div>
<span style="flex:1"></span>%s%s</div></header>
%s<nav class="tabs">%s</nav><footer>Operado con SAHJONY LLC</footer></body></html>"""
            % (_e(title), CSS, brand_label, _e(email), bell, switcher, body, nav))


def _write_agency(ctx: dict, loc: str) -> dict:
    """Agencia autorizada para escribir. loc puede ser '' (primera) o un id."""
    ags = {a["id"]: a for a in ctx["agencies"]}
    try:
        lid = int(loc or 0)
    except (ValueError, TypeError):
        lid = 0
    if lid and lid in ags:
        return ags[lid]
    if not lid:
        return ctx["agencies"][0]
    from fastapi import HTTPException as _H
    raise _H(404, "Locación no autorizada")


def _order_scope(ctx: dict, loc: str):
    """(ids, working_id): ids para listar; working_id para formularios con locación."""
    ids = ctx["agency_ids"]
    ags = {a["id"]: a for a in ctx["agencies"]}
    try:
        lid = int(loc or 0)
    except (ValueError, TypeError):
        lid = 0
    wid = lid if lid in ags else ids[0]
    return ids, wid


def _loc_options(ctx: dict, wid: int) -> str:
    return "".join(
        '<option value="%d"%s>%s</option>'
        % (a["id"], " selected" if a["id"] == wid else "", _e(_brand(a)))
        for a in ctx["agencies"])


def _loc_selector(ctx: dict, wid: int) -> str:
    """Selector de locación SIN formularios: enlaces GET con ?loc=ID.
    Nunca produce HTML inválido (sin forms anidados) y el id se valida
    después con _write_agency / _order_scope (id ajeno → se ignora o 404)."""
    if not ctx["multi"]:
        return ""
    pills = "".join(
        ' <a class="btn sm%s" href="?loc=%d">%s</a>'
        % (" ok" if a["id"] == wid else " sec", a["id"], _e(_brand(a)))
        for a in ctx["agencies"])
    return ('<div class="noprint" style="margin:8px 0">'
            '<span class="muted">📍 Locación:</span>%s</div>' % pills)
