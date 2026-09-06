from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from logistics_a_to_z_orchestrator import ShipmentControl, Stage, can_transition, lifecycle_blueprint

app = FastAPI(title='SAHJONY Logistics A-to-Z Control', version='1.0.0', docs_url=None, redoc_url=None)


class TransitionIn(BaseModel):
    current_stage: Stage
    target_stage: Stage
    customer_verified: bool = False
    pricing_floor_passed: bool = False
    capacity_confirmed: bool = False
    compliance_cleared: bool = False
    payment_cleared: bool = False
    pickup_provider_verified: bool = False
    virtual_hub_provider_verified: bool = False
    gateway_selected: bool = False
    carrier_booked: bool = False
    customs_released: bool = False
    last_mile_provider_verified: bool = False
    final_address_present: bool = False
    pod_recorded: bool = False
    recipient_verified: bool = False
    exception_open: bool = False
    financial_reconciled: bool = False


@app.get('/logistics-a-to-z/health')
async def health():
    return {
        'status': 'ok',
        'door_to_door_default': True,
        'stage_skipping_blocked': True,
        'provider_verification_required': True,
        'payment_gate_required': True,
        'pod_required': True,
        'recipient_verification_required': True,
        'exception_and_claims_path': True,
        'financial_reconciliation_required_to_close': True,
    }


@app.get('/logistics-a-to-z/blueprint')
async def blueprint():
    return lifecycle_blueprint()


@app.post('/logistics-a-to-z/transition-check')
async def transition_check(p: TransitionIn):
    controls = ShipmentControl(stage=p.current_stage, **p.model_dump(exclude={'current_stage','target_stage'}))
    return can_transition(p.current_stage, p.target_stage, controls)
