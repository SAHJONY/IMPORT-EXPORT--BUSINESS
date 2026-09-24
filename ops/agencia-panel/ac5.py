"""Centro de comando — parte 5: embarques/manifiestos, facturas, cobros,
gastos, métodos de pago, economía."""
from __future__ import annotations

from ac_shared import *

router = APIRouter()

SHIP_LABEL = {"preparando": "Preparando", "listo": "Listo",
              "en_transito": "En tránsito", "entregado": "Entregado"}
SHIP_NEXT = {"preparando": ["listo"], "listo": ["en_transito", "preparando"],
             "en_transito": ["entregado"], "entregado": []}


# ---------------------------------------------------------------- embarques
@router.get("/agencia/embarques", response_class=HTMLResponse)
def agencia_shipments(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        ships = []
        for aid in ctx["agency_ids"]:
            for s in dbmod.get_agency_shipments(conn, aid):
                ag = next(a for a in ctx["agencies"] if a["id"] == aid)
                ships.append((ag, s))
        ships.sort(key=lambda t: t[1]["id"], reverse=True)
    finally:
        conn.close()
    rows = "".join(
        '<tr><td><a href="/agencia/embarques/%d"><b>%s</b></a><br>'
        '<span class="muted">%s · %s</span></td><td>%d paq</td>'
        '<td>%s</td></tr>'
        % (s["id"], _e(s["code"]), _e(_brand(ag)), _e(s["mode"] or ""),
           s["package_count"] or 0,
           '<span class="badge">%s</span>' % _e(SHIP_LABEL.get(s["status"] or "", s["status"] or "")))
        for ag, s in ships)
    return HTMLResponse(_layout(
        "Embarques", ctx,
        '<a class="btn" href="/agencia/embarques/nuevo">+ Nuevo embarque</a>'
        '<table>%s</table>' % (rows or '<tr><td class="muted">Sin embarques.</td></tr>')))


@router.get("/agencia/embarques/nuevo", response_class=HTMLResponse)
def agencia_shipment_new_form(request: Request, loc: str = ""):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    ids, wid = _order_scope(ctx, loc)
    conn = dbmod.get_db()
    try:
        ag = next(a for a in ctx["agencies"] if a["id"] == wid)
        pkgs = conn.execute(
            """SELECT p.*, o.order_number FROM packages p
               JOIN orders o ON o.id=p.order_id
               LEFT JOIN agency_shipment_packages sp ON sp.package_id=p.id
               WHERE o.agency_id=? AND sp.package_id IS NULL
               ORDER BY p.id DESC LIMIT 200""", (wid,)).fetchall()
    finally:
        conn.close()
    checks = "".join(
        '<label style="font-weight:normal"><input type="checkbox" name="pkg" value="%d" '
        'style="width:auto"> <b>%s</b> — %s (%.1f lb)</label>'
        % (p["id"], _e(p["code"]), _e((p["contents"] or "")[:50]),
           (p["weight_kg"] or 0) * 2.20462) for p in pkgs)
    body = (('<div class="card"><h3>Nuevo embarque — %s</h3><form method="post">'
             '<input type="hidden" name="loc" value="%d">'
             + (_loc_selector(ctx, wid) if ctx["multi"] else "") +
             '<label>Modo<select name="mode"><option value="aereo">Aéreo</option>'
             '<option value="maritimo">Marítimo</option></select></label>'
             '<label>Transportista<input name="carrier"></label>'
             '<label>Fecha de salida<input name="departure_date" type="date"></label>'
             '<label>Notas<textarea name="notes" rows="2"></textarea></label>'
             '<h3>Paquetes (sin embarque)</h3>%s'
             '<button class="btn ok" style="width:100%%">Crear embarque</button></form></div>')
            % (_e(_brand(ag)), wid,
               checks or '<p class="muted">No hay paquetes pendientes.</p>'))
    return HTMLResponse(_layout("Nuevo embarque", ctx, body))


@router.post("/agencia/embarques/nuevo")
async def agencia_shipment_create(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    ag = _write_agency(ctx, form.get("loc") or "")
    mode = form.get("mode") or ""
    if mode not in ("aereo", "maritimo"):
        raise HTTPException(400, "Modo inválido.")
    pids = []
    for v in form.getlist("pkg"):
        try:
            pids.append(int(v))
        except (ValueError, TypeError):
            pass
    if not pids:
        raise HTTPException(400, "Selecciona al menos un paquete.")
    conn = dbmod.get_db()
    try:
        sid = dbmod.create_agency_shipment(
            conn, ag["id"], mode, (form.get("carrier") or "").strip(),
            (form.get("departure_date") or "").strip(),
            (form.get("notes") or "").strip()[:500], pids)
        conn.commit()
        adb.audit(conn, ag["id"], "owner", "shipment_created", entity="shipments",
                  entity_id=sid, detail="%s %s n=%d" % (mode, form.get("carrier") or "", len(pids)),
                  actor_id=ctx["email"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        conn.close()
    return RedirectResponse("/agencia/embarques/%d" % sid, status_code=303)


@router.get("/agencia/embarques/{shipment_id}", response_class=HTMLResponse)
def agencia_shipment_detail(request: Request, shipment_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        sh = ag = None
        for aid in ctx["agency_ids"]:
            sh = dbmod.get_agency_shipment(conn, aid, shipment_id)
            if sh:
                ag = next(a for a in ctx["agencies"] if a["id"] == aid)
                break
        if not sh:
            raise HTTPException(404, "Embarque no encontrado")
        pkgs = dbmod.get_shipment_packages(conn, shipment_id)
    finally:
        conn.close()
    total_lb = sum((p["weight_kg"] or 0) * 2.20462 for p in pkgs)
    rows = "".join(
        '<tr><td><b>%s</b><br><span class="muted">%s · %s, %s</span></td>'
        '<td>%.1f lb</td><td>%s</td></tr>'
        % (_e(p["code"]), _e(p["recipient_name"] or ""), _e(p["province"] or ""),
           _e(p["municipality"] or ""), (p["weight_kg"] or 0) * 2.20462,
           _e(p["status"])) for p in pkgs)
    nexts = "".join(
        '<form method="post" action="/agencia/embarques/%d/estado" style="display:inline">'
        '<input type="hidden" name="nuevo" value="%s">'
        '<button class="btn sm ok">→ %s</button></form> '
        % (shipment_id, ns, _e(SHIP_LABEL.get(ns, ns)))
        for ns in SHIP_NEXT.get(sh["status"] or "", []))
    body = ('<div class="card"><h2>Embarque %s</h2>'
            '<table><tr><td>Locación</td><td>%s</td></tr>'
            '<tr><td>Modo</td><td>%s</td></tr>'
            '<tr><td>Transportista</td><td>%s</td></tr>'
            '<tr><td>Salida</td><td>%s</td></tr>'
            '<tr><td>Estado</td><td><span class="badge">%s</span></td></tr>'
            '<tr><td>Paquetes / peso</td><td>%d · %.1f lb</td></tr></table>'
            '<div class="noprint">%s <a class="btn sm sec" '
            'href="/agencia/embarques/%d/manifiesto">📄 Manifiesto</a></div></div>'
            '<div class="card"><h3>Paquetes</h3><table>%s</table></div>'
            % (_e(sh["code"]), _e(_brand(ag)), _e(sh["mode"] or ""),
               _e(sh["carrier"] or "—"), _e(sh["departure_date"] or "—"),
               _e(SHIP_LABEL.get(sh["status"] or "", sh["status"] or "")),
               len(pkgs), total_lb, nexts, shipment_id,
               rows or '<tr><td class="muted">Sin paquetes.</td></tr>'))
    return HTMLResponse(_layout("Embarque " + sh["code"], ctx, body))


@router.post("/agencia/embarques/{shipment_id}/estado")
async def agencia_shipment_status(request: Request, shipment_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    nuevo = (form.get("nuevo") or "").strip()
    conn = dbmod.get_db()
    try:
        ok = False
        for aid in ctx["agency_ids"]:
            try:
                if dbmod.set_shipment_status(conn, aid, shipment_id, nuevo):
                    ok = True
                    adb.audit(conn, aid, "owner", "shipment_status",
                              entity="shipments", entity_id=shipment_id,
                              detail="→ %s" % nuevo, actor_id=ctx["email"])
                    break
            except ValueError:
                pass
        if not ok:
            raise HTTPException(400, "Transición no permitida o embarque no encontrado.")
    finally:
        conn.close()
    return RedirectResponse("/agencia/embarques/%d" % shipment_id, status_code=303)


@router.get("/agencia/embarques/{shipment_id}/manifiesto", response_class=HTMLResponse)
def agencia_shipment_manifest(request: Request, shipment_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        sh = ag = None
        for aid in ctx["agency_ids"]:
            sh = dbmod.get_agency_shipment(conn, aid, shipment_id)
            if sh:
                ag = next(a for a in ctx["agencies"] if a["id"] == aid)
                break
        if not sh:
            raise HTTPException(404, "Embarque no encontrado")
        pkgs = dbmod.get_shipment_packages(conn, shipment_id)
        total_lb = sum((p["weight_kg"] or 0) * 2.20462 for p in pkgs)
        rows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s, %s</td><td>%s</td><td>%.1f</td></tr>"
            % (_e(p["code"]), _e(p["recipient_name"] or ""), _e(p["province"] or ""),
               _e(p["municipality"] or ""), _e(p["contents"] or "")[:60],
               (p["weight_kg"] or 0) * 2.20462) for p in pkgs)
        html = ("""<h1>Manifiesto de embarque %s</h1>
<p><b>Agencia:</b> %s · <b>Modo:</b> %s · <b>Transportista:</b> %s ·
<b>Salida:</b> %s · <b>Paquetes:</b> %d · <b>Peso:</b> %.1f lb</p>
<table border="1" cellpadding="6"><tr><th>Código</th><th>Destinatario</th>
<th>Destino</th><th>Contenido</th><th>Peso (lb)</th></tr>%s</table>
<p class="muted">Operado con SAHJONY LLC</p>"""
                % (_e(sh["code"]), _e(_brand(ag)), _e(sh["mode"] or ""),
                   _e(sh["carrier"] or "—"), _e(sh["departure_date"] or "—"),
                   len(pkgs), total_lb, rows))
        doc = adocs.write_doc(conn, ag["id"], "manifiesto", "man_%s" % sh["code"],
                              html, ref_table="shipments", ref_id=shipment_id,
                              created_by="owner", label="Manifiesto " + sh["code"])
        adb.audit(conn, ag["id"], "owner", "manifest_generated", entity="shipments",
                  entity_id=shipment_id, detail="doc=%d" % doc["id"],
                  actor_id=ctx["email"])
    finally:
        conn.close()
    return HTMLResponse(_layout("Manifiesto " + sh["code"], ctx,
                                html + '<br><br><div class="noprint">'
                                '<button class="btn" onclick="window.print()">🖨 Imprimir</button></div>'))


# ---------------------------------------------------------------- facturas
@router.get("/agencia/facturas", response_class=HTMLResponse)
def agencia_invoices(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        invs = []
        for aid in ctx["agency_ids"]:
            ag = next(a for a in ctx["agencies"] if a["id"] == aid)
            for i in adb.list_invoices(conn, aid):
                paid, bal = adb.invoice_balance(conn, i["id"])
                invs.append((ag, i, paid, bal))
        invs.sort(key=lambda t: t[1]["id"], reverse=True)
    finally:
        conn.close()
    rows = "".join(
        '<tr><td><a href="/agencia/facturas/%d"><b>%s</b></a><br><span class="muted">%s</span></td>'
        '<td>$%.2f</td><td>%s<br><span class="muted">saldo $%.2f</span></td></tr>'
        % (i["id"], _e(i["number"]), _e(_brand(ag)), i["total"] or 0,
           '<span class="badge green">pagada</span>' if (i["status"] or "") == "pagada"
           else ('<span class="badge amber">parcial</span>' if (i["status"] or "") == "parcial"
                 else '<span class="badge red">pendiente</span>'), bal)
        for ag, i, paid, bal in invs)
    return HTMLResponse(_layout(
        "Facturas", ctx,
        '<a class="btn" href="/agencia/facturas/nueva">+ Nueva factura</a>'
        '<table>%s</table>' % (rows or '<tr><td class="muted">Sin facturas.</td></tr>')))


@router.get("/agencia/facturas/nueva", response_class=HTMLResponse)
def agencia_invoice_new_form(request: Request, loc: str = ""):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    ids, wid = _order_scope(ctx, loc)
    conn = dbmod.get_db()
    try:
        ag = next(a for a in ctx["agencies"] if a["id"] == wid)
        customers = adb.owner_customers(conn, [wid])
    finally:
        conn.close()
    copts = "".join('<option value="%d">%s</option>' % (c["id"], _e(c["name"]))
                    for c in customers)
    lines = "".join(
        '<tr><td><input name="label%d" placeholder="Concepto"></td>'
        '<td><input name="qty%d" inputmode="decimal" value="1"></td>'
        '<td><input name="price%d" inputmode="decimal" placeholder="0.00"></td></tr>' % (n, n, n)
        for n in range(1, 4))
    body = (('<div class="card"><h3>Nueva factura — %s</h3><form method="post">'
             '<input type="hidden" name="loc" value="%d">'
             + (_loc_selector(ctx, wid) if ctx["multi"] else "") +
             '<label>Cliente<select name="customer_id">%s</select></label>'
             '<table>%s</table>'
             '<label>Descuento $<input name="discount" inputmode="decimal" value="0"></label>'
             '<label>Vence<input name="due_date" type="date"></label>'
             '<label>Notas<textarea name="notes" rows="2"></textarea></label>'
             '<button class="btn ok" style="width:100%%">Crear factura</button></form></div>')
            % (_e(_brand(ag)), wid, copts or '<option value="0">—</option>', lines))
    return HTMLResponse(_layout("Nueva factura", ctx, body))


@router.post("/agencia/facturas/nueva")
async def agencia_invoice_create(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    ag = _write_agency(ctx, form.get("loc") or "")
    items = []
    for n in range(1, 4):
        label = (form.get("label%d" % n) or "").strip()
        try:
            qty = float(form.get("qty%d" % n) or 0)
            price = float(form.get("price%d" % n) or 0)
        except ValueError:
            raise HTTPException(400, "Cantidad/precio inválidos.")
        if label and qty > 0 and price >= 0:
            items.append((label, qty, price))
    if not items:
        raise HTTPException(400, "Agrega al menos una línea con concepto, cantidad y precio.")
    try:
        discount = float(form.get("discount") or 0)
    except ValueError:
        raise HTTPException(400, "Descuento inválido.")
    conn = dbmod.get_db()
    try:
        cid = int(form.get("customer_id") or 0)
        if cid:
            hit = conn.execute(
                "SELECT 1 FROM customer_agencies WHERE customer_id=? AND agency_id=?",
                (cid, ag["id"])).fetchone()
            if not hit:
                raise HTTPException(404, "Cliente no autorizado")
        inv_id = adb.create_invoice(conn, ag["id"], customer_id=cid, items=items,
                                    discount=discount,
                                    due_date=(form.get("due_date") or "").strip(),
                                    notes=(form.get("notes") or "").strip(),
                                    created_by=ctx["email"])
    finally:
        conn.close()
    return RedirectResponse("/agencia/facturas/%d" % inv_id, status_code=303)


@router.get("/agencia/facturas/{invoice_id}", response_class=HTMLResponse)
def agencia_invoice_detail(request: Request, invoice_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        inv = ag = items = paid = bal = None
        for aid in ctx["agency_ids"]:
            inv, items = adb.get_invoice(conn, aid, invoice_id)
            if inv:
                ag = next(a for a in ctx["agencies"] if a["id"] == aid)
                paid, bal = adb.invoice_balance(conn, invoice_id)
                break
        if not inv:
            raise HTTPException(404, "Factura no encontrada")
        methods = adb.list_payment_methods(conn, ag["id"])
    finally:
        conn.close()
    trs = "".join(
        '<tr><td>%s</td><td>%.2f</td><td>$%.2f</td><td>$%.2f</td></tr>'
        % (_e(i["label"]), i["qty"] or 0, i["unit_price"] or 0, i["amount"] or 0)
        for i in items)
    pay_form = ""
    if bal > 0.005:
        mopts = "".join('<option>%s</option>' % _e(m["label"]) for m in methods)
        pay_form = ('<div class="card"><h3>💵 Registrar cobro</h3>'
                    '<p class="muted">Registro contable: no mueve dinero real, '
                    'solo anota lo que el cliente te pagó.</p>'
                    '<form method="post" action="/agencia/facturas/%d/cobrar">'
                    '<label>Monto $<input name="amount" inputmode="decimal" required '
                    'max="%.2f"></label>'
                    '<label>Método<select name="method"><option value="">—</option>%s</select></label>'
                    '<label>Referencia<input name="reference"></label>'
                    '<button class="btn ok" style="width:100%%">Registrar cobro</button></form></div>'
                    % (invoice_id, bal, mopts))
    body = ('<div class="card"><h2>Factura %s</h2>'
            '<table><tr><td>Locación</td><td>%s</td></tr>'
            '<tr><td>Total</td><td>$%.2f</td></tr>'
            '<tr><td>Cobrado</td><td>$%.2f</td></tr>'
            '<tr><td>Saldo</td><td><b>$%.2f</b></td></tr>'
            '<tr><td>Estado</td><td>%s</td></tr>'
            '<tr><td>Vence</td><td>%s</td></tr></table></div>'
            '<div class="card"><h3>Líneas</h3><table><tr><th>Concepto</th><th>Cant.</th>'
            '<th>Precio</th><th>Monto</th></tr>%s</table></div>%s'
            % (_e(inv["number"]), _e(_brand(ag)), inv["total"] or 0, paid, bal,
               _e(inv["status"]), _e(inv["due_date"] or "—"), trs, pay_form))
    return HTMLResponse(_layout("Factura " + inv["number"], ctx, body))


@router.post("/agencia/facturas/{invoice_id}/cobrar")
async def agencia_invoice_pay(request: Request, invoice_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    try:
        amount = float(form.get("amount") or 0)
    except ValueError:
        raise HTTPException(400, "Monto inválido.")
    conn = dbmod.get_db()
    try:
        pag = None
        for aid in ctx["agency_ids"]:
            inv, _it = adb.get_invoice(conn, aid, invoice_id)
            if inv:
                pag = aid
                break
        if pag is None:
            raise HTTPException(404, "Factura no encontrada")
        _paid, bal = adb.invoice_balance(conn, invoice_id)
        if amount <= 0 or amount > bal + 0.005:
            raise HTTPException(400, "Monto inválido (saldo: $%.2f)." % bal)
        adb.record_payment(conn, pag, invoice_id, amount,
                           method=(form.get("method") or "").strip(),
                           reference=(form.get("reference") or "").strip(),
                           received_by=ctx["email"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        conn.close()
    return RedirectResponse("/agencia/facturas/%d" % invoice_id, status_code=303)


# ---------------------------------------------------------------- cobros
@router.get("/agencia/pagos", response_class=HTMLResponse)
def agencia_payments(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        rows_l = []
        for aid in ctx["agency_ids"]:
            ag = next(a for a in ctx["agencies"] if a["id"] == aid)
            for p in adb.list_payments(conn, aid):
                rows_l.append((ag, p))
        rows_l.sort(key=lambda t: t[1]["id"], reverse=True)
    finally:
        conn.close()
    rows = "".join(
        '<tr><td><b>$%.2f</b><br><span class="muted">%s · %s</span></td>'
        '<td>%s<br><span class="muted">%s</span></td>'
        '<td>%s</td></tr>'
        % (p["amount"] or 0, _e(p["method"] or "—"), _e((p["paid_at"] or "")[:10]),
           _e(p["inv_number"] or "—"), _e(p["reference"] or ""), _e(_brand(ag)))
        for ag, p in rows_l)
    return HTMLResponse(_layout(
        "Cobros", ctx,
        '<p class="muted">Registro contable de lo que tus clientes te pagaron.</p>'
        '<table>%s</table>' % (rows or '<tr><td class="muted">Sin cobros.</td></tr>')))


# ---------------------------------------------------------------- gastos
@router.get("/agencia/gastos", response_class=HTMLResponse)
def agencia_expenses(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        rows_l = []
        for aid in ctx["agency_ids"]:
            ag = next(a for a in ctx["agencies"] if a["id"] == aid)
            for e in adb.list_expenses(conn, aid):
                rows_l.append((ag, e))
        total = sum(e["amount"] or 0 for _ag, e in rows_l)
    finally:
        conn.close()
    rows = "".join(
        '<tr><td><b>%s</b><br><span class="muted">%s · %s</span></td>'
        '<td>$%.2f</td><td class="noprint"><form method="post" '
        'action="/agencia/gastos/%d/borrar" style="display:inline" '
        'onsubmit="return confirm(\'¿Borrar este gasto?\')"><button class="btn sm sec">✖</button>'
        '</form></td></tr>'
        % (_e(e["label"]), _e(e["category"] or ""), _e(e["spent_at"] or ""),
           e["amount"] or 0, e["id"]) for ag, e in rows_l)
    body = (('<div class="card"><form method="post" action="/agencia/gastos/agregar">'
             '<input type="hidden" name="loc" value="%d">'
             % ctx["agency_ids"][0]
             + (_loc_selector(ctx, ctx["agency_ids"][0]) if ctx["multi"] else "") +
             '<label>Concepto*<input name="label" required></label>'
             '<label>Monto $*<input name="amount" inputmode="decimal" required></label>'
             '<label>Categoría<select name="category"><option value="">—</option>'
             '<option>Transporte</option><option>Materiales</option><option>Renta</option>'
             '<option>Servicios</option><option>Otro</option></select></label>'
             '<button class="btn sm ok">Agregar gasto</button></form></div>'
             '<div class="card"><h3>Total: $%.2f</h3><table>%s</table></div>')
            % (total, rows or '<tr><td class="muted">Sin gastos.</td></tr>'))
    return HTMLResponse(_layout("Gastos", ctx, body))


@router.post("/agencia/gastos/agregar")
async def agencia_expense_add(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    ag = _write_agency(ctx, form.get("loc") or "")
    try:
        amount = float(form.get("amount") or 0)
    except ValueError:
        raise HTTPException(400, "Monto inválido.")
    if not (form.get("label") or "").strip():
        raise HTTPException(400, "El concepto es obligatorio.")
    conn = dbmod.get_db()
    try:
        adb.add_expense(conn, ag["id"], (form.get("label") or "").strip(), amount,
                        category=(form.get("category") or "").strip(),
                        created_by=ctx["email"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        conn.close()
    return RedirectResponse("/agencia/gastos", status_code=303)


@router.post("/agencia/gastos/{expense_id}/borrar")
def agencia_expense_delete(request: Request, expense_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        for aid in ctx["agency_ids"]:
            adb.delete_expense(conn, aid, expense_id)
    finally:
        conn.close()
    return RedirectResponse("/agencia/gastos", status_code=303)


# ---------------------------------------------------------------- métodos de pago
@router.get("/agencia/metodos", response_class=HTMLResponse)
def agencia_paymethods(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        cards = ""
        for a in ctx["agencies"]:
            rows = adb.list_payment_methods(conn, a["id"])
            trs = "".join(
                '<tr><td><b>%s</b><br><span class="muted">%s · %s</span></td>'
                '<td class="noprint"><form method="post" action="/agencia/metodos/%d/borrar" '
                'style="display:inline" onsubmit="return confirm(\'¿Borrar este método?\')">'
                '<button class="btn sm sec">✖</button></form></td></tr>'
                % (_e(m["label"]), _e(m["kind"]), _e(m["details"] or ""), m["id"])
                for m in rows)
            cards += ('<div class="card"><h3>%s</h3><table>%s</table>'
                      '<form method="post" action="/agencia/metodos/agregar">'
                      '<input type="hidden" name="loc" value="%d">'
                      '<label>Nombre*<input name="label" required placeholder="Zelle, efectivo…"></label>'
                      '<label>Tipo<select name="kind"><option value="efectivo">Efectivo</option>'
                      '<option value="zelle">Zelle</option><option value="cashapp">Cash App</option>'
                      '<option value="transferencia">Transferencia</option>'
                      '<option value="otro">Otro</option></select></label>'
                      '<label>Detalles<input name="details" placeholder="número, nota…"></label>'
                      '<button class="btn sm ok">Agregar</button></form></div>'
                      % (_e(_brand(a)),
                         trs or '<tr><td class="muted">Sin métodos.</td></tr>', a["id"]))
    finally:
        conn.close()
    return HTMLResponse(_layout("Cómo me pagan", ctx,
                                '<p class="muted">Tus formas de cobro. '
                                'No se mueve dinero real desde aquí.</p>' + cards))


@router.post("/agencia/metodos/agregar")
async def agencia_paymethod_add(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    ag = _write_agency(ctx, form.get("loc") or "")
    if not (form.get("label") or "").strip():
        raise HTTPException(400, "El nombre es obligatorio.")
    conn = dbmod.get_db()
    try:
        adb.add_payment_method(conn, ag["id"], (form.get("label") or "").strip(),
                               (form.get("kind") or "otro").strip(),
                               (form.get("details") or "").strip())
        adb.audit(conn, ag["id"], "owner", "paymethod_added",
                  detail=form.get("label", "")[:60], actor_id=ctx["email"])
    finally:
        conn.close()
    return RedirectResponse("/agencia/metodos", status_code=303)


@router.post("/agencia/metodos/{method_id}/borrar")
def agencia_paymethod_delete(request: Request, method_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        for aid in ctx["agency_ids"]:
            adb.delete_payment_method(conn, aid, method_id)
    finally:
        conn.close()
    return RedirectResponse("/agencia/metodos", status_code=303)


# ---------------------------------------------------------------- economía
@router.get("/agencia/economia", response_class=HTMLResponse)
def agencia_economy(request: Request, dias: int = 30):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    dias = max(1, min(dias, 365))
    conn = dbmod.get_db()
    try:
        cards = ""
        tc = tg = 0.0
        for a in ctx["agencies"]:
            s = adb.economy_summary(conn, a["id"], dias)
            tc += s["cobrado"]
            tg += s["gastado"]
            cards += ('<div class="card"><h3>%s</h3><table>'
                      '<tr><td>Cobrado</td><td><b>$%.2f</b></td></tr>'
                      '<tr><td>Gastado</td><td>$%.2f</td></tr>'
                      '<tr><td>Neto</td><td><b>$%.2f</b></td></tr>'
                      '<tr><td>Facturado pendiente</td><td>$%.2f</td></tr></table></div>'
                      % (_e(_brand(a)), s["cobrado"], s["gastado"], s["neto"],
                         s["facturado_pendiente"]))
    finally:
        conn.close()
    body = ('<p class="muted">Últimos %d días.</p>' % dias + cards +
            '<div class="card"><h3>Todas las locaciones</h3><table>'
            '<tr><td>Cobrado</td><td><b>$%.2f</b></td></tr>'
            '<tr><td>Gastado</td><td>$%.2f</td></tr>'
            '<tr><td>Neto</td><td><b>$%.2f</b></td></tr></table>'
            '<p class="muted">Esto es tu contabilidad, no la de SAHJONY. '
            'Lo que le debes a SAHJONY está en <a href="/agencia/liquidacion">Mi liquidación</a>.</p></div>'
            % (tc, tg, tc - tg))
    return HTMLResponse(_layout("Mi economía", ctx, body))
