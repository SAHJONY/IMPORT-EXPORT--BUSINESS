from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

VOICE_NUMBER = os.getenv("SOFIA_PRIMARY_VOICE_NUMBER", "+13465346545").strip()
WHATSAPP_NUMBER = os.getenv("SAHJONY_WHATSAPP_BUSINESS_NUMBER", "+12816628581").strip()
SOFIA_IDENTITY = "Sofía Smith"

BUSINESS_ROUTES = {
    "global_trade": {"name": "SAHJONY Global Trade", "app": "import-export-business"},
    "wholesale_real_estate": {"name": "Wholesale Real Estate", "app": "wholesale-ops-app"},
    "ecommerce": {"name": "SAHJONY E-Commerce", "app": "sahjony-e-commerce"},
    "marketing_agency": {"name": "SAHJONY Marketing Agency", "app": "sahjony-marketing-agency"},
    "frontdesk": {"name": "FrontDesk Agents", "app": "frontdesk-agents"},
    "energy": {"name": "SAHJONY Energy", "app": "sahjony-energy"},
}

LEGACY_BUSINESS_ALIASES = {
    "cima": "wholesale_real_estate",
    "cima_real_estate": "wholesale_real_estate",
    "cima real estate": "wholesale_real_estate",
    "cima real estate llc": "wholesale_real_estate",
    "sahjony-real-estate-platform": "wholesale_real_estate",
}

app = FastAPI(title="Sofía Unified Communications", version="2.0.0")


def channel_registry() -> dict[str, Any]:
    return {
        "identity": SOFIA_IDENTITY,
        "voice": {
            "number": VOICE_NUMBER,
            "provider": "autocalls",
            "status": "production",
        },
        "whatsapp": {
            "number": WHATSAPP_NUMBER,
            "provider": "meta_whatsapp",
            "status": "production",
        },
        "continuity": {
            "shared_identity": True,
            "shared_business_context": True,
            "business_data_isolation_required": True,
            "owner_approval_for_binding_actions": True,
        },
        "business_routes": BUSINESS_ROUTES,
        "legacy_business_aliases": LEGACY_BUSINESS_ALIASES,
        "real_estate_canonical_business": "wholesale_real_estate",
        "real_estate_canonical_application": "SAHJONY/Wholesale--ops-app",
    }


@app.get("/communications/sofia-unified/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "sofia-unified-communications", **channel_registry()}
