from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, Field


class TradeMode(str, Enum):
    IMPORT = "import"
    EXPORT = "export"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


class TradeScenario(BaseModel):
    mode: TradeMode
    origin_country: str = Field(min_length=2, max_length=80)
    destination_country: str = Field(min_length=2, max_length=80)
    product: str = Field(min_length=2, max_length=160)
    hs_code: str | None = Field(default=None, max_length=20)
    quantity: float = Field(gt=0)
    unit_cost: float = Field(ge=0)
    freight_cost: float = Field(default=0, ge=0)
    insurance_cost: float = Field(default=0, ge=0)
    duty_rate_pct: float = Field(default=0, ge=0, le=100)
    broker_fees: float = Field(default=0, ge=0)
    inland_cost: float = Field(default=0, ge=0)
    other_costs: float = Field(default=0, ge=0)
    target_sale_price_per_unit: float | None = Field(default=None, ge=0)
    incoterm: str = Field(default="EXW", max_length=10)
    supplier_verified: bool = False
    buyer_verified: bool = False
    documents_complete: bool = False
    sanctions_screened: bool = False
    product_regulatory_reviewed: bool = False


@dataclass(frozen=True)
class AgentFinding:
    agent: str
    status: str
    score: int
    summary: str
    actions: list[str]
    evidence: dict[str, Any]


@dataclass(frozen=True)
class TradeDecision:
    decision_id: str
    created_at: str
    readiness_score: int
    risk_level: str
    release_gate: str
    landed_cost_total: float
    landed_cost_per_unit: float
    gross_margin_pct: float | None
    findings: list[dict[str, Any]]
    next_best_actions: list[str]


class LandedCostAgent:
    name = "landed-cost-agent"

    def run(self, s: TradeScenario) -> AgentFinding:
        merchandise = s.quantity * s.unit_cost
        customs_value = merchandise + s.freight_cost + s.insurance_cost
        duty = customs_value * (s.duty_rate_pct / 100)
        total = customs_value + duty + s.broker_fees + s.inland_cost + s.other_costs
        per_unit = total / s.quantity
        sale_total = None
        margin_pct = None
        if s.target_sale_price_per_unit is not None:
            sale_total = s.target_sale_price_per_unit * s.quantity
            margin_pct = ((sale_total - total) / sale_total * 100) if sale_total else None
        actions: list[str] = []
        score = 100
        if s.hs_code is None:
            score -= 20
            actions.append("Classify the product and verify the HS/HTS code before relying on duty estimates.")
        if s.freight_cost == 0:
            score -= 10
            actions.append("Obtain a live freight quote for the selected lane and Incoterm.")
        if s.target_sale_price_per_unit is None:
            score -= 10
            actions.append("Set a target sale price to calculate unit economics and margin.")
        return AgentFinding(
            agent=self.name,
            status="pass" if score >= 80 else "review",
            score=max(score, 0),
            summary=f"Estimated landed cost: ${total:,.2f} (${per_unit:,.2f}/unit).",
            actions=actions,
            evidence={
                "merchandise_value": round(merchandise, 2),
                "customs_value": round(customs_value, 2),
                "estimated_duty": round(duty, 2),
                "landed_cost_total": round(total, 2),
                "landed_cost_per_unit": round(per_unit, 2),
                "estimated_gross_margin_pct": round(margin_pct, 2) if margin_pct is not None else None,
            },
        )


class ComplianceAgent:
    name = "trade-compliance-agent"

    def run(self, s: TradeScenario) -> AgentFinding:
        score = 100
        actions: list[str] = []
        blockers: list[str] = []
        if not s.sanctions_screened:
            score -= 35
            blockers.append("sanctions_screening")
            actions.append("Run denied-party, sanctions and restricted-party screening for all counterparties.")
        if not s.product_regulatory_reviewed:
            score -= 25
            blockers.append("product_regulatory_review")
            actions.append("Complete destination-country product admissibility and agency review.")
        if not s.documents_complete:
            score -= 20
            actions.append("Complete the commercial invoice, packing list and shipment-specific documentation pack.")
        if not s.hs_code:
            score -= 20
            blockers.append("classification")
            actions.append("Verify HS/HTS classification and applicable tariff treatment.")
        status = "blocked" if blockers else ("pass" if score >= 85 else "review")
        return AgentFinding(
            agent=self.name,
            status=status,
            score=max(score, 0),
            summary="Compliance release gate is fail-closed until mandatory screening and classification are complete.",
            actions=actions,
            evidence={"blockers": blockers, "incoterm": s.incoterm},
        )


class CounterpartyAgent:
    name = "counterparty-risk-agent"

    def run(self, s: TradeScenario) -> AgentFinding:
        score = 100
        actions: list[str] = []
        if not s.supplier_verified:
            score -= 35
            actions.append("Verify supplier legal identity, beneficial ownership, banking coordinates and production capability.")
        if not s.buyer_verified:
            score -= 35
            actions.append("Verify buyer identity, authority, payment capacity and delivery details.")
        status = "pass" if score >= 80 else "review"
        return AgentFinding(
            agent=self.name,
            status=status,
            score=score,
            summary="Counterparty readiness reflects supplier and buyer verification gates.",
            actions=actions,
            evidence={"supplier_verified": s.supplier_verified, "buyer_verified": s.buyer_verified},
        )


class LogisticsAgent:
    name = "logistics-agent"

    VALID_INCOTERMS = {"EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"}

    def run(self, s: TradeScenario) -> AgentFinding:
        term = s.incoterm.upper()
        actions: list[str] = []
        score = 100
        if term not in self.VALID_INCOTERMS:
            score -= 50
            actions.append("Replace the Incoterm with a recognized Incoterms rule and define the named place/port.")
        if s.freight_cost <= 0:
            score -= 20
            actions.append("Collect a carrier or forwarder quote before release.")
        if s.insurance_cost <= 0 and term in {"CIF", "CIP"}:
            score -= 20
            actions.append("Record cargo insurance cost and coverage required by the selected Incoterm.")
        return AgentFinding(
            agent=self.name,
            status="pass" if score >= 80 else "review",
            score=max(score, 0),
            summary=f"Lane readiness evaluated for {s.origin_country} → {s.destination_country} under {term}.",
            actions=actions,
            evidence={"incoterm": term, "freight_cost": s.freight_cost, "insurance_cost": s.insurance_cost},
        )


class MarginAgent:
    name = "commercial-margin-agent"

    def run(self, s: TradeScenario, landed: AgentFinding) -> AgentFinding:
        total = float(landed.evidence["landed_cost_total"])
        actions: list[str] = []
        if s.target_sale_price_per_unit is None:
            return AgentFinding(
                agent=self.name,
                status="review",
                score=50,
                summary="No target sale price supplied; profitability cannot be released.",
                actions=["Set a target sale price and minimum acceptable gross margin."],
                evidence={"landed_cost_total": total, "gross_margin_pct": None},
            )
        revenue = s.target_sale_price_per_unit * s.quantity
        margin = ((revenue - total) / revenue * 100) if revenue else -100
        score = 100
        if margin < 10:
            score = 25
            actions.append("Renegotiate buy price, freight, duty exposure or selling price; margin is below 10%.")
        elif margin < 20:
            score = 60
            actions.append("Review working-capital, FX and delay buffers before committing.")
        elif margin < 30:
            score = 85
        return AgentFinding(
            agent=self.name,
            status="pass" if score >= 80 else "review",
            score=score,
            summary=f"Estimated gross margin: {margin:.2f}% before financing, taxes, FX and exception costs.",
            actions=actions,
            evidence={"revenue": round(revenue, 2), "landed_cost_total": total, "gross_margin_pct": round(margin, 2)},
        )


class AgenticTradeOS:
    """Deterministic policy layer for trade decisions.

    LLMs can enrich research and explanations, but this release gate is intentionally
    deterministic: agents cannot bypass mandatory compliance checks.
    """

    def __init__(self) -> None:
        self.landed = LandedCostAgent()
        self.compliance = ComplianceAgent()
        self.counterparty = CounterpartyAgent()
        self.logistics = LogisticsAgent()
        self.margin = MarginAgent()

    def analyze(self, scenario: TradeScenario) -> TradeDecision:
        landed = self.landed.run(scenario)
        compliance = self.compliance.run(scenario)
        counterparty = self.counterparty.run(scenario)
        logistics = self.logistics.run(scenario)
        margin = self.margin.run(scenario, landed)
        findings = [landed, compliance, counterparty, logistics, margin]

        readiness = round(sum(f.score for f in findings) / len(findings))
        blocked = any(f.status == "blocked" for f in findings)
        reviews = sum(f.status == "review" for f in findings)
        if blocked:
            risk = RiskLevel.BLOCKED
            gate = "HOLD"
        elif readiness < 60 or reviews >= 3:
            risk = RiskLevel.HIGH
            gate = "HOLD"
        elif readiness < 80 or reviews:
            risk = RiskLevel.MEDIUM
            gate = "REVIEW"
        else:
            risk = RiskLevel.LOW
            gate = "READY"

        actions = self._dedupe(action for f in findings for action in f.actions)
        margin_pct = margin.evidence.get("gross_margin_pct")
        stamp = datetime.now(timezone.utc)
        return TradeDecision(
            decision_id=f"trade-{int(stamp.timestamp() * 1000)}",
            created_at=stamp.isoformat(),
            readiness_score=readiness,
            risk_level=risk.value,
            release_gate=gate,
            landed_cost_total=float(landed.evidence["landed_cost_total"]),
            landed_cost_per_unit=float(landed.evidence["landed_cost_per_unit"]),
            gross_margin_pct=float(margin_pct) if margin_pct is not None else None,
            findings=[asdict(f) for f in findings],
            next_best_actions=actions[:10],
        )

    @staticmethod
    def _dedupe(items: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                output.append(item)
        return output
