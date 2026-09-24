"""SAHJONY LLC — agency command center: schema + helpers.

Tablas nuevas (via migrate()): agency_owners, agency_creation_requests,
terms_acceptances, audit_log, notification_templates, customer_notifications,
notifications (bandeja de envíos agencia→cliente), dismissed_alerts,
app_settings. Columnas nuevas: agencies.agency_type, agencies.created_by_owner_email,
documents.doc_type/ref_table/ref_id/code/version/superseded/created_by/immutable.

Todo el aislamiento es por agency_id: ninguna función acepta agency_id del
formulario; las rutas lo toman de la sesión y lo validan contra la lista.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.request
import urllib.error


# ---------------------------------------------------------------- utilidades base
def _cols(conn: sqlite3.Connection, table: str) -> set:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _cols(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


# ---------------------------------------------------------------- migración
def migrate(conn: sqlite3.Connection) -> None:
    # Tipo de agencia: 'agencia' (negocio formal) | 'punto_recogida' (casa).
    _ensure_column(conn, "agencies", "agency_type", "TEXT DEFAULT 'agencia'")
    _ensure_column(conn, "agencies", "created_by_owner_email", "TEXT DEFAULT ''")
    # Punto de recogida: WhatsApp, zonas y horario visibles en recibos/rastreo.
    _ensure_column(conn, "agencies", "whatsapp", "TEXT DEFAULT ''")
    _ensure_column(conn, "agencies", "service_areas", "TEXT DEFAULT ''")
    _ensure_column(conn, "agencies", "pickup_hours", "TEXT DEFAULT ''")
    conn.execute("UPDATE agencies SET agency_type='agencia' "
                 "WHERE agency_type IS NULL OR agency_type=''")

    # Acceso web del dueño (columnas del modelo probado; ensure idempotente).
    for col, ddl in [
            ("owner_email", "TEXT DEFAULT ''"),
            ("owner_password_hash", "TEXT DEFAULT ''"),
            ("owner_login_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("owner_must_change_password", "INTEGER NOT NULL DEFAULT 0")]:
        _ensure_column(conn, "agencies", col, ddl)

    # Dueños a nivel de cuenta (un email puede tener varias locaciones).
    conn.execute("""CREATE TABLE IF NOT EXISTS agency_owners (
        email TEXT PRIMARY KEY,
        display_name TEXT DEFAULT '',
        can_create_agencies INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    for r in conn.execute(
            "SELECT DISTINCT lower(owner_email) AS e FROM agencies "
            "WHERE owner_email IS NOT NULL AND trim(owner_email)<>''").fetchall():
        if r["e"]:
            conn.execute("INSERT OR IGNORE INTO agency_owners(email) VALUES (?)", (r["e"],))

    # Solicitudes de nueva locación (flujo con autorización).
    conn.execute("""CREATE TABLE IF NOT EXISTS agency_creation_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_email TEXT NOT NULL,
        agency_type TEXT NOT NULL DEFAULT 'agencia',
        business_name TEXT DEFAULT '',
        brand TEXT DEFAULT '',
        city TEXT DEFAULT '',
        address TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        whatsapp TEXT DEFAULT '',
        email TEXT DEFAULT '',
        service_area TEXT DEFAULT '',
        hours TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pendiente',
        review_note TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        reviewed_at TEXT DEFAULT '',
        reviewed_by TEXT DEFAULT '')""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_acr_owner "
                 "ON agency_creation_requests(owner_email)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_acr_status "
                 "ON agency_creation_requests(status)")

    # Aceptación de términos (protección legal de SAHJONY).
    conn.execute("""CREATE TABLE IF NOT EXISTS terms_acceptances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agency_id INTEGER NOT NULL REFERENCES agencies(id),
        terms_version TEXT NOT NULL,
        accepted_at TEXT NOT NULL DEFAULT (datetime('now')),
        ip TEXT DEFAULT '')""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_terms_ag "
                 "ON terms_acceptances(agency_id)")

    # Bitácora de auditoría (solo agregar; nunca editar ni borrar).
    conn.execute("""CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agency_id INTEGER NOT NULL,
        actor TEXT NOT NULL,
        actor_id TEXT DEFAULT '',
        action TEXT NOT NULL,
        entity TEXT DEFAULT '',
        entity_id INTEGER DEFAULT 0,
        detail TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ag "
                 "ON audit_log(agency_id, created_at)")

    # Plantillas de notificación por agencia.
    conn.execute("""CREATE TABLE IF NOT EXISTS notification_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agency_id INTEGER NOT NULL REFERENCES agencies(id),
        event TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT 'portal',
        title_template TEXT DEFAULT '',
        body_template TEXT DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ntpl_ag_ev_ch "
                 "ON notification_templates(agency_id, event, channel)")

    # Notificaciones a clientes (bandeja del portal del cliente).
    conn.execute("""CREATE TABLE IF NOT EXISTS customer_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agency_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        order_id INTEGER DEFAULT 0,
        event TEXT DEFAULT '',
        channel TEXT DEFAULT 'portal',
        title TEXT DEFAULT '',
        body TEXT DEFAULT '',
        status TEXT DEFAULT 'enviada',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        read_at TEXT DEFAULT '')""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cnotif_cust "
                 "ON customer_notifications(customer_id, created_at)")

    # Registro de envíos de la agencia a sus clientes (portal/email/whatsapp).
    # Nombre propio: la tabla `notifications` ya existe con otro esquema
    # (avisos WhatsApp automáticos del sistema); no tocarla.
    conn.execute("""CREATE TABLE IF NOT EXISTS agency_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agency_id INTEGER NOT NULL,
        customer_id INTEGER DEFAULT 0,
        order_id INTEGER DEFAULT 0,
        event TEXT DEFAULT '',
        channel TEXT DEFAULT 'portal',
        content TEXT DEFAULT '',
        recipient TEXT DEFAULT '',
        status TEXT DEFAULT 'enviada',
        created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agnotif_ag "
                 "ON agency_notifications(agency_id, created_at)")

    # Alertas descartadas por el dueño.
    conn.execute("""CREATE TABLE IF NOT EXISTS dismissed_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agency_id INTEGER NOT NULL,
        alert_key TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_dismissed_ag_key "
                 "ON dismissed_alerts(agency_id, alert_key)")

    # Ajustes de la app (ej. remitente de correos).
    conn.execute("""CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT (datetime('now')))""")

    # Documentos: tabla del pipeline único (si no existe) + columnas del pipeline.
    conn.execute("""CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch TEXT DEFAULT '',
        agency_id INTEGER NOT NULL DEFAULT 0,
        doc_type TEXT DEFAULT 'documento',
        ref_table TEXT DEFAULT '',
        ref_id INTEGER DEFAULT 0,
        code TEXT DEFAULT '',
        version INTEGER DEFAULT 1,
        superseded INTEGER DEFAULT 0,
        doc_key TEXT DEFAULT '',
        label TEXT DEFAULT '',
        file_path TEXT DEFAULT '',
        sha256 TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        created_by TEXT DEFAULT '',
        immutable INTEGER DEFAULT 1)""")
    for col, ddl in [
            ("doc_type", "TEXT DEFAULT 'documento'"),
            ("ref_table", "TEXT DEFAULT ''"),
            ("ref_id", "INTEGER DEFAULT 0"),
            ("code", "TEXT DEFAULT ''"),
            ("version", "INTEGER DEFAULT 1"),
            ("superseded", "INTEGER DEFAULT 0"),
            ("created_by", "TEXT DEFAULT ''"),
            ("immutable", "INTEGER DEFAULT 1"),
            ("batch", "TEXT DEFAULT ''"),
            ("doc_key", "TEXT DEFAULT ''"),
            ("label", "TEXT DEFAULT ''"),
            ("file_path", "TEXT DEFAULT ''"),
            ("sha256", "TEXT DEFAULT ''")]:
        _ensure_column(conn, "documents", col, ddl)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_agency "
                 "ON documents(agency_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_code "
                 "ON documents(agency_id, doc_type, code, version)")
    # Facturas, cobros, gastos y métodos de pago (esquema propio, sano).
    conn.executescript(_ECON_SCHEMA)
    # Vínculo explícito cliente↔agencia (visible aunque no tenga órdenes).
    conn.execute("""CREATE TABLE IF NOT EXISTS customer_agencies (
        customer_id INTEGER NOT NULL, agency_id INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (customer_id, agency_id))""")
    # Backfill: clientes con órdenes existentes quedan vinculados a su agencia.
    try:
        conn.execute(
            """INSERT OR IGNORE INTO customer_agencies (customer_id, agency_id)
               SELECT customer_id, agency_id FROM orders
               WHERE customer_id IS NOT NULL AND agency_id IS NOT NULL""")
    except Exception:
        pass
    conn.commit()


# ---------------------------------------------------------------- auditoría
def audit(conn: sqlite3.Connection, agency_id: int, actor: str, action: str,
          entity: str = "", entity_id: int = 0, detail: str = "",
          actor_id: str = "") -> None:
    """Append-only. Nunca se edita ni se borra desde la app."""
    conn.execute(
        "INSERT INTO audit_log (agency_id, actor, actor_id, action, entity, entity_id, detail)"
        " VALUES (?,?,?,?,?,?,?)",
        (agency_id, actor, actor_id or "", action, entity or "", entity_id or 0,
         (detail or "")[:2000]))
    conn.commit()


# ---------------------------------------------------------------- dueños
def find_agencies_by_owner_email(conn: sqlite3.Connection, email: str):
    """TODAS las agencias del dueño (login multi-locación)."""
    email = _norm_email(email)
    if not email:
        return []
    return conn.execute(
        "SELECT * FROM agencies WHERE lower(owner_email)=? "
        "AND owner_login_enabled=1 AND active=1 ORDER BY id",
        (email,)).fetchall()


def get_owner_row(conn: sqlite3.Connection, email: str):
    return conn.execute("SELECT * FROM agency_owners WHERE email=?",
                        (_norm_email(email),)).fetchone()


def ensure_owner_row(conn: sqlite3.Connection, email: str, display_name: str = "") -> None:
    email = _norm_email(email)
    if not email:
        return
    conn.execute(
        "INSERT INTO agency_owners(email, display_name) VALUES (?,?) "
        "ON CONFLICT(email) DO NOTHING", (email, display_name or ""))
    conn.commit()


def set_can_create(conn: sqlite3.Connection, email: str, flag: bool, by: str = "") -> None:
    ensure_owner_row(conn, email)
    conn.execute("UPDATE agency_owners SET can_create_agencies=? WHERE email=?",
                 (1 if flag else 0, _norm_email(email)))
    conn.commit()
    audit(conn, 0, "staff", "can_create_agencies=%d" % (1 if flag else 0),
          entity="agency_owner", detail="email=%s" % _norm_email(email), actor_id=by)


# ---------------------------------------------------------------- solicitudes de nueva locación
REQ_FIELDS = ["agency_type", "business_name", "brand", "city", "address", "phone",
              "whatsapp", "email", "service_area", "hours", "notes"]


def create_request(conn: sqlite3.Connection, owner_email: str, data: dict) -> int:
    owner_email = _norm_email(owner_email)
    atype = (data.get("agency_type") or "agencia").strip()
    if atype not in ("agencia", "punto_recogida"):
        atype = "agencia"
    vals = [owner_email, atype] + [(data.get(f) or "").strip()[:500] for f in REQ_FIELDS[1:]]
    cur = conn.execute(
        """INSERT INTO agency_creation_requests
           (owner_email, agency_type, business_name, brand, city, address, phone,
            whatsapp, email, service_area, hours, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", vals)
    conn.commit()
    audit(conn, 0, "owner", "creation_request", entity="agency_creation_requests",
          entity_id=cur.lastrowid, detail="tipo=%s marca=%s" % (atype, vals[3]),
          actor_id=owner_email)
    return cur.lastrowid


def list_requests(conn: sqlite3.Connection, owner_email: str | None = None,
                  status: str | None = None):
    sql = "SELECT * FROM agency_creation_requests WHERE 1=1"
    params: list = []
    if owner_email:
        sql += " AND owner_email=?"; params.append(_norm_email(owner_email))
    if status:
        sql += " AND status=?"; params.append(status)
    return conn.execute(sql + " ORDER BY id DESC", params).fetchall()


def get_request(conn: sqlite3.Connection, req_id: int, owner_email: str | None = None):
    sql = "SELECT * FROM agency_creation_requests WHERE id=?"
    params: list = [req_id]
    if owner_email:
        sql += " AND owner_email=?"; params.append(_norm_email(owner_email))
    return conn.execute(sql, params).fetchone()


def review_request(conn: sqlite3.Connection, req_id: int, approve: bool,
                   note: str, by: str) -> bool:
    r = get_request(conn, req_id)
    if not r or r["status"] != "pendiente":
        return False
    conn.execute(
        "UPDATE agency_creation_requests SET status=?, review_note=?, reviewed_at=?,"
        " reviewed_by=? WHERE id=?",
        ("aprobada" if approve else "rechazada", (note or "").strip()[:1000],
         _now(), by or "", req_id))
    conn.commit()
    audit(conn, 0, "staff", "request_%s" % ("approved" if approve else "rejected"),
          entity="agency_creation_requests", entity_id=req_id,
          detail=(note or "")[:500], actor_id=by)
    return True


def _brand_prefix(brand: str) -> str:
    return "".join(c for c in (brand or "AG").upper() if c.isalnum())[:6] or "AG"


def staff_create_agency_from_request(conn: sqlite3.Connection, req_id: int,
                                     terms: dict, by: str = "") -> int:
    """Staff crea la agencia directamente (opción a). owner_email FORZADO al solicitante."""
    r = get_request(conn, req_id)
    if not r or r["status"] != "aprobada":
        raise LookupError("Solicitud no aprobada")
    atype = r["agency_type"] or "agencia"
    brand = (r["brand"] or r["business_name"] or "").strip() or "Nueva agencia"
    legal = (r["business_name"] or "").strip() or brand
    cur = conn.execute(
        """INSERT INTO agencies (legal_name, brand, contact_name, phone, email, address,
                                 city, state, agency_type, commission_per_package,
                                 commission_per_order, rate_per_lb, monthly_fee, notes, active)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
        (legal, brand, legal if atype == "punto_recogida" else "",
         r["phone"] or "", r["email"] or "", r["address"] or "", r["city"] or "", "",
         atype,
         terms.get("commission_per_package"), terms.get("commission_per_order"),
         terms.get("rate_per_lb"), terms.get("monthly_fee"),
         ("Solicitud #%d. " % req_id) + (r["notes"] or "")))
    agency_id = cur.lastrowid
    ensure_owner_row(conn, r["owner_email"], legal)
    seed_templates(conn, agency_id)
    conn.commit()
    audit(conn, agency_id, "staff", "agency_created_from_request",
          entity="agencies", entity_id=agency_id,
          detail="solicitud #%d" % req_id, actor_id=by)
    return agency_id


def check_create_ratelimit(conn: sqlite3.Connection, owner_email: str,
                           limit: int = 5) -> bool:
    """5 autocreaciones/día por dueño."""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM agencies WHERE lower(created_by_owner_email)=?"
        " AND date(created_at)=date('now')", (_norm_email(owner_email),)).fetchone()
    return (row["c"] if row else 0) < limit


def owner_self_create(conn: sqlite3.Connection, owner_email: str, data: dict) -> int:
    """Autocreación (bandera can_create_agencies=1). REGLA DURA: owner_email
    siempre es el de la sesión; no hay forma de crear para otro dueño."""
    owner_email = _norm_email(owner_email)
    owner = get_owner_row(conn, owner_email)
    if not owner or not owner["can_create_agencies"]:
        raise PermissionError("Autocreación no autorizada")
    if not check_create_ratelimit(conn, owner_email):
        raise PermissionError("Límite diario de creaciones alcanzado (5/día)")
    atype = (data.get("agency_type") or "agencia").strip()
    if atype not in ("agencia", "punto_recogida"):
        atype = "agencia"
    if atype == "punto_recogida":
        person = (data.get("person_name") or "").strip()
        if not person:
            raise ValueError("Indique el nombre de la persona")
        brand, legal = person, person
        contact = person
    else:
        brand = (data.get("brand") or "").strip()
        legal = (data.get("business_name") or "").strip() or brand
        contact = (data.get("contact_name") or "").strip()
        if not brand:
            raise ValueError("Indique la marca del negocio")
    cur = conn.execute(
        """INSERT INTO agencies (legal_name, brand, contact_name, phone, email, address,
                                 city, state, agency_type, owner_email,
                                 owner_login_enabled, owner_must_change_password,
                                 created_by_owner_email, active)
           VALUES (?,?,?,?,?,?,?,?,?,?,1,0,?,1)""",
        (legal, brand, contact,
         (data.get("phone") or "").strip()[:60],
         (data.get("email") or "").strip()[:120],
         (data.get("address") or "").strip()[:300],
         (data.get("city") or "").strip()[:120], "",
         atype, owner_email, owner_email))
    agency_id = cur.lastrowid
    seed_templates(conn, agency_id)
    conn.commit()
    audit(conn, agency_id, "owner", "agency_self_created", entity="agencies",
          entity_id=agency_id, detail="tipo=%s marca=%s" % (atype, brand),
          actor_id=owner_email)
    return agency_id


# ---------------------------------------------------------------- términos (aceptación)
def terms_version(agency) -> str:
    """Versión = hash de los términos económicos con SAHJONY."""
    blob = "|".join(str(agency[k] if agency[k] is not None else "")
                    for k in ("commission_per_package", "commission_per_order",
                              "rate_per_lb", "monthly_fee", "notes"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def terms_pending(agency) -> bool:
    return (agency["commission_per_package"] is None
            and agency["commission_per_order"] is None
            and agency["rate_per_lb"] is None
            and agency["monthly_fee"] is None)


def last_acceptance(conn: sqlite3.Connection, agency_id: int):
    return conn.execute(
        "SELECT * FROM terms_acceptances WHERE agency_id=? ORDER BY id DESC LIMIT 1",
        (agency_id,)).fetchone()


def needs_reaccept(conn: sqlite3.Connection, agency) -> bool:
    acc = last_acceptance(conn, agency["id"])
    return (not acc) or (acc["terms_version"] != terms_version(agency))


def accept_terms(conn: sqlite3.Connection, agency_id: int, ip: str = "",
                 actor: str = "owner", actor_id: str = "") -> str:
    ag = conn.execute("SELECT * FROM agencies WHERE id=?", (agency_id,)).fetchone()
    ver = terms_version(ag) if ag else "none"
    conn.execute("INSERT INTO terms_acceptances (agency_id, terms_version, ip)"
                 " VALUES (?,?,?)", (agency_id, ver, (ip or "")[:60]))
    conn.commit()
    audit(conn, agency_id, actor, "terms_accepted", entity="agencies",
          entity_id=agency_id, detail="version=%s" % ver, actor_id=actor_id)
    return ver


# ---------------------------------------------------------------- checklist inicial
def checklist(conn: sqlite3.Connection, agency_ids: list[int]) -> dict:
    items = []
    if not agency_ids:
        return {"items": items, "done": 0, "total": 5, "complete": False}
    ph = ",".join("?" for _ in agency_ids)
    prof = conn.execute(
        f"SELECT COUNT(*) AS c FROM agencies WHERE id IN ({ph})"
        " AND trim(phone)<>'' AND trim(address)<>''", agency_ids).fetchone()["c"]
    items.append(("profile", "Completa el perfil de tu negocio",
                  "/agencia/perfil", prof > 0))
    pr = conn.execute(
        f"SELECT COUNT(*) AS c FROM agency_price_list WHERE agency_id IN ({ph})"
        " AND active=1", agency_ids).fetchone()["c"]
    items.append(("prices", "Pon tu lista de precios",
                  "/agencia/precios", pr > 0))
    pm = conn.execute(
        f"SELECT COUNT(*) AS c FROM agency_payment_methods WHERE agency_id IN ({ph})"
        " AND active=1", agency_ids).fetchone()["c"]
    items.append(("paymethods", "Configura cómo te pagan",
                  "/agencia/metodos", pm > 0))
    ta = conn.execute(
        f"SELECT COUNT(*) AS c FROM terms_acceptances WHERE agency_id IN ({ph})",
        agency_ids).fetchone()["c"]
    items.append(("terms", "Acepta los términos con SAHJONY",
                  "/agencia/terminos", ta > 0))
    cu = conn.execute(
        f"SELECT COUNT(DISTINCT o.customer_id) AS c FROM orders o WHERE o.agency_id IN ({ph})",
        agency_ids).fetchone()["c"]
    items.append(("customer", "Agrega tu primer cliente",
                  "/agencia/clientes", cu > 0))
    done = sum(1 for _, _, _, ok in items if ok)
    return {"items": items, "done": done, "total": len(items),
            "complete": done == len(items)}


# ---------------------------------------------------------------- plantillas de notificación
DEFAULT_TEMPLATES = [
    # event, channel, title, body
    ("orden_creada", "portal", "Nueva orden {{order_number}}",
     "Hola {{customer_name}}: {{brand}} registró tu orden {{order_number}} (rastreo {{tracking}}). Te avisaremos de cada avance."),
    ("cambio_estado", "portal", "Tu paquete {{pkg_code}}: {{status}}",
     "Hola {{customer_name}}: tu paquete {{pkg_code}} de la orden {{order_number}} ahora está: {{status}}. {{brand}}."),
    ("cambio_estado", "email", "Tu paquete {{pkg_code}}: {{status}}",
     "Hola {{customer_name}}:\n\nTu paquete {{pkg_code}} de la orden {{order_number}} ahora está: {{status}}.\n\n{{brand}}"),
    ("pago_recibido", "portal", "Pago recibido: ${{amount}}",
     "Hola {{customer_name}}: {{brand}} recibió tu pago de ${{amount}} para la factura {{invoice}}. ¡Gracias!"),
    ("pago_recibido", "email", "Recibo de pago ${{amount}} — {{brand}}",
     "Hola {{customer_name}}:\n\nConfirmamos tu pago de ${{amount}} para la factura {{invoice}}.\n\nGracias,\n{{brand}}"),
    ("nuevo_mensaje", "portal", "Nuevo mensaje de {{brand}}",
     "Hola {{customer_name}}: {{brand}} te escribió sobre tu orden {{order_number}}. Revísalo en tu cuenta."),
    ("envio_transito", "portal", "Tu envío va en camino",
     "Hola {{customer_name}}: tus paquetes de la orden {{order_number}} ya van en tránsito. {{brand}}."),
    ("entregado", "portal", "¡Entregado! {{pkg_code}}",
     "Hola {{customer_name}}: tu paquete {{pkg_code}} fue entregado. ¡Gracias por confiar en {{brand}}!"),
    ("entregado", "email", "Paquete entregado — {{brand}}",
     "Hola {{customer_name}}:\n\nTu paquete {{pkg_code}} fue entregado.\n\n¡Gracias por confiar en {{brand}}!"),
    ("aviso_general", "portal", "{{title}}",
     "{{body}}"),
]


def seed_templates(conn: sqlite3.Connection, agency_id: int) -> None:
    for event, channel, title, body in DEFAULT_TEMPLATES:
        conn.execute(
            """INSERT INTO notification_templates
               (agency_id, event, channel, title_template, body_template)
               VALUES (?,?,?,?,?)
               ON CONFLICT(agency_id, event, channel) DO NOTHING""",
            (agency_id, event, channel, title, body))
    conn.commit()


_TPL_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_tpl(text: str, ctx: dict) -> str:
    def _rep(m):
        return str(ctx.get(m.group(1), ""))
    return _TPL_VAR.sub(_rep, text or "")


def get_templates(conn: sqlite3.Connection, agency_id: int):
    return conn.execute(
        "SELECT * FROM notification_templates WHERE agency_id=? ORDER BY event, channel",
        (agency_id,)).fetchall()


def get_template(conn: sqlite3.Connection, agency_id: int, event: str, channel: str):
    return conn.execute(
        "SELECT * FROM notification_templates WHERE agency_id=? AND event=? AND channel=?",
        (agency_id, event, channel)).fetchone()


def tpl_active(conn: sqlite3.Connection, agency_id: int, event: str) -> bool:
    """El dueño puede apagar auto-notificaciones por evento."""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM notification_templates WHERE agency_id=? AND event=?"
        " AND channel='portal' AND active=1", (agency_id, event)).fetchone()
    return (row["c"] if row else 0) > 0


# ---------------------------------------------------------------- notificaciones a clientes
def notify_customer(conn: sqlite3.Connection, agency_id: int, customer_id: int,
                    order_id: int, event: str, ctx: dict,
                    channels: tuple = ("portal",)) -> list:
    """Crea notificaciones portal (+email si hay). Nunca lanza excepción."""
    made = []
    try:
        if not tpl_active(conn, agency_id, event):
            return made
        cust = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not cust:
            return made
        full = dict(ctx or {})
        full.setdefault("customer_name", cust["name"] or "")
        for ch in channels:
            tpl = get_template(conn, agency_id, event, ch)
            if not tpl or not tpl["active"]:
                continue
            title = render_tpl(tpl["title_template"], full)
            body = render_tpl(tpl["body_template"], full)
            if ch == "portal":
                conn.execute(
                    """INSERT INTO customer_notifications
                       (agency_id, customer_id, order_id, event, channel, title, body)
                       VALUES (?,?,?,?,?,?,?)""",
                    (agency_id, customer_id, order_id or 0, event, ch, title, body))
                made.append(("portal", title))
            elif ch == "email" and (cust["email"] or "").strip():
                queue_email(conn, agency_id, event, (cust["email"] or "").strip(),
                            title, body, customer_id=customer_id, order_id=order_id or 0)
                made.append(("email", title))
        conn.commit()
    except Exception:
        pass
    return made


def log_manual_notify(conn: sqlite3.Connection, agency_id: int, customer_id: int,
                      order_id: int, event: str, channel: str, content: str,
                      recipient: str = "", status: str = "enviada") -> int:
    cur = conn.execute(
        """INSERT INTO agency_notifications
           (agency_id, customer_id, order_id, event, channel, content, recipient, status)
           VALUES (?,?,?,?,?,?,?,?)""",
        (agency_id, customer_id, order_id or 0, event, channel, (content or "")[:2000],
         (recipient or "")[:200], status))
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------- correo (Resend)
RESEND_KEY_FILE = "/opt/sahjony-packages/.resend_key"
DEFAULT_FROM = "notificaciones@sahjony.com"


def resend_key() -> str:
    """Lee la clave SOLO de archivo root 600 o variable de entorno. Nunca se registra."""
    try:
        if os.path.exists(RESEND_KEY_FILE):
            with open(RESEND_KEY_FILE, "r", encoding="utf-8") as f:
                k = f.read().strip()
                if k:
                    return k
    except Exception:
        pass
    return (os.environ.get("RESEND_API_KEY") or "").strip()


def resend_active() -> bool:
    return bool(resend_key())


def _db_path() -> str:
    """Ruta de la DB sin importar el módulo db (evita import circular)."""
    return os.environ.get("DB_PATH", "/opt/sahjony-packages/data/sahjony_packages.db")


def _open_app_db() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def get_notify_from() -> str:
    try:
        conn = _open_app_db()
        try:
            r = conn.execute("SELECT value FROM app_settings WHERE key='notify_from_address'").fetchone()
            if r and (r["value"] or "").strip():
                return r["value"].strip()
        finally:
            conn.close()
    except Exception:
        pass
    return DEFAULT_FROM


def set_notify_from(addr: str) -> None:
    conn = _open_app_db()
    try:
        conn.execute("INSERT INTO app_settings(key, value) VALUES ('notify_from_address', ?)"
                     " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                     " updated_at=datetime('now')", ((addr or "").strip()[:200],))
        conn.commit()
    finally:
        conn.close()


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    r = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return (r["value"] or "") if r else ""


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO app_settings(key, value) VALUES (?,?)"
                 " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                 " updated_at=datetime('now')", (key, (value or "")[:2000]))
    conn.commit()


def send_via_resend(to: str, subject: str, html: str, brand: str = "") -> tuple[bool, str]:
    """Envía por Resend HTTPS API. Reintenta una vez. Nunca lanza excepción.
    Devuelve (ok, detalle). La clave jamás se incluye en el detalle."""
    key = resend_key()
    if not key:
        return False, "sin clave configurada"
    from_addr = get_notify_from()
    disp = (brand or "Agencia").strip() or "Agencia"
    payload = json.dumps({
        "from": "%s <%s>" % (disp, from_addr),
        "to": [to],
        "subject": subject,
        "html": html,
    }).encode("utf-8")
    last_err = ""
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                "https://api.resend.com/emails", data=payload,
                headers={"Authorization": "Bearer " + key,
                         "Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", "replace")[:300]
                if 200 <= resp.status < 300:
                    return True, "ok"
                last_err = "http %d" % resp.status
        except urllib.error.HTTPError as e:
            last_err = "http %d" % (e.code or 0)
        except Exception as e:
            last_err = type(e).__name__
    return False, last_err or "error"


def queue_email(conn: sqlite3.Connection, agency_id: int, event: str, to: str,
                subject: str, html: str, customer_id: int = 0, order_id: int = 0) -> int:
    """Encola y trata de enviar. El fallo jamás rompe la acción principal."""
    body_html = "<html><body><pre>%s</pre></body></html>" % (html or "")
    cur = conn.execute(
        """INSERT INTO agency_notifications
           (agency_id, customer_id, order_id, event, channel, content, recipient, status)
           VALUES (?,?,?,?,?,?,?,?)""",
        (agency_id, customer_id, order_id, event, "email",
         ("%s\n---\n%s" % (subject, html or ""))[:2000],
         (to or "")[:200], "pendiente"))
    nid = cur.lastrowid
    conn.commit()
    status, detail = send_via_resend(to, subject, body_html)
    if status:
        conn.execute("UPDATE agency_notifications SET status='enviada' WHERE id=?", (nid,))
    elif resend_active():
        conn.execute("UPDATE agency_notifications SET status='fallida' WHERE id=?", (nid,))
    else:
        conn.execute("UPDATE agency_notifications SET status='pendiente-config' WHERE id=?", (nid,))
    conn.commit()
    audit(conn, agency_id, "system", "email_%s" % ("sent" if status else "queued"),
          entity="agency_notifications", entity_id=nid,
          detail="to=%s evento=%s (%s)" % ((to or "")[:60], event, detail))
    return nid


# ---------------------------------------------------------------- WhatsApp (wa.me manual)
def wa_link(phone: str, text: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    from urllib.parse import quote
    return "https://wa.me/%s?text=%s" % (digits, quote(text or ""))


# ---------------------------------------------------------------- respuestas sugeridas (reglas, sin IA externa)
INTENTS = [
    ("estado", ["estado", "donde", "dónde", "llegó", "llego", "cuando", "cuándo", "rastreo", "seguimiento", "paquete"],
     "Tu orden {order_number} (rastreo {tracking}) está en estado: {status}. Te avisaremos de cada avance. — {brand}"),
    ("precio", ["precio", "cuanto", "cuánto", "costo", "tarifa", "cuesta"],
     "Hola {customer_name}: con gusto te cotizamos. ¿Qué quieres enviar y cuánto pesa? Así te doy el precio exacto. — {brand}"),
    ("retraso", ["retraso", "demora", "tarda", "atrasado", "no llega"],
     "Hola {customer_name}: entiendo tu preocupación. Tu orden {order_number} está en: {status}. La estamos moviendo lo más rápido posible. — {brand}"),
    ("reclamo", ["reclamo", "queja", "mal", "roto", "faltante", "perdido", "error"],
     "Hola {customer_name}: lamento lo ocurrido con tu orden {order_number}. Cuéntame qué pasó y lo resolvemos hoy mismo. — {brand}"),
    ("agradecimiento", ["gracias", "excelente", "buen", "feliz", "contento"],
     "¡Gracias a ti, {customer_name}! Nos alegra servirte. Aquí estamos para tu próximo envío. — {brand}"),
    ("saludo", ["hola", "buenos días", "buenas tardes", "buenas noches", "saludos"],
     "¡Hola {customer_name}! Gracias por escribir a {brand}. ¿En qué te ayudo hoy?"),
]


def suggest_replies(message_text: str, ctx: dict) -> list[tuple[str, str]]:
    """Devuelve [(intent, borrador)]. Nada se envía solo."""
    low = (message_text or "").lower()
    out = []
    for intent, keywords, tpl in INTENTS:
        if any(k in low for k in keywords):
            try:
                out.append((intent, tpl.format(**{k: str(v) for k, v in ctx.items()})))
            except Exception:
                pass
        if len(out) >= 3:
            break
    if not out:
        out.append(("general",
                    "Hola %s: gracias por tu mensaje sobre la orden %s. Te respondo enseguida. — %s"
                    % (ctx.get("customer_name", ""), ctx.get("order_number", ""),
                       ctx.get("brand", ""))))
    return out[:3]


# ---------------------------------------------------------------- briefing diario + alertas
def compute_briefing(conn: sqlite3.Connection, agency_ids: list[int]) -> dict:
    b: dict = {"yesterday_orders": 0, "yesterday_payments": 0.0,
               "yesterday_messages": 0, "stale_orders": [], "overdue_invoices": [],
               "unread_messages": 0, "settlement_note": ""}
    if not agency_ids:
        return b
    ph = ",".join("?" for _ in agency_ids)
    b["yesterday_orders"] = conn.execute(
        f"SELECT COUNT(*) AS c FROM orders WHERE agency_id IN ({ph})"
        " AND date(created_at)=date('now','-1 day')", agency_ids).fetchone()["c"]
    b["yesterday_payments"] = conn.execute(
        f"SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE agency_id IN ({ph})"
        " AND date(paid_at)=date('now','-1 day')", agency_ids).fetchone()["s"] or 0
    b["yesterday_messages"] = conn.execute(
        f"SELECT COUNT(*) AS c FROM portal_messages WHERE agency_id IN ({ph})"
        " AND sender='customer' AND date(created_at)=date('now','-1 day')",
        agency_ids).fetchone()["c"]
    b["unread_messages"] = conn.execute(
        f"SELECT COUNT(*) AS c FROM portal_messages WHERE agency_id IN ({ph})"
        " AND sender='customer' AND read_by_staff=0", agency_ids).fetchone()["c"]
    b["stale_orders"] = conn.execute(
        f"""SELECT o.id, o.order_number, MAX(p.created_at) AS last_move
            FROM orders o JOIN packages p ON p.order_id=o.id
            WHERE o.agency_id IN ({ph}) AND p.status NOT IN ('ENTREGADO','CANCELADO')
            GROUP BY o.id HAVING date(last_move) < date('now','-5 days')
            ORDER BY last_move LIMIT 10""", agency_ids).fetchall()
    b["overdue_invoices"] = conn.execute(
        f"""SELECT i.id, i.number, i.total FROM invoices i
            WHERE i.agency_id IN ({ph}) AND i.status!='pagada'
            AND i.due_date<>'' AND date(i.due_date) < date('now')
            ORDER BY i.due_date LIMIT 10""", agency_ids).fetchall()
    return b


def _dismissed(conn, agency_id: int) -> set:
    return {r["alert_key"] for r in conn.execute(
        "SELECT alert_key FROM dismissed_alerts WHERE agency_id=?", (agency_id,)).fetchall()}


def compute_alerts(conn: sqlite3.Connection, agency_ids: list[int]) -> list[dict]:
    """Alertas con acción de un toque. Reglas puras, sin IA."""
    alerts: list[dict] = []
    if not agency_ids:
        return alerts
    ph = ",".join("?" for _ in agency_ids)
    dis = set()
    for aid in agency_ids:
        dis |= {(aid, k) for k in _dismissed(conn, aid)}

    def _add(aid, key, title, why, action_label, action_url):
        if (aid, key) not in dis:
            alerts.append({"agency_id": aid, "key": key, "title": title, "why": why,
                           "action_label": action_label, "action_url": action_url})

    for ag in conn.execute(
            f"SELECT * FROM agencies WHERE id IN ({ph})", agency_ids).fetchall():
        aid = ag["id"]
        if terms_pending(ag):
            _add(aid, "terms_pending", "Términos con SAHJONY pendientes",
                 "Aún no tienes términos confirmados. Tus números se calcularán cuando el personal los fije.",
                 "Ver términos", "/agencia/terminos?loc=%d" % aid)
        elif needs_reaccept(conn, ag):
            _add(aid, "terms_reaccept", "Tus términos cambiaron: revísalos",
                 "SAHJONY actualizó tus términos. Debes aceptarlos de nuevo.",
                 "Aceptar términos", "/agencia/terminos?loc=%d" % aid)
    stale = conn.execute(
        f"""SELECT o.agency_id, o.id, o.order_number FROM orders o
            JOIN packages p ON p.order_id=o.id
            WHERE o.agency_id IN ({ph}) AND p.status NOT IN ('ENTREGADO','CANCELADO')
            GROUP BY o.id HAVING date(MAX(p.created_at)) < date('now','-5 days') LIMIT 5""",
        agency_ids).fetchall()
    for s in stale:
        _add(s["agency_id"], "stale_%d" % s["id"],
             "Orden %s sin movimiento hace 5+ días" % s["order_number"],
             "Revisa su estado o avisa al cliente.",
             "Ver orden", "/agencia/ordenes/%d" % s["id"])
    od = conn.execute(
        f"SELECT agency_id, id, number FROM invoices WHERE agency_id IN ({ph})"
        " AND status!='pagada' AND due_date<>'' AND date(due_date) < date('now') LIMIT 5",
        agency_ids).fetchall()
    for r in od:
        _add(r["agency_id"], "overdue_%d" % r["id"],
             "Factura %s vencida" % r["number"],
             "Está vencida y sin pagar completo.",
             "Notificar al cliente", "/agencia/facturas/%d" % r["id"])
    um = conn.execute(
        f"""SELECT agency_id, order_id, COUNT(*) AS c FROM portal_messages
            WHERE agency_id IN ({ph}) AND sender='customer' AND read_by_staff=0
            AND datetime(created_at) < datetime('now','-24 hours')
            GROUP BY agency_id, order_id LIMIT 5""", agency_ids).fetchall()
    for r in um:
        _add(r["agency_id"], "unread_%d" % r["order_id"],
             "%d mensajes sin leer hace 24h+ (orden #%d)" % (r["c"], r["order_id"]),
             "El cliente espera respuesta.",
             "Responder", "/agencia/ordenes/%d#mensajes" % r["order_id"])
    if conn.execute(
            f"SELECT COUNT(*) AS c FROM agency_price_list WHERE agency_id IN ({ph})"
            " AND active=1", agency_ids).fetchone()["c"] == 0:
        _add(agency_ids[0], "no_prices", "No tienes lista de precios",
             "Sin precios no puedes cotizar ni facturar.",
             "Crear precios", "/agencia/precios")
    if conn.execute(
            f"SELECT COUNT(*) AS c FROM agency_payment_methods WHERE agency_id IN ({ph})"
            " AND active=1", agency_ids).fetchone()["c"] == 0:
        _add(agency_ids[0], "no_paymethods", "No configuraste cómo te pagan",
             "Agrega tus métodos de cobro para que salgan en los recibos.",
             "Configurar", "/agencia/metodos")
    return alerts


def dismiss_alert(conn: sqlite3.Connection, agency_id: int, key: str,
                  actor_id: str = "") -> None:
    conn.execute("INSERT OR IGNORE INTO dismissed_alerts(agency_id, alert_key) VALUES (?,?)",
                 (agency_id, (key or "")[:120]))
    conn.commit()
    audit(conn, agency_id, "owner", "alert_dismissed", detail="key=%s" % key,
          actor_id=actor_id)


# ---------------------------------------------------------------- acceso multi-locación del dueño
# Las credenciales viven en la tabla agencies (owner_email / owner_password_hash /
# owner_login_enabled / owner_must_change_password), igual que el código probado.
# Un mismo email une automáticamente todas sus locaciones: la sesión firma el
# email y el panel opera sobre TODAS las agencias activas de ese dueño.
def _dbmod():
    import db as _db  # módulo top-level en /opt/sahjony-packages/app
    return _db


def owner_agencies(conn: sqlite3.Connection, email: str):
    """Todas las agencias activas con login habilitado para este email."""
    email = _norm_email(email)
    if not email:
        return []
    try:
        return conn.execute(
            "SELECT * FROM agencies WHERE lower(owner_email)=? "
            "AND owner_login_enabled=1 AND active=1 ORDER BY id",
            (email,)).fetchall()
    except Exception:
        return []


def owner_login(conn: sqlite3.Connection, email: str, password: str):
    """Verifica la contraseña contra las agencias del email. Devuelve la lista
    de agencias si alguna coincide, o [] si no."""
    rows = owner_agencies(conn, email)
    if not rows:
        return []
    dbm = _dbmod()
    ok = [r for r in rows
          if (r["owner_password_hash"] or "") and
          dbm.verify_customer_password(r["owner_password_hash"], password or "")]
    return ok


def owner_must_change(conn: sqlite3.Connection, email: str) -> bool:
    email = _norm_email(email)
    if not email:
        return False
    try:
        r = conn.execute(
            "SELECT COUNT(*) AS c FROM agencies WHERE lower(owner_email)=? "
            "AND owner_login_enabled=1 AND owner_must_change_password=1",
            (email,)).fetchone()
        return (r["c"] if r else 0) > 0
    except Exception:
        return False


def grant_owner_access(conn: sqlite3.Connection, agency_id: int, email: str):
    """Otorga acceso web a una agencia. Si el email ya tiene contraseña en otra
    locación, se REUTILIZA (unifica); si no, genera una temporal (mostrar 1 vez).
    Devuelve (temp_o_None, reutilizada: bool)."""
    email = _norm_email(email)
    if not email or "@" not in email:
        raise ValueError("Email inválido")
    dbm = _dbmod()
    src = conn.execute(
        "SELECT owner_password_hash, owner_must_change_password FROM agencies "
        "WHERE lower(owner_email)=? AND id<>? AND owner_password_hash<>'' LIMIT 1",
        (email, agency_id)).fetchone()
    if src:
        conn.execute(
            "UPDATE agencies SET owner_email=?, owner_password_hash=?, "
            "owner_login_enabled=1, owner_must_change_password=? WHERE id=?",
            (email, src["owner_password_hash"],
             1 if src["owner_must_change_password"] else 0, agency_id))
        conn.commit()
        ensure_owner_row(conn, email)
        audit(conn, agency_id, "staff", "owner_access_granted",
              entity="agencies", entity_id=agency_id,
              detail="email=%s (contraseña unificada)" % email, actor_id="staff")
        return None, True
    temp = dbm.issue_temp_password(10)
    conn.execute(
        "UPDATE agencies SET owner_email=?, owner_password_hash=?, "
        "owner_login_enabled=1, owner_must_change_password=1 WHERE id=?",
        (email, dbm.hash_customer_password(temp), agency_id))
    conn.commit()
    ensure_owner_row(conn, email)
    audit(conn, agency_id, "staff", "owner_access_granted",
          entity="agencies", entity_id=agency_id,
          detail="email=%s (temporal generada)" % email, actor_id="staff")
    return temp, False


def owner_set_password(conn: sqlite3.Connection, email: str, new_password: str) -> None:
    """Cambia la contraseña en TODAS las locaciones del email (unificada)."""
    email = _norm_email(email)
    if not email:
        raise ValueError("Email inválido")
    if not new_password or len(new_password) < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres")
    dbm = _dbmod()
    conn.execute(
        "UPDATE agencies SET owner_password_hash=?, owner_must_change_password=0 "
        "WHERE lower(owner_email)=?",
        (dbm.hash_customer_password(new_password), email))
    conn.commit()
    audit(conn, 0, "owner", "password_changed", detail="email=%s" % email,
          actor_id=email)


# ---------------------------------------------------------------- solicitudes: aprobar / rechazar (atajos)
def approve_request(conn: sqlite3.Connection, req_id: int, by: str = "staff") -> int:
    """Aprueba y crea la agencia (términos NULL = pendientes). Devuelve agency_id.
    El acceso web se otorga después con grant_owner_access (muestra la temporal)."""
    r = get_request(conn, req_id)
    if not r or r["status"] != "pendiente":
        raise LookupError("Solicitud no encontrada o ya decidida")
    review_request(conn, req_id, True, "", by)
    return staff_create_agency_from_request(conn, req_id, {}, by)


def reject_request(conn: sqlite3.Connection, req_id: int, by: str = "staff") -> bool:
    return review_request(conn, req_id, False, "", by)


# ---------------------------------------------------------------- plantillas: guardar
def upsert_template(conn: sqlite3.Connection, agency_id: int, event: str,
                    channel: str, title: str, body: str) -> None:
    conn.execute(
        """INSERT INTO notification_templates
           (agency_id, event, channel, title_template, body_template)
           VALUES (?,?,?,?,?)
           ON CONFLICT(agency_id, event, channel) DO UPDATE SET
             title_template=excluded.title_template,
             body_template=excluded.body_template""",
        (agency_id, (event or "").strip()[:80], (channel or "portal").strip()[:20],
         (title or "").strip()[:200], (body or "").strip()[:2000]))
    conn.commit()


# ---------------------------------------------------------------- Resend: guardar clave + envío con remitente
def save_resend_key(api_key: str) -> None:
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Clave vacía")
    d = os.path.dirname(RESEND_KEY_FILE)
    os.makedirs(d, exist_ok=True)
    with open(RESEND_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key + "\n")
    os.chmod(RESEND_KEY_FILE, 0o600)


def resend_key_exists() -> bool:
    return resend_active()


def send_resend_email(to: str, subject: str, html: str, sender: str = None):
    """Envío con remitente configurable. Nunca lanza excepción."""
    if sender:
        try:
            set_notify_from(sender)
        except Exception:
            pass
    return send_via_resend(to, subject, html, brand="SAHJONY")


# ---------------------------------------------------------------- escaneo: fotos → PDF
# Límite anti "bomba de descompresión": ninguna foto puede exceder 50 MP
# (~una cámara de 50 megapíxeles). Pillow además trae su propio límite.
_SCAN_MAX_PIXELS = 50_000_000

def scan_images_to_pdf(images: list) -> bytes:
    """Combina fotos (bytes) en un PDF multipágina. Requiere PIL.
    Verifica cada imagen con Pillow (rechaza lo que no sea imagen real) y
    limita las dimensiones para evitar bombas de descompresión."""
    from PIL import Image
    import io as _io
    pages = []
    for raw in images:
        img = Image.open(_io.BytesIO(raw))
        img.load()  # decodifica de verdad; falla si no es imagen
        w, h = img.size
        if w * h > _SCAN_MAX_PIXELS:
            raise ValueError("Imagen demasiado grande (máx 50 MP)")
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        pages.append(img)
    if not pages:
        raise ValueError("Sin imágenes")
    buf = _io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


# ---------------------------------------------------------------- economía:
# facturas, cobros, gastos y métodos de pago (esquema propio, sano).
_ECON_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY, agency_id INTEGER NOT NULL, number TEXT NOT NULL,
  customer_id INTEGER DEFAULT 0, order_id INTEGER DEFAULT 0,
  subtotal REAL DEFAULT 0, discount REAL DEFAULT 0, tax REAL DEFAULT 0,
  total REAL DEFAULT 0, status TEXT DEFAULT 'pendiente',
  due_date TEXT DEFAULT '', notes TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS invoice_items (
  id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL, label TEXT NOT NULL,
  qty REAL DEFAULT 1, unit_price REAL DEFAULT 0, amount REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY, agency_id INTEGER NOT NULL, invoice_id INTEGER DEFAULT 0,
  customer_id INTEGER DEFAULT 0, order_id INTEGER DEFAULT 0,
  amount REAL NOT NULL, method TEXT DEFAULT '', reference TEXT DEFAULT '',
  notes TEXT DEFAULT '', paid_at TEXT DEFAULT (datetime('now')),
  received_by TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY, agency_id INTEGER NOT NULL, category TEXT DEFAULT '',
  label TEXT NOT NULL, amount REAL NOT NULL,
  spent_at TEXT DEFAULT (date('now')), notes TEXT DEFAULT '',
  created_by TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS agency_payment_methods (
  id INTEGER PRIMARY KEY, agency_id INTEGER NOT NULL, label TEXT NOT NULL,
  kind TEXT DEFAULT 'otro', details TEXT DEFAULT '', is_default INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS agency_price_list (
  id INTEGER PRIMARY KEY, agency_id INTEGER NOT NULL, label TEXT NOT NULL,
  price REAL DEFAULT 0, unit TEXT DEFAULT '', active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS idx_invoices_ag ON invoices(agency_id, id);
CREATE INDEX IF NOT EXISTS idx_payments_ag ON payments(agency_id, id);
CREATE INDEX IF NOT EXISTS idx_expenses_ag ON expenses(agency_id, id);
CREATE INDEX IF NOT EXISTS idx_paymethods_ag ON agency_payment_methods(agency_id, id);
CREATE INDEX IF NOT EXISTS idx_pricelist_ag ON agency_price_list(agency_id, id);
"""


def next_invoice_number(conn, agency_id) -> str:
    """Número legible por agencia: A-<ag>-0001 (secuencia por agencia)."""
    row = conn.execute(
        "SELECT number FROM invoices WHERE agency_id=? ORDER BY id DESC LIMIT 1",
        (agency_id,)).fetchone()
    n = 0
    if row and row["number"]:
        try:
            n = int(row["number"].rsplit("-", 1)[1])
        except (ValueError, IndexError):
            n = 0
    return "A-%d-%04d" % (agency_id, n + 1)


def create_invoice(conn, agency_id, customer_id=0, order_id=0, items=(),
                   discount=0.0, tax=0.0, due_date="", notes="", created_by="owner") -> int:
    """Crea factura con sus líneas. items: [(label, qty, unit_price)]."""
    agency_id = int(agency_id)
    number = next_invoice_number(conn, agency_id)
    lines = []
    subtotal = 0.0
    for label, qty, price in items:
        amount = (qty or 0) * (price or 0)
        subtotal += amount
        lines.append((str(label)[:200], qty or 0, price or 0, amount))
    total = subtotal - (discount or 0) + (tax or 0)
    cur = conn.execute(
        """INSERT INTO invoices
           (agency_id, number, customer_id, order_id, subtotal, discount, tax, total,
            status, due_date, notes, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
        (agency_id, number, customer_id or 0, order_id or 0, subtotal,
         discount or 0, tax or 0, total,
         "pendiente" if total > 0 else "pagada", due_date or "",
         (notes or "")[:500]))
    inv_id = cur.lastrowid
    for label, qty, price, amount in lines:
        conn.execute(
            "INSERT INTO invoice_items (invoice_id, label, qty, unit_price, amount)"
            " VALUES (?,?,?,?,?)", (inv_id, label, qty, price, amount))
    conn.commit()
    audit(conn, agency_id, created_by or "owner", "invoice_created",
          entity="invoices", entity_id=inv_id, detail="%s $%.2f" % (number, total),
          actor_id=created_by or "owner")
    return inv_id


def get_invoice(conn, agency_id, invoice_id):
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND agency_id=?",
                       (invoice_id, agency_id)).fetchone()
    if not inv:
        return None, []
    items = conn.execute("SELECT * FROM invoice_items WHERE invoice_id=?",
                         (invoice_id,)).fetchall()
    return inv, items


def list_invoices(conn, agency_id, limit=100):
    return conn.execute(
        "SELECT * FROM invoices WHERE agency_id=? ORDER BY id DESC LIMIT ?",
        (agency_id, limit)).fetchall()


def invoice_balance(conn, invoice_id) -> tuple:
    """(pagado, saldo). Cálculo directo, sin subfunciones rotas."""
    inv = conn.execute("SELECT total FROM invoices WHERE id=?",
                       (invoice_id,)).fetchone()
    total = (inv["total"] or 0) if inv else 0
    paid = conn.execute("SELECT COALESCE(SUM(amount),0) p FROM payments WHERE invoice_id=?",
                        (invoice_id,)).fetchone()["p"] or 0
    return paid, max(total - paid, 0)


def record_payment(conn, agency_id, invoice_id, amount, method="", reference="",
                   notes="", received_by="owner") -> int:
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND agency_id=?",
                       (invoice_id, agency_id)).fetchone()
    if not inv:
        raise ValueError("Factura no encontrada")
    if amount <= 0:
        raise ValueError("Monto inválido")
    cur = conn.execute(
        """INSERT INTO payments
           (agency_id, invoice_id, customer_id, order_id, amount, method, reference,
            notes, paid_at, received_by)
           VALUES (?,?,?,?,?,?,?, ?, datetime('now'), ?)""",
        (agency_id, invoice_id, inv["customer_id"] or 0, inv["order_id"] or 0,
         amount, (method or "")[:60], (reference or "")[:120],
         (notes or "")[:300], received_by or "owner"))
    pid = cur.lastrowid
    paid, balance = invoice_balance(conn, invoice_id)
    conn.execute("UPDATE invoices SET status=? WHERE id=?",
                 ("pagada" if balance <= 0.005 else "parcial", invoice_id))
    conn.commit()
    audit(conn, agency_id, received_by or "owner", "payment_recorded",
          entity="payments", entity_id=pid,
          detail="factura %s $%.2f" % (inv["number"], amount),
          actor_id=received_by or "owner")
    return pid


def list_payments(conn, agency_id, limit=100):
    return conn.execute(
        """SELECT p.*, i.number AS inv_number FROM payments p
           LEFT JOIN invoices i ON i.id=p.invoice_id
           WHERE p.agency_id=? ORDER BY p.id DESC LIMIT ?""",
        (agency_id, limit)).fetchall()


def add_expense(conn, agency_id, label, amount, category="", notes="",
                created_by="owner") -> int:
    if amount <= 0:
        raise ValueError("Monto inválido")
    cur = conn.execute(
        """INSERT INTO expenses
           (agency_id, category, label, amount, spent_at, notes, created_by)
           VALUES (?,?,?, ?, date('now'), ?, ?)""",
        (agency_id, (category or "")[:60], (label or "")[:200], amount,
         (notes or "")[:300], created_by or "owner"))
    conn.commit()
    audit(conn, agency_id, created_by or "owner", "expense_added",
          entity="expenses", entity_id=cur.lastrowid,
          detail="%s $%.2f" % (label[:60], amount), actor_id=created_by or "owner")
    return cur.lastrowid


def list_expenses(conn, agency_id, limit=100):
    return conn.execute(
        "SELECT * FROM expenses WHERE agency_id=? ORDER BY spent_at DESC, id DESC LIMIT ?",
        (agency_id, limit)).fetchall()


def delete_expense(conn, agency_id, expense_id) -> bool:
    cur = conn.execute("DELETE FROM expenses WHERE id=? AND agency_id=?",
                       (expense_id, agency_id))
    conn.commit()
    return cur.rowcount > 0


def list_payment_methods(conn, agency_id):
    return conn.execute(
        "SELECT * FROM agency_payment_methods WHERE agency_id=? AND active=1"
        " ORDER BY is_default DESC, id",
        (agency_id,)).fetchall()


def add_payment_method(conn, agency_id, label, kind="otro", details="") -> int:
    cur = conn.execute(
        "INSERT INTO agency_payment_methods (agency_id, label, kind, details, active)"
        " VALUES (?,?,?,?,1)",
        (agency_id, (label or "")[:120], (kind or "otro")[:30], (details or "")[:300]))
    conn.commit()
    return cur.lastrowid


def delete_payment_method(conn, agency_id, method_id) -> bool:
    cur = conn.execute("UPDATE agency_payment_methods SET active=0 WHERE id=? AND agency_id=?",
                       (method_id, agency_id))
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------- paquetes: estado con ownership
PKG_STATUSES = ("RECIBIDO", "EN_TRANSITO", "EN_ADUANA", "EN_REPARTO",
                "ENTREGADO", "CANCELADO")


def set_package_status(conn, agency_id, package_id, new_status, actor="owner",
                       actor_id="") -> bool:
    """Actualiza el estado solo si el paquete pertenece a la agencia."""
    if new_status not in PKG_STATUSES:
        raise ValueError("Estado inválido")
    hit = conn.execute(
        """SELECT p.id FROM packages p JOIN orders o ON o.id=p.order_id
           WHERE p.id=? AND o.agency_id=?""", (package_id, agency_id)).fetchone()
    if not hit:
        return False
    conn.execute("UPDATE packages SET status=? WHERE id=?", (new_status, package_id))
    conn.commit()
    audit(conn, agency_id, actor, "package_status", entity="packages",
          entity_id=package_id, detail="→ %s" % new_status, actor_id=actor_id or actor)
    return True


# ---------------------------------------------------------------- clientes con asociación explícita
def add_customer(conn, agency_id, name, phone, email="", notes="", created_by="owner") -> int:
    """Crea el cliente y lo vincula a la agencia (visible aunque no tenga órdenes)."""
    dbm = _dbmod()
    cid = dbm.add_agency_customer(conn, (name or "").strip(), (phone or "").strip(),
                                  (email or "").strip(), (notes or "")[:500])
    conn.execute("INSERT OR IGNORE INTO customer_agencies(customer_id, agency_id)"
                 " VALUES (?,?)", (cid, int(agency_id)))
    conn.commit()
    audit(conn, int(agency_id), created_by or "owner", "customer_created",
          entity="customers", entity_id=cid, detail=(name or "")[:60],
          actor_id=created_by or "owner")
    return cid


def owner_customers(conn, agency_ids, q=None):
    """Clientes vinculados a estas agencias (aunque no tengan órdenes)."""
    if not agency_ids:
        return []
    ph = ",".join("?" for _ in agency_ids)
    sql = (f"""SELECT c.*, (SELECT COUNT(*) FROM orders o WHERE o.customer_id=c.id
                    AND o.agency_id IN ({ph})) AS n_orders
               FROM customers c JOIN customer_agencies ca ON ca.customer_id=c.id
               WHERE ca.agency_id IN ({ph})""")
    params = list(agency_ids) * 2
    if q:
        sql += " AND (c.name LIKE ? OR c.phone LIKE ?)"
        like = "%%%s%%" % q
        params += [like, like]
    return conn.execute(sql + " GROUP BY c.id ORDER BY c.name", params).fetchall()


# ---------------------------------------------------------------- lista de precios
def list_price_list(conn, agency_id):
    return conn.execute(
        "SELECT * FROM agency_price_list WHERE agency_id=? AND active=1 ORDER BY id",
        (agency_id,)).fetchall()


def add_price(conn, agency_id, label, price, unit="") -> int:
    cur = conn.execute(
        "INSERT INTO agency_price_list (agency_id, label, price, unit, active)"
        " VALUES (?,?,?,?,1)",
        (agency_id, (label or "")[:120], price or 0, (unit or "")[:30]))
    conn.commit()
    return cur.lastrowid


def delete_price(conn, agency_id, item_id) -> bool:
    cur = conn.execute("UPDATE agency_price_list SET active=0 WHERE id=? AND agency_id=?",
                       (item_id, agency_id))
    conn.commit()
    return cur.rowcount > 0


def economy_summary(conn, agency_id, days=30) -> dict:
    """Resumen simple: cobrado, gastado, facturado pendiente."""
    days = int(days)
    cob = conn.execute(
        "SELECT COALESCE(SUM(amount),0) t FROM payments WHERE agency_id=?"
        " AND paid_at >= datetime('now','-%d days')" % days, (agency_id,)).fetchone()["t"] or 0
    gas = conn.execute(
        "SELECT COALESCE(SUM(amount),0) t FROM expenses WHERE agency_id=?"
        " AND spent_at >= date('now','-%d days')" % days, (agency_id,)).fetchone()["t"] or 0
    row3 = conn.execute(
        "SELECT COALESCE(SUM(total),0) t,"
        " COALESCE(SUM(CASE WHEN status='pendiente' THEN total ELSE 0 END),0) p"
        " FROM invoices WHERE agency_id=?", (agency_id,)).fetchone()
    return {"cobrado": cob, "gastado": gas, "neto": cob - gas,
            "facturado_total": row3["t"] or 0, "facturado_pendiente": row3["p"] or 0}
