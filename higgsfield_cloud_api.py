from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner

app = FastAPI(title="SAHJONY Higgsfield Cloud Control", version="1.0.0", docs_url=None, redoc_url=None)

DEFAULT_APPLICATION = "seedance_2_5"

SCENES: dict[str, dict[str, str]] = {
    "entrance": {
        "chapter": "01 / Entrance",
        "prompt": "Cinematic aerial night approach to a global container port, luminous trade routes crossing a dark ocean, cranes and vessels moving with precise choreography, deep navy and restrained warm gold color grade, photorealistic premium B2B film, slow forward camera movement, no logos, no text, no people, 16:9.",
    },
    "demand": {
        "chapter": "02 / Demand",
        "prompt": "Cinematic macro-to-wide sequence of industrial goods being measured, counted and prepared for international shipment inside a modern warehouse, precise scanning light and organized pallets, deep navy shadows with warm gold highlights, photorealistic premium trade film, controlled dolly movement, no logos, no text, 16:9.",
    },
    "sourcing": {
        "chapter": "03 / Global sourcing",
        "prompt": "Cinematic journey through a modern global manufacturing floor, verified production lines, quality inspection and export-ready cargo, confident international scale, deep navy and restrained warm gold grade, photorealistic premium B2B film, elegant lateral tracking camera, no logos, no text, 16:9.",
    },
    "control": {
        "chapter": "04 / Trade control",
        "prompt": "Abstract cinematic trade control room with physical documents, container seals, inspection instruments and subtle data light moving across a dark operations table, evidence and compliance atmosphere, deep navy with warm gold accents, photorealistic, slow orbital camera, no readable text, no logos, 16:9.",
    },
    "execution": {
        "chapter": "05 / Execution",
        "prompt": "Cinematic container journey from port crane to cargo vessel at blue hour, powerful scale, sea mist, precise logistics movement and realistic industrial detail, deep navy with warm gold port lights, photorealistic premium global trade film, smooth tracking camera, no logos, no text, 16:9.",
    },
    "finale": {
        "chapter": "06 / Grand finale",
        "prompt": "Epic cinematic view of Earth at night from low orbit with restrained luminous trade corridors linking ports across continents, elegant and credible rather than science fiction, deep navy and warm gold palette, slow majestic pullback, photorealistic premium global trading operating system film, no logos, no text, 16:9.",
    },
}


class GenerateSceneRequest(BaseModel):
    scene: Literal["entrance", "demand", "sourcing", "control", "execution", "finale"]
    confirm: Literal["GENERATE"]
    duration: int = Field(default=5, ge=4, le=10)
    resolution: Literal["480p", "720p", "1080p"] = "720p"


def _configured() -> bool:
    return bool(os.getenv("HF_KEY", "").strip()) or bool(
        os.getenv("HF_API_KEY", "").strip() and os.getenv("HF_API_SECRET", "").strip()
    )


def _application() -> str:
    return os.getenv("HF_SEEDANCE_APPLICATION", DEFAULT_APPLICATION).strip() or DEFAULT_APPLICATION


def _client_module():
    if not _configured():
        raise HTTPException(status_code=503, detail="Higgsfield Cloud credentials are not configured in this deployment")
    try:
        import higgsfield_client
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Higgsfield Cloud SDK is unavailable in this deployment") from exc
    return higgsfield_client


def _safe_provider_error(exc: Exception) -> HTTPException:
    message = str(exc).strip() or type(exc).__name__
    return HTTPException(status_code=502, detail=f"Higgsfield Cloud request failed: {message[:400]}")


@app.get("/higgsfield-cloud/health", dependencies=[Depends(verify_owner)])
async def health():
    return {
        "status": "ready" if _configured() else "configuration_required",
        "service": "higgsfield-cloud",
        "provider": "Higgsfield Cloud",
        "model": "Seedance 2.5",
        "application": _application(),
        "credentials_configured": _configured(),
        "credentials_exposed": False,
        "owner_only": True,
        "async_submission": True,
        "scene_count": len(SCENES),
    }


@app.get("/higgsfield-cloud/cinematic/scenes", dependencies=[Depends(verify_owner)])
async def cinematic_scenes():
    return {
        "model": "Seedance 2.5",
        "application": _application(),
        "scenes": [
            {"id": scene_id, "chapter": scene["chapter"], "prompt": scene["prompt"]}
            for scene_id, scene in SCENES.items()
        ],
    }


@app.post("/higgsfield-cloud/cinematic/generations", dependencies=[Depends(verify_owner)])
async def generate_scene(payload: GenerateSceneRequest):
    client = _client_module()
    scene = SCENES[payload.scene]
    try:
        controller = await client.submit_async(
            _application(),
            arguments={
                "prompt": scene["prompt"],
                "mode": "t2v",
                "duration": payload.duration,
                "resolution": payload.resolution,
                "generate_audio": False,
                "bitrate_mode": "high",
                "aspect_ratio": "16:9",
            },
        )
    except Exception as exc:
        raise _safe_provider_error(exc) from exc
    return {
        "status": "submitted",
        "scene": payload.scene,
        "chapter": scene["chapter"],
        "request_id": controller.request_id,
        "duration": payload.duration,
        "resolution": payload.resolution,
        "model": "Seedance 2.5",
    }


@app.get("/higgsfield-cloud/cinematic/generations/{request_id}", dependencies=[Depends(verify_owner)])
async def generation_status(request_id: str):
    if not request_id or len(request_id) > 160:
        raise HTTPException(status_code=400, detail="Invalid Higgsfield request id")
    client = _client_module()
    try:
        status = await client.status_async(request_id=request_id)
        state = type(status).__name__.lower()
        response: dict[str, Any] = {"request_id": request_id, "status": state}
        if state == "completed":
            response["result"] = await client.result_async(request_id=request_id)
        return response
    except Exception as exc:
        raise _safe_provider_error(exc) from exc


@app.post("/higgsfield-cloud/cinematic/generations/{request_id}/cancel", dependencies=[Depends(verify_owner)])
async def cancel_generation(request_id: str):
    if not request_id or len(request_id) > 160:
        raise HTTPException(status_code=400, detail="Invalid Higgsfield request id")
    client = _client_module()
    try:
        await client.cancel_async(request_id=request_id)
    except Exception as exc:
        raise _safe_provider_error(exc) from exc
    return {"request_id": request_id, "status": "cancel_requested"}
