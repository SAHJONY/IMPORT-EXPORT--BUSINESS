from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from auth import (
    create_browser_session,
    require_browser_role,
    verify_customer_token,
    verify_employee_token,
    verify_owner_token,
)

app = FastAPI(title="SAHJONY Global Trade Portal Gateway", docs_url=None, redoc_url=None)
BASE_DIR = Path(__file__).parent
ROLE_FILES = {
    "owner": BASE_DIR / "dashboard.html",
    "employee": BASE_DIR / "index.html",
    "customer": BASE_DIR / "client.html",
}


class LoginRequest(BaseModel):
    role: str = Field(pattern="^(owner|employee|customer)$")
    token: str = Field(min_length=8, max_length=512)


def _login_page(role: str) -> HTMLResponse:
    labels = {"owner": "Owner Command Center", "employee": "Employee Operations", "customer": "Customer Portal"}
    label = labels[role]
    html = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{label} · Secure Access</title><style>
    *{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#07111f;color:#f7fbff;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:20px}}.card{{width:min(460px,100%);padding:32px;border:1px solid rgba(255,255,255,.12);border-radius:24px;background:linear-gradient(180deg,#10233a,#091522);box-shadow:0 30px 90px rgba(0,0,0,.4)}}.eyebrow{{font-size:12px;letter-spacing:.16em;color:#56d7ff;font-weight:800}}h1{{font-size:34px;line-height:1.05;margin:12px 0}}p{{color:#9db0c2;line-height:1.6}}input{{width:100%;margin-top:18px;padding:15px;border-radius:14px;border:1px solid rgba(255,255,255,.14);background:#07111f;color:white;font-size:16px}}button{{width:100%;margin-top:12px;padding:15px;border:0;border-radius:14px;background:linear-gradient(135deg,#56d7ff,#79f2c0);color:#03111b;font-weight:900;font-size:15px;cursor:pointer}}#msg{{min-height:20px;margin-top:12px;color:#ffca67;font-size:13px}}
    </style></head><body><main class="card"><div class="eyebrow">SAHJONY GLOBAL TRADE · SECURE ACCESS</div><h1>{label}</h1><p>Enter the credential assigned to this role. Sessions are server-signed, HttpOnly and expire automatically.</p><input id="token" type="password" autocomplete="current-password" placeholder="Access credential"><button onclick="login()">Continue securely</button><div id="msg"></div></main><script>
    async function login(){{const token=document.getElementById('token').value;const msg=document.getElementById('msg');msg.textContent='Verifying…';try{{const r=await fetch('/auth/login',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{role:'{role}',token}})}});const j=await r.json();if(!r.ok)throw new Error(j.detail||'Access denied');location.href='/{role}';}}catch(e){{msg.textContent=e.message;}}}}
    document.getElementById('token').addEventListener('keydown',e=>{{if(e.key==='Enter')login()}})
    </script></body></html>'''
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/login/{role}", include_in_schema=False)
async def login_page(role: str):
    if role not in ROLE_FILES:
        raise HTTPException(status_code=404, detail="Unknown portal role")
    return _login_page(role)


@app.post("/auth/login", include_in_schema=False)
async def login(payload: LoginRequest):
    subject = payload.role
    valid = False
    if payload.role == "owner":
        valid = verify_owner_token(payload.token)
    elif payload.role == "employee":
        valid = verify_employee_token(payload.token)
    else:
        customer = verify_customer_token(payload.token)
        valid = bool(customer)
        if customer:
            subject = str(customer["participant_id"])
    if not valid:
        raise HTTPException(status_code=403, detail="Invalid credential for this portal")
    response = JSONResponse({"ok": True, "role": payload.role})
    response.set_cookie(
        "trade_os_session",
        create_browser_session(payload.role, subject),
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=8 * 60 * 60,
        path="/",
    )
    return response


@app.post("/auth/logout", include_in_schema=False)
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie("trade_os_session", path="/")
    return response


def _portal(request: Request, role: str):
    if not require_browser_role(request, role):
        return RedirectResponse(url=f"/login/{role}", status_code=303)
    page = ROLE_FILES[role]
    if not page.exists():
        raise HTTPException(status_code=503, detail="Portal shell unavailable")
    return FileResponse(str(page), media_type="text/html", headers={"Cache-Control": "no-store"})


@app.get("/owner", include_in_schema=False)
async def owner(request: Request):
    return _portal(request, "owner")


@app.get("/employee", include_in_schema=False)
async def employee(request: Request):
    return _portal(request, "employee")


@app.get("/customer", include_in_schema=False)
async def customer(request: Request):
    return _portal(request, "customer")
