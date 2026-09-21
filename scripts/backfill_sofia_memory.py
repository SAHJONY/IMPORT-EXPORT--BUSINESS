"""One-shot backfill of Sofia's temporal memory from existing whatsapp_messages.

Chunked per phone, idempotent via the memory_summaries watermark
(last_message_id): re-running only processes turns not yet covered.

MANUAL USE ONLY — never executed automatically on import or at service start.

Usage:
    python3 scripts/backfill_sofia_memory.py [--phone +535XXXXXXXX] [--limit-phones N] [--batch N]

Reads/writes the same logical tables as sofia_memory.py. No secrets are
printed. Message bodies are never printed to stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from insforge_backend import get_backend

import sofia_memory


async def _phones(limit: int, phone_filter: str | None) -> list[str]:
    backend = get_backend()
    rows = await backend.select(
        "whatsapp_messages",
        params={"order": "received_at.asc", "limit": "10000"},
    ) or []
    phones: list[str] = []
    seen: set[str] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        p = str(r.get("phone") or "").strip()
        if not p or p in seen:
            continue
        if phone_filter and p != phone_filter:
            continue
        seen.add(p)
        phones.append(p)
        if len(phones) >= limit:
            break
    return phones


async def _watermark(backend: Any, phone: str) -> str:
    try:
        rows = await backend.select(
            "memory_summaries", params={"id": "eq.summary_" + phone, "limit": "1"}
        ) or []
        if rows:
            return str(rows[0].get("last_message_id") or "")
    except Exception:
        pass
    return ""


async def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Sofia temporal memory.")
    parser.add_argument("--phone", default="", help="Only backfill this phone number.")
    parser.add_argument("--limit-phones", type=int, default=200, help="Max phones.")
    parser.add_argument("--batch", type=int, default=6, help="Turns per consolidation chunk.")
    args = parser.parse_args()

    backend = get_backend()
    phones = await _phones(args.limit_phones, args.phone.strip() or None)
    if not phones:
        print("backfill: no phones found")
        return 0

    batch_size = max(1, min(50, args.batch))
    total_chunks = 0
    for i, phone in enumerate(phones, 1):
        try:
            rows = await backend.select(
                "whatsapp_messages",
                params={
                    "phone": f"eq.{phone}",
                    "order": "received_at.asc",
                    "limit": "10000",
                },
            ) or []
        except Exception:
            print(f"[{i}/{len(phones)}] {phone}: select failed, skipping")
            continue
        rows = [r for r in rows if isinstance(r, dict)]
        wm = await _watermark(backend, phone)
        pending = [r for r in rows if str(r.get("message_id") or "") != wm]
        # Drop everything up to and including the watermark position.
        if wm:
            after = False
            kept: list[dict[str, Any]] = []
            for r in rows:
                if after:
                    kept.append(r)
                elif str(r.get("message_id") or "") == wm:
                    after = True
            pending = kept
        if not pending:
            print(f"[{i}/{len(phones)}] {phone}: already covered, skipping")
            continue
        chunks = [pending[j:j + batch_size] for j in range(0, len(pending), batch_size)]
        print(f"[{i}/{len(phones)}] {phone}: {len(pending)} pending turns, {len(chunks)} chunk(s)")
        for chunk in chunks:
            try:
                await sofia_memory._process_turn_batch(backend, phone, None, chunk)
            except Exception:
                pass
            total_chunks += 1
            await asyncio.sleep(0.2)
    print(f"backfill: done, {total_chunks} chunks over {len(phones)} phones")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
