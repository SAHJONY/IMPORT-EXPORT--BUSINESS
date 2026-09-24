"""supa.py — Cliente Supabase para el estado de seguridad de PAQUETES.SAHJONY.com.

Sin dependencias nuevas: usa urllib de la librería estándar contra la API
REST (PostgREST) con la service_role key.

Variables de entorno:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

Tablas (crear una vez con deploy/supabase-schema.sql):
  staff_users, staff_sessions, login_attempts, scan_events, agency_resets

Reglas de fallo (diseñadas para no bloquear el negocio):
  - Sesiones: si Supabase no responde, el llamador decide (main.py usa el
    formato HMAC anterior como respaldo).
  - Throttle / scan / resets: fail-open con log si Supabase no responde.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import secrets as _secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def sb_enabled() -> bool:
    """Hay credenciales de Supabase configuradas."""
    return bool(_URL and _KEY)


class _NetErr(Exception):
    """Supabase no responde (red / timeout / sin configurar)."""


class _ApiErr(Exception):
    """Supabase respondió con error (tabla inexistente, etc.)."""


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _req(method: str, table: str, params: dict | None = None,
         body=None, timeout: int = 4):
    if not sb_enabled():
        raise _NetErr("supabase no configurado")
    qs = urllib.parse.urlencode(params or {})
    url = "%s/rest/v1/%s%s" % (_URL, table, ("?" + qs) if qs else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", _KEY)
    req.add_header("Authorization", "Bearer %s" % _KEY)
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "count=exact" if method == "GET"
                  else "return=minimal")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            total = None
            cr = r.headers.get("Content-Range", "")
            if "/" in cr:
                try:
                    total = int(cr.rsplit("/", 1)[-1])
                except ValueError:
                    total = None
            return (json.loads(raw) if raw else []), total
    except urllib.error.HTTPError as e:
        raise _ApiErr("supabase %s en %s" % (e.code, table))
    except Exception as e:
        raise _NetErr("supabase red: %s" % e)


def _prune(table: str, field: str = "ts", older_than: int = 86400):
    """Borra filas viejas para que las tablas no crezcan sin límite."""
    try:
        _req("DELETE", table, params={field: "lt.%s" % _iso(time.time() - older_than)})
    except Exception as e:
        print("[supa] prune %s: %s" % (table, e), flush=True)


# ---------------------------------------------------------------- throttle
def throttle_ok(key: str, limit: int = 10, window: int = 300) -> bool:
    """¿Cabe un intento más para esta llave en la ventana? Fail-open."""
    try:
        _, total = _req("GET", "login_attempts",
                        {"select": "id", "key": "eq.%s" % key,
                         "ts": "gte.%s" % _iso(time.time() - window)})
        return (total or 0) < limit
    except Exception as e:
        print("[supa] throttle_ok fail-open: %s" % e, flush=True)
        return True


def throttle_hit(key: str) -> None:
    try:
        _req("POST", "login_attempts", body=[{"key": key}])
        _prune("login_attempts")
    except Exception as e:
        print("[supa] throttle_hit: %s" % e, flush=True)


# ---------------------------------------------------------------- escaneo
def scan_ok(agency_id: int, limit: int = 120, window: int = 3600) -> bool:
    """Límite de escaneos por agencia y hora. Fail-open."""
    try:
        _, total = _req("GET", "scan_events",
                        {"select": "id", "agency_id": "eq.%d" % int(agency_id),
                         "ts": "gte.%s" % _iso(time.time() - window)})
        return (total or 0) < limit
    except Exception as e:
        print("[supa] scan_ok fail-open: %s" % e, flush=True)
        return True


def scan_hit(agency_id: int) -> None:
    try:
        _req("POST", "scan_events", body=[{"agency_id": int(agency_id)}])
        _prune("scan_events")
    except Exception as e:
        print("[supa] scan_hit: %s" % e, flush=True)


# ---------------------------------------------------------------- contraseñas
def hash_password(pw: str) -> str:
    salt = _secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(),
                            bytes.fromhex(salt), 200_000).hex()
    return "pbkdf2$200000$%s$%s" % (salt, h)


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, iters, salt, h = (stored or "").split("$")
        if algo != "pbkdf2":
            return False
        c = hashlib.pbkdf2_hmac("sha256", pw.encode(),
                                bytes.fromhex(salt), int(iters)).hex()
        return _hmac.compare_digest(c, h)
    except Exception:
        return False


# ---------------------------------------------------------------- staff: usuarios
def staff_user_get(username: str):
    rows, _ = _req("GET", "staff_users",
                   {"select": "username,pw_hash,created_at",
                    "username": "eq.%s" % (username or "").strip(),
                    "limit": "1"})
    return rows[0] if rows else None


def staff_user_create(username: str, pw: str) -> None:
    _req("POST", "staff_users",
         body=[{"username": (username or "").strip(),
                "pw_hash": hash_password(pw)}])


def staff_users_list():
    rows, _ = _req("GET", "staff_users",
                   {"select": "username,created_at", "order": "created_at"})
    return rows or []


# ---------------------------------------------------------------- staff: sesiones
def staff_session_create(username: str, ttl: int = 12 * 3600) -> str:
    token = _secrets.token_urlsafe(32)
    th = hashlib.sha256(token.encode()).hexdigest()
    _req("POST", "staff_sessions",
         body=[{"token_hash": th, "username": username,
                "expires_at": _iso(time.time() + ttl)}])
    return token


def staff_session_check(token: str):
    """Username si la sesión es válida; None si no. Lanza _NetErr/_ApiErr."""
    th = hashlib.sha256((token or "").encode()).hexdigest()
    rows, _ = _req("GET", "staff_sessions",
                   {"select": "username,expires_at,revoked",
                    "token_hash": "eq.%s" % th, "limit": "1"})
    if not rows:
        return None
    r = rows[0]
    if r.get("revoked"):
        return None
    try:
        exp = datetime.fromisoformat(
            str(r["expires_at"]).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None
    if exp < time.time():
        return None
    return r.get("username")


def staff_session_revoke(token: str) -> None:
    try:
        th = hashlib.sha256((token or "").encode()).hexdigest()
        _req("PATCH", "staff_sessions",
             params={"token_hash": "eq.%s" % th}, body={"revoked": True})
    except Exception as e:
        print("[supa] revoke: %s" % e, flush=True)


# ---------------------------------------------------------------- recuperación de acceso (agencias)
def reset_create(owner_email: str, ttl: int = 3600) -> str:
    token = _secrets.token_urlsafe(32)
    th = hashlib.sha256(token.encode()).hexdigest()
    _req("POST", "agency_resets",
         body=[{"owner_email": (owner_email or "").strip().lower(),
                "token_hash": th, "expires_at": _iso(time.time() + ttl)}])
    return token


def reset_consume(token: str):
    """Devuelve el owner_email y marca el token como usado. None si inválido."""
    th = hashlib.sha256((token or "").encode()).hexdigest()
    rows, _ = _req("GET", "agency_resets",
                   {"select": "owner_email,expires_at,used",
                    "token_hash": "eq.%s" % th, "limit": "1"})
    if not rows:
        return None
    r = rows[0]
    if r.get("used"):
        return None
    try:
        exp = datetime.fromisoformat(
            str(r["expires_at"]).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None
    if exp < time.time():
        return None
    _req("PATCH", "agency_resets",
         params={"token_hash": "eq.%s" % th}, body={"used": True})
    return r.get("owner_email")
