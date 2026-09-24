"""Centro de comando — parte 3: órdenes, paquetes en orden, mensajes, notificar."""
from __future__ import annotations

from ac_shared import *

router = APIRouter()

STATUS_LABEL = {"RECIBIDO": "Recibido", "EN_TRANSITO": "En tránsito",
                "EN_ADUANA": "En aduana", "EN_REPARTO": "En reparto",
                "ENTREGADO": "Entregado", "CANCELADO": "Cancelado",
                "preparando": "Preparando", "en_transito": "En tránsito",
                "entregado": "Entregado", "cerrado": "Cerrado"}


def _status_badge(st: str) -> str:
    return '<span class="badge">%s</span>' % _e(STATUS_LABEL.get(st or "", st or "—"))


@router.get("/agencia/ordenes", response_class=HTMLResponse)
def agencia_orders(request: Request, q: str = "", estado: str = "", loc: str = ""):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    ids, _w = _order_scope(ctx, loc)
    conn = dbmod.get_db()
    try:
        orders = []
        for aid in ids:
            orders += dbmod.get_agency_orders(conn, aid, q=q or None, limit=200)
        orders.sort(key=lambda o: o["id"], reverse=True)
        # Peso total por orden en una sola consulta.
        wmap = {}
        if orders:
            ph = ",".join("?" for _ in orders)
            for r in conn.execute(
                    f"SELECT order_id, COALESCE(SUM(weight_kg),0) AS kg FROM packages "
                    f"WHERE order_id IN ({ph}) GROUP BY order_id",
                    [o["id"] for o in orders]).fetchall():
                wmap[r["order_id"]] = (r["kg"] or 0) * 2.20462
    finally:
        conn.close()
    rows = "".join(
        '<tr><td><a href="/agencia/ordenes/%d"><b>%s</b></a><br><span class="muted">%s · %s</span></td>'
        '<td>%d paq<br><span class="muted">%.1f lb</span></td>'
        '<td>%s<br><span class="muted">%s</span></td></tr>'
        % (o["id"], _e(o["order_number"]), _e(o["customer_name"] or ""),
           _e(o["tracking_code"] or ""), o["package_count"] or 0,
           wmap.get(o["id"], 0), _status_badge(o["payment_status"]),
           _e((o["created_at"] or "")[:10])) for o in orders)
    body = ('<form method="get" class="noprint"><label>Buscar<input name="q" value="%s" '
            'placeholder="Orden, rastreo, cliente, teléfono"></label>'
            '<button class="btn sm">Buscar</button></form>'
            '<table>%s</table>'
            '<a class="btn" href="/agencia/ordenes/nueva">+ Nueva orden</a> '
            '<a class="btn sec" href="/agencia/ordenes.csv">⬇ CSV</a>'
            % (_e(q), rows or '<tr><td class="muted">Aún no tienes órdenes.</td></tr>'))
    return HTMLResponse(_layout("Órdenes", ctx, body, active="ordenes"))


@router.get("/agencia/ordenes/nueva", response_class=HTMLResponse)
def agencia_order_new_form(request: Request, loc: str = ""):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    ids, wid = _order_scope(ctx, loc)
    body = ('<div class="card"><form method="post">%s'
            '<label>Cliente (nombre)*<input name="customer_name" required></label>'
            '<label>Teléfono del cliente*<input name="customer_phone" required></label>'
            '<label>Correo del cliente<input name="customer_email" type="email"></label>'
            '<label>Notas<textarea name="notes" rows="2"></textarea></label>'
            '<h3>Paquete 1</h3>'
            '<label>Destinatario en Cuba*<input name="recipient_name" required></label>'
            '<label>Teléfono destinatario<input name="recipient_phone"></label>'
            '<label>Provincia<input name="province"></label>'
            '<label>Municipio<input name="municipality"></label>'
            '<label>Contenido*<input name="contents" required></label>'
            '<label>Peso (lb)*<input name="weight_lb" inputmode="decimal" required></label>'
            '<button class="btn ok" style="width:100%%">Crear orden</button></form></div>'
            % (('<input type="hidden" name="loc" value="%d">' % wid) +
               (_loc_selector(ctx, wid) if ctx["multi"] else "")))
    return HTMLResponse(_layout("Nueva orden", ctx, body, active="ordenes"))


@router.post("/agencia/ordenes/nueva")
async def agencia_order_create(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    ag = _write_agency(ctx, form.get("loc") or "")
    try:
        weight_lb = float(form.get("weight_lb") or 0)
    except ValueError:
        raise HTTPException(400, "Peso inválido.")
    if weight_lb <= 0:
        raise HTTPException(400, "El peso debe ser mayor que cero.")
    for f in ("customer_name", "customer_phone", "recipient_name", "contents"):
        if not (form.get(f) or "").strip():
            raise HTTPException(400, "Faltan datos obligatorios.")
    conn = dbmod.get_db()
    try:
        # Alcance por agencia: solo se reutiliza un cliente si ya está
        # vinculado a ESTA agencia (nunca el de otra locación/otro dueño).
        cust = conn.execute(
            """SELECT c.id FROM customers c
               JOIN customer_agencies ca ON ca.customer_id=c.id
               WHERE c.phone=? AND ca.agency_id=?""",
            ((form.get("customer_phone") or "").strip(), ag["id"])).fetchone()
        if cust:
            customer_id = cust["id"]
            conn.execute("UPDATE customers SET name=?, email=? WHERE id=?",
                         ((form.get("customer_name") or "").strip(),
                          (form.get("customer_email") or "").strip(), customer_id))
        else:
            customer_id = adb.add_customer(
                conn, ag["id"], (form.get("customer_name") or "").strip(),
                (form.get("customer_phone") or "").strip(),
                (form.get("customer_email") or "").strip(), "", created_by=ctx["email"])
        rcur = conn.execute(
            "INSERT INTO recipients (name, phone, province, municipality) VALUES (?,?,?,?)",
            ((form.get("recipient_name") or "").strip(),
             (form.get("recipient_phone") or "").strip(),
             (form.get("province") or "").strip()[:80],
             (form.get("municipality") or "").strip()[:80]))
        recipient_id = rcur.lastrowid
        onum = dbmod.next_order_number(conn)
        tcode = dbmod.new_order_tracking_code(conn)
        ocur = conn.execute(
            "INSERT INTO orders (order_number, customer_id, agency_id, tracking_code,"
            " payment_status, notes) VALUES (?,?,?,?,?,?)",
            (onum, customer_id, ag["id"], tcode, "PENDIENTE",
             (form.get("notes") or "").strip()[:1000]))
        order_id = ocur.lastrowid
        conn.execute(
            "INSERT INTO packages (code, order_id, recipient_id, contents, weight_kg, status)"
            " VALUES (?,?,?,?,?,?)",
            (dbmod.new_package_code(), order_id, recipient_id,
             (form.get("contents") or "").strip()[:500], weight_lb / 2.20462, "RECIBIDO"))
        conn.commit()
        adb.audit(conn, ag["id"], "owner", "order_created", entity="orders",
                  entity_id=order_id, detail=onum, actor_id=ctx["email"])
        adb.notify_customer(conn, ag["id"], customer_id, order_id, "orden_creada",
                            {"brand": _brand(ag), "order_number": onum, "tracking": tcode},
                            channels=("portal", "email"))
    finally:
        conn.close()
    return RedirectResponse("/agencia/ordenes/%d" % order_id, status_code=303)


@router.get("/agencia/ordenes/{order_id}", response_class=HTMLResponse)
def agencia_order_detail(request: Request, order_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        order = pag = None
        for aid in ctx["agency_ids"]:
            order = dbmod.get_agency_order(conn, aid, order_id)
            if order:
                pag = aid
                break
        if not order:
            raise HTTPException(404, "Orden no encontrada")
        ag = next(a for a in ctx["agencies"] if a["id"] == pag)
        pkgs = dbmod.get_agency_order_packages(conn, pag, order_id)
        msgs = dbmod.get_portal_messages(conn, order_id)
        dbmod.mark_portal_messages_read(conn, order_id, "staff")
    finally:
        conn.close()
    total_lb = sum((p["weight_kg"] or 0) * 2.20462 for p in pkgs)
    pkg_rows = "".join(
        '<tr><td><b>%s</b><br><span class="muted">%s</span></td>'
        '<td>%.1f lb</td><td>%s</td>'
        '<td class="noprint"><form method="post" action="/agencia/paquetes/%d/estado" '
        'style="display:inline"><select name="status">%s</select>'
        '<button class="btn sm sec">OK</button></form> '
        '<a class="btn sm sec" href="/agencia/paquetes/%d/etiqueta">🏷</a></td></tr>'
        % (_e(p["code"]), _e(p["contents"] or "")[:60],
           (p["weight_kg"] or 0) * 2.20462, _status_badge(p["status"]), p["id"],
           "".join('<option value="%s"%s>%s</option>'
                   % (s, " selected" if s == p["status"] else "", _e(STATUS_LABEL.get(s, s)))
                   for s in ("RECIBIDO", "EN_TRANSITO", "EN_ADUANA", "EN_REPARTO",
                             "ENTREGADO", "CANCELADO")),
           p["id"]) for p in pkgs)
    msg_rows = "".join(
        '<div class="card" style="%s"><b>%s</b> <span class="muted">%s</span><br>%s</div>'
        % ("background:#eef4ff" if m["sender"] == "customer" else "",
           "Cliente" if m["sender"] == "customer" else _e(_brand(ag)),
           _e((m["created_at"] or "")[:16]), _e(m["body"]))
        for m in msgs)
    last_customer = next((m["body"] for m in reversed(msgs) if m["sender"] == "customer"), "")
    sug = ""
    if last_customer:
        sugs = adb.suggest_replies(last_customer, {
            "order_number": order["order_number"], "tracking": order["tracking_code"] or "",
            "status": STATUS_LABEL.get(pkgs[0]["status"], "") if pkgs else "",
            "customer_name": (order["customer_name"] or "").split(" ")[0],
            "brand": _brand(ag)})
        sug = ('<div class="card"><h3>💡 Respuestas sugeridas (tócala para usarla)</h3>' +
               "".join(
                   '<button type="button" class="sug" data-t="%s" onclick="document.'
                   'getElementById(\'replybody\').value=this.dataset.t">💡 <b>%s</b></button>'
                   % (_e(text).replace('"', "&quot;"), _e(intent)) for intent, text in sugs) +
               '<p class="muted">Nada se envía solo: revísala y pulsa Enviar.</p></div>')
    body = ('<div class="card"><h2>Orden %s</h2>'
            '<span class="muted">%s · Rastreo: <b>%s</b><br>%s · %d paquetes · %.1f lb</span><br>'
            '%s</div>'
            '<div class="card"><h3>Paquetes</h3><table>%s</table>'
            '<a class="btn sm sec" href="/agencia/ordenes/%d/etiquetas">🖨 Etiquetas (todas)</a></div>'
            '<div class="card" id="mensajes"><h3>💬 Mensajes</h3>%s%s'
            '<form method="post" action="/agencia/ordenes/%d/mensaje">'
            '<label>Responder<textarea id="replybody" name="body" rows="3" maxlength="2000" '
            'required></textarea></label>'
            '<button class="btn ok">Enviar al cliente</button></form></div>'
            '<div class="card"><h3>🔔 Notificar al cliente</h3>'
            '<div class="noprint">'
            '<form method="post" action="/agencia/ordenes/%d/notificar" style="display:inline">'
            '<input type="hidden" name="canal" value="portal">'
            '<button class="btn sm sec">Portal</button></form> '
            '<form method="post" action="/agencia/ordenes/%d/notificar" style="display:inline">'
            '<input type="hidden" name="canal" value="email">'
            '<button class="btn sm sec">Email</button></form> '
            '<form method="post" action="/agencia/ordenes/%d/notificar" style="display:inline">'
            '<input type="hidden" name="canal" value="whatsapp">'
            '<button class="btn sm sec">WhatsApp</button></form>'
            '</div></div>'
            '<div class="card"><h3>📎 Documentos</h3>'
            '<a class="btn sm sec" href="/agencia/documentos?tipo=&q_orden=%d">Ver documentos</a></div>'
            % (_e(order["order_number"]), _e(order["customer_name"] or ""),
               _e(order["tracking_code"] or ""), _e(order["customer_phone"] or ""),
               len(pkgs), total_lb, _status_badge(order["payment_status"]),
               pkg_rows or '<tr><td class="muted">Sin paquetes.</td></tr>',
               order_id, msg_rows or '<p class="muted">Sin mensajes.</p>', sug,
               order_id, order_id, order_id, order_id, order_id))
    return HTMLResponse(_layout("Orden " + order["order_number"], ctx, body, active="ordenes"))


@router.post("/agencia/ordenes/{order_id}/mensaje")
async def agencia_order_message(request: Request, order_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    body = (form.get("body") or "").strip()
    if not body or len(body) > 2000:
        raise HTTPException(400, "Mensaje inválido (1–2000 caracteres).")
    ip = request.client.host if request.client else "?"
    key = "msg:%s:%d" % (ip, order_id)
    if not _throttle_ok(key, 10, 300):
        raise HTTPException(429, "Demasiados mensajes. Espera unos minutos.")
    _throttle_hit(key)
    conn = dbmod.get_db()
    try:
        order = pag = None
        for aid in ctx["agency_ids"]:
            order = dbmod.get_agency_order(conn, aid, order_id)
            if order:
                pag = aid
                break
        if not order:
            raise HTTPException(404, "Orden no encontrada")
        dbmod.send_portal_message(conn, order_id, order["customer_id"], pag, "staff", body)
        ag = next(a for a in ctx["agencies"] if a["id"] == pag)
        adb.notify_customer(conn, pag, order["customer_id"], order_id, "nuevo_mensaje",
                            {"brand": _brand(ag), "order_number": order["order_number"]},
                            channels=("portal", "email"))
        adb.audit(conn, pag, "owner", "message_sent", entity="orders",
                  entity_id=order_id, detail=body[:120], actor_id=ctx["email"])
    finally:
        conn.close()
    return RedirectResponse("/agencia/ordenes/%d#mensajes" % order_id, status_code=303)


@router.get("/agencia/mensajes", response_class=HTMLResponse)
def agencia_inbox(request: Request):
    """Bandeja unificada: hilos con mensajes no leídos por la agencia."""
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        rows = conn.execute(
            """SELECT pm.order_id, o.order_number, c.name AS customer_name,
                      MAX(pm.id) AS last_id,
                      SUM(CASE WHEN pm.read_by_staff=0 THEN 1 ELSE 0 END) AS n
               FROM portal_messages pm
               JOIN orders o ON o.id=pm.order_id
               JOIN customers c ON c.id=pm.customer_id
               WHERE pm.agency_id IN (%s)
               GROUP BY pm.order_id
               HAVING n>0
               ORDER BY last_id DESC""" % ",".join("?" * len(ctx["agency_ids"])),
            ctx["agency_ids"]).fetchall()
        body = "".join(
            '<div class="card"><b>Orden %s</b> — %s '
            '<span class="badge">%d sin leer</span><br>'
            '<a class="btn sm" href="/agencia/ordenes/%d#mensajes">Abrir</a></div>'
            % (_e(r["order_number"]), _e(r["customer_name"] or ""), r["n"], r["order_id"])
            for r in rows) or '<div class="card">Sin mensajes nuevos. 🎉</div>'
    finally:
        conn.close()
    return HTMLResponse(_layout("Mensajes", ctx, "<h2>💬 Mensajes</h2>" + body))


@router.post("/agencia/ordenes/{order_id}/notificar")
async def agencia_order_notify(request: Request, order_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    canal = (form.get("canal") or "portal").strip()
    if canal not in ("portal", "email", "whatsapp"):
        raise HTTPException(400, "Canal inválido.")
    conn = dbmod.get_db()
    try:
        order = pag = None
        for aid in ctx["agency_ids"]:
            order = dbmod.get_agency_order(conn, aid, order_id)
            if order:
                pag = aid
                break
        if not order:
            raise HTTPException(404, "Orden no encontrada")
        ag = next(a for a in ctx["agencies"] if a["id"] == pag)
        cust = conn.execute("SELECT * FROM customers WHERE id=?",
                            (order["customer_id"],)).fetchone()
        ctxd = {"brand": _brand(ag), "order_number": order["order_number"],
                "tracking": order["tracking_code"] or "",
                "customer_name": (cust["name"] if cust else "").split(" ")[0]}
        made = adb.notify_customer(conn, pag, order["customer_id"], order_id,
                                   "aviso_general", dict(ctxd, title="Aviso de " + _brand(ag),
                                                         body="Tienes novedades en tu orden %s."
                                                         % order["order_number"]),
                                   channels=(canal,))
        wa_url = ""
        if canal == "whatsapp" and cust and (cust["phone"] or "").strip():
            tpl = adb.get_template(conn, pag, "aviso_general", "portal")
            text = adb.render_tpl((tpl["body_template"] if tpl else
                                   "Hola {{customer_name}}: tienes novedades en tu orden {{order_number}}. — {{brand}}"),
                                  ctxd)
            wa_url = adb.wa_link(cust["phone"], text)
            adb.log_manual_notify(conn, pag, order["customer_id"], order_id,
                                  "aviso_general", "whatsapp", text, cust["phone"])
        if made and canal != "whatsapp":
            adb.log_manual_notify(conn, pag, order["customer_id"], order_id,
                                  "aviso_general", canal, made[0][1],
                                  recipient=(cust["name"] if cust else ""), status="enviada")
        adb.audit(conn, pag, "owner", "manual_notify", entity="orders",
                  entity_id=order_id, detail="canal=%s" % canal, actor_id=ctx["email"])
    finally:
        conn.close()
    if wa_url:
        return RedirectResponse(wa_url, status_code=303)
    note = ("✅ Aviso enviado por %s." % canal) if made else \
        "⚠️ No se pudo enviar (revisa el canal o los datos del cliente)."
    body = ('<div class="card"><p>%s</p><a class="btn" href="/agencia/ordenes/%d">Volver</a></div>'
            % (note, order_id))
    return HTMLResponse(_layout("Notificar", ctx, body, active="ordenes"))
