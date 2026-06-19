import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Header, Request, Body
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import json

from database import get_connection
from auth import verify_owner, verify_participant, generate_participant_token

from config_loader import load_config, save_config


app = FastAPI(title="Cuba Veg Export API", version="1.0.0")

# Mount static files and templates (ensure directories exist)
import os
from pathlib import Path
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

class Order(BaseModel):
    id: str
    product: str
    quantity_lb: float
    status: str
    buyer: str

class Submission(BaseModel):
    data_type: str
    payload: dict

# In‑memory placeholder for orders (can be moved to DB later)
orders = {}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# Mount static files (including the cinematic hero page)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static_root")

# Serve root by redirecting to the index page
@app.get("/", response_class=RedirectResponse)
async def root_redirect():
    return RedirectResponse(url="/index.html")

# ----- Owner‑only order endpoints -----

# ----- Dynamic trade config endpoints -----
@app.post("/order")
async def create_order(order: Order, authorized: bool = Depends(verify_owner)):
    if order.id in orders:
        raise HTTPException(status_code=400, detail="Order already exists")
    orders[order.id] = order
    return {"msg": "order created", "order": order}

@app.get("/order/{order_id}")
async def get_order(order_id: str, authorized: bool = Depends(verify_owner)):
    if order_id not in orders:
        raise HTTPException(status_code=404, detail="Order not found")
    return orders[order_id]

# ----- Trade config management -----
@app.post("/config/{name}")
async def save_trade_config(name: str, config: dict = Body(...), authorized: bool = Depends(verify_owner)):
    path = save_config(name, config)
    return {"msg": "config saved", "path": path}

@app.get("/config/{name}")
async def get_trade_config(name: str, authorized: bool = Depends(verify_owner)):
    try:
        cfg = load_config(name)
        return {"config": cfg}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="config not found")

@app.post("/run/{name}")
async def run_workflow(name: str, authorized: bool = Depends(verify_owner)):
    # placeholder – in production this would trigger a delegate_task
    return {"msg": f"Workflow '{name}' triggered"}

# ----- Owner‑only participant management -----
@app.post("/admin/add_participant")
async def add_participant(business_id: str, participant_id: str, authorized: bool = Depends(verify_owner)):
    token = generate_participant_token()
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO participants (participant_id, business_id, token) VALUES (?,?,?)",
            (participant_id, business_id, token),
        )
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))
    conn.close()
    return {"participant_id": participant_id, "business_id": business_id, "token": token}

# ----- Participant data submission (write‑only) -----
@app.post("/submit")
async def submit_data(submission: Submission, info: dict = Depends(verify_participant)):
    participant_id = info["participant_id"]
    business_id = info["business_id"]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO submissions (business_id, participant_id, data_type, payload) VALUES (?,?,?,?)",
        (business_id, participant_id, submission.data_type, json.dumps(submission.payload)),
    )
    conn.commit()
    conn.close()
    return {"msg": "data submitted", "business_id": business_id, "participant_id": participant_id}

# ----- Owner view of all submissions -----
@app.get("/admin/submissions")
async def view_submissions(authorized: bool = Depends(verify_owner)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM submissions ORDER BY timestamp DESC")
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"submissions": rows}

# ----- Participant read‑only view of own submissions -----
@app.get("/my_submissions")
async def my_submissions(info: dict = Depends(verify_participant)):
    participant_id = info["participant_id"]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM submissions WHERE participant_id = ? ORDER BY timestamp DESC",
        (participant_id,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"submissions": rows}

# ----- Dashboard UI (participant) -----
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, token: str = None):
    # token can be passed via query string; the page's JS will use it for auth
    return templates.TemplateResponse("dashboard.html", {"request": request, "token": token})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=50001)
