from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import persistent_backend_status

app = FastAPI(
    title="SAHJONY Cuba Vehicle Export Department",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

GateStatus = Literal["PASS", "FAIL", "PENDING", "NOT_APPLICABLE"]
VehicleCondition = Literal["NEW", "USED"]
Powertrain = Literal["GASOLINE", "DIESEL", "HYBRID", "PHEV", "EV", "OTHER"]
ImporterType = Literal[
    "CUBAN_PRIVATE_BUSINESS",
    "AUTHORIZED_CUBAN_IMPORTER",
    "INDIVIDUAL_CONSUMER",
    "OTHER",
]
BisBasis = Literal["UNDETERMINED", "SCP", "BIS_LICENSE", "OTHER_LICENSE_EXCEPTION", "NOT_SUBJECT_TO_EAR"]
OfacBasis = Literal["UNDETERMINED", "CACR_GENERAL_AUTHORIZATION", "OFAC_SPECIFIC_LICENSE", "EXEMPT"]

REQUIRED_GATES = [
    "vehicle_identity_and_title",
    "used_vehicle_cbp_export_requirements",
    "aes_eei_itn",
    "ear_classification",
    "bis_authorization_basis",
    "ofac_cacr_authorization_basis",
    "restricted_party_screening",
    "cuban_importer_eligibility",
    "end_user_and_end_use",
    "carrier_acceptance",
    "dangerous_goods_review",
    "commercial_documents",
    "cuba_customs_import_readiness",
]

AUTHORITY_NOTES = {
    "bis_cuba": (
        "Exports or reexports to Cuba of items subject to the EAR generally require a BIS license unless a listed "
        "license exception or other EAR exclusion applies. License Exception SCP is transaction-specific and must not "
        "be presumed from product category alone."
    ),
    "ofac": (
        "OFAC Cuba authorizations must be evaluated independently from BIS export controls. A Cuba general license does "
        "not expand activity beyond its stated scope, and a specific OFAC license may be required where no general "
        "authorization applies."
    ),
    "cbp_used_vehicles": (
        "Used self-propelled vehicles exported from the United States require vehicle ownership/export documentation and "
        "Electronic Export Information filing in AES. Applicable CBP presentation/72-hour requirements must be satisfied "
        "for the actual port and shipment before export."
    ),
    "ev_shipping": (
        "Electric or hybrid vehicles are not automatically prohibited. Battery configuration and carrier rules require a "
        "dangerous-goods review, including the applicable maritime transport requirements, before booking."
    ),
    "no_automatic_legal_clearance": (
        "This department is a fail-closed operating workflow. It does not create legal clearance, a government license, "
        "customs authorization, or carrier acceptance."
    ),
}


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(auth.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid or expired owner session")


class GateEvidence(BaseModel):
    status: GateStatus = "PENDING"
    evidence_reference: str | None = Field(default=None, max_length=1500)
    evidence_summary: str | None = Field(default=None, max_length=4000)


class VehicleIn(BaseModel):
    vin: str = Field(min_length=11, max_length=25)
    year: int = Field(ge=1900, le=2100)
    make: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=160)
    condition: VehicleCondition
    powertrain: Powertrain = "GASOLINE"
    value_usd: float | None = Field(default=None, ge=0)
    title_state: str | None = Field(default=None, max_length=80)
    title_number: str | None = Field(default=None, max_length=160)
    ownership_document_verified: bool = False
    origin_city_state: str = Field(min_length=2, max_length=240)
    proposed_us_export_port: str | None = Field(default=None, max_length=240)
    proposed_cuba_port: str | None = Field(default=None, max_length=240)
    aes_itn: str | None = Field(default=None, max_length=120)
    eccn_or_ear99: str | None = Field(default=None, max_length=120)
    bis_authorization_basis: BisBasis = "UNDETERMINED"
    bis_authorization_reference: str | None = Field(default=None, max_length=600)
    ofac_authorization_basis: OfacBasis = "UNDETERMINED"
    ofac_authorization_reference: str | None = Field(default=None, max_length=600)
    restricted_party_screening: GateStatus = "PENDING"
    dangerous_goods_review: GateStatus = "PENDING"
    carrier_acceptance: GateStatus = "PENDING"


class ShipmentPreflightIn(BaseModel):
    vehicles: list[VehicleIn] = Field(min_length=1, max_length=20)
    importer_name: str = Field(min_length=2, max_length=300)
    importer_type: ImporterType
    importer_registration_reference: str | None = Field(default=None, max_length=1200)
    importer_eligibility: GateStatus = "PENDING"
    end_user_name: str = Field(min_length=2, max_length=300)
    end_use: str = Field(min_length=3, max_length=1600)
    end_user_end_use_eligibility: GateStatus = "PENDING"
    cuba_customs_readiness: GateStatus = "PENDING"
    commercial_documents: GateStatus = "PENDING"
    proposed_incoterm: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=5000)


class ManualGateReviewIn(BaseModel):
    gates: dict[str, GateEvidence] = Field(default_factory=dict)


def _vehicle_gate_state(v: VehicleIn) -> dict[str, GateStatus]:
    return {
        "vehicle_identity_and_title": "PASS" if v.ownership_document_verified and bool(v.vin) else "PENDING",
        "used_vehicle_cbp_export_requirements": "NOT_APPLICABLE" if v.condition == "NEW" else "PENDING",
        "aes_eei_itn": "PASS" if bool(v.aes_itn) else "PENDING",
        "ear_classification": "PASS" if bool(v.eccn_or_ear99) else "PENDING",
        "bis_authorization_basis": "PASS" if v.bis_authorization_basis != "UNDETERMINED" else "PENDING",
        "ofac_cacr_authorization_basis": "PASS" if v.ofac_authorization_basis != "UNDETERMINED" else "PENDING",
        "restricted_party_screening": v.restricted_party_screening,
        "carrier_acceptance": v.carrier_acceptance,
        "dangerous_goods_review": (
            v.dangerous_goods_review
            if v.powertrain in {"EV", "PHEV", "HYBRID"}
            else "NOT_APPLICABLE"
        ),
    }


def _shipment_gate_state(p: ShipmentPreflightIn) -> dict[str, GateStatus]:
    vehicle_states = [_vehicle_gate_state(v) for v in p.vehicles]
    aggregate: dict[str, GateStatus] = {}
    for key in REQUIRED_GATES:
        values = [s[key] for s in vehicle_states if key in s]
        if values:
            if "FAIL" in values:
                aggregate[key] = "FAIL"
            elif "PENDING" in values:
                aggregate[key] = "PENDING"
            elif all(v == "NOT_APPLICABLE" for v in values):
                aggregate[key] = "NOT_APPLICABLE"
            else:
                aggregate[key] = "PASS"
    aggregate["cuban_importer_eligibility"] = p.importer_eligibility
    aggregate["end_user_and_end_use"] = p.end_user_end_use_eligibility
    aggregate["commercial_documents"] = p.commercial_documents
    aggregate["cuba_customs_import_readiness"] = p.cuba_customs_readiness
    return aggregate


@app.get("/cuba-vehicles/health")
async def health():
    persistence = persistent_backend_status()
    return {
        "status": "ok",
        "service": "sahjony-cuba-vehicle-export-department",
        "version": "1.0.0",
        "scope": "US_TO_CUBA_VEHICLE_EXPORTS_ONLY",
        "fail_closed": True,
        "default_release_status": "HOLD",
        "government_license_generation": False,
        "automatic_legal_clearance": False,
        "automatic_customs_clearance": False,
        "automatic_carrier_booking": False,
        "automatic_payment_authority": False,
        "owner_binding_approval_required": True,
        "required_gates": REQUIRED_GATES,
        "persistence_provider": persistence.get("provider"),
        "authority_notes": AUTHORITY_NOTES,
    }


@app.post("/cuba-vehicles/preflight")
async def preflight(
    payload: ShipmentPreflightIn,
    authorization: str | None = Header(None, alias="Authorization"),
):
    owner(authorization)
    gates = _shipment_gate_state(payload)
    failed = sorted(k for k, v in gates.items() if v == "FAIL")
    pending = sorted(k for k, v in gates.items() if v == "PENDING")
    release_allowed = not failed and not pending
    return {
        "status": "READY_FOR_OWNER_REVIEW" if release_allowed else "HOLD",
        "release_allowed": False,
        "binding_release_requires_owner_action": True,
        "vehicle_count": len(payload.vehicles),
        "gates": gates,
        "failed_gates": failed,
        "pending_gates": pending,
        "next_action": (
            "Owner/compliance review after all documentary evidence is attached"
            if release_allowed
            else "Resolve failed/pending compliance and logistics gates before quoting shipment as executable"
        ),
        "authority_notes": AUTHORITY_NOTES,
    }


@app.post("/cuba-vehicles/gate-review")
async def gate_review(
    payload: ManualGateReviewIn,
    authorization: str | None = Header(None, alias="Authorization"),
):
    owner(authorization)
    unknown = sorted(set(payload.gates) - set(REQUIRED_GATES))
    if unknown:
        raise HTTPException(400, "Unknown vehicle-export gates: " + ", ".join(unknown))
    failed = sorted(k for k, v in payload.gates.items() if v.status == "FAIL")
    pending = sorted(k for k, v in payload.gates.items() if v.status == "PENDING")
    return {
        "status": "HOLD" if failed or pending else "REVIEW_COMPLETE",
        "release_allowed": False,
        "owner_binding_approval_required": True,
        "failed_gates": failed,
        "pending_gates": pending,
    }
