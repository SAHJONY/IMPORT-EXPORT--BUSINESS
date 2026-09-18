"""Immutable append-only audit log (JSONL).

Every stage of the swarm pipeline is recorded: draft_created -> gate_verdict
-> queued_for_approval -> approved/rejected -> (external) enqueue -> delivery
status. Each record chains to the previous record's SHA-256 hash, so any
tampering with history is detectable. There is no edit or delete API —
records are append-only by construction.

The 'enqueue' and 'delivery' events are recorded from the EXTERNAL
governed outbox workflow (Juan-dispatched); this package never produces
them itself.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    """Append-only JSONL audit log with a hash chain.

    AuditLog() with no path keeps records in memory (default — safe for
    tests and for the scaffold, which must not write anywhere unexpected).
    Pass a path to persist to disk.
    """

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._records: list[dict] = []
        self._last_hash = "genesis"
        if self._path is not None and self._path.exists():
            self._load_existing()

    # -- writing ----------------------------------------------------------

    def append(self, event: str, payload: dict | None = None) -> dict:
        """Append one immutable record. Returns the record."""
        if not event or not str(event).strip():
            raise ValueError("AuditLog.append requires a non-empty event name.")
        record = {
            "seq": len(self._records),
            "at": datetime.now(timezone.utc).isoformat(),
            "event": str(event).strip(),
            "payload": dict(payload or {}),
            "prev_hash": self._last_hash,
        }
        record["hash"] = self._hash_record(record)
        self._records.append(record)
        self._last_hash = record["hash"]
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    # -- reading ----------------------------------------------------------

    def records(self) -> list[dict]:
        """All records, oldest first. Returns copies (records are immutable)."""
        return [dict(r) for r in self._records]

    def verify_chain(self) -> bool:
        """Recompute the hash chain. False => history was tampered with."""
        prev = "genesis"
        for record in self._records:
            if record.get("prev_hash") != prev:
                return False
            expected = self._hash_record({k: v for k, v in record.items()
                                         if k != "hash"})
            if record.get("hash") != expected:
                return False
            prev = record["hash"]
        return True

    def __len__(self) -> int:
        return len(self._records)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _hash_record(record: dict) -> str:
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _load_existing(self) -> None:
        assert self._path is not None
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    record = json.loads(line)
                    self._records.append(record)
                    self._last_hash = record["hash"]
