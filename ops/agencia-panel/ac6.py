"""Centro de comando — parte 6: documentos, escaneo, perfil, términos,
nueva locación, auditoría, notificaciones, plantillas, CSV, recibos,
rastreo público y rutas staff."""
from __future__ import annotations

import mimetypes
from urllib.parse import quote

from ac_shared import *

router = APIRouter()


# ---------------------------------------------------------------- documentos
@router.get("/agencia/documentos", response_class=HTMLResponse)
def agencia_documents(request: Request, tipo: str = ""):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        rows = []
        for aid in ctx["agency_ids"]:
            ag = next(a for a in ctx["agencies"] if a["id"] == aid)
            for d in adocs.list_agency_docs(conn, aid, tipo or ""):
                rows.append((ag, d))
        rows.sort(key=lambda t: t[1]["id"], reverse=True)
    finally:
        conn.close()
    trs = "".join(
        '<tr><td><b>%s</b><br><span class="muted">%s · v%d · %s</span></td>'
        '<td>%s</td><td>%s</td>'
        '<td class="noprint"><a class="btn sm sec" href="/agencia/documentos/%d">⬇</a></td></tr>'
        % (_e(d["label"] or d["code"]), _e(_brand(ag)),
           d["version"] or 1, _e((d["created_at"] or "")[:16]),
           _e(d["doc_type"]), "reemplazado" if d["superseded"] else "vigente",
           d["id"]) for ag, d in rows)
    return HTMLResponse(_layout("Documentos", ctx, '<table>%s</table>' %
                                (trs or '<tr><td class="muted">Sin documentos.</td></tr>')))


@router.get("/agencia/documentos/{doc_id}")
def agencia_doc_download(request: Request, doc_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        doc = adocs.get_doc_for_download(conn, doc_id, ctx["agency_ids"])
        if not doc:
            raise HTTPException(404, "Documento no encontrado")
        root = os.path.realpath(adocs.docs_root())
        full = os.path.realpath(os.path.join(root, doc["file_path"] or ""))
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            raise HTTPException(404, "Archivo no disponible")
        data = adocs.read_doc_bytes(doc)
        fname = "%s_v%d.%s" % (doc["code"] or "doc", doc["version"] or 1,
                               (doc["file_path"] or "").rsplit(".", 1)[-1] or "html")
        mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    finally:
        conn.close()
    return StreamingResponse(io.BytesIO(data), media_type=mime,
                             headers={"Content-Disposition":
                                      'attachment; filename="%s"' % fname})


# ---------------------------------------------------------------- recibo de orden
@router.get("/agencia/ordenes/{order_id}/recibo", response_class=HTMLResponse)
def agencia_order_receipt(request: Request, order_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        order = ag = None
        for aid in ctx["agency_ids"]:
            order = dbmod.get_agency_order(conn, aid, order_id)
            if order:
                ag = next(a for a in ctx["agencies"] if a["id"] == aid)
                break
        if not order:
            raise HTTPException(404, "Orden no encontrada")
        pkgs = dbmod.get_agency_order_packages(conn, ag["id"], order_id)
        total_lb = sum((p["weight_kg"] or 0) * 2.20462 for p in pkgs)
        rows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%.1f</td></tr>"
            % (_e(p["code"]), _e(p["contents"] or "")[:60],
               (p["weight_kg"] or 0) * 2.20462) for p in pkgs)
        html = ("""<h1>Recibo — Orden %s</h1>
<p><b>%s</b><br>%s<br>Tel: %s</p>
<p><b>Cliente:</b> %s · %s<br><b>Rastreo:</b> %s<br><b>Fecha:</b> %s</p>
<table border="1" cellpadding="6"><tr><th>Paquete</th><th>Contenido</th><th>Peso (lb)</th></tr>%s</table>
<p><b>Total paquetes:</b> %d · <b>Peso total:</b> %.1f lb</p>
<p class="muted">Operado con SAHJONY LLC</p>"""
                % (_e(order["order_number"]), _e(_brand(ag)), _e(_addr(ag)),
                   _e(ag["phone"] or ""), _e(order["customer_name"] or ""),
                   _e(order["customer_phone"] or ""), _e(order["tracking_code"] or ""),
                   _e((order["created_at"] or "")[:10]), rows, len(pkgs), total_lb))
        doc = adocs.write_doc(conn, ag["id"], "recibo", "rcb_%s" % order["order_number"],
                              html, ref_table="orders", ref_id=order_id,
                              created_by="owner",
                              label="Recibo orden " + order["order_number"])
        adb.audit(conn, ag["id"], "owner", "receipt_generated", entity="orders",
                  entity_id=order_id, detail="doc=%d" % doc["id"],
                  actor_id=ctx["email"])
    finally:
        conn.close()
    return HTMLResponse(_layout("Recibo " + order["order_number"], ctx,
                                html + '<br><br><div class="noprint">'
                                '<button class="btn" onclick="window.print()">🖨 Imprimir</button></div>',
                                active="ordenes"))


# ---------------------------------------------------------------- escaneo
# Límites de subida (servidor; el HTML es solo ayuda visual)
_SCAN_MAX_FILES = 20
_SCAN_MAX_BYTES = 15 * 1024 * 1024

@router.get("/agencia/escanear", response_class=HTMLResponse)
def agencia_scan_form(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    wid = ctx["agency_ids"][0]
    body = ('<div class="card"><h2>📷 Escanear</h2>'
            '<p class="muted">Toma fotos con tu teléfono y se combinan en un PDF.</p>'
            '<form method="post" enctype="multipart/form-data">'
            '<input type="hidden" name="loc" value="%d">'
            % wid
            + (_loc_selector(ctx, wid) if ctx["multi"] else "") +
            '<label>Nombre del documento<input name="label" required '
            'placeholder="Ej: Factura proveedor enero"></label>'
            '<label>Fotos (máx 20, 15 MB cada una)<input type="file" name="fotos" '
            'accept="image/*" multiple capture="environment" required></label>'
            '<button class="btn ok" style="width:100%">Crear PDF</button></form></div>')
    return HTMLResponse(_layout("Escanear", ctx, body))


@router.post("/agencia/escanear", response_class=HTMLResponse)
async def agencia_scan(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    ag = _write_agency(ctx, form.get("loc") or "")
    label = (form.get("label") or "").strip()[:120] or "Escaneo"
    uploads = form.getlist("fotos")
    # Límites: máx 20 archivos, 15 MB cada uno, solo imágenes verificadas.
    # La verificación real la hace Pillow (scan_images_to_pdf); aquí se
    # rechaza por tamaño antes de guardar nada en memoria.
    if len(uploads) > _SCAN_MAX_FILES:
        raise HTTPException(400, "Máximo %d fotos por escaneo." % _SCAN_MAX_FILES)
    datas = []
    for u in uploads:
        raw = await u.read()
        if raw and len(raw) <= _SCAN_MAX_BYTES:
            datas.append(raw)
    if not datas:
        raise HTTPException(400, "Sube al menos una foto (máx 15 MB cada una).")
    try:
        pdf = adb.scan_images_to_pdf(datas)
    except Exception as exc:
        raise HTTPException(400, "No se pudo crear el PDF: %s" % exc)
    conn = dbmod.get_db()
    try:
        doc = adocs.store_upload(conn, ag["id"], "escaneo", label, pdf,
                                 "application/pdf", created_by="owner")
    finally:
        conn.close()
    body = ('<div class="okmsg">✅ PDF creado: <b>%s</b> (%d páginas).</div>'
            '<a class="btn" href="/agencia/documentos/%d">⬇ Descargar</a> '
            '<a class="btn sec" href="/agencia/escanear">Otro</a>'
            % (_e(label), len(datas), doc["id"]))
    return HTMLResponse(_layout("Escanear", ctx, body))


# ---------------------------------------------------------------- perfil
_PROFILE_FIELDS = ("brand", "legal_name", "phone", "whatsapp", "address",
                   "city", "state", "service_areas", "pickup_hours")


@router.get("/agencia/perfil", response_class=HTMLResponse)
def agencia_profile(request: Request, loc: str = ""):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    ids, wid = _order_scope(ctx, loc)
    ag = next(a for a in ctx["agencies"] if a["id"] == wid)
    tipo = "Agencia formal" if (ag["agency_type"] or "agencia") == "agencia" else "Punto de recogida"
    inputs = "".join(
        '<label>%s<input name="%s" value="%s"></label>'
        % ({"brand": "Marca", "legal_name": "Nombre legal", "phone": "Teléfono",
            "whatsapp": "WhatsApp", "address": "Dirección", "city": "Ciudad",
            "state": "Estado", "service_areas": "Zonas que atiendes",
            "pickup_hours": "Horario de recogida"}[f], f, _e(ag[f] or ""))
        for f in _PROFILE_FIELDS)
    body = (('<div class="card"><h2>👤 Mi perfil</h2>'
             '<p class="muted">Tipo: <b>%s</b></p>'
             '<form method="post"><input type="hidden" name="loc" value="%d">'
             + (_loc_selector(ctx, wid) if ctx["multi"] else "") + '%s'
             '<button class="btn ok" style="width:100%%">Guardar</button></form></div>'
             '<div class="card"><h3>🔑 Cambiar contraseña</h3>'
             '<p class="muted">Es la misma para todas tus locaciones.</p>'
             '<a class="btn sec" href="/agencia/password">Cambiar</a></div>')
            % (tipo, wid, inputs))
    return HTMLResponse(_layout("Mi perfil", ctx, body))


@router.post("/agencia/perfil")
async def agencia_profile_save(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    ag = _write_agency(ctx, form.get("loc") or "")
    vals = {f: (form.get(f) or "").strip()[:200] for f in _PROFILE_FIELDS}
    if not vals["brand"]:
        raise HTTPException(400, "La marca es obligatoria.")
    conn = dbmod.get_db()
    try:
        sets = ", ".join("%s=?" % f for f in _PROFILE_FIELDS)
        conn.execute("UPDATE agencies SET %s WHERE id=?" % sets,
                     [vals[f] for f in _PROFILE_FIELDS] + [ag["id"]])
        conn.commit()
        adb.audit(conn, ag["id"], "owner", "profile_updated",
                  detail="marca=%s" % vals["brand"][:60], actor_id=ctx["email"])
    finally:
        conn.close()
    return RedirectResponse("/agencia/perfil?loc=%d" % ag["id"], status_code=303)


# ---------------------------------------------------------------- términos
@router.get("/agencia/terminos", response_class=HTMLResponse)
def agencia_terms(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        cards = ""
        for ag in ctx["agencies"]:
            full = conn.execute("SELECT * FROM agencies WHERE id=?",
                                (ag["id"],)).fetchone()
            if adb.terms_pending(full):
                cards += ('<div class="card"><h3>%s</h3><div class="alert">'
                          'Términos pendientes de confirmación. '
                          'SAHJONY te los confirmará pronto.</div></div>'
                          % _e(_brand(ag)))
                continue
            ver = adb.terms_version(full)
            acc = adb.last_acceptance(conn, ag["id"])
            accepted = acc and acc["terms_version"] == ver
            def _monto(v):
                return ("$%.2f" % v) if v is not None else \
                    "<span class='muted'>pendiente</span>"
            econ = ('<table><tr><td>Por orden</td><td>%s</td></tr>'
                    '<tr><td>Por paquete</td><td>%s</td></tr>'
                    '<tr><td>Por libra</td><td>%s</td></tr>'
                    '<tr><td>Mensualidad</td><td>%s</td></tr></table>'
                    % (_monto(full["commission_per_order"]),
                       _monto(full["commission_per_package"]),
                       _monto(full["rate_per_lb"]), _monto(full["monthly_fee"])))
            if accepted:
                cards += ('<div class="card"><h3>%s</h3>%s'
                          '<p class="okmsg">✅ Aceptados el %s.</p></div>'
                          % (_e(_brand(ag)), econ, _e((acc["accepted_at"] or "")[:10])))
            else:
                cards += ('<div class="card"><h3>%s</h3>%s'
                          '<form method="post" action="/agencia/terminos/%d/aceptar">'
                          '<button class="btn ok">Acepto estos términos</button></form>'
                          '<p class="muted">Solo lectura: los fija SAHJONY.</p></div>'
                          % (_e(_brand(ag)), econ, ag["id"]))
    finally:
        conn.close()
    return HTMLResponse(_layout("Términos", ctx, cards))


@router.post("/agencia/terminos/{agency_id}/aceptar")
async def agencia_terms_accept(request: Request, agency_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    if agency_id not in ctx["agency_ids"]:
        raise HTTPException(404, "Locación no autorizada")
    ip = request.client.host if request.client else ""
    conn = dbmod.get_db()
    try:
        full = conn.execute("SELECT * FROM agencies WHERE id=?", (agency_id,)).fetchone()
        if not full or adb.terms_pending(full):
            raise HTTPException(400, "Términos pendientes de confirmación.")
        adb.accept_terms(conn, agency_id, ip=ip, actor="owner", actor_id=ctx["email"])
    finally:
        conn.close()
    return RedirectResponse("/agencia/terminos", status_code=303)


# ---------------------------------------------------------------- nueva locación
@router.get("/agencia/nueva-locacion", response_class=HTMLResponse)
def agencia_newloc_form(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        own = conn.execute("SELECT can_create_agencies FROM agency_owners WHERE email=?",
                           (ctx["email"],)).fetchone()
        can = bool(own and own["can_create_agencies"])
        reqs = adb.list_requests(conn, owner_email=ctx["email"])
    finally:
        conn.close()
    if can:
        body = ('<div class="card"><h2>🏪 Nueva locación</h2>'
                '<p class="muted">Puedes crearla tú mismo; queda bajo tu mismo correo.</p>'
                '<form method="post">'
                '<label>Tipo<select name="agency_type"><option value="agencia">Agencia formal</option>'
                '<option value="punto_recogida">Punto de recogida (desde casa)</option></select></label>'
                '<label>Marca*<input name="brand" required></label>'
                '<label>Nombre legal<input name="legal_name"></label>'
                '<label>Ciudad<input name="city"></label>'
                '<label>Dirección<input name="address"></label>'
                '<label>Teléfono<input name="phone"></label>'
                '<button class="btn ok" style="width:100%">Crear locación</button></form></div>')
    else:
        body = ('<div class="card"><h2>🏪 Solicitar nueva locación</h2>'
                '<p class="muted">SAHJONY la revisa y te avisa. Nada se cobra por solicitar.</p>'
                '<form method="post">'
                '<label>Tipo<select name="agency_type"><option value="agencia">Agencia formal</option>'
                '<option value="punto_recogida">Punto de recogida (desde casa)</option></select></label>'
                '<label>Marca*<input name="brand" required></label>'
                '<label>Ciudad<input name="city"></label>'
                '<label>Dirección<input name="address"></label>'
                '<label>Teléfono<input name="phone"></label>'
                '<label>WhatsApp<input name="whatsapp"></label>'
                '<label>Zonas que atenderías<input name="service_area"></label>'
                '<label>Horario<input name="hours"></label>'
                '<label>Notas<textarea name="notes" rows="2"></textarea></label>'
                '<button class="btn ok" style="width:100%">Enviar solicitud</button></form></div>')
    rq = "".join(
        '<tr><td><b>%s</b><br><span class="muted">%s · %s</span></td><td>%s</td></tr>'
        % (_e(r["brand"] or r["business_name"] or "—"), _e(r["agency_type"]),
           _e((r["created_at"] or "")[:10]), _e(r["status"]))
        for r in reqs)
    body += '<div class="card"><h3>Mis solicitudes</h3><table>%s</table></div>' % \
        (rq or '<tr><td class="muted">Sin solicitudes.</td></tr>')
    return HTMLResponse(_layout("Nueva locación", ctx, body))


@router.post("/agencia/nueva-locacion")
async def agencia_newloc(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    data = {k: (form.get(k) or "").strip()[:200]
            for k in ("agency_type", "brand", "legal_name", "business_name",
                      "city", "address", "phone", "whatsapp", "email",
                      "service_area", "hours", "notes")}
    if not data["brand"]:
        raise HTTPException(400, "La marca es obligatoria.")
    if data["agency_type"] not in ("agencia", "punto_recogida"):
        raise HTTPException(400, "Tipo inválido.")
    conn = dbmod.get_db()
    try:
        own = conn.execute("SELECT can_create_agencies FROM agency_owners WHERE email=?",
                           (ctx["email"],)).fetchone()
        can = bool(own and own["can_create_agencies"])
        if can:
            try:
                new_id = adb.owner_self_create(conn, ctx["email"], data)
            except (PermissionError, ValueError) as exc:
                raise HTTPException(400, str(exc))
            msg = "✅ Locación creada. Usa la misma contraseña para entrar."
            back = "/agencia/panel"
        else:
            rid = adb.create_request(conn, ctx["email"], data)
            adb.audit(conn, ctx["agency_ids"][0], "owner", "location_requested",
                      entity_id=rid, detail=data["brand"][:60], actor_id=ctx["email"])
            msg = "✅ Solicitud enviada. SAHJONY la revisará."
            back = "/agencia/nueva-locacion"
    finally:
        conn.close()
    body = '<div class="card"><p>%s</p><a class="btn" href="%s">Continuar</a></div>' % (msg, back)
    return HTMLResponse(_layout("Nueva locación", ctx, body))


# ---------------------------------------------------------------- auditoría
@router.get("/agencia/auditoria", response_class=HTMLResponse)
def agencia_audit(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        ph = ",".join("?" for _ in ctx["agency_ids"])
        rows = conn.execute(
            f"SELECT * FROM audit_log WHERE agency_id IN ({ph})"
            " ORDER BY id DESC LIMIT 100", ctx["agency_ids"]).fetchall()
    finally:
        conn.close()
    trs = "".join(
        '<tr><td><b>%s</b><br><span class="muted">%s · %s</span></td>'
        '<td>%s</td></tr>'
        % (_e(r["action"]), _e(r["actor"] or ""), _e((r["created_at"] or "")[:16]),
           _e(r["detail"] or "")) for r in rows)
    return HTMLResponse(_layout("Actividad", ctx, '<table>%s</table>' %
                                (trs or '<tr><td class="muted">Sin actividad.</td></tr>')))


# ---------------------------------------------------------------- notificaciones (registro de envíos)
@router.get("/agencia/notificaciones", response_class=HTMLResponse)
def agencia_notifications(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        ph = ",".join("?" for _ in ctx["agency_ids"])
        rows = conn.execute(
            f"SELECT * FROM agency_notifications WHERE agency_id IN ({ph})"
            " ORDER BY id DESC LIMIT 100", ctx["agency_ids"]).fetchall()
    finally:
        conn.close()
    trs = "".join(
        '<tr><td><b>%s</b><br><span class="muted">%s · %s · %s</span></td>'
        '<td>%s</td></tr>'
        % (_e(r["event"]), _e(r["channel"]), _e(r["recipient"] or ""),
           _e((r["created_at"] or "")[:16]), _e((r["content"] or "")[:120]))
        for r in rows)
    return HTMLResponse(_layout("Notificaciones", ctx, '<table>%s</table>' %
                                (trs or '<tr><td class="muted">Sin envíos aún.</td></tr>')))


# ---------------------------------------------------------------- plantillas
@router.get("/agencia/plantillas", response_class=HTMLResponse)
def agencia_templates(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        cards = ""
        for a in ctx["agencies"]:
            tpls = adb.get_templates(conn, a["id"])
            trs = "".join(
                '<div class="card"><b>%s · %s</b>'
                '<form method="post" action="/agencia/plantillas/guardar">'
                '<input type="hidden" name="loc" value="%d">'
                '<input type="hidden" name="event" value="%s">'
                '<input type="hidden" name="channel" value="%s">'
                '<label>Asunto<input name="subject" value="%s"></label>'
                '<label>Texto<textarea name="body" rows="4">%s</textarea></label>'
                '<label style="font-weight:normal"><input type="checkbox" name="active" '
                'value="1"%s style="width:auto"> Activa</label>'
                '<button class="btn sm ok">Guardar</button></form></div>'
                % (_e(t["event"]), _e(t["channel"]), a["id"], _e(t["event"]),
                   _e(t["channel"]), _e(t["title_template"] or ""),
                   _e(t["body_template"] or ""),
                   " checked" if t["active"] else "") for t in tpls)
            cards += '<h2>%s</h2>%s' % (_e(_brand(a)), trs or
                                       '<p class="muted">Sin plantillas.</p>')
    finally:
        conn.close()
    return HTMLResponse(_layout("Plantillas", ctx,
                                '<p class="muted">Variables: {{brand}} {{customer_name}} '
                                '{{order_number}} {{tracking}} {{status}}.</p>' + cards))


@router.post("/agencia/plantillas/guardar")
async def agencia_template_save(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    ag = _write_agency(ctx, form.get("loc") or "")
    conn = dbmod.get_db()
    try:
        adb.upsert_template(conn, ag["id"], (form.get("event") or "").strip(),
                            (form.get("channel") or "").strip(),
                            (form.get("subject") or "").strip()[:200],
                            (form.get("body") or "").strip()[:2000])
        conn.execute("UPDATE notification_templates SET active=? "
                     "WHERE agency_id=? AND event=? AND channel=?",
                     (1 if form.get("active") else 0, ag["id"],
                      (form.get("event") or "").strip(),
                      (form.get("channel") or "").strip()))
        conn.commit()
        adb.audit(conn, ag["id"], "owner", "template_saved",
                  detail="%s/%s" % (form.get("event"), form.get("channel")),
                  actor_id=ctx["email"])
    finally:
        conn.close()
    return RedirectResponse("/agencia/plantillas", status_code=303)


# ---------------------------------------------------------------- CSV de órdenes
@router.get("/agencia/ordenes.csv")
def agencia_orders_csv(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        orders = []
        for aid in ctx["agency_ids"]:
            orders += dbmod.get_agency_orders(conn, aid, limit=1000)
        orders.sort(key=lambda o: o["id"])
        brands = {a["id"]: _brand(a) for a in ctx["agencies"]}
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["orden", "locacion", "cliente", "telefono", "rastreo",
                    "paquetes", "estado_pago", "creada"])
        for o in orders:
            w.writerow([o["order_number"], brands.get(o["agency_id"], ""),
                        o["customer_name"] or "", o["customer_phone"] or "",
                        o["tracking_code"] or "", o["package_count"] or 0,
                        o["payment_status"] or "", (o["created_at"] or "")[:10]])
        data = buf.getvalue().encode("utf-8-sig")
    finally:
        conn.close()
    return StreamingResponse(io.BytesIO(data), media_type="text/csv",
                             headers={"Content-Disposition":
                                      'attachment; filename="ordenes.csv"'})


# ---------------------------------------------------------------- rastreo público
@router.get("/rastreo", response_class=HTMLResponse)
def public_tracking(request: Request, code: str = ""):
    code = (code or "").strip()
    body = ('<div class="card"><h2>📍 Rastrear paquete</h2>'
            '<form method="get"><label>Código<input name="code" value="%s" required></label>'
            '<button class="btn" style="width:100%%">Rastrear</button></form></div>' % _e(code))
    if code and dbmod is not None:
        conn = dbmod.get_db()
        try:
            row = conn.execute(
                """SELECT p.*, o.order_number, a.brand, a.whatsapp, a.pickup_hours
                   FROM packages p JOIN orders o ON o.id=p.order_id
                   JOIN agencies a ON a.id=o.agency_id
                   WHERE p.code=? LIMIT 1""", (code,)).fetchone()
        finally:
            conn.close()
        if row:
            body += ('<div class="card"><h3>Paquete %s</h3><table>'
                     '<tr><td>Estado</td><td><b>%s</b></td></tr>'
                     '<tr><td>Agencia</td><td>%s</td></tr>'
                     '<tr><td>Peso</td><td>%.1f lb</td></tr></table>'
                     '<p class="muted">%s<br>%s</p>'
                     '<p class="muted">Operado con SAHJONY LLC</p></div>'
                     % (_e(row["code"]), _e(row["status"]), _e(row["brand"] or ""),
                        (row["weight_kg"] or 0) * 2.20462,
                        _e("WhatsApp: " + row["whatsapp"]) if row["whatsapp"] else "",
                        _e("Horario: " + row["pickup_hours"]) if row["pickup_hours"] else ""))
        else:
            body += '<div class="err">No encontramos ese código.</div>'
    shell = ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>Rastreo</title><style>%s</style></head><body>%s'
             '<footer>Operado con SAHJONY LLC</footer></body></html>' % (CSS, body))
    return HTMLResponse(shell)


# ---------------------------------------------------------------- staff
def _staff_guard(request: Request):
    if not _staff_ok(request):
        raise HTTPException(404, "No encontrado")
    return True


@router.get("/staff/agencias/nueva", response_class=HTMLResponse)
def staff_agency_new_form(request: Request):
    _staff_guard(request)
    return HTMLResponse(_layout("Nueva agencia", None,
        "<h2>➕ Crear agencia directamente</h2>"
        "<form method='post' action='/staff/agencias/nueva' class='card'>"
        "<p>Marca<br><input name='brand' required></p>"
        "<p>Razón social<br><input name='legal_name'></p>"
        "<p>Tipo<br><select name='agency_type'><option value='agencia'>Agencia formal</option>"
        "<option value='punto_recogida'>Punto de recogida</option></select></p>"
        "<p>Email del dueño<br><input name='owner_email' type='email'></p>"
        "<p>Teléfono<br><input name='phone'></p>"
        "<p>Dirección<br><input name='address'></p>"
        "<p>Ciudad<br><input name='city'></p>"
        "<p><i>Deja los términos vacíos para que queden pendientes de confirmación.</i></p>"
        "<p>Comisión por paquete $<input name='commission_per_package' type='number' step='0.01' min='0'></p>"
        "<p>Comisión por orden $<input name='commission_per_order' type='number' step='0.01' min='0'></p>"
        "<p>Tarifa por libra $<input name='rate_per_lb' type='number' step='0.01' min='0'></p>"
        "<p>Mensualidad $<input name='monthly_fee' type='number' step='0.01' min='0'></p>"
        "<p><button class='btn'>Crear</button></p></form>", active="staff"))


@router.post("/staff/agencias/nueva")
async def staff_agency_new(request: Request):
    _staff_guard(request)
    form = await request.form()
    brand = (form.get("brand") or "").strip()
    if not brand:
        raise HTTPException(400, "La marca es obligatoria.")
    email = (form.get("owner_email") or "").strip().lower()
    if email and "@" not in email:
        raise HTTPException(400, "Email inválido.")
    def _num(k):
        try:
            return float(form.get(k) or "") if (form.get(k) or "").strip() else None
        except ValueError:
            return None
    conn = dbmod.get_db()
    try:
        cur = conn.execute(
            """INSERT INTO agencies (legal_name, brand, phone, address, city,
                                     agency_type, commission_per_package,
                                     commission_per_order, rate_per_lb, monthly_fee,
                                     active)
               VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
            ((form.get("legal_name") or "").strip() or brand, brand,
             (form.get("phone") or "").strip(), (form.get("address") or "").strip(),
             (form.get("city") or "").strip(), form.get("agency_type") or "agencia",
             _num("commission_per_package"), _num("commission_per_order"),
             _num("rate_per_lb"), _num("monthly_fee")))
        new_id = cur.lastrowid
        adb.seed_templates(conn, new_id)
        adb.audit(conn, new_id, "staff", "agency_created_direct",
                  entity="agencies", entity_id=new_id,
                  detail="brand=%s email=%s" % (brand, email), actor_id="staff")
        conn.commit()
    finally:
        conn.close()
    if email:
        return RedirectResponse("/staff/agencias/%d/acceso?email=%s"
                                % (new_id, quote(email)), status_code=303)
    return RedirectResponse("/staff/agencias", status_code=303)


@router.get("/staff/agencias/{agency_id}/acceso", response_class=HTMLResponse)
def staff_agency_access_form(request: Request, agency_id: int, email: str = ""):
    """Confirmación previa: el GET solo muestra el formulario; el POST otorga."""
    _staff_guard(request)
    conn = dbmod.get_db()
    try:
        row = conn.execute("SELECT id, brand FROM agencies WHERE id=?",
                           (agency_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "Agencia no encontrada")
    return HTMLResponse(_layout("Otorgar acceso", None,
        '<div class="card"><h2>🔑 Otorgar acceso web</h2>'
        '<p>Locación: <b>%s</b> (#%d)</p>'
        '<form method="post" action="/staff/agencias/%d/acceso">'
        '<label>Email del dueño*<input name="email" type="email" required '
        'value="%s" autocomplete="off"></label>'
        '<button class="btn ok" style="width:100%%">Otorgar acceso</button></form>'
        '<p class="muted">Genera una contraseña temporal de un solo uso.</p>'
        '<p><a href="/staff/agencias">← Agencias</a></p></div>'
        % (_e(row["brand"] or "—"), agency_id, agency_id,
           _e((email or "").strip().lower())), active="staff"))


@router.post("/staff/agencias/{agency_id}/acceso", response_class=HTMLResponse)
async def staff_agency_access(request: Request, agency_id: int):
    """Otorga acceso web al dueño. La temporal se muestra UNA sola vez aquí."""
    _staff_guard(request)
    form = await request.form()
    email = ((form.get("email") or "")).strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Email inválido.")
    conn = dbmod.get_db()
    try:
        row = conn.execute("SELECT id FROM agencies WHERE id=?",
                           (agency_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Agencia no encontrada")
        temp, reused = adb.grant_owner_access(conn, agency_id, email)
        conn.commit()
    finally:
        conn.close()
    if reused:
        msg = ("<p>Se reutilizó la contraseña de sus otras locaciones: %s ahora entra "
               "con su misma contraseña.</p>") % _e(email)
    else:
        msg = ("<h1>✅ Acceso otorgado</h1>"
               "<p>Agencia #%d — dueño: %s</p>"
               "<p>Contraseña temporal (mostrar UNA vez): <b>%s</b></p>"
               "<p class='muted'>Compártela por un canal seguro. No se volverá a mostrar.</p>"
               % (agency_id, _e(email), _e(temp or "")))
    return HTMLResponse(_layout("Acceso otorgado", None, msg + "<p><a href='/staff/agencias'>"
        "← Agencias</a></p>", active="staff"))


@router.get("/staff/agencias", response_class=HTMLResponse)
def staff_agencies(request: Request):
    _staff_guard(request)
    conn = dbmod.get_db()
    try:
        rows = conn.execute(
            "SELECT id, brand, legal_name, agency_type, owner_email, city, state,"
            " subscription_status, owner_login_enabled, active"
            " FROM agencies ORDER BY id DESC LIMIT 100").fetchall()
    finally:
        conn.close()
    trs = "".join(
        '<tr><td><b>%s</b><br><span class="muted">#%d · %s · %s</span></td>'
        '<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
        % (_e(r["brand"] or r["legal_name"] or "—"), r["id"],
           _e(r["agency_type"] or ""), _e(r["city"] or ""),
           _e(r["owner_email"] or "—"), _e(r["subscription_status"] or "—"),
           "✅" if r["owner_login_enabled"] else "—",
           "activa" if r["active"] else "inactiva") for r in rows)
    return HTMLResponse(
        "<h1>Agencias</h1><p><a href='/staff/agencias/solicitudes'>Solicitudes</a> · "
        "<a href='/staff/resend'>Resend</a> · <a href='/staff/verificar-docs'>"
        "Verificar documentos</a></p><table border='1' cellpadding='6'>%s</table>" % trs)


@router.get("/staff/agencias/solicitudes", response_class=HTMLResponse)
def staff_requests(request: Request, estado: str = "pendiente"):
    _staff_guard(request)
    conn = dbmod.get_db()
    try:
        reqs = adb.list_requests(conn, status=estado or "")
    finally:
        conn.close()
    trs = "".join(
        '<tr><td><b>%s</b><br><span class="muted">%s · %s · %s</span></td>'
        '<td class="noprint">'
        '<form method="post" action="/staff/agencias/solicitudes/%d/aprobar" style="display:inline">'
        '<button class="btn sm ok">✅ Aprobar</button></form> '
        '<form method="post" action="/staff/agencias/solicitudes/%d/rechazar" style="display:inline" '
        'onsubmit="return confirm(\'¿Rechazar esta solicitud?\')">'
        '<button class="btn sm sec">❌ Rechazar</button></form></td></tr>'
        % (_e(r["brand"] or r["business_name"] or "—"), _e(r["owner_email"]),
           _e(r["agency_type"]), _e((r["created_at"] or "")[:10]), r["id"], r["id"])
        for r in reqs)
    return HTMLResponse(
        "<h1>Solicitudes (%s)</h1><table border='1' cellpadding='6'>%s</table>" %
        (_e(estado), trs or "<tr><td>Sin solicitudes.</td></tr>"))


@router.post("/staff/agencias/solicitudes/{req_id}/aprobar", response_class=HTMLResponse)
def staff_request_approve(request: Request, req_id: int):
    _staff_guard(request)
    conn = dbmod.get_db()
    try:
        req = adb.get_request(conn, req_id)
        if not req:
            raise HTTPException(404, "Solicitud no encontrada")
        if req["status"] != "pendiente":
            raise HTTPException(400, "Ya fue revisada.")
        # Aprueba y crea la agencia con términos pendientes; el acceso web se
        # otorga después (la temporal se muestra UNA sola vez aquí).
        try:
            new_id = adb.approve_request(conn, req_id, by="staff")
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        temp, reused = adb.grant_owner_access(conn, new_id, req["owner_email"])
        conn.commit()
    finally:
        conn.close()
    note = ("Se reutilizó la contraseña de sus otras locaciones." if reused else
            "Contraseña temporal (mostrar UNA vez): <b>%s</b>" % _e(temp or ""))
    return HTMLResponse(
        "<h1>✅ Aprobada</h1><p>Agencia #%d creada y acceso otorgado a %s.</p><p>%s</p>"
        "<p><a href='/staff/agencias/solicitudes'>Volver</a></p>"
        % (new_id, _e(req["owner_email"]), note))


@router.post("/staff/agencias/solicitudes/{req_id}/rechazar", response_class=HTMLResponse)
def staff_request_reject(request: Request, req_id: int):
    _staff_guard(request)
    conn = dbmod.get_db()
    try:
        ok = adb.reject_request(conn, req_id, by="staff")
    finally:
        conn.close()
    if not ok:
        raise HTTPException(404, "Solicitud no encontrada")
    return HTMLResponse("<h1>Rechazada</h1><p><a href='/staff/agencias/solicitudes'>Volver</a></p>")


@router.get("/staff/resend", response_class=HTMLResponse)
def staff_resend_form(request: Request):
    _staff_guard(request)
    status = "✅ configurado" if adb.resend_active() else "⚠️ sin clave"
    return HTMLResponse(
        "<h1>Resend</h1><p>Estado: %s · Remitente: %s</p>"
        "<form method='post'><label>Clave API (se guarda cifrada en el servidor)"
        "<input name='api_key' type='password'></label>"
        "<label>Remitente<input name='sender' value='%s'></label>"
        "<button>Guardar</button></form>"
        % (status, _e(adb.get_notify_from()), _e(adb.get_notify_from())))


@router.post("/staff/resend")
async def staff_resend_save(request: Request):
    _staff_guard(request)
    form = await request.form()
    if form.get("api_key"):
        adb.save_resend_key(form.get("api_key"))
    if form.get("sender"):
        adb.set_notify_from(form.get("sender"))
    return RedirectResponse("/staff/resend", status_code=303)


@router.get("/staff/verificar-docs", response_class=HTMLResponse)
def staff_verify_docs(request: Request):
    _staff_guard(request)
    conn = dbmod.get_db()
    try:
        rep = adocs.verify_all(conn)
    finally:
        conn.close()
    trs = "".join(
        '<tr><td>%s</td><td>%d</td><td>%d</td><td>%d</td></tr>'
        % (_e(s["brand"]), s["ok"], s["missing"], s["mismatch"])
        for s in rep["per_agency"])
    orph = "".join("<li>%s</li>" % _e(o) for o in rep["orphans"])
    return HTMLResponse(
        "<h1>Verificación de documentos</h1><table border='1' cellpadding='6'>"
        "<tr><th>Agencia</th><th>OK</th><th>Faltantes</th><th>Hash alterado</th></tr>%s</table>"
        "<h2>Huérfanos en disco (%d)</h2><ul>%s</ul>" % (trs, len(rep["orphans"]), orph))
