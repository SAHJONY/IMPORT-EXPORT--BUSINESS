"""Centro de comando — parte 4: paquetes, etiquetas QR, clientes, precios,
bandeja de mensajes, rastreo interno."""
from __future__ import annotations

import base64
import io

from ac_shared import *

router = APIRouter()

STATUSES = ("RECIBIDO", "EN_TRANSITO", "EN_ADUANA", "EN_REPARTO",
            "ENTREGADO", "CANCELADO")


def _qr_svg(text: str) -> str:
    try:
        import qrcode
        img = qrcode.make(text, box_size=6, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return ("data:image/png;base64," +
                base64.b64encode(buf.getvalue()).decode())
    except ImportError:
        return ""


def _public_track_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "https://paquetes.sahjony.com").rstrip("/")


def _pkg_belongs(conn, agency_id: int, package_id: int):
    """Paquete solo si su orden es de esta agencia (si no → None)."""
    return conn.execute(
        """SELECT p.* FROM packages p JOIN orders o ON o.id=p.order_id
           WHERE p.id=? AND o.agency_id=?""", (package_id, agency_id)).fetchone()


@router.get("/agencia/paquetes", response_class=HTMLResponse)
def agencia_packages(request: Request, estado: str = "", q: str = "", loc: str = ""):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    ids, _w = _order_scope(ctx, loc)
    conn = dbmod.get_db()
    try:
        pkgs = []
        for aid in ids:
            pkgs += dbmod.get_agency_packages(conn, aid,
                                              status=estado or None, q=q or None, limit=300)
        pkgs.sort(key=lambda p: p["id"], reverse=True)
    finally:
        conn.close()
    rows = "".join(
        '<tr><td><b>%s</b><br><span class="muted">%s · %s</span></td>'
        '<td>%.1f lb</td><td>%s</td>'
        '<td class="noprint"><a class="btn sm sec" href="/agencia/paquetes/%d/etiqueta">🏷</a></td></tr>'
        % (_e(p["code"]), _e(p["contents"] or "")[:40],
           _e(p["order_number"] or ""), (p["weight_kg"] or 0) * 2.20462,
           _e(p["status"]), p["id"]) for p in pkgs)
    opts = "".join('<option value="%s"%s>%s</option>'
                   % (s, " selected" if s == estado else "", s.replace("_", " ").title())
                   for s in [""] + list(STATUSES))
    body = ('<form method="get" class="noprint"><label>Estado<select name="estado">%s</select></label>'
            '<label>Buscar<input name="q" value="%s"></label>'
            '<button class="btn sm">Filtrar</button></form><table>%s</table>'
            % (opts, _e(q), rows or '<tr><td class="muted">Sin paquetes.</td></tr>'))
    return HTMLResponse(_layout("Paquetes", ctx, body))


@router.post("/agencia/paquetes/{package_id}/estado")
async def agencia_package_status(request: Request, package_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    status = form.get("status") or ""
    if status not in STATUSES:
        raise HTTPException(400, "Estado inválido.")
    conn = dbmod.get_db()
    try:
        row = order_id = pag = order = None
        for aid in ctx["agency_ids"]:
            row = _pkg_belongs(conn, aid, package_id)
            if row:
                order_id, pag = row["order_id"], aid
                order = dbmod.get_agency_order(conn, aid, order_id)
                break
        if not row or not order:
            raise HTTPException(404, "Paquete no encontrado")
        if not adb.set_package_status(conn, pag, package_id, status, "owner",
                                      ctx["email"]):
            raise HTTPException(404, "Paquete no encontrado")
        ag = next(a for a in ctx["agencies"] if a["id"] == pag)
        adb.notify_customer(conn, pag, order["customer_id"], order_id, "cambio_estado",
                            {"brand": _brand(ag), "order_number": order["order_number"],
                             "tracking": order["tracking_code"] or "",
                             "status": status.replace("_", " ").title()},
                            channels=("portal", "email"))
    finally:
        conn.close()
    return RedirectResponse("/agencia/ordenes/%d" % order_id, status_code=303)


def _label_html(conn, aid: int, pkg, ag) -> str:
    track_url = "%s/rastreo?code=%s" % (_public_track_url(), pkg["code"])
    qr = _qr_svg(track_url)
    return ("""<div class="card" style="page-break-inside:avoid">
<h3>%s — Paquete %s</h3>
<p><b>Destinatario:</b> %s · <b>Destino:</b> %s, %s<br>
<b>Contenido:</b> %s<br><b>Peso:</b> %.1f lb · <b>Orden:</b> %s</p>
<p><b>Rastreo:</b> %s</p>%s<p class="muted">Operado con SAHJONY LLC</p></div>"""
            % (_e(_brand(ag)), _e(pkg["code"]), _e(pkg["recipient_name"] or ""),
               _e(pkg["province"] or ""), _e(pkg["municipality"] or ""),
               _e(pkg["contents"] or ""), (pkg["weight_kg"] or 0) * 2.20462,
               _e(pkg["order_number"] or ""), _e(track_url),
               ('<img src="%s" style="max-width:180px">' % qr) if qr else ""))


@router.get("/agencia/paquetes/{package_id}/etiqueta", response_class=HTMLResponse)
def agencia_package_label(request: Request, package_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        row = pag = None
        for aid in ctx["agency_ids"]:
            row = conn.execute(
                """SELECT p.*, o.order_number, r.name AS recipient_name,
                          r.province, r.municipality
                   FROM packages p JOIN orders o ON o.id=p.order_id
                   LEFT JOIN recipients r ON r.id=p.recipient_id
                   WHERE p.id=? AND o.agency_id=?""",
                (package_id, aid)).fetchone()
            if row:
                pag = aid
                break
        if not row:
            raise HTTPException(404, "Paquete no encontrado")
        ag = next(a for a in ctx["agencies"] if a["id"] == pag)
        html = _label_html(conn, pag, row, ag)
        doc = adocs.write_doc(conn, pag, "etiqueta", "etq_%s" % row["code"], html,
                              ref_table="packages", ref_id=row["id"],
                              created_by="owner", label="Etiqueta " + row["code"])
        adb.audit(conn, pag, "owner", "label_generated", entity="packages",
                  entity_id=row["id"], detail="doc=%d" % doc["id"], actor_id=ctx["email"])
    finally:
        conn.close()
    return HTMLResponse(_layout("Etiqueta " + row["code"], ctx, html + '<br><br>'
                                '<div class="noprint"><button class="btn" '
                                'onclick="window.print()">🖨 Imprimir</button></div>',
                                active="ordenes"))


@router.get("/agencia/ordenes/{order_id}/etiquetas", response_class=HTMLResponse)
def agencia_order_labels(request: Request, order_id: int):
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
        pkgs = conn.execute(
            """SELECT p.*, o.order_number, r.name AS recipient_name,
                      r.province, r.municipality
               FROM packages p JOIN orders o ON o.id=p.order_id
               LEFT JOIN recipients r ON r.id=p.recipient_id
               WHERE p.order_id=?""", (order_id,)).fetchall()
        if not pkgs:
            raise HTTPException(404, "La orden no tiene paquetes.")
        html = "".join(_label_html(conn, pag, p, ag) for p in pkgs)
        doc = adocs.write_doc(conn, pag, "etiquetas",
                              "etqs_orden_%s" % order["order_number"], html,
                              ref_table="orders", ref_id=order_id,
                              created_by="owner",
                              label="Etiquetas orden " + order["order_number"])
        adb.audit(conn, pag, "owner", "labels_generated", entity="orders",
                  entity_id=order_id, detail="doc=%d n=%d" % (doc["id"], len(pkgs)),
                  actor_id=ctx["email"])
    finally:
        conn.close()
    return HTMLResponse(_layout("Etiquetas", ctx, html + '<br><br>'
                                '<div class="noprint"><button class="btn" '
                                'onclick="window.print()">🖨 Imprimir todas</button></div>',
                                active="ordenes"))


# ---------------------------------------------------------------- clientes
@router.get("/agencia/clientes", response_class=HTMLResponse)
def agencia_customers(request: Request, q: str = ""):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        customers = adb.owner_customers(conn, ctx["agency_ids"], q or None)
    finally:
        conn.close()
    rows = "".join(
        '<tr><td><a href="/agencia/clientes/%d"><b>%s</b></a><br>'
        '<span class="muted">%s</span></td><td>%d órdenes</td></tr>'
        % (c["id"], _e(c["name"]), _e(c["phone"] or ""), c["n_orders"] or 0)
        for c in customers)
    body = ('<form method="get" class="noprint"><label>Buscar<input name="q" value="%s"></label>'
            '<button class="btn sm">Buscar</button></form>'
            '<a class="btn" href="/agencia/clientes/nuevo">+ Nuevo cliente</a><table>%s</table>'
            % (_e(q), rows or '<tr><td class="muted">Sin clientes aún.</td></tr>'))
    return HTMLResponse(_layout("Clientes", ctx, body))


@router.get("/agencia/clientes/nuevo", response_class=HTMLResponse)
def agencia_customer_new_form(request: Request, loc: str = ""):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    ids, wid = _order_scope(ctx, loc)
    body = ('<div class="card"><form method="post">'
            '<input type="hidden" name="loc" value="%d">'
            % wid
            + (_loc_selector(ctx, wid) if ctx["multi"] else "") +
            '<label>Nombre*<input name="name" required></label>'
            '<label>Teléfono*<input name="phone" required></label>'
            '<label>Correo<input name="email" type="email"></label>'
            '<label>Notas<textarea name="notes" rows="2"></textarea></label>'
            '<button class="btn ok" style="width:100%">Guardar</button></form></div>')
    return HTMLResponse(_layout("Nuevo cliente", ctx, body))


@router.post("/agencia/clientes/nuevo")
async def agencia_customer_create(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    if not (form.get("name") or "").strip() or not (form.get("phone") or "").strip():
        raise HTTPException(400, "Nombre y teléfono son obligatorios.")
    ag = _write_agency(ctx, form.get("loc") or "")
    conn = dbmod.get_db()
    try:
        cid = adb.add_customer(conn, ag["id"], (form.get("name") or "").strip(),
                               (form.get("phone") or "").strip(),
                               (form.get("email") or "").strip(),
                               (form.get("notes") or "").strip()[:500])
        adb.audit(conn, ag["id"], "owner", "customer_created", entity="customers",
                  entity_id=cid, detail=form.get("name", "")[:60], actor_id=ctx["email"])
    finally:
        conn.close()
    return RedirectResponse("/agencia/clientes", status_code=303)


@router.get("/agencia/clientes/{customer_id}", response_class=HTMLResponse)
def agencia_customer_detail(request: Request, customer_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        cust = ag = order = None
        for aid in ctx["agency_ids"]:
            cust = conn.execute(
                """SELECT c.* FROM customers c
                   JOIN customer_agencies ca ON ca.customer_id=c.id
                   WHERE c.id=? AND ca.agency_id=?""", (customer_id, aid)).fetchone()
            if cust:
                ag = next(a for a in ctx["agencies"] if a["id"] == aid)
                break
        if not cust:
            raise HTTPException(404, "Cliente no encontrado")
        orders = dbmod.get_agency_orders(conn, ag["id"], limit=50)
        orders = [o for o in orders if o["customer_id"] == customer_id]
    finally:
        conn.close()
    rows = "".join(
        '<tr><td><a href="/agencia/ordenes/%d"><b>%s</b></a></td><td>%d paq</td>'
        '<td>%s</td></tr>'
        % (o["id"], _e(o["order_number"]), o["package_count"] or 0,
           _e((o["created_at"] or "")[:10])) for o in orders)
    body = ('<div class="card"><h2>%s</h2><span class="muted">%s<br>%s<br>%s</span></div>'
            '<div class="card"><h3>Órdenes</h3><table>%s</table></div>'
            % (_e(cust["name"]), _e(cust["phone"] or ""), _e(cust["email"] or ""),
               _e(cust["notes"] or ""),
               rows or '<tr><td class="muted">Sin órdenes.</td></tr>'))
    return HTMLResponse(_layout(cust["name"], ctx, body))


# ---------------------------------------------------------------- precios
@router.get("/agencia/precios", response_class=HTMLResponse)
def agencia_prices(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        cards = ""
        for a in ctx["agencies"]:
            rows = adb.list_price_list(conn, a["id"])
            trs = "".join(
                '<tr><td><b>%s</b></td><td>$%.2f</td>'
                '<td class="noprint"><form method="post" action="/agencia/precios/%d/borrar" '
                'style="display:inline" onsubmit="return confirm(\'¿Borrar este precio?\')">'
                '<button class="btn sm sec">✖</button></form></td></tr>'
                % (_e(r["label"]), r["price"] or 0, r["id"]) for r in rows)
            cards += ('<div class="card"><h3>%s</h3><table>%s</table>'
                      '<form method="post" action="/agencia/precios/agregar">'
                      '<input type="hidden" name="loc" value="%d">'
                      '<label>Concepto<input name="label" required></label>'
                      '<label>Precio $<input name="price" inputmode="decimal" required></label>'
                      '<label>Unidad<input name="unit" value="lb"></label>'
                      '<button class="btn sm ok">Agregar</button></form></div>'
                      % (_e(_brand(a)),
                         trs or '<tr><td class="muted">Sin precios publicados.</td></tr>',
                         a["id"]))
    finally:
        conn.close()
    return HTMLResponse(_layout("Mi lista de precios", ctx,
                                '<p class="muted">Tus precios de venta al público. '
                                'SAHJONY no los ve como tus costos: tus costos solo los ves en Liquidación.</p>'
                                + cards))


@router.post("/agencia/precios/agregar")
async def agencia_price_add(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    ag = _write_agency(ctx, form.get("loc") or "")
    try:
        price = float(form.get("price") or 0)
    except ValueError:
        raise HTTPException(400, "Precio inválido.")
    if price < 0:
        raise HTTPException(400, "Precio inválido.")
    conn = dbmod.get_db()
    try:
        adb.add_price(conn, ag["id"], (form.get("label") or "").strip(),
                      price, (form.get("unit") or "").strip()[:20])
        adb.audit(conn, ag["id"], "owner", "price_added", detail=form.get("label", "")[:60],
                  actor_id=ctx["email"])
    finally:
        conn.close()
    return RedirectResponse("/agencia/precios", status_code=303)


@router.post("/agencia/precios/{item_id}/borrar")
def agencia_price_delete(request: Request, item_id: int):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    conn = dbmod.get_db()
    try:
        ok = any(adb.delete_price(conn, aid, item_id) for aid in ctx["agency_ids"])
        if ok:
            adb.audit(conn, ctx["agency_ids"][0], "owner", "price_deleted",
                      entity_id=item_id, actor_id=ctx["email"])
    finally:
        conn.close()
    return RedirectResponse("/agencia/precios", status_code=303)


# ---------------------------------------------------------------- bandeja de mensajes (dueño)
# NOTA: GET /agencia/mensajes vive en ac3.py (agencia_inbox). No duplicar aquí:
# FastAPI atiende la primera ruta registrada y la segunda quedaría muerta.


# ---------------------------------------------------------------- rastreo interno
@router.get("/agencia/rastreo", response_class=HTMLResponse)
def agencia_tracking(request: Request, code: str = ""):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    found = None
    if code.strip():
        conn = dbmod.get_db()
        try:
            ph = ",".join("?" for _ in ctx["agency_ids"])
            found = conn.execute(
                f"""SELECT p.*, o.order_number FROM packages p
                    JOIN orders o ON o.id=p.order_id
                    WHERE p.code=? AND o.agency_id IN ({ph}) LIMIT 1""",
                [code.strip()] + ctx["agency_ids"]).fetchone()
        finally:
            conn.close()
    body = ('<div class="card"><form method="get"><label>Código de rastreo'
            '<input name="code" value="%s" required></label>'
            '<button class="btn">Buscar</button></form></div>' % _e(code))
    if code.strip():
        if found:
            body += ('<div class="card"><h3>Paquete %s</h3><table>'
                     '<tr><td>Estado</td><td><b>%s</b></td></tr>'
                     '<tr><td>Contenido</td><td>%s</td></tr>'
                     '<tr><td>Peso</td><td>%.1f lb</td></tr>'
                     '<tr><td>Orden</td><td><a href="/agencia/ordenes/%d">%s</a></td></tr>'
                     '</table></div>'
                     % (_e(found["code"]), _e(found["status"]),
                        _e(found["contents"] or ""), (found["weight_kg"] or 0) * 2.20462,
                        found["order_id"], _e(found["order_number"] or "")))
        else:
            body += '<div class="err">No encontramos ese código en tus locaciones.</div>'
    return HTMLResponse(_layout("Rastreo interno", ctx, body))
