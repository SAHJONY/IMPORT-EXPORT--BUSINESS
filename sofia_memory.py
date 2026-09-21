"""Sofia's temporal persistent-memory layer.

Three logical layers on the existing logical-table backend (no DDL required):
  - episodic   : whatsapp_messages (raw turns, already persisted)
  - semantic   : memory_facts  (LLM-extracted facts with validity windows;
                 contradictions INVALIDATE old facts via valid_to/superseded_by,
                 never delete)
  - entities   : memory_entities (canonical entities + aliases per phone, e.g.
                 "mi tío" -> Juan)
  - procedural : rolling per-phone summaries in memory_summaries (compact prompt
                 injection)

Retrieval (recall) runs on the reply path: a single hybrid score over
in-force facts (valid_to IS NULL) + entity aliases + rolling summary.
Extraction (consolidation) runs async via queue_consolidation after each
outbound message — never on the reply critical path.

Facts are stored verbatim in the contact's language (Spanish stays Spanish;
never translate).

This module imports ONLY insforge_backend + stdlib + httpx. It must NOT
import sofia_whatsapp_runtime (import cycle).
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from insforge_backend import get_backend

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
EMBED_URL = (
    os.getenv("SOFIA_MEMORY_EMBED_URL", "").strip()
    or "https://api.openai.com/v1/embeddings"
)
EMBED_MODEL = (
    os.getenv("SOFIA_MEMORY_EMBED_MODEL", "").strip() or "text-embedding-3-small"
)
CHAT_MODEL = (
    os.getenv("SOFIA_WHATSAPP_MODEL", "").strip() or "gpt-5.6-sol"
)

FACTS_TABLE = "memory_facts"
ENTITIES_TABLE = "memory_entities"
SUMMARIES_TABLE = "memory_summaries"
MESSAGES_TABLE = "whatsapp_messages"

EMBED_DIMS = 1536
SUMMARY_REFRESH_EVERY_TURNS = 5
RECALL_FETCH_LIMIT = 300
RECALL_BLOCK_MAX_CHARS = 3200
CONSOLIDATION_RECENT_TURNS = 6
HTTP_TIMEOUT = 30.0

FACT_TYPES = {"identity", "preference", "commitment", "commercial", "status", "other"}
ENTITY_TYPES = {"person", "product", "place", "org", "other"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts() -> str:
    return _now()


# ---------------------------------------------------------------------------
# Pure functions (unit-testable, no IO)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-záéíóúüñ0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(str(text or "").lower())


def cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [0, 1]; returns 0.0 on malformed input."""
    try:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na <= 0.0 or nb <= 0.0:
            return 0.0
        return max(0.0, min(1.0, dot / (na * nb)))
    except Exception:
        return 0.0


def keyword_overlap(query: str, text: str) -> float:
    """Overlap of query tokens present in text, in [0, 1]; 0.0 on no tokens."""
    try:
        qt = [t for t in _tokens(query) if len(t) > 2]
        if not qt:
            return 0.0
        tt = set(_tokens(text))
        hits = sum(1 for t in qt if t in tt)
        return hits / len(qt)
    except Exception:
        return 0.0


def recency_decay(updated_at_iso: str, half_life_days: float = 60.0) -> float:
    """Exponential decay toward 0 for old facts; 1.0 = fresh, 0.0 = unparseable."""
    try:
        dt = datetime.fromisoformat(str(updated_at_iso).replace("Z", "+00:00"))
        age_days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
        return 0.5 ** (age_days / max(half_life_days, 1e-6))
    except Exception:
        return 0.0


def hybrid_score(
    embedding: list[float],
    query_embedding: list[float],
    fact_text: str,
    query_text: str,
    updated_at_iso: str,
) -> float:
    """0.7*cosine + 0.2*keyword + 0.1*recency_decay, in [0, 1]."""
    try:
        cos = cosine_sim(embedding, query_embedding)
        kw = keyword_overlap(query_text, fact_text)
        rec = recency_decay(updated_at_iso)
        return 0.7 * cos + 0.2 * kw + 0.1 * rec
    except Exception:
        return 0.0


def format_memory_block(
    facts: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    summary: str,
) -> str:
    """Compact human-readable block for prompt injection (<= ~3200 chars).

    Facts are rendered verbatim in their stored language. The header instructs
    the model to treat them as known (feeds the known-fact drop guard).
    """
    lines: list[str] = []
    if summary:
        lines.append(f"Resumen: {summary.strip()}")
    for ent in entities:
        name = str(ent.get("canonical_name") or "").strip()
        if not name:
            continue
        aliases = [str(a) for a in (ent.get("aliases") or []) if str(a).strip()]
        etype = str(ent.get("entity_type") or "other").strip()
        alias_txt = f" (también: {', '.join(aliases)})" if aliases else ""
        lines.append(f"- Entidad [{etype}]: {name}{alias_txt}")
    for f in facts:
        text = str(f.get("fact_text") or "").strip()
        if not text:
            continue
        ftype = str(f.get("fact_type") or "other").strip()
        vf = str(f.get("valid_from") or "").strip()
        date_txt = f" [desde {vf[:10]}]" if vf else ""
        lines.append(f"- ({ftype}){date_txt} {text}")
    block = "\n".join(lines)
    if len(block) > RECALL_BLOCK_MAX_CHARS:
        block = block[: RECALL_BLOCK_MAX_CHARS - 1] + "…"
    return block


def safe_parse_extraction(raw: str) -> dict[str, Any]:
    """Parse the LLM extraction JSON; on any failure return an empty structure."""
    empty = {"facts": [], "entities": [], "contradictions": [], "summary_update": ""}
    try:
        text = str(raw or "").strip()
        if not text:
            return empty
        # Tolerate ```json fences.
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
        data = json.loads(text)
        if not isinstance(data, dict):
            return empty
        facts: list[dict[str, Any]] = []
        for f in data.get("facts") or []:
            if not isinstance(f, dict):
                continue
            ftext = str(f.get("text") or "").strip()
            if not ftext:
                continue
            ftype = str(f.get("type") or "other").strip().lower()
            if ftype not in FACT_TYPES:
                ftype = "other"
            try:
                conf = float(f.get("confidence", 0.7))
            except (TypeError, ValueError):
                conf = 0.7
            facts.append({
                "text": ftext[:2000],
                "type": ftype,
                "subject_entity": str(f.get("subject_entity") or "").strip()[:200] or None,
                "confidence": max(0.0, min(1.0, conf)),
            })
        entities: list[dict[str, Any]] = []
        for e in data.get("entities") or []:
            if not isinstance(e, dict):
                continue
            name = str(e.get("canonical_name") or "").strip()
            if not name:
                continue
            aliases = [str(a).strip() for a in (e.get("aliases") or []) if str(a).strip()]
            etype = str(e.get("type") or "other").strip().lower()
            if etype not in ENTITY_TYPES:
                etype = "other"
            entities.append({
                "canonical_name": name[:200],
                "aliases": aliases[:20],
                "type": etype,
            })
        contradictions: list[dict[str, Any]] = []
        for c in data.get("contradictions") or []:
            if not isinstance(c, dict):
                continue
            new_t = str(c.get("new_fact_text") or "").strip()
            old_t = str(c.get("old_fact_text") or "").strip()
            if new_t and old_t:
                contradictions.append({"new_fact_text": new_t[:2000], "old_fact_text": old_t[:2000]})
        summary_update = str(data.get("summary_update") or "").strip()
        return {
            "facts": facts,
            "entities": entities,
            "contradictions": contradictions,
            "summary_update": summary_update,
        }
    except Exception:
        return empty


# ---------------------------------------------------------------------------
# OpenAI helpers (own tiny copies — do NOT import sofia_whatsapp_runtime)
# ---------------------------------------------------------------------------


def _responses_text(data: dict[str, Any]) -> str:
    """Extract text from a Responses API payload."""
    direct = str(data.get("output_text") or "").strip()
    if direct:
        return direct
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"].strip())
    return "\n".join(x for x in parts if x).strip()


async def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts; returns one zero-vector per input on failure."""
    zeros = [[0.0] * EMBED_DIMS for _ in texts]
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or not texts:
        return zeros
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.post(
                EMBED_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": EMBED_MODEL, "input": texts},
            )
        if response.status_code >= 400:
            return zeros
        data = response.json().get("data") or []
        out: list[list[float]] = []
        for i in range(len(texts)):
            vec = None
            for item in data:
                if isinstance(item, dict) and item.get("index") == i:
                    vec = item.get("embedding")
                    break
            if isinstance(vec, list) and len(vec) == EMBED_DIMS:
                out.append([float(x) for x in vec])
            else:
                out.append([0.0] * EMBED_DIMS)
        return out
    except Exception:
        return zeros


async def _chat_json(system: str, user: str, max_tokens: int = 1200) -> str:
    """One Responses-API call returning raw text (JSON expected)."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return ""
    payload = {
        "model": CHAT_MODEL,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": [{"type": "input_text", "text": user}]},
        ],
        "max_output_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.post(
            OPENAI_RESPONSES_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 400:
        return ""
    return _responses_text(response.json())


# ---------------------------------------------------------------------------
# Retrieval — sync path used by the reply flow. NEVER raises.
# ---------------------------------------------------------------------------

async def recall(phone: str, query_text: str, k: int = 8) -> dict[str, Any]:
    """Retrieve dated long-term memory for a phone number.

    Returns {"facts":[...], "entities":[...], "summary": str, "block": str}.
    Never raises: any failure degrades to empty memory (today's behavior).
    """
    empty = {"facts": [], "entities": [], "summary": "", "block": ""}
    try:
        phone = str(phone or "").strip()
        if not phone:
            return empty
        backend = get_backend()
        try:
            fact_rows = await backend.select(
                FACTS_TABLE,
                params={
                    "phone": f"eq.{phone}",
                    "valid_to": "is.null",
                    "order": "updated_at.desc",
                    "limit": str(RECALL_FETCH_LIMIT),
                },
            ) or []
        except Exception:
            fact_rows = []
        try:
            entity_rows = await backend.select(
                ENTITIES_TABLE, params={"phone": f"eq.{phone}", "limit": "50"}
            ) or []
        except Exception:
            entity_rows = []
        summary_text = ""
        try:
            sum_rows = await backend.select(
                SUMMARIES_TABLE, params={"id": "eq.summary_" + phone, "limit": "1"}
            ) or []
            if sum_rows:
                summary_text = str(sum_rows[0].get("summary_text") or "")
        except Exception:
            summary_text = ""

        ranked: list[tuple[float, dict[str, Any]]] = []
        if fact_rows:
            try:
                qvecs = await _embed_texts([str(query_text or "")[:2000]])
                qvec = qvecs[0] if qvecs else [0.0] * EMBED_DIMS
            except Exception:
                qvec = [0.0] * EMBED_DIMS
            for row in fact_rows:
                if not isinstance(row, dict):
                    continue
                vec = row.get("embedding")
                if not isinstance(vec, list) or len(vec) != EMBED_DIMS:
                    continue
                score = hybrid_score(
                    vec,
                    qvec,
                    str(row.get("fact_text") or ""),
                    str(query_text or ""),
                    str(row.get("updated_at") or ""),
                )
                ranked.append((score, row))
            ranked.sort(key=lambda x: x[0], reverse=True)

        facts = [r for s, r in ranked[: max(1, int(k))]]
        entities = [r for r in entity_rows if isinstance(r, dict)]
        block = format_memory_block(facts, entities, summary_text)
        return {
            "facts": facts,
            "entities": entities,
            "summary": summary_text,
            "block": block,
        }
    except Exception:
        return empty


# ---------------------------------------------------------------------------
# Consolidation — background worker. Swallows ALL exceptions.
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM = (
    "Eres un extractor de memoria para un agente de ventas por WhatsApp. "
    "Devuelve SOLO un objeto JSON válido, sin texto adicional ni fences. "
    "Esquema:\n"
    '{"facts":[{"text":str,"type":"identity|preference|commitment|commercial|status|other",'
    '"subject_entity":str|null,"confidence":0..1}],'
    '"entities":[{"canonical_name":str,"aliases":[str],"type":"person|product|place|org|other"}],'
    '"contradictions":[{"new_fact_text":str,"old_fact_text":str}],'
    '"summary_update":str}\n'
    "Reglas:\n"
    "- facts: solo hechos DURADEROS y verificables en la conversación (quién es la persona, "
    "rol, precios confirmados, compromisos, preferencias). Nada obvio ni efímero.\n"
    "- Escribe text EN EL IDIOMA ORIGINAL del contacto (español se queda español; no traduzcas).\n"
    "- entities: personas/productos/lugares/orgs mencionadas con sus alias (apodos, "
    'pronombres como "mi tío").\n'
    "- contradictions: solo si un hecho NUEVO invalida uno ANTERIOR (precio cambiado, "
    "decisión revertida). old_fact_text debe citar el hecho anterior en sus palabras.\n"
    '- summary_update: 1-2 frases que actualicen el resumen del contacto ("" si no hay cambios).\n'
    "- Si no hay nada que extraer, devuelve listas vacías y summary_update vacío."
)


def _turn_text(row: dict[str, Any]) -> str:
    direction = str(row.get("direction") or "?").strip()
    text = str(row.get("text") or "").strip()
    return f"[{direction}] {text}"


def _norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", str(t or "").lower()).strip()


async def consolidate_turn(phone: str, lead_id: str | None = None) -> None:
    """Extract facts/entities from the latest turns and refresh memory tables.

    Background worker — failures are swallowed so memory degrades to today's
    behavior, never breaking replies.
    """
    try:
        phone = str(phone or "").strip()
        if not phone:
            return
        backend = get_backend()
        try:
            rows = await backend.select(
                MESSAGES_TABLE,
                params={
                    "phone": f"eq.{phone}",
                    "order": "received_at.desc",
                    "limit": str(CONSOLIDATION_RECENT_TURNS),
                },
            ) or []
        except Exception:
            return
        rows = [r for r in rows if isinstance(r, dict)]
        rows.reverse()  # oldest -> newest
        await _process_turn_batch(backend, phone, lead_id, rows)
    except Exception:
        return


async def _process_turn_batch(
    backend: Any,
    phone: str,
    lead_id: str | None,
    rows: list[dict[str, Any]],
) -> None:
    """Process one ordered batch of turns (oldest -> newest).

    Shared by the live worker and the backfill script. Skips turns already
    covered by the summary watermark. Swallows ALL exceptions.
    """
    try:
        if not rows:
            return
        # Load watermark and keep only uncovered turns.
        watermark = ""
        sum_rows: list[dict[str, Any]] = []
        try:
            sum_rows = await backend.select(
                SUMMARIES_TABLE, params={"id": "eq.summary_" + phone, "limit": "1"}
            ) or []
            if sum_rows:
                watermark = str(sum_rows[0].get("last_message_id") or "")
        except Exception:
            watermark = ""
            sum_rows = []
        new_rows = [r for r in rows if str(r.get("message_id") or "") != watermark]
        if not new_rows:
            return
        newest_id = str(new_rows[-1].get("message_id") or "")
        if newest_id == watermark:
            return

        # Extract with the LLM.
        transcript = "\n".join(_turn_text(r) for r in new_rows)
        existing = ""
        try:
            fact_rows = await backend.select(
                FACTS_TABLE,
                params={
                    "phone": f"eq.{phone}",
                    "valid_to": "is.null",
                    "order": "updated_at.desc",
                    "limit": "60",
                },
            ) or []
            existing = "\n".join(
                f"- {r.get('fact_text')}" for r in fact_rows if isinstance(r, dict)
            )[:4000]
        except Exception:
            fact_rows = []
            existing = ""
        user = (
            f"Hechos ya conocidos (no repetirlos, úsalos para detectar contradicciones):\n"
            f"{existing or '(ninguno)'}\n\n"
            f"Nuevos turnos de la conversación:\n{transcript[:6000]}"
        )
        raw = await _chat_json(EXTRACTION_SYSTEM, user)
        parsed = safe_parse_extraction(raw)
        if (
            not parsed["facts"]
            and not parsed["entities"]
            and not parsed["contradictions"]
            and not parsed["summary_update"]
        ):
            # Nothing new — still advance the watermark so we don't re-scan.
            await _advance_watermark(backend, phone, newest_id, new_rows)
            return

        # 3) Embed new facts and insert them.
        now = _ts()
        fact_texts = [f["text"] for f in parsed["facts"]]
        embeddings = await _embed_texts(fact_texts) if fact_texts else []
        new_ids: list[str] = []
        inserts: list[dict[str, Any]] = []
        for f, vec in zip(parsed["facts"], embeddings):
            fid = f"fact_{secrets.token_urlsafe(12)}"
            new_ids.append(fid)
            inserts.append({
                "id": fid,
                "phone": phone,
                "lead_id": lead_id,
                "subject_entity": f.get("subject_entity"),
                "fact_text": f["text"],
                "fact_type": f["type"],
                "embedding": [float(x) for x in vec] if len(vec) == EMBED_DIMS else [0.0] * EMBED_DIMS,
                "valid_from": now,
                "valid_to": None,
                "superseded_by": None,
                "confidence": f["confidence"],
                "source_message_id": newest_id or None,
                "created_at": now,
                "updated_at": now,
            })
        if inserts:
            try:
                await backend.insert(FACTS_TABLE, inserts)
            except Exception:
                pass

        # 4) Handle contradictions: invalidate old facts (never delete).
        for c in parsed["contradictions"]:
            try:
                old = _find_fact_by_text(fact_rows, c["old_fact_text"])
                if old is None:
                    continue
                old_id = str(old.get("id") or "")
                if not old_id:
                    continue
                new_id = _find_new_fact_id(new_ids, fact_texts, c["new_fact_text"]) or None
                updated = dict(old)
                updated["valid_to"] = now
                updated["superseded_by"] = new_id
                updated["updated_at"] = now
                await backend.insert(FACTS_TABLE, updated)
            except Exception:
                continue

        # 5) Upsert entities (merge aliases by canonical_name).
        for e in parsed["entities"]:
            try:
                eid = await _upsert_entity(backend, phone, e, now)
            except Exception:
                eid = None

        # 6) Rolling summary: refresh every N turns.
        try:
            prior = ""
            turns_covered = 0
            if sum_rows:
                prior = str(sum_rows[0].get("summary_text") or "")
                turns_covered = int(sum_rows[0].get("turns_covered") or 0)
            total_turns = turns_covered + len(new_rows)
            summary_text = prior
            if parsed["summary_update"] and (total_turns % SUMMARY_REFRESH_EVERY_TURNS == 0 or not prior):
                summary_text = _merge_summary(prior, parsed["summary_update"])
            await backend.insert(SUMMARIES_TABLE, {
                "id": f"summary_{phone}",
                "phone": phone,
                "summary_text": summary_text[:1200],
                "turns_covered": total_turns,
                "last_message_id": newest_id,
                "updated_at": now,
            })
        except Exception:
            await _advance_watermark(backend, phone, newest_id, new_rows)
    except Exception:
        return


async def _advance_watermark(
    backend: Any, phone: str, newest_id: str, rows: list[dict[str, Any]]
) -> None:
    """Advance only the watermark when extraction produced nothing."""
    try:
        sum_rows = await backend.select(
            SUMMARIES_TABLE, params={"id": "eq.summary_" + phone, "limit": "1"}
        ) or []
        prior = ""
        turns = 0
        if sum_rows:
            prior = str(sum_rows[0].get("summary_text") or "")
            turns = int(sum_rows[0].get("turns_covered") or 0)
        await backend.insert(SUMMARIES_TABLE, {
            "id": f"summary_{phone}",
            "phone": phone,
            "summary_text": prior[:1200],
            "turns_covered": turns + len(rows),
            "last_message_id": newest_id,
            "updated_at": _ts(),
        })
    except Exception:
        pass


def _find_fact_by_text(
    fact_rows: list[dict[str, Any]], old_text: str
) -> dict[str, Any] | None:
    """Match the contradicted old fact by normalized text similarity."""
    target = _norm_text(old_text)
    if not target:
        return None
    best: dict[str, Any] | None = None
    best_score = 0.0
    for r in fact_rows:
        if not isinstance(r, dict):
            continue
        cand = _norm_text(str(r.get("fact_text") or ""))
        if not cand:
            continue
        if cand == target:
            return r
        # Token overlap on long text; require strong overlap.
        tset, cset = set(target.split()), set(cand.split())
        if not tset or not cset:
            continue
        score = len(tset & cset) / max(len(tset), len(cset))
        if score > best_score:
            best_score, best = score, r
    if best_score >= 0.8:
        return best
    return None


def _find_new_fact_id(
    new_ids: list[str], fact_texts: list[str], new_text: str
) -> str | None:
    target = _norm_text(new_text)
    for fid, ft in zip(new_ids, fact_texts):
        if _norm_text(ft) == target:
            return fid
    return None


async def _upsert_entity(
    backend: Any, phone: str, entity: dict[str, Any], now: str
) -> str:
    """Merge an extracted entity into memory_entities by canonical_name."""
    name = str(entity.get("canonical_name") or "").strip()
    rows = await backend.select(
        ENTITIES_TABLE,
        params={"phone": f"eq.{phone}", "canonical_name": f"eq.{name}", "limit": "1"},
    ) or []
    if rows and isinstance(rows[0], dict):
        existing = dict(rows[0])
        aliases = [str(a) for a in (existing.get("aliases") or [])]
        for a in entity.get("aliases") or []:
            a = str(a).strip()
            if a and a not in aliases:
                aliases.append(a)
        existing["aliases"] = aliases[:20]
        existing["notes"] = str(existing.get("notes") or "")
        existing["updated_at"] = now
        await backend.insert(ENTITIES_TABLE, existing)
        return str(existing.get("id") or "")
    eid = f"ent_{secrets.token_urlsafe(12)}"
    await backend.insert(ENTITIES_TABLE, {
        "id": eid,
        "phone": phone,
        "canonical_name": name,
        "aliases": [str(a).strip() for a in (entity.get("aliases") or []) if str(a).strip()][:20],
        "entity_type": entity.get("type") or "other",
        "notes": "",
        "created_at": now,
        "updated_at": now,
    })
    return eid


def _merge_summary(prior: str, update: str) -> str:
    """Roll the LLM's summary_update into the running per-contact summary.

    Keeps it compact (~300 tokens): newest update first, then older context
    truncated. No LLM call — consolidation must stay cheap and local.
    """
    update = str(update or "").strip()
    prior = str(prior or "").strip()
    if not update:
        return prior[:1200]
    merged = f"{update}\n{prior}" if prior else update
    # Cap at ~1200 chars (~300 tokens).
    if len(merged) > 1200:
        merged = merged[:1197] + "…"
    return merged


# ---------------------------------------------------------------------------
# Fire-and-forget scheduler for the post-outbound hook. Never raises.
# ---------------------------------------------------------------------------

def queue_consolidation(phone: str, lead_id: str | None = None) -> None:
    """Schedule consolidate_turn on the running loop; never raises."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        loop.create_task(consolidate_turn(str(phone or ""), lead_id))
    except Exception:
        pass
