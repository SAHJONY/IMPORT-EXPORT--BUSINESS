#!/usr/bin/env python3
"""Hermes Agent Swarm — go-live runner (phase 1: read + draft, never send).

Runs ALONGSIDE the Hermes WhatsApp transport (127.0.0.1:8102), never inside
it. Hosts the SwarmCoordinator from the hermes_swarm package (pure Python,
no network I/O of its own) and adds:

  - a 60s transport-health poll (open /whatsapp/health endpoint only),
  - a localhost HTTP surface (127.0.0.1:8104) for status, roster, approval
    queue, audit chain, kill switch, live pipeline self-test, and the
    no-send-ban proof,
  - a persistent append-only audit log (JSONL, SHA-256 hash chain).

HARD LINES (structural, not policy):
  - No agent can send: enforced by SwarmAgent.__init_subclass__ (any
    send/enqueue/deliver method definition raises TypeError at import).
  - SwarmCoordinator.deliver_approved() raises NotImplementedError. This
    runner NEVER calls it except through the /send-attempt proof endpoint,
    which expects the refusal and audit-logs it.
  - The approval queue never auto-advances: only an explicit ApprovalInput
    from Juan moves a draft to APPROVED, and even then nothing transmits —
    delivery stays with the existing Juan-dispatched governed outbox
    workflow, which this service cannot invoke.
  - Kill switch: stop() halts all drafting immediately (SwarmHalted);
    resume() re-arms. Both are audit-logged.

Phase-2 (not in this runner): signed-consumer wiring for
GET /whatsapp/recovery/backlog and the CRM bridge scopes — the transport's
read APIs require the HMAC bridge secret, which this service does not hold.
Until then, inbound events enter via the /ingest endpoint (same shape as a
transport event) or the /selftest synthetic pipeline run.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from hermes_swarm.agents import SwarmHalted, build_roster
from hermes_swarm.audit import AuditLog
from hermes_swarm.coordinator import ApprovalInput, SwarmCoordinator

BASE_DIR = Path(__file__).resolve().parent
AUDIT_PATH = BASE_DIR / "audit.jsonl"
TRANSPORT = "http://127.0.0.1:8102"
POLL_SECONDS = 60

_lock = threading.RLock()
_audit = AuditLog(path=AUDIT_PATH)
_coordinator = SwarmCoordinator(audit=_audit)
_transport_state: dict = {"status": "unknown", "last_poll": None, "last_error": None}
_backlog_auth_note_logged = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _poll_transport() -> None:
    """Read-only poll of the transport health endpoint."""
    global _backlog_auth_note_logged
    try:
        with urllib.request.urlopen(
            TRANSPORT + "/whatsapp/health", timeout=10
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        with _lock:
            prev = _transport_state.get("status")
            _transport_state.update(
                {
                    "status": data.get("status"),
                    "send_ready": data.get("send_ready"),
                    "ai_ready": data.get("ai_ready"),
                    "last_poll": _now(),
                    "last_error": None,
                }
            )
            if prev != data.get("status"):
                _audit.append(
                    "transport_state",
                    {"status": data.get("status"),
                     "send_ready": data.get("send_ready")},
                )
                print(f"[swarm] transport state -> {data.get('status')}", flush=True)
    except Exception as exc:  # noqa: BLE001 - poll must never crash the loop
        with _lock:
            _transport_state.update({"status": "unreachable",
                                     "last_poll": _now(),
                                     "last_error": str(exc)[:200]})
        print(f"[swarm] transport poll failed: {exc}", flush=True)

    # The backlog/inbox read APIs require the HMAC bridge secret, which this
    # service does not hold. Note it once in the audit trail (phase-2 item).
    if not _backlog_auth_note_logged:
        _backlog_auth_note_logged = True
        try:
            with urllib.request.urlopen(
                TRANSPORT + "/whatsapp/recovery/backlog", timeout=10
            ) as resp:
                code = resp.status
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", "error")
        with _lock:
            _audit.append(
                "inbox_poll_deferred",
                {"reason": "transport read APIs require the HMAC bridge "
                           "secret; this service does not hold it",
                 "backlog_probe": str(code),
                 "phase": "phase-2 wiring"},
            )
        print("[swarm] inbox poll deferred: backlog API requires bridge "
              "auth (phase-2 wiring)", flush=True)


def _poll_loop() -> None:
    while True:
        _poll_transport()
        time.sleep(POLL_SECONDS)


def _run_pipeline(event: dict) -> dict:
    """Full live pipeline for one inbound event:
    triage -> draft -> compliance gate -> approval queue. Returns a report."""
    with _lock:
        context = _coordinator.handle_inbound(event)
        draft = _coordinator.draft_for(context.conversation_id,
                                       agent_id="customer-care")
        result = {
            "conversation_id": context.conversation_id,
            "track": context.track,
            "lang": context.lang,
            "sanctions_hold": bool(
                context.metadata.get("sanctions_hold")),
            "triage": context.metadata.get("triage"),
            "draft_id": draft.draft_id if draft else None,
            "draft_kind": draft.kind if draft else None,
            "queue_depth": len(_coordinator.queue),
            "halted": _coordinator.kill_switch.halted,
        }
        return result


class _Handler(BaseHTTPRequestHandler):
    server_version = "SwarmRunner/1.0"

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def log_message(self, *args):  # quieter than BaseHTTPRequestHandler
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        try:
            if path == "/health":
                with _lock:
                    self._send(200, {
                        "status": "ok",
                        "service": "sahjony-fallback-swarm",
                        "agents_registered": len(_coordinator.roster),
                        "halted": _coordinator.kill_switch.halted,
                        "queue_depth": len(_coordinator.queue),
                        "audit_records": len(_audit),
                        "audit_chain_valid": _audit.verify_chain(),
                        "transport": dict(_transport_state),
                        "no_send_ban": "structural "
                        "(deliver_approved raises NotImplementedError)",
                    })
            elif path == "/agents":
                with _lock:
                    self._send(200, {"agents": [
                        a.describe() for a in _coordinator.roster]})
            elif path == "/queue":
                with _lock:
                    self._send(200, {"pending": [
                        {"draft_id": q.draft.draft_id,
                         "agent_id": q.draft.agent_id,
                         "track": q.draft.track,
                         "lang": q.draft.lang,
                         "kind": q.draft.kind,
                         "text": q.draft.text,
                         "stage": q.stage.value,
                         "queued_at": q.queued_at,
                         "gate_verdict": q.gate_verdict}
                        for q in _coordinator.queue.pending()]})
            elif path == "/audit/tail":
                with _lock:
                    records = _audit.records()[-50:]
                    self._send(200, {"records": records,
                                     "total": len(_audit)})
            elif path == "/audit/verify":
                with _lock:
                    self._send(200, {"chain_valid": _audit.verify_chain(),
                                     "records": len(_audit)})
            else:
                self._send(404, {"error": "unknown route"})
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._send(500, {"error": str(exc)[:300]})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        try:
            if path == "/ingest":
                event = self._read_json()
                if not event.get("conversation_id"):
                    self._send(400, {"error":
                                     "event['conversation_id'] required"})
                    return
                try:
                    report = _run_pipeline(event)
                except SwarmHalted as exc:
                    with _lock:
                        _audit.append("ingest_refused_halted",
                                      {"reason": str(exc)[:200]})
                    self._send(423, {"refused": True,
                                     "reason": "kill switch engaged"})
                    return
                self._send(200, report)
            elif path == "/selftest":
                event = {
                    "conversation_id": "selftest-" + _now(),
                    "phone": "+10000000000",
                    "text": ("Hola, ¿cuánto cuesta el flete de un contenedor "
                             "de arroz?"),
                    "window_state": {"within_24h_window": True,
                                     "rate_ok": True},
                    "metadata": {"source": "swarm-selftest"},
                }
                try:
                    report = _run_pipeline(event)
                except SwarmHalted as exc:
                    self._send(423, {"refused": True,
                                     "reason": str(exc)[:200]})
                    return
                report["selftest"] = True
                self._send(200, report)
            elif path == "/send-attempt":
                # LIVE PROOF OF THE NO-SEND BAN: the only code path that
                # could reach the wire is a stub that refuses.
                body = self._read_json()
                draft_id = body.get("draft_id") or "probe"
                try:
                    _coordinator.deliver_approved(
                        type("Q", (), {"draft": type(
                            "D", (), {"draft_id": draft_id})()})())
                    # Unreachable by design; if reached, something is wrong.
                    self._send(500, {"refused": False,
                                     "error": "BAN VIOLATION: stub did not "
                                              "raise"})
                except NotImplementedError as exc:
                    with _lock:
                        _audit.append("send_refused", {
                            "draft_id": draft_id,
                            "reason": "deliver_approved is a go-live stub; "
                                      "the swarm has no send path",
                            "detail": str(exc)[:200]})
                    self._send(200, {"refused": True,
                                     "ban": "structural no-send ban held",
                                     "detail": str(exc)[:200]})
            elif path == "/kill/stop":
                body = self._read_json()
                with _lock:
                    _coordinator.kill_switch.stop(
                        body.get("reason") or "manual stop")
                    self._send(200, {"halted": True})
            elif path == "/kill/resume":
                body = self._read_json()
                with _lock:
                    _coordinator.kill_switch.resume(
                        body.get("reason") or "manual resume")
                    self._send(200, {"halted": False})
            elif path == "/approve":
                # Explicit ApprovalInput from Juan. Moves a queued draft to
                # APPROVED in the data structure. NOTHING transmits — delivery
                # remains the Juan-dispatched governed outbox workflow.
                body = self._read_json()
                approval = ApprovalInput(
                    approver=body.get("approver") or "",
                    draft_id=body.get("draft_id") or "",
                    decision=body.get("decision") or "",
                    note=body.get("note") or "",
                )
                with _lock:
                    moved = _coordinator.queue.process(approval)
                self._send(200, {
                    "moved_to_approved": [q.draft.draft_id for q in moved],
                    "note": "APPROVED is a queue state only. No message was "
                            "sent; sending stays with the Juan-dispatched "
                            "governed outbox workflow.",
                })
            else:
                self._send(404, {"error": "unknown route"})
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._send(500, {"error": str(exc)[:300]})


def main() -> None:
    with _lock:
        _audit.append("swarm_runner_started", {
            "agents": [a.agent_id for a in _coordinator.roster],
            "phase": "phase-1 (read + draft, never send)",
        })
    print(f"[swarm] started: {len(_coordinator.roster)} agents registered, "
          f"audit at {AUDIT_PATH}", flush=True)
    threading.Thread(target=_poll_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 8104), _Handler)
    print("[swarm] listening on 127.0.0.1:8104", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
