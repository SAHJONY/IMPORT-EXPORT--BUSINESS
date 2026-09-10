"""Deterministic buyer-requirement extraction for Sofia's governed trade flow."""

from __future__ import annotations

import re
from typing import Any


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" -/.,")


def interpret_buyer_requirement(text: str) -> dict[str, Any]:
    raw = _clean(text)
    lowered = raw.casefold()
    parts = [_clean(part) for part in re.split(r"\s*/\s*", raw) if _clean(part)]
    container = re.search(r"(\d+)\s*(?:x|×)\s*(20|40)\s*['’]?(?:\s*(?:ft|foot|feet))?\s*(?:containers?|contenedores?)?", raw, re.I)
    packaging = re.search(r"\b(\d+(?:\.\d+)?)\s*[- ]?\s*(l|liters?|litros?|kg|kilograms?|kilogramos?)\b(?:\s*(?:packaging|packing|envases?|formato))?", raw, re.I)
    timing = next((p for p in parts if re.search(r"\b(asap|urgent|urgente|immediately|inmediato|required by|needed by)\b", p, re.I)), None)
    known: dict[str, Any] = {}
    if parts:
        known["product"] = parts[0]
    if container:
        known.update({
            "container_count": int(container.group(1)),
            "container_size_ft": int(container.group(2)),
            "container_type": f"{container.group(2)}FT FCL",
            "quantity": f"{container.group(1)} × {container.group(2)}' containers",
        })
    if packaging:
        unit = packaging.group(2).upper().replace("LITERS", "L").replace("LITROS", "L")
        known["packaging"] = f"{packaging.group(1)}-{unit}"
        known["specification"] = f"{known.get('product', 'Product')} in {known['packaging']} packaging"
    if timing:
        known["delivery_timeline"] = "ASAP" if "asap" in timing.casefold() else timing
    excluded = {parts[0] if parts else "", timing or ""}
    destination_candidates = [p for p in parts[1:] if p not in excluded and not re.search(r"container|contenedor|packag|envase|\d+\s*[- ]?(?:l|kg)\b", p, re.I)]
    if destination_candidates:
        known["destination"] = destination_candidates[-1]

    trade_intent = bool(known.get("product") and (container or any(word in lowered for word in ("buy", "need", "require", "compr", "cotiz", "rfq"))))
    required = ("product", "specification", "quantity", "destination", "delivery_timeline")
    missing = [field for field in required if not known.get(field)]
    return {
        "trade_intent": trade_intent,
        "known": known,
        "missing": missing,
        "rfq_complete": trade_intent and not missing,
        "container_utilization": {
            "status": "CALCULATION_REQUIRED" if container else "CONTAINER_BASIS_REQUIRED",
            "inputs_required": ["supplier case dimensions", "case gross weight", "palletization", "payload limit", "stowage allowance"],
            "do_not_assume_units": True,
        },
    }


def trade_execution_lifecycle(requirement: dict[str, Any]) -> list[dict[str, Any]]:
    rfq_ready = bool(requirement.get("rfq_complete"))
    return [
        {"stage": "BUYER_REQUIREMENT", "status": "READY" if requirement.get("trade_intent") else "HOLD", "authority": "autonomous"},
        {"stage": "RFQ_COMPLETENESS", "status": "READY" if rfq_ready else "HOLD", "authority": "autonomous", "missing": requirement.get("missing") or []},
        {"stage": "SUPPLIER_SOURCING", "status": "OPEN" if rfq_ready else "BLOCKED", "authority": "autonomous"},
        {"stage": "CONTAINER_UTILIZATION", "status": "OPEN" if rfq_ready else "BLOCKED", "authority": "autonomous", "gate": "verified packing and payload inputs"},
        {"stage": "FREIGHT_LANE", "status": "OPEN" if rfq_ready else "BLOCKED", "authority": "autonomous", "gate": "origin and forwarder/carrier evidence"},
        {"stage": "LANDED_COST", "status": "BLOCKED", "authority": "autonomous", "gate": "supplier + utilization + freight + duties/fees"},
        {"stage": "SAHJONY_MARGIN", "status": "BLOCKED", "authority": "owner_approval", "gate": "verified landed cost and margin policy"},
        {"stage": "COMPLIANCE_CHECK", "status": "OPEN" if rfq_ready else "BLOCKED", "authority": "autonomous_research_owner_release"},
        {"stage": "FORMAL_QUOTE", "status": "BLOCKED", "authority": "owner_approval", "gate": "verified commercial and compliance evidence"},
        {"stage": "NEGOTIATION", "status": "BLOCKED", "authority": "owner_approval_for_binding_terms"},
        {"stage": "PURCHASE_ORDER", "status": "BLOCKED", "authority": "owner_approval", "gate": "accepted quote, buyer authority, terms and compliance"},
    ]
