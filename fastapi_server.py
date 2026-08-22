from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agentic_control_plane import control_plane
from auth import generate_participant_token, hash_token, verify_owner, verify_participant
from config_loader import load_config, save_config
from database import get_connection
from insforge_backend import InsForgeConfigurationError, get_backend
from production_readiness import evaluate_production_readiness
from trade_connectors import trade_connectors
from trade_os import TradeScenario

app = FastAPI(
    title="SAHJONY Global Trade Intelligence OS",
    description="AI-agentic import/export control plane with deterministic compliance release gates.",
    version="2.2.0",
)

BASE_DIR = Path(__file__).parent
INDEX_FILE = BASE_DIR / "index.html"
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class Order(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    product: str = Field(min_length=2, max_length=160)
    quantity_lb: float = Field(gt=0)
    status: str = Field(default="draft", max_length=40)
    buyer: str = Field(min_length=1, max_length=160)


class Submission(BaseModel):
    data_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any]


class PersistedTradeCase(BaseModel):
    scenario: TradeScenario
    persist: bool = True


class ScreeningRequest(BaseModel):
    name: str = Field(min_length=2, max_length=240)
    limit: int = Field(default=25, ge=1, le=100)


orders: dict[str, Order] = {}


def _insforge_status() -> dict[str, Any]:
    configured = bool(os.getenv("INSFORGE_BASE_URL") and os.getenv("INSFORGE_API_KEY"))
    return {
        "configured": configured,
        "base_url_present": bool(os.getenv("INSFORGE_BASE_URL")),
        "server_key_present": bool(os.getenv("INSFORGE_API_KEY")),
    }


def _command_center_response() -> FileResponse:
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=503, detail="Command Center shell is unavailable")
    return FileResponse(str(INDEX_FILE), media_type="text/html")


def _legacy_write_allowed() -> bool:
    return os.getenv("PRODUCTION_MODE", "false").lower() != "true"


async def _persist_decision(scenario: TradeScenario, evaluation: dict[str, Any]) -> Any:
    backend = get_backend()
    decision = evaluation["decision"]
    case_payload = {
        "mode": scenario.mode.value,
        "origin_country": scenario.origin_country,
        "destination_country": scenario.destination_country,
        "product": scenario.product,
        "hs_code": scenario.hs_code,
        "incoterm": scenario.incoterm.upper(),
        "quantity": scenario.quantity,
        "unit_cost": scenario.unit_cost,
        "target_sale_price_per_unit": scenario.target_sale_price_per_unit,
        "status": "analyzed",
        "readiness_score": decision["readiness_score"],
        "release_gate": decision["release_gate"],
    }
    return await backend.insert("trade_cases", case_payload)


@app.get("/", include_in_schema=False)
async def owner_command_center():
    return _command_center_response()


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return _command_center_response()


@app.get("/health")
async def health_check():
    readiness = evaluate_production_readiness(runtime_ok=True)
    return {
        "status": "ok",
        "service": "global-trade-intelligence-os",
        "version": "2.2.0",
        "insforge": _insforge_status(),
        "release_policy": "fail-closed",
        "production_ready": readiness["production_ready"],
        "readiness_score": readiness["score"],
    }


@app.get("/v2/agents")
async def list_agents(authorized: bool = Depends(verify_owner)):
    return {"agents": control_plane.registry(), "count": len(control_plane.registry())}


@app.get("/v2/connectors/health")
async def connector_health(authorized: bool = Depends(verify_owner)):
    return await trade_connectors.health()


@app.post("/v2/compliance/ofac/screen")
async def ofac_screen(request: ScreeningRequest, authorized: bool = Depends(verify_owner)):
    try:
        return await trade_connectors.ofac_screen(request.name, limit=request.limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OFAC screening source unavailable: {type(exc).__name__}") from exc


@app.get("/v2/fx/reference")
async def fx_reference(base: str = "USD", quote: str = "EUR", authorized: bool = Depends(verify_owner)):
    try:
        return await trade_connectors.fx_reference(base, quote)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Official FX reference source unavailable: {type(exc).__name__}") from exc


@app.post("/v2/trade/analyze")
async def analyze_trade(request: PersistedTradeCase, authorized: bool = Depends(verify_owner)):
    evaluation = control_plane.evaluate(request.scenario)
    queue = control_plane.next_agent_queue(request.scenario)
    persistence: dict[str, Any] = {"requested": request.persist, "persisted": False}
    if request.persist:
        try:
            persistence["result"] = await _persist_decision(request.scenario, evaluation)
            persistence["persisted"] = True
        except InsForgeConfigurationError as exc:
            persistence["reason"] = str(exc)
        except Exception as exc:
            persistence["reason"] = f"InsForge persistence failed: {type(exc).__name__}"
    if os.getenv("PRODUCTION_MODE", "false").lower() == "true" and not persistence["persisted"]:
        raise HTTPException(status_code=503, detail="Production trade analysis requires durable InsForge persistence")
    return {**evaluation, "agent_queue": queue, "persistence": persistence}


@app.post("/v2/trade/simulate")
async def simulate_trade(scenario: TradeScenario, authorized: bool = Depends(verify_owner)):
    evaluation = control_plane.evaluate(scenario)
    return {**evaluation, "agent_queue": control_plane.next_agent_queue(scenario)}


@app.get("/v2/platform/readiness")
async def platform_readiness(authorized: bool = Depends(verify_owner)):
    connectors = await trade_connectors.health()
    return evaluate_production_readiness(runtime_ok=True, connector_health=connectors)


@app.get("/ui/generate")
async def ui_generate(query: str, domain: str = "product", stack: str = "html-tailwind", authorized: bool = Depends(verify_owner)):
    script_path = BASE_DIR / "ui-ux-pro-max-skill" / "src" / "ui-ux-pro-max" / "scripts" / "search.py"
    if not script_path.exists():
        raise HTTPException(status_code=500, detail="UI/UX skill script not found")
    cmd = [sys.executable, str(script_path), query, "--domain", domain, "--stack", stack, "-n", "5"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="UI/UX skill timed out") from exc
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail="UI/UX skill execution failed")
    return {"query": query, "domain": domain, "stack": stack, "results": result.stdout}


@app.post("/order")
async def create_order(order: Order, authorized: bool = Depends(verify_owner)):
    if not _legacy_write_allowed():
        raise HTTPException(status_code=503, detail="Legacy in-memory orders are disabled in production")
    if order.id in orders:
        raise HTTPException(status_code=400, detail="Order already exists")
    orders[order.id] = order
    return {"msg": "order created", "order": order}


@app.get("/order/{order_id}")
async def get_order(order_id: str, authorized: bool = Depends(verify_owner)):
    if order_id not in orders:
        raise HTTPException(status_code=404, detail="Order not found")
    return orders[order_id]


@app.post("/config/{name}")
async def save_trade_config(name: str, config: dict = Body(...), authorized: bool = Depends(verify_owner)):
    if not _legacy_write_allowed():
        raise HTTPException(status_code=503, detail="Local config writes are disabled in production")
    path = save_config(name, config)
    return {"msg": "config saved", "path": path}


@app.get("/config/{name}")
async def get_trade_config(name: str, authorized: bool = Depends(verify_owner)):
    try:
        return {"config": load_config(name)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="config not found") from exc


@app.post("/run/{name}")
async def run_workflow(name: str, authorized: bool = Depends(verify_owner)):
    known = {agent["name"] for agent in control_plane.registry()}
    if name not in known:
        raise HTTPException(status_code=404, detail="Unknown agent/workflow")
    return {
        "msg": f"Workflow '{name}' accepted",
        "status": "queued",
        "note": "Execution adapters must be configured before autonomous external actions are enabled.",
    }


@app.post("/admin/add_participant")
async def add_participant(business_id: str, participant_id: str, authorized: bool = Depends(verify_owner)):
    if not _legacy_write_allowed():
        raise HTTPException(status_code=503, detail="Legacy participant store is disabled in production; use InsForge Auth")
    token = generate_participant_token()
    conn = get_connection()
    try:
        conn.execute("INSERT INTO participants (participant_id, business_id, token_hash) VALUES (?,?,?)", (participant_id, business_id, hash_token(token)))
        conn.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to create participant") from exc
    finally:
        conn.close()
    return {"participant_id": participant_id, "business_id": business_id, "token": token}


@app.post("/submit")
async def submit_data(submission: Submission, info: dict = Depends(verify_participant)):
    if not _legacy_write_allowed():
        raise HTTPException(status_code=503, detail="Legacy submission store is disabled in production")
    conn = get_connection()
    try:
        conn.execute("INSERT INTO submissions (business_id, participant_id, data_type, payload) VALUES (?,?,?,?)", (info["business_id"], info["participant_id"], submission.data_type, json.dumps(submission.payload)))
        conn.commit()
    finally:
        conn.close()
    return {"msg": "data submitted", **info}


@app.get("/admin/submissions")
async def view_submissions(authorized: bool = Depends(verify_owner)):
    if not _legacy_write_allowed():
        raise HTTPException(status_code=503, detail="Legacy submission store is disabled in production")
    conn = get_connection()
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM submissions ORDER BY timestamp DESC").fetchall()]
    finally:
        conn.close()
    return {"submissions": rows}


@app.get("/my_submissions")
async def my_submissions(info: dict = Depends(verify_participant)):
    if not _legacy_write_allowed():
        raise HTTPException(status_code=503, detail="Legacy submission store is disabled in production")
    conn = get_connection()
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM submissions WHERE participant_id = ? ORDER BY timestamp DESC", (info["participant_id"],)).fetchall()]
    finally:
        conn.close()
    return {"submissions": rows}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "50001")))
