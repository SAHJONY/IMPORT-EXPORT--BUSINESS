"""Tests for Sofia's three self-systems: improvement, healing, selling.

All tests run offline with injected fakes — no network, no backend, no
subprocess execution (recovery dispatch is dry-run / monkeypatched).
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import sofia_self_healing as healing
import sofia_self_improvement as improvement
import sofia_self_selling as selling


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeBackend:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.inserted = []

    async def select(self, table, *, params=None):
        out = []
        for row in self.rows:
            if params and "source_type" in params:
                expr = params["source_type"]
                if expr.startswith("eq.") and row.get("source_type") != expr[3:]:
                    continue
            out.append(row)
        return out

    async def insert(self, table, row):
        self.inserted.append((table, row))
        return row


def _lesson_row(source_type, lesson):
    return {
        "source_type": source_type,
        "event_type": "learning",
        "summary": lesson,
        "payload": {"lesson": lesson},
    }


@pytest.fixture(autouse=True)
def _clean_state():
    healing.DECISION_LOG.clear()
    selling.clear_draft_queue()
    yield
    healing.DECISION_LOG.clear()
    selling.clear_draft_queue()


def _utc_now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. Self-improvement
# ---------------------------------------------------------------------------
def test_sanitize_lesson_redacts_secrets():
    dirty = (
        "Sofia must use api_key=sk-abcdef1234567890 and Bearer nvapi-xyz987654321 "
        "password: hunter2 call 12816628581 tomorrow"
    )
    clean = improvement.sanitize_lesson(dirty)
    assert "sk-abcdef1234567890" not in clean
    assert "nvapi-xyz987654321" not in clean
    assert "hunter2" not in clean
    assert "12816628581" not in clean
    assert "[redacted]" in clean
    # business content survives
    assert "Sofia" in clean and "tomorrow" in clean


def test_is_near_duplicate():
    existing = ["Never mention PRIMO; it is a retired initiative."]
    assert improvement.is_near_duplicate(
        "never mention primo, it is a retired initiative!", existing
    )
    assert not improvement.is_near_duplicate(
        "Always greet the customer by name in Spanish.", existing
    )


def test_record_correction_rejects_near_duplicate():
    backend = FakeBackend()
    existing = ["Never mention PRIMO; it is a retired initiative."]
    result = asyncio.run(
        improvement.record_correction(
            lesson_text="never mention primo — retired initiative.",
            context="whatsapp self-chat",
            backend=backend,
            existing_lessons=existing,
        )
    )
    assert result["stored"] is False
    assert result["reason"] == "near_duplicate_lesson"
    assert backend.inserted == []


def test_record_correction_stores_distinct_lesson():
    backend = FakeBackend()
    result = asyncio.run(
        improvement.record_correction(
            lesson_text="Address Juan as Chairman and owner of SAHJONY LLC.",
            context="identity fix 2026-09-16",
            backend=backend,
            existing_lessons=[],
        )
    )
    assert result["stored"] is True
    assert result["lesson_id"]
    table, row = backend.inserted[0]
    assert table == "business_events"
    assert row["source_type"] == "sofia_self_improvement"
    assert row["event_type"] == "learning"
    assert "Chairman and owner" in row["payload"]["lesson"]


def test_get_active_lessons_merges_sources_and_dedups():
    backend = FakeBackend(
        rows=[
            _lesson_row("sofia_self_improvement", "Lesson A from corrections."),
            _lesson_row("sofia_adaptive_intelligence", "Lesson A from corrections."),
            _lesson_row("sofia_adaptive_intelligence", "Lesson B from adaptive."),
        ]
    )
    lessons = asyncio.run(improvement.get_active_lessons(limit=10, backend=backend))
    assert len(lessons) == 2
    assert any("Lesson A" in l for l in lessons)
    assert any("Lesson B" in l for l in lessons)


def test_review_recent_conversations_detects_owner_correction():
    conversations = [
        {"role": "owner", "text": "Te dije que nunca menciones PRIMO.", "conversation_id": "c1"},
        {"role": "sofia", "text": "Entendido.", "conversation_id": "c1"},
        {"role": "owner", "text": "Gracias por la ayuda.", "conversation_id": "c2"},
    ]
    candidates = improvement.review_recent_conversations(conversations)
    assert len(candidates) == 1
    assert candidates[0]["signal"] == "owner_correction"
    assert candidates[0]["auto_stored"] is False


def test_review_recent_conversations_none_is_empty():
    assert improvement.review_recent_conversations(None) == []
    assert improvement.review_recent_conversations([]) == []


# ---------------------------------------------------------------------------
# 2. Self-healing
# ---------------------------------------------------------------------------
def _healthy_snapshot():
    return {
        "ok": True,
        "send_ready": True,
        "webhook_ready": True,
        "ai_auto_reply_enabled": True,
        "gateway_fresh": True,
    }


def _fresh_state():
    return {
        "last_recovery_attempt": None,
        "failed_recoveries": 0,
        "pending_recovery": False,
        "last_decision": None,
    }


def test_evaluate_health_healthy():
    decision = healing.evaluate_health(_healthy_snapshot(), state=_fresh_state(), now=_utc_now())
    assert decision["state"] == "healthy"
    assert decision["recommended_action"] is None
    assert decision["escalate_to_owner"] is False


def test_evaluate_health_degraded_recommends_safe_clean():
    snapshot = _healthy_snapshot()
    snapshot["send_ready"] = False
    decision = healing.evaluate_health(snapshot, state=_fresh_state(), now=_utc_now())
    assert decision["state"] == "degraded"
    assert "whatsapp_send_not_ready" in decision["reasons"]
    action = decision["recommended_action"]
    assert action["type"] == "dispatch_workflow"
    assert action["workflow"] == "Hostinger Hermes Safe Clean"
    assert "gh workflow run" in action["via"]


def test_evaluate_health_cooldown_blocks_retrigger():
    now = _utc_now()
    state = _fresh_state()
    state["last_recovery_attempt"] = (now - timedelta(minutes=10)).isoformat()
    snapshot = _healthy_snapshot()
    snapshot["ai_auto_reply_enabled"] = False
    decision = healing.evaluate_health(snapshot, state=state, now=now)
    assert decision["state"] == "degraded"
    assert decision["recommended_action"]["type"] == "wait"
    assert "recovery_cooldown_active" in decision["reasons"]


def test_evaluate_health_max_attempts_escalates_critical():
    now = _utc_now()
    state = _fresh_state()
    snapshot = _healthy_snapshot()
    snapshot["ok"] = False
    # Simulate 3 failed recoveries: dispatch, wait out cooldown, still broken.
    for _ in range(3):
        d = healing.evaluate_health(snapshot, state=state, now=now)
        assert d["state"] == "degraded"
        # a recovery was dispatched and failed: mark attempted, then re-evaluate
        state["last_recovery_attempt"] = now.isoformat()
        state["pending_recovery"] = True
        now = now + timedelta(minutes=31)
        d2 = healing.evaluate_health(snapshot, state=state, now=now)
    assert d2["state"] == "critical"
    assert d2["escalate_to_owner"] is True
    assert d2["recommended_action"]["type"] == "escalate"
    # No further auto-recovery after escalation
    d3 = healing.evaluate_health(snapshot, state=state, now=now + timedelta(hours=2))
    assert d3["state"] == "critical"
    assert d3["recommended_action"]["type"] == "escalate"


def test_evaluate_health_unreachable_snapshot_needs_manual_check():
    decision = healing.evaluate_health(None, state=_fresh_state(), now=_utc_now())
    assert decision["state"] == "degraded"
    assert decision["recommended_action"]["type"] == "manual_check"
    assert decision["escalate_to_owner"] is False


def test_trigger_recovery_dry_run_does_not_execute(monkeypatch):
    calls = []
    monkeypatch.setattr(healing.subprocess, "run", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("must not execute")))
    result = healing.trigger_recovery(dry_run=True, state=_fresh_state())
    assert result["dry_run"] is True
    assert result["dispatched"] is False
    assert result["command"][:3] == ["gh", "workflow", "run"]
    assert "Hostinger Hermes Safe Clean" in result["command"]
    assert calls == []


def test_trigger_recovery_real_run_updates_state(monkeypatch):
    class Proc:
        returncode = 0
        stdout = "run url"
        stderr = ""

    monkeypatch.setattr(healing.subprocess, "run", lambda *a, **k: Proc())
    state = _fresh_state()
    result = healing.trigger_recovery(dry_run=False, state=state, now=_utc_now())
    assert result["dispatched"] is True
    assert state["pending_recovery"] is True
    assert state["last_recovery_attempt"] is not None


def test_note_recovery_outcome_resets_and_counts():
    state = _fresh_state()
    out = healing.note_recovery_outcome(True, state=state)
    assert out["failed_recoveries"] == 0 and out["escalated"] is False
    for _ in range(3):
        out = healing.note_recovery_outcome(False, state=state)
    assert out["failed_recoveries"] == 3
    assert out["escalated"] is True


def test_every_decision_is_logged():
    healing.DECISION_LOG.clear()
    healing.evaluate_health(_healthy_snapshot(), state=_fresh_state(), now=_utc_now())
    healing.evaluate_health(None, state=_fresh_state(), now=_utc_now())
    log = healing.get_decision_log()
    assert len(log) == 2
    assert all("decided_at" in entry and "state" in entry for entry in log)


# ---------------------------------------------------------------------------
# 3. Self-selling: scanner + draft queue
# ---------------------------------------------------------------------------
def _lead(**overrides):
    base = {
        "lead_id": "lead_1",
        "name": "Mariela",
        "phone": "+53 5 123 4567",
        "status": "contacted",
        "opted_out": False,
        "last_contact_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        "business_track": "my_cuba_cash",
        "product_interest": "pago a proveedor",
    }
    base.update(overrides)
    return base


def test_scan_opportunities_tags_tracks_and_excludes_ambiguous():
    leads = [
        _lead(lead_id="a", business_track="my_cuba_cash"),
        _lead(lead_id="b", business_track="import_export", utm_campaign="cuba_import_export_group"),
        _lead(lead_id="c", business_track="mystery"),  # ambiguous -> excluded
        _lead(lead_id="d", business_track=None),  # ambiguous -> excluded
    ]
    opps = selling.scan_opportunities(crm_source=lambda: leads)
    by_id = {o["lead_id"]: o for o in opps}
    assert by_id["a"]["business_track"] == "my_cuba_cash"
    assert by_id["b"]["business_track"] == "import_export"
    assert "c" not in by_id and "d" not in by_id
    assert by_id["a"]["source_table"] == "cuba_partner_accounts"
    assert by_id["b"]["source_table"] == "trade_rfq_intakes"
    # phone masked in opportunity records
    assert "51234567" not in by_id["a"]["phone_masked"]


def test_scan_opportunities_warmth_and_exclusions():
    now = datetime.now(timezone.utc)
    leads = [
        _lead(lead_id="warm", last_contact_at=(now - timedelta(days=10)).isoformat()),
        _lead(lead_id="dormant", last_contact_at=(now - timedelta(days=45)).isoformat()),
        _lead(lead_id="recent", last_contact_at=(now - timedelta(days=1)).isoformat()),
        _lead(lead_id="optout", opted_out=True),
        _lead(lead_id="closed", status="converted"),
    ]
    opps = selling.scan_opportunities(crm_source=lambda: leads, now=now)
    by_id = {o["lead_id"]: o for o in opps}
    assert by_id["warm"]["warmth"] == "warm"
    assert by_id["dormant"]["warmth"] == "dormant"
    assert "recent" not in by_id
    assert "optout" not in by_id
    assert "closed" not in by_id


def test_scan_opportunities_no_source_returns_empty():
    assert selling.scan_opportunities() == []


def test_draft_followup_is_spanish_first_and_track_tagged():
    opp = selling.scan_opportunities(crm_source=lambda: [_lead()])[0]
    draft = selling.draft_followup(opp)
    assert draft["business_track"] == "my_cuba_cash"
    assert draft["status"] == "pending"
    assert draft["language"] == "es"
    assert draft["text"].startswith("Hola")
    assert "Sofia Smith" in draft["text"]
    assert "SAHJONY LLC" in draft["text"]
    # no invented commercial claims
    assert "%" not in draft["text"]


def test_draft_followup_rejects_english_cuba_draft():
    opp = selling.scan_opportunities(crm_source=lambda: [_lead()])[0]
    with pytest.raises(ValueError, match="Spanish-first"):
        selling.draft_followup(opp, language="en")


def test_draft_followup_rejects_missing_track():
    with pytest.raises(ValueError, match="exactly one business track"):
        selling.draft_followup({"lead_id": "x"})


def test_draft_primo_ban():
    opp = selling.scan_opportunities(
        crm_source=lambda: [_lead(product_interest="PRIMO launch")]
    )[0]
    with pytest.raises(ValueError, match="identity compliance"):
        selling.draft_followup(opp)


def test_draft_queue_approve_reject_flow():
    opp = selling.scan_opportunities(crm_source=lambda: [_lead(lead_id="q1")])[0]
    draft = selling.draft_followup(opp)
    draft_id = selling.queue_draft(draft)
    assert selling.get_draft(draft_id)["status"] == "pending"
    assert len(selling.list_pending_drafts()) == 1
    assert len(selling.list_pending_drafts(track="my_cuba_cash")) == 1
    assert selling.list_pending_drafts(track="import_export") == []

    approved = selling.approve_draft(draft_id, approver="juan")
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "juan"
    assert selling.list_pending_drafts() == []  # no longer pending

    opp2 = selling.scan_opportunities(crm_source=lambda: [_lead(lead_id="q2")])[0]
    draft2 = selling.draft_followup(opp2)
    did2 = selling.queue_draft(draft2)
    rejected = selling.reject_draft(did2, reason="wrong product")
    assert rejected["status"] == "rejected"
    assert rejected["rejected_reason"] == "wrong product"

    # cannot approve twice / unknown draft
    with pytest.raises(ValueError):
        selling.approve_draft(draft_id, approver="juan")
    with pytest.raises(KeyError):
        selling.approve_draft("draft_missing", approver="juan")


def test_queue_draft_rejects_non_pending_or_untracked():
    with pytest.raises(ValueError):
        selling.queue_draft({"draft_id": "x", "status": "approved", "business_track": "my_cuba_cash"})
    with pytest.raises(ValueError):
        selling.queue_draft({"draft_id": "y", "status": "pending", "business_track": "unknown"})


def test_no_send_function_exists():
    assert not hasattr(selling, "send_draft")
    assert not hasattr(selling, "send_whatsapp")


def test_identity_constants():
    assert improvement.SOFIA_IDENTITY == "Sofia Smith, Executive Manager of SAHJONY LLC"
    assert improvement.OWNER_IDENTITY == "Juan Gonzalez, Chairman and owner of SAHJONY LLC"
    assert "PRIMO" in improvement.RETIRED_INITIATIVES
