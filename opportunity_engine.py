from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agentic_control_plane import control_plane
from trade_os import TradeScenario


@dataclass(frozen=True)
class OpportunityScore:
    rank_score: float
    decision: str
    readiness_score: int
    gross_margin_pct: float | None
    release_gate: str
    risk_level: str
    rationale: list[str]
    scenario: dict[str, Any]


class GlobalTradeOpportunityEngine:
    """Ranks candidate import/export opportunities without bypassing release gates.

    Ranking is deterministic and evidence-first. A high commercial score can never
    convert a HOLD/REVIEW compliance outcome into READY.
    """

    def score(self, scenario: TradeScenario) -> OpportunityScore:
        evaluation = control_plane.evaluate(scenario)
        decision = evaluation["decision"]
        readiness = int(decision["readiness_score"])
        margin = decision.get("gross_margin_pct")
        gate = str(decision["release_gate"])
        risk = str(decision["risk_level"])

        margin_component = 0.0
        if margin is not None:
            margin_component = max(-25.0, min(float(margin), 60.0))

        readiness_component = readiness * 0.55
        margin_component *= 0.75

        gate_penalty = {"READY": 0.0, "REVIEW": 22.0, "HOLD": 65.0}.get(gate, 65.0)
        risk_penalty = {"low": 0.0, "medium": 8.0, "high": 22.0, "blocked": 45.0}.get(risk, 25.0)

        raw = readiness_component + margin_component - gate_penalty - risk_penalty
        rank_score = round(max(0.0, min(raw, 100.0)), 2)

        rationale = [
            f"Readiness contributes {readiness_component:.1f} points.",
            f"Margin contributes {margin_component:.1f} points.",
        ]
        if gate_penalty:
            rationale.append(f"Release gate {gate} subtracts {gate_penalty:.0f} points.")
        if risk_penalty:
            rationale.append(f"Risk level {risk} subtracts {risk_penalty:.0f} points.")

        if gate == "READY" and rank_score >= 70:
            commercial_decision = "PRIORITIZE"
        elif gate == "READY":
            commercial_decision = "WATCH"
        elif gate == "REVIEW":
            commercial_decision = "REVIEW"
        else:
            commercial_decision = "HOLD"

        return OpportunityScore(
            rank_score=rank_score,
            decision=commercial_decision,
            readiness_score=readiness,
            gross_margin_pct=float(margin) if margin is not None else None,
            release_gate=gate,
            risk_level=risk,
            rationale=rationale,
            scenario=scenario.model_dump(mode="json"),
        )

    def rank(self, scenarios: list[TradeScenario]) -> list[dict[str, Any]]:
        scored = [self.score(scenario) for scenario in scenarios]
        scored.sort(key=lambda item: item.rank_score, reverse=True)
        return [
            {"rank": index, **asdict(item)}
            for index, item in enumerate(scored, start=1)
        ]


opportunity_engine = GlobalTradeOpportunityEngine()
