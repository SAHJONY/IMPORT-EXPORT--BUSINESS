from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from trade_os import AgenticTradeOS, TradeScenario


@dataclass(frozen=True)
class AgentSpec:
    name: str
    mission: str
    domain: str
    can_block_release: bool = False


AGENT_REGISTRY: tuple[AgentSpec, ...] = (
    AgentSpec("trade-orchestrator", "Coordinate the case, evidence and next-best actions.", "orchestration"),
    AgentSpec("supplier-intelligence", "Discover, compare and score suppliers without fabricating evidence.", "sourcing"),
    AgentSpec("buyer-intelligence", "Identify qualified buyers, demand signals and commercial fit.", "sales"),
    AgentSpec("classification-agent", "Recommend HS/HTS candidates and force human verification before release.", "classification", True),
    AgentSpec("trade-compliance-agent", "Evaluate sanctions, denied parties, admissibility, licenses and permits.", "compliance", True),
    AgentSpec("landed-cost-agent", "Model merchandise, freight, duty, insurance, broker and inland costs.", "finance"),
    AgentSpec("commercial-margin-agent", "Evaluate gross margin, working-capital buffer and downside cases.", "finance"),
    AgentSpec("counterparty-risk-agent", "Verify legal identity, beneficial ownership, bank details and risk evidence.", "risk", True),
    AgentSpec("logistics-agent", "Plan lanes, Incoterms, carriers, milestones and exception handling.", "logistics"),
    AgentSpec("document-agent", "Build and validate invoice, packing list, certificates and document packs.", "documents", True),
    AgentSpec("shipment-watch-agent", "Monitor ETA, temperature, customs and operational exceptions.", "operations"),
    AgentSpec("treasury-agent", "Model FX, payment terms, cash conversion and financing exposure.", "treasury"),
    AgentSpec("executive-copilot", "Summarize portfolio risk, margin, blockers and recommended owner decisions.", "executive"),
)


class AgenticControlPlane:
    """Evidence-first control plane for global trade automation.

    Generative AI may research, summarize and propose. Deterministic policy owns the
    release gate. Any blocking agent can force HOLD; no LLM can override that gate.
    """

    def __init__(self, policy: AgenticTradeOS | None = None) -> None:
        self.policy = policy or AgenticTradeOS()

    def registry(self) -> list[dict[str, Any]]:
        return [asdict(agent) for agent in AGENT_REGISTRY]

    def evaluate(self, scenario: TradeScenario) -> dict[str, Any]:
        decision = self.policy.analyze(scenario)
        return {
            "control_plane_version": "2.0",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "decision": asdict(decision),
            "governance": {
                "release_authority": "deterministic-policy",
                "ai_override_allowed": False,
                "mandatory_human_review": decision.release_gate != "READY",
                "evidence_required": True,
            },
        }

    def next_agent_queue(self, scenario: TradeScenario) -> list[dict[str, str]]:
        decision = self.policy.analyze(scenario)
        actions = decision.next_best_actions
        queue: list[dict[str, str]] = []
        mapping: list[tuple[str, str]] = [
            ("sanctions", "trade-compliance-agent"),
            ("admissibility", "trade-compliance-agent"),
            ("HS/HTS", "classification-agent"),
            ("classification", "classification-agent"),
            ("supplier", "supplier-intelligence"),
            ("buyer", "buyer-intelligence"),
            ("freight", "logistics-agent"),
            ("insurance", "logistics-agent"),
            ("document", "document-agent"),
            ("margin", "commercial-margin-agent"),
            ("price", "commercial-margin-agent"),
        ]
        for action in actions:
            assigned = "trade-orchestrator"
            for token, agent in mapping:
                if token.lower() in action.lower():
                    assigned = agent
                    break
            queue.append({"agent": assigned, "task": action})
        return queue


control_plane = AgenticControlPlane()
