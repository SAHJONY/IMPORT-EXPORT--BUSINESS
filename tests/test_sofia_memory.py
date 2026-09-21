"""Unit tests for sofia_memory.py — pure functions + recall/consolidate logic
against a stubbed backend. No network calls.

The stub replaces sofia_memory.get_backend (and the LLM/embedding helpers) so
tests run fully offline.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

sys.path.insert(0, ".")

import sofia_memory


# ---------------------------------------------------------------------------
# Stub backend
# ---------------------------------------------------------------------------

class StubBackend:
    def __init__(self):
        self.tables: dict[str, dict[str, dict[str, Any]]] = {}
        self.calls: list[tuple[str, str, Any]] = []

    async def select(self, table: str, *, params=None) -> list[dict[str, Any]]:
        self.calls.append(("select", table, dict(params or {})))
        rows = list(self.tables.get(table, {}).values())
        p = dict(params or {})
        phone = p.get("phone")
        if phone and phone.startswith("eq."):
            rows = [r for r in rows if r.get("phone") == phone[3:]]
        if "valid_to" in p and p["valid_to"] == "is.null":
            rows = [r for r in rows if r.get("valid_to") is None]
        if "id" in p and p["id"].startswith("eq."):
            rows = [r for r in rows if r.get("id") == p["id"][3:]]
        if "canonical_name" in p and p["canonical_name"].startswith("eq."):
            rows = [r for r in rows if r.get("canonical_name") == p["canonical_name"][3:]]
        order = p.get("order")
        if order == "updated_at.desc":
            rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
        elif order == "received_at.desc":
            rows.sort(key=lambda r: str(r.get("received_at") or ""), reverse=True)
        elif order == "received_at.asc":
            rows.sort(key=lambda r: str(r.get("received_at") or ""))
        try:
            limit = int(p.get("limit", "0") or "0")
        except ValueError:
            limit = 0
        if limit > 0:
            rows = rows[:limit]
        return [dict(r) for r in rows]

    async def insert(self, table: str, rows) -> None:
        self.calls.append(("insert", table, rows))
        payload = rows if isinstance(rows, list) else [rows]
        store = self.tables.setdefault(table, {})
        for row in payload:
            if not isinstance(row, dict):
                continue
            key = row.get("id") or row.get("message_id") or str(id(row))
            store[key] = dict(row)


def _patch_backend(stub: StubBackend):
    orig = sofia_memory.get_backend
    sofia_memory.get_backend = lambda: stub  # type: ignore[assignment]
    return orig


def _restore(orig):
    sofia_memory.get_backend = orig  # type: ignore[assignment]


def _make_fact(fid: str, phone: str, text: str, embedding: list[float], **kw) -> dict:
    row = {
        "id": fid,
        "phone": phone,
        "lead_id": None,
        "subject_entity": None,
        "fact_text": text,
        "fact_type": "commercial",
        "embedding": embedding,
        "valid_from": "2026-09-20T12:00:00+00:00",
        "valid_to": None,
        "superseded_by": None,
        "confidence": 0.9,
        "source_message_id": "m1",
        "created_at": "2026-09-20T12:00:00+00:00",
        "updated_at": "2026-09-20T12:00:00+00:00",
    }
    row.update(kw)
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_cosine_sim_basic():
    assert sofia_memory.cosine_sim([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert sofia_memory.cosine_sim([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert sofia_memory.cosine_sim([], [1.0]) == 0.0
    assert sofia_memory.cosine_sim([1.0], [1.0, 2.0]) == 0.0  # length mismatch
    assert sofia_memory.cosine_sim([0.0, 0.0], [1.0, 1.0]) == 0.0  # zero vector


def test_keyword_overlap():
    assert sofia_memory.keyword_overlap("precio harina sacos", "el precio de la harina") > 0.6
    assert sofia_memory.keyword_overlap("xyz qqq", "el precio de la harina") == 0.0
    assert sofia_memory.keyword_overlap("", "algo") == 0.0


def test_hybrid_score_weights():
    v = [1.0] + [0.0] * 9
    q = [1.0] + [0.0] * 9
    high = sofia_memory.hybrid_score(v, q, "precio harina", "precio harina", "2026-09-20T23:00:00+00:00")
    low = sofia_memory.hybrid_score(v, q, "perro gato", "precio harina", "2020-01-01T00:00:00+00:00")
    assert high > low
    assert 0.0 <= high <= 1.0
    assert sofia_memory.hybrid_score([], q, "x", "x", "bad-date") == 0.0


def test_format_memory_block_caps_and_spanish():
    facts = [{"fact_text": "El precio confirmado es $50 por saco.", "fact_type": "commercial", "valid_from": "2026-09-20T12:00:00+00:00"}]
    entities = [{"canonical_name": "Juan", "aliases": ["mi tío"], "entity_type": "person"}]
    block = sofia_memory.format_memory_block(facts, entities, "Juan negocia harina.")
    assert "El precio confirmado es $50 por saco." in block  # Spanish verbatim
    assert "mi tío" in block
    assert "Juan negocia harina." in block
    big = sofia_memory.format_memory_block([{"fact_text": "x" * 5000, "fact_type": "other", "valid_from": ""}], [], "")
    assert len(big) <= sofia_memory.RECALL_BLOCK_MAX_CHARS


def test_safe_parse_extraction_valid():
    raw = json.dumps({
        "facts": [{"text": "Ingrid es sobrina de Juan.", "type": "identity", "subject_entity": "Ingrid", "confidence": 0.95}],
        "entities": [{"canonical_name": "Ingrid", "aliases": ["Ingri"], "type": "person"}],
        "contradictions": [],
        "summary_update": "Ingrid vende para SAHJONY.",
    })
    p = sofia_memory.safe_parse_extraction(raw)
    assert p["facts"][0]["text"] == "Ingrid es sobrina de Juan."
    assert p["facts"][0]["type"] == "identity"
    assert p["entities"][0]["aliases"] == ["Ingri"]
    assert p["summary_update"] == "Ingrid vende para SAHJONY."


def test_safe_parse_extraction_garbage_and_fences():
    assert sofia_memory.safe_parse_extraction("")["facts"] == []
    assert sofia_memory.safe_parse_extraction("not json at all")["facts"] == []
    fenced = "```json\n" + json.dumps({"facts": [{"text": "hola", "type": "weird-type"}]}) + "\n```"
    p = sofia_memory.safe_parse_extraction(fenced)
    assert p["facts"][0]["type"] == "other"  # unknown type normalized


def test_recall_never_raises_and_ranks():
    stub = StubBackend()
    dims = sofia_memory.EMBED_DIMS
    good = _make_fact("fact_1", "+5350000001", "precio confirmado harina $50 saco", [1.0] + [0.0] * (dims - 1))
    bad = _make_fact("fact_2", "+5350000001", "el perro ladra en la noche", [0.0] * (dims - 1) + [1.0])
    other_phone = _make_fact("fact_3", "+5350000002", "precio confirmado harina $50 saco", [1.0] + [0.0] * (dims - 1))
    invalidated = _make_fact("fact_4", "+5350000001", "precio confirmado harina $50 saco", [1.0] + [0.0] * (dims - 1), valid_to="2026-09-19T00:00:00+00:00")
    stub.tables["memory_facts"] = {r["id"]: r for r in (good, bad, other_phone, invalidated)}
    stub.tables["memory_entities"] = {"ent_1": {"id": "ent_1", "phone": "+5350000001", "canonical_name": "Juan", "aliases": ["mi tío"], "entity_type": "person"}}
    stub.tables["memory_summaries"] = {"summary_+5350000001": {"id": "summary_+5350000001", "phone": "+5350000001", "summary_text": "Resumen de prueba."}}

    orig = _patch_backend(stub)
    orig_embed = sofia_memory._embed_texts
    async def fake_embed(texts):
        return [[1.0] + [0.0] * (dims - 1) for _ in texts]
    sofia_memory._embed_texts = fake_embed  # type: ignore[assignment]
    try:
        result = asyncio.run(sofia_memory.recall("+5350000001", "precio harina"))
        assert result["facts"][0]["id"] == "fact_1"  # semantically ranked first
        ids = [f["id"] for f in result["facts"]]
        assert "fact_4" not in ids  # invalidated facts excluded
        assert "fact_3" not in ids  # other phone excluded
        assert "mi tío" in result["block"]
        assert "Resumen de prueba." in result["block"]
        # Failure path: empty phone returns empty, never raises.
        empty = asyncio.run(sofia_memory.recall("", "q"))
        assert empty == {"facts": [], "entities": [], "summary": "", "block": ""}
    finally:
        sofia_memory._embed_texts = orig_embed  # type: ignore[assignment]
        _restore(orig)


def test_recall_backend_failure_degrades():
    class BoomBackend(StubBackend):
        async def select(self, table, *, params=None):
            raise RuntimeError("backend down")
    orig = _patch_backend(BoomBackend())
    try:
        result = asyncio.run(sofia_memory.recall("+5350000001", "precio harina"))
        assert result == {"facts": [], "entities": [], "summary": "", "block": ""}
    finally:
        _restore(orig)


def test_consolidate_inserts_facts_and_invalidates():
    stub = StubBackend()
    dims = sofia_memory.EMBED_DIMS
    old = _make_fact("fact_old", "+5350000001", "El precio es $45 por saco", [0.5] * dims)
    stub.tables["memory_facts"] = {"fact_old": old}
    stub.tables["whatsapp_messages"] = {
        "m1": {"message_id": "m1", "phone": "+5350000001", "direction": "inbound", "text": "¿Cuál es el precio?", "received_at": "2026-09-20T20:00:00+00:00"},
        "m2": {"message_id": "m2", "phone": "+5350000001", "direction": "outbound", "text": "El precio es $50 por saco.", "received_at": "2026-09-20T20:01:00+00:00"},
    }
    orig = _patch_backend(stub)
    orig_chat = sofia_memory._chat_json
    orig_embed = sofia_memory._embed_texts
    async def fake_chat(system, user, max_tokens=1200):
        return json.dumps({
            "facts": [{"text": "El precio es $50 por saco", "type": "commercial", "subject_entity": None, "confidence": 0.9}],
            "entities": [{"canonical_name": "Fresco & Rey", "aliases": [], "type": "org"}],
            "contradictions": [{"new_fact_text": "El precio es $50 por saco", "old_fact_text": "El precio es $45 por saco"}],
            "summary_update": "",
        })
    async def fake_embed(texts):
        return [[0.7] * dims for _ in texts]
    sofia_memory._chat_json = fake_chat  # type: ignore[assignment]
    sofia_memory._embed_texts = fake_embed  # type: ignore[assignment]
    try:
        asyncio.run(sofia_memory.consolidate_turn("+5350000001"))
        facts = stub.tables.get("memory_facts", {})
        new_facts = [r for r in facts.values() if r["id"] != "fact_old"]
        assert len(new_facts) == 1
        assert new_facts[0]["fact_text"] == "El precio es $50 por saco"
        assert len(new_facts[0]["embedding"]) == dims
        assert facts["fact_old"]["valid_to"] is not None  # invalidated, not deleted
        assert facts["fact_old"]["superseded_by"] == new_facts[0]["id"]
        ents = stub.tables.get("memory_entities", {})
        assert any(e["canonical_name"] == "Fresco & Rey" for e in ents.values())
        summ = stub.tables.get("memory_summaries", {}).get("summary_+5350000001")
        assert summ is not None and summ["last_message_id"] == "m2"  # watermark advanced
    finally:
        sofia_memory._chat_json = orig_chat  # type: ignore[assignment]
        sofia_memory._embed_texts = orig_embed  # type: ignore[assignment]
        _restore(orig)


def test_consolidate_watermark_skips_done_work():
    stub = StubBackend()
    stub.tables["whatsapp_messages"] = {
        "m1": {"message_id": "m1", "phone": "+5350000001", "direction": "inbound", "text": "hola", "received_at": "2026-09-20T20:00:00+00:00"},
    }
    stub.tables["memory_summaries"] = {"summary_+5350000001": {"id": "summary_+5350000001", "phone": "+5350000001", "summary_text": "", "turns_covered": 1, "last_message_id": "m1", "updated_at": "x"}}
    orig = _patch_backend(stub)
    try:
        asyncio.run(sofia_memory.consolidate_turn("+5350000001"))
        selects = [c for c in stub.calls if c[0] == "select"]
        # Only the watermark + last-6 fetches happened; no inserts at all.
        inserts = [c for c in stub.calls if c[0] == "insert"]
        assert inserts == []
        assert len(selects) == 2
    finally:
        _restore(orig)


def test_consolidate_swallows_llm_failure():
    stub = StubBackend()
    stub.tables["whatsapp_messages"] = {
        "m1": {"message_id": "m1", "phone": "+5350000001", "direction": "inbound", "text": "hola", "received_at": "2026-09-20T20:00:00+00:00"},
    }
    orig = _patch_backend(stub)
    orig_chat = sofia_memory._chat_json
    async def boom(system, user, max_tokens=1200):
        raise RuntimeError("openai down")
    sofia_memory._chat_json = boom  # type: ignore[assignment]
    try:
        asyncio.run(sofia_memory.consolidate_turn("+5350000001"))  # must not raise
        # Nothing was written (no facts, no summary row): the failure is
        # transient, so the next outbound will retry these turns.
        assert stub.tables.get("memory_facts", {}) == {}
        assert stub.tables.get("memory_summaries", {}) == {}
    finally:
        sofia_memory._chat_json = orig_chat  # type: ignore[assignment]
        _restore(orig)


def test_queue_consolidation_no_loop_and_no_raise():
    # No running loop here (plain function context) — must not raise.
    sofia_memory.queue_consolidation("+5350000001")
    sofia_memory.queue_consolidation("")  # empty phone, still must not raise


def test_queue_consolidation_schedules_on_loop():
    stub = StubBackend()
    orig = _patch_backend(stub)
    calls: list[tuple] = []
    orig_consolidate = sofia_memory.consolidate_turn
    async def fake(phone, lead_id=None):
        calls.append((phone, lead_id))
    sofia_memory.consolidate_turn = fake  # type: ignore[assignment]
    async def runner():
        sofia_memory.queue_consolidation("+5350000001", lead_id="L1")
        await asyncio.sleep(0.05)
    try:
        asyncio.run(runner())
        assert calls == [("+5350000001", "L1")]
    finally:
        sofia_memory.consolidate_turn = orig_consolidate  # type: ignore[assignment]
        _restore(orig)
