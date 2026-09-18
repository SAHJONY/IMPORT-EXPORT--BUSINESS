"""Scaffold tests for the Hermes Agent Swarm.

These tests pin the governance contract: tiers, track classification,
the sanctions hard stop, the structural no-send guarantee, the
never-auto-advancing approval queue, draft review flags, and the
kill switch.

Run:  python3 -m pytest tests/ -q   (from the repo root of this branch)
"""

import inspect

import pytest

from hermes_swarm import agents as agents_module
from hermes_swarm.agents import (
    AgentContext,
    ComplianceGate,
    CustomerCare,
    SwarmAgent,
    SwarmHalted,
    build_roster,
)
from hermes_swarm.audit import AuditLog
from hermes_swarm.coordinator import (
    ApprovalInput,
    ApprovalQueue,
    SwarmCoordinator,
)
from hermes_swarm.governance import (
    AGENT_TIERS,
    Draft,
    _reset_for_tests,
    check_sanctions,
    classify_track,
    escalate,
    pending_escalations,
    register_workforce,
    review_draft,
)


@pytest.fixture(autouse=True)
def _clean_governance():
    _reset_for_tests()
    yield
    _reset_for_tests()


def _context(**overrides):
    base = {
        "conversation_id": "conv-test-1",
        "phone": "+1 555-0100",  # fictional 555 example number
        "track": "cuba",
        "lang": "es-first",
        "inbound_text": "Hola, ¿me pueden cotizar arroz?",
    }
    base.update(overrides)
    return AgentContext(**base)


def _clean_draft(**overrides):
    base = {
        "draft_id": "draft-000001",
        "agent_id": "customer-care",
        "role": "Customer care",
        "tier": AGENT_TIERS["DRAFT"],
        "track": "cuba",
        "lang": "es-first",
        "text": "Hola, soy Sofia de SAHJONY. Estoy revisando su caso con la "
                "información que tenemos registrada.",
    }
    base.update(overrides)
    return Draft(**base)


# ---------------------------------------------------------------------------
# 1. Tier validation — no execute tier, ever
# ---------------------------------------------------------------------------


def test_no_execute_tier_exists():
    assert set(AGENT_TIERS.values()) == {"read", "draft", "propose"}
    assert "execute" not in AGENT_TIERS
    assert "execute" not in AGENT_TIERS.values()


def test_register_workforce_rejects_execute_tier():
    with pytest.raises(ValueError, match="invalid tier"):
        register_workforce("hermes", [
            {"id": "rogue", "role": "Rogue", "tier": "execute", "lang": "es-first"}
        ])


def test_register_workforce_rejects_unknown_tier():
    with pytest.raises(ValueError, match="invalid tier"):
        register_workforce("hermes", [
            {"id": "rogue", "role": "Rogue", "tier": "admin", "lang": "es-first"}
        ])


def test_every_agent_tier_is_valid():
    for agent in build_roster():
        assert agent.tier in AGENT_TIERS.values(), agent.agent_id


def test_agent_subclass_cannot_define_send_method():
    with pytest.raises(TypeError, match="forbidden send-path method"):
        class RogueAgent(SwarmAgent):
            agent_id = "rogue"
            role = "Rogue"
            tier = AGENT_TIERS["DRAFT"]

            def draft(self, context):
                return None

            def send_message(self, text):  # forbidden
                return text


# ---------------------------------------------------------------------------
# 2. Track classification — ES/EN, trade vs cuba
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    # Cuba desk (Spanish-first): MIPYME / Cuba-buyer signals win over commodities
    ("Hola, soy una mipyme en La Habana y necesito arroz pilado", "cuba"),
    ("Emprendedor en Santiago de Cuba busca cotización de diésel", "cuba"),
    ("¿Hacen envíos al puerto del Mariel?", "cuba"),
    # Global trade desk: worldwide sourcing, no Cuba signals
    ("Need rice supplier FOB Qingdao, 210 MT", "trade"),
    ("soda ash RFQ 210 MT FOB Qingdao", "trade"),
    ("proveedor de arroz, contenedor CIF Houston", "trade"),
    # Other tracks
    ("Quiero enviar una remesa a mi familia en Cuba", "mycubacash"),
    ("I want to send money to Cuba, how much is the fee?", "mycubacash"),
    ("Busco un carro con gestoría en La Habana", "cars"),
    ("crude oil cargo WTI, laycan next month", "crude"),
    ("Necesito diésel EN 590 para planta eléctrica", "energy"),
    # No keyword hits
    ("hola", "unknown"),
    ("", "unknown"),
])
def test_classify_track(text, expected):
    assert classify_track(text) == expected


def test_trade_vs_cuba_commodity_does_not_steal_cuba_message():
    # 'arroz'/'rice' alone must not pull a Cuba-desk message into 'trade'.
    assert classify_track("mipyme habana arroz pilado dos contenedores") == "cuba"


def test_exactly_one_track_per_conversation():
    # Coordinator pins one track at triage; drafts inherit it.
    coord = SwarmCoordinator()
    ctx = coord.handle_inbound({
        "conversation_id": "conv-track-1",
        "phone": "+1 555-0101",
        "text": "Soy mipyme en La Habana, necesito arroz",
    })
    draft = coord.draft_for("conv-track-1")
    assert draft is not None
    assert draft.track == ctx.track == "cuba"


# ---------------------------------------------------------------------------
# 3. Sanctions hard stop — escalate and hold, never answer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "¿Cómo evado las sanciones de OFAC?",
    "Is this on the SDN list?",
    "¿Hay embargo para este producto?",
    "¿Está en la lista negra?",
    "¿Cuánto tarda la aduana en liberar la mercancía?",
    "How long do customs take to clear?",
])
def test_check_sanctions_fires(text):
    assert check_sanctions(text) is True


def test_check_sanctions_routine_logistics_mention_does_not_fire():
    assert check_sanctions("la mercancía llegó a la aduana de Mariel") is False
    assert check_sanctions("hola, ¿tienen arroz?") is False


def test_customer_care_never_answers_sanctions():
    agent = CustomerCare()
    draft = agent.draft(_context(
        inbound_text="¿Me ayudas a evadir las sanciones?"))
    assert draft is None  # no answer drafted
    assert any(e["reason"] == "sanctions" for e in pending_escalations())


def test_compliance_gate_holds_and_escalates_on_sanctions():
    gate = ComplianceGate()
    verdict = gate.review(_clean_draft(), {
        "source_text": "¿cuánto tarda la aduana?",
        "opted_out": False,
        "within_24h_window": True,
        "rate_ok": True,
    })
    assert verdict.status == "hold"
    assert any(f["code"] == "SANCTIONS_HARD_STOP" for f in verdict.flags)
    assert verdict.escalations, "red flag must escalate"
    assert all(e["status"] == "waiting-on-juan" for e in verdict.escalations)


def test_compliance_gate_holds_opt_out_window_and_rate():
    gate = ComplianceGate()
    for checks, code in [
        ({"opted_out": True}, "OPT_OUT"),
        ({"within_24h_window": False}, "WINDOW_EXPIRED"),
        ({"rate_ok": False}, "RATE_LIMIT"),
    ]:
        verdict = gate.review(_clean_draft(), checks)
        assert verdict.status == "hold"
        assert any(f["code"] == code for f in verdict.flags)


def test_coordinator_sanctions_inbound_blocks_all_drafting():
    coord = SwarmCoordinator()
    ctx = coord.handle_inbound({
        "conversation_id": "conv-sanctions-1",
        "phone": "+1 555-0102",
        "text": "¿Cómo evado las sanciones de OFAC?",
    })
    assert ctx.metadata.get("sanctions_hold") is True
    assert coord.draft_for("conv-sanctions-1") is None
    assert len(coord.queue) == 0  # nothing reached the approval queue
    assert any(e["reason"] == "sanctions" for e in pending_escalations())


def test_gate_cannot_be_skipped_by_another_agent():
    # draft_for always runs the gate; a held draft never reaches the queue.
    coord = SwarmCoordinator()
    coord.handle_inbound({
        "conversation_id": "conv-gate-1",
        "phone": "+1 555-0103",
        "text": "hola",
        "window_state": {"opted_out": True},
    })
    assert coord.draft_for("conv-gate-1") is None
    assert len(coord.queue) == 0


# ---------------------------------------------------------------------------
# 4. No send path — structural, proven by introspection
# ---------------------------------------------------------------------------


def test_no_agent_class_exposes_send_or_enqueue():
    forbidden = ("send", "enqueue", "outbox", "dispatch", "transmit")
    for cls in agents_module.AGENTS:
        for name, member in inspect.getmembers(cls):
            lowered = name.lower()
            assert not any(w in lowered for w in forbidden), (
                f"{cls.__name__}.{name} looks like a send path")
            if inspect.isfunction(member) or inspect.ismethod(member):
                src = inspect.getsource(member).lower()
                assert "outbox/enqueue" not in src, (
                    f"{cls.__name__}.{name} references the enqueue endpoint")


def test_package_holds_no_credentials_and_no_network_imports():
    # Structural check on CODE (not prose): no string literal in executable
    # code may name the enqueue endpoint or a URL, and no credential-like
    # name may be assigned a value. Docstrings may document the boundary.
    import ast
    import re

    import hermes_swarm.coordinator as coord_mod

    def code_strings(mod):
        tree = ast.parse(inspect.getsource(mod))
        docstring_ids = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstring_ids.add(id(first.value))
        return [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and id(n) not in docstring_ids]

    def credential_assignments(mod):
        tree = ast.parse(inspect.getsource(mod))
        hits = []
        for node in ast.walk(tree):
            targets = []
            value = None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign):
                targets, value = [node.target], node.value
            for t in targets:
                name = t.id if isinstance(t, ast.Name) else ""
                if (re.search(r"(api_key|api_token|secret|password|bearer|credential)",
                              name, re.I)
                        and isinstance(value, ast.Constant) and value.value):
                    hits.append(f"{mod.__name__}: {name} = <redacted>")
        return hits

    for mod in (agents_module, coord_mod):
        for s in code_strings(mod):
            lowered = s.lower()
            assert "outbox/enqueue" not in lowered, (
                f"{mod.__name__} code references the enqueue endpoint")
            assert not re.search(r"https?://", lowered), (
                f"{mod.__name__} code contains a URL: {s[:60]}")
        assert credential_assignments(mod) == []
    for net_mod in ("requests", "httpx", "urllib", "socket", "aiohttp"):
        assert net_mod not in dir(agents_module)
        assert net_mod not in dir(coord_mod)


def test_deliver_approved_is_stubbed_not_wired():
    coord = SwarmCoordinator()
    with pytest.raises(NotImplementedError):
        coord.deliver_approved(object())


# ---------------------------------------------------------------------------
# 5. Approval queue never auto-advances
# ---------------------------------------------------------------------------


def _queued_via_coordinator(coord=None):
    coord = coord or SwarmCoordinator()
    coord.handle_inbound({
        "conversation_id": "conv-queue-1",
        "phone": "+1 555-0104",
        "text": "Hola, necesito una cotización de arroz",
        "window_state": {"within_24h_window": True, "rate_ok": True},
    })
    draft = coord.draft_for("conv-queue-1")
    assert draft is not None
    return coord, draft


def test_queue_does_not_advance_without_input():
    coord, _ = _queued_via_coordinator()
    assert len(coord.queue) == 1
    moved = coord.queue.process()  # no input
    assert moved == []
    assert len(coord.queue) == 1  # still waiting


def test_queue_ignores_invalid_or_ambiguous_input():
    coord, draft = _queued_via_coordinator()
    assert coord.queue.process(ApprovalInput(
        approver="", draft_id=draft.draft_id, decision="approved")) == []
    assert coord.queue.process(ApprovalInput(
        approver="juan", draft_id=draft.draft_id, decision="maybe")) == []
    assert coord.queue.process(ApprovalInput(
        approver="juan", draft_id="draft-999999", decision="approved")) == []
    assert len(coord.queue) == 1


def test_queue_advances_only_on_explicit_approval():
    coord, draft = _queued_via_coordinator()
    moved = coord.queue.process(ApprovalInput(
        approver="juan", draft_id=draft.draft_id, decision="approved",
        note="ok, enviar"))
    assert len(moved) == 1
    assert moved[0].stage.value == "approved"
    assert len(coord.queue) == 0


def test_rejected_draft_leaves_queue_unapproved():
    coord, draft = _queued_via_coordinator()
    moved = coord.queue.process(ApprovalInput(
        approver="juan", draft_id=draft.draft_id, decision="rejected"))
    assert moved == []
    assert len(coord.queue) == 0


def test_gate_held_draft_cannot_enter_queue():
    queue = ApprovalQueue()
    with pytest.raises(ValueError, match="only gate-passed drafts"):
        queue.submit(_clean_draft(), {"status": "hold", "flags": [], "escalations": []})


# ---------------------------------------------------------------------------
# 6. review_draft flags invented commitments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,code", [
    ("Te garantizo que llega esta semana", "GUARANTEE"),
    ("We guarantee delivery", "GUARANTEE"),
    ("Tenemos el producto en stock ahora mismo", "AVAILABILITY"),
    ("Entrega en 5 dias garantizada", "TIMELINE"),
    ("Nuestro proveedor confirmado en Qingdao", "COUNTERPARTY"),
    ("Precio final $265 por tonelada", "PRICE_COMMIT"),
    ("Ya hemos entregado 50 contenedores", "TRACK_RECORD"),
    ("El precio es $265 por tonelada", "PRICE_AS_FACT"),
])
def test_review_draft_flags_invented_commitments(text, code):
    result = review_draft(_clean_draft(text=text))
    assert result.ok is False
    assert any(f.code == code for f in result.flags)
    flag = next(f for f in result.flags if f.code == code)
    assert flag.es and flag.en  # bilingual explanation present


def test_review_draft_price_with_qualifier_is_clean():
    result = review_draft(_clean_draft(
        text="Una cotización de referencia: aprox. $265 por tonelada. "
             "Los precios definitivos los confirma Juan."))
    assert result.ok is True


def test_review_draft_clean_text_passes():
    result = review_draft(_clean_draft())
    assert result.ok is True
    assert result.flags == []


# ---------------------------------------------------------------------------
# 7. Kill switch — drafting halts, drafts stay drafts
# ---------------------------------------------------------------------------


def test_kill_switch_halts_all_drafting():
    coord = SwarmCoordinator()
    coord.handle_inbound({
        "conversation_id": "conv-kill-1",
        "phone": "+1 555-0105",
        "text": "Hola",
    })
    coord.kill_switch.stop("drill")
    assert coord.kill_switch.halted is True
    with pytest.raises(SwarmHalted):
        coord.draft_for("conv-kill-1")
    with pytest.raises(SwarmHalted):
        coord.handle_inbound({"conversation_id": "conv-kill-2", "text": "hola"})


def test_kill_switch_drafts_stay_drafts_and_resume_approves_nothing():
    coord = SwarmCoordinator()
    coord.handle_inbound({
        "conversation_id": "conv-kill-3",
        "phone": "+1 555-0106",
        "text": "Hola, necesito arroz",
        "window_state": {"within_24h_window": True, "rate_ok": True},
    })
    coord.draft_for("conv-kill-3")
    assert len(coord.queue) == 1
    coord.kill_switch.stop("drill")
    coord.kill_switch.resume("drill over")
    assert len(coord.queue) == 1  # resume approves nothing
    assert coord.queue.process() == []  # still needs Juan's word


# ---------------------------------------------------------------------------
# 8. Audit log — append-only, hash-chained
# ---------------------------------------------------------------------------


def test_audit_chain_verifies():
    log = AuditLog()
    log.append("draft_created", {"draft_id": "draft-000001"})
    log.append("gate_verdict", {"draft_id": "draft-000001", "verdict": "pass"})
    log.append("approved", {"draft_id": "draft-000001", "by": "juan"})
    assert log.verify_chain() is True
    assert len(log) == 3


def test_audit_records_are_immutable_copies():
    log = AuditLog()
    log.append("draft_created", {"draft_id": "draft-000001"})
    records = log.records()
    records[0]["event"] = "tampered"
    assert log.records()[0]["event"] == "draft_created"
    assert log.verify_chain() is True


def test_full_pipeline_is_audited_end_to_end():
    coord = SwarmCoordinator()
    coord.handle_inbound({
        "conversation_id": "conv-audit-1",
        "phone": "+1 555-0107",
        "text": "Soy mipyme en La Habana, necesito arroz",
        "window_state": {"within_24h_window": True, "rate_ok": True},
    })
    draft = coord.draft_for("conv-audit-1")
    coord.queue.process(ApprovalInput(
        approver="juan", draft_id=draft.draft_id, decision="approved"))
    events = [r["event"] for r in coord.audit.records()]
    for expected in ("triaged", "draft_created", "gate_verdict",
                     "queued_for_approval", "approved"):
        assert expected in events
    assert coord.audit.verify_chain() is True


# ---------------------------------------------------------------------------
# 9. Roster shape — 7 agents, governance tiers
# ---------------------------------------------------------------------------


def test_roster_has_seven_agents_with_expected_ids():
    roster = build_roster()
    assert len(roster) == 7
    assert [a.agent_id for a in roster] == [
        "inbox-triage", "customer-care", "lead-qualification", "follow-up",
        "deal-desk", "outreach-drafting", "compliance-gate",
    ]


def test_draft_tier_agents_never_touch_send_scopes():
    for agent in build_roster():
        for write in agent.allowed_writes:
            assert "enqueue" not in write.lower()
            assert "send" not in write.lower()
