"""Centro de comando — parte 2: panel, briefing diario, alertas, liquidación."""
from __future__ import annotations

from ac_shared import *

router = APIRouter()


def _week_start() -> str:
    from datetime import date as _d, timedelta as _td
    today = _d.today()
    return (today - _td(days=today.weekday())).isoformat()


@router.get("/agencia/panel", response_class=HTMLResponse)
def agencia_panel(request: Request, loc: str = ""):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    ids, _w = _order_scope(ctx, loc)
    conn = dbmod.get_db()
    try:
        ph = ",".join("?" for _ in ids)
        n_orders = conn.execute(
            f"SELECT COUNT(*) c FROM orders WHERE agency_id IN ({ph})", ids).fetchone()["c"]
        n_pkgs = conn.execute(
            f"""SELECT COUNT(*) c FROM packages p JOIN orders o ON o.id=p.order_id
                WHERE o.agency_id IN ({ph})""", ids).fetchone()["c"]
        unread = conn.execute(
            f"""SELECT COUNT(*) c FROM portal_messages
                WHERE agency_id IN ({ph}) AND sender='customer' AND read_by_staff=0""",
            ids).fetchone()["c"]
        briefing = adb.compute_briefing(conn, ids)
        alerts = adb.compute_alerts(conn, ids)
        # Liquidación por locación (claves reales de agency_week_settlement).
        ws = _week_start()
        settle_cards = ""
        settle_total = 0.0
        terms_notes = []
        for a in ctx["agencies"]:
            if a["id"] not in ids:
                continue
            s = dbmod.agency_week_settlement(conn, a["id"], ws)
            if s.get("pending"):
                terms_notes.append(_brand(a))
                settle_cards += ('<div class="card"><b>%s</b><div class="alert">'
                                 'Términos pendientes de confirmación.</div></div>'
                                 % _e(_brand(a)))
            else:
                settle_total += s.get("total") or 0
                settle_cards += ('<div class="card"><b>%s</b><br>'
                                 '<span class="muted">%d órdenes · %d paquetes · %.1f lb</span><br>'
                                 'A SAHJONY: <b>$%.2f</b></div>'
                                 % (_e(_brand(a)), s.get("n_orders") or 0,
                                    s.get("n_pkgs") or 0, s.get("lb") or 0,
                                    s.get("total") or 0))
    finally:
        conn.close()

    b = briefing
    brief_html = ('<div class="card"><h3>📋 Tu día</h3><table>'
                  '<tr><td>Órdenes ayer</td><td><b>%d</b></td></tr>'
                  '<tr><td>Cobrado ayer</td><td><b>$%.2f</b></td></tr>'
                  '<tr><td>Mensajes de clientes sin leer</td><td><b>%d</b></td></tr>'
                  '</table></div>' % (b["yesterday_orders"], b["yesterday_payments"],
                                      b["unread_messages"]))
    stale = "".join(
        '<tr><td><a href="/agencia/ordenes/%d">%s</a></td></tr>' % (s["id"], _e(s["order_number"]))
        for s in b["stale_orders"])
    if stale:
        brief_html += ('<div class="card"><h3>⚠️ Sin movimiento 5+ días</h3><table>%s</table></div>'
                       % stale)
    overdue = "".join(
        '<tr><td><a href="/agencia/facturas/%d">%s</a></td><td>$%.2f</td></tr>'
        % (i["id"], _e(i["number"]), i["total"] or 0) for i in b["overdue_invoices"])
    if overdue:
        brief_html += ('<div class="card"><h3>⏰ Facturas vencidas</h3><table>%s</table></div>'
                       % overdue)

    alert_html = ""
    for al in alerts[:6]:
        alert_html += ('<div class="alert"><b>%s</b><br><span class="muted">%s</span><br>'
                       '<a class="btn sm" href="%s">%s</a> '
                       '<form method="post" action="/agencia/alertas/descartar" style="display:inline">'
                       '<input type="hidden" name="key" value="%s"><input type="hidden" name="aid" value="%d">'
                       '<button class="btn sm sec">Descartar</button></form></div>'
                       % (_e(al["title"]), _e(al["why"]), _e(al["action_url"]),
                          _e(al["action_label"]), _e(al["key"]), al["agency_id"]))

    body = (brief_html + alert_html +
            '<div class="kpi"><div class="card"><b>%d</b>Órdenes</div>'
            '<div class="card"><b>%d</b>Paquetes</div>'
            '<div class="card"><b>%d</b>Sin leer</div>'
            '<div class="card"><b>$%.2f</b>A SAHJONY (sem)</div></div>'
            '<div class="card"><h3>🤝 Liquidación semanal por locación</h3>%s'
            '<p class="muted">Semana desde %s.</p></div>'
            '<a class="btn" href="/agencia/ordenes/nueva">+ Nueva orden</a> '
            '<a class="btn sec" href="/agencia/checklist">Primeros pasos</a>'
            % (n_orders, n_pkgs, unread, settle_total, settle_cards, ws))
    return HTMLResponse(_layout("Panel", ctx, body, active="panel"))


@router.post("/agencia/alertas/descartar")
async def agencia_alert_dismiss(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    form = await request.form()
    key = (form.get("key") or "").strip()
    try:
        aid = int(form.get("aid") or 0)
    except (TypeError, ValueError):
        aid = 0
    if aid not in ctx["agency_ids"]:
        raise HTTPException(404, "Locación no autorizada")
    conn = dbmod.get_db()
    try:
        adb.dismiss_alert(conn, aid, key, ctx["email"])
    finally:
        conn.close()
    return RedirectResponse("/agencia/panel", status_code=303)


@router.get("/agencia/liquidacion", response_class=HTMLResponse)
def agencia_settlement(request: Request):
    ctx, redir = _guard_strict(request)
    if redir:
        return redir
    ws = _week_start()
    conn = dbmod.get_db()
    try:
        cards = ""
        total = 0.0
        for a in ctx["agencies"]:
            s = dbmod.agency_week_settlement(conn, a["id"], ws)
            if s.get("pending"):
                cards += ('<div class="card"><h3>%s</h3><div class="alert">'
                          'Términos pendientes de confirmación. '
                          'Tus números aparecerán cuando SAHJONY los confirme.</div></div>'
                          % _e(_brand(a)))
                continue
            total += s.get("total") or 0
            cards += ('<div class="card"><h3>%s</h3><table>'
                      '<tr><td>Órdenes</td><td>%d</td></tr>'
                      '<tr><td>Paquetes</td><td>%d</td></tr>'
                      '<tr><td>Peso</td><td>%.1f lb</td></tr>'
                      '<tr><td>Por órdenes</td><td>$%.2f</td></tr>'
                      '<tr><td>Por paquetes</td><td>$%.2f</td></tr>'
                      '<tr><td>Por peso</td><td>$%.2f</td></tr>'
                      '<tr><td><b>Total a SAHJONY</b></td><td><b>$%.2f</b></td></tr>'
                      '</table></div>'
                      % (_e(_brand(a)), s.get("n_orders") or 0, s.get("n_pkgs") or 0,
                         s.get("lb") or 0, s.get("amt_orders") or 0,
                         s.get("amt_packages") or 0, s.get("amt_weight") or 0,
                         s.get("total") or 0))
    finally:
        conn.close()
    body = ('<p class="muted">Semana desde %s. Lo que le corresponde a SAHJONY.</p>' % ws +
            cards + '<div class="card"><h3>Total todas las locaciones: $%.2f</h3></div>' % total)
    return HTMLResponse(_layout("Mi liquidación", ctx, body))
