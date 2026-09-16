"""Sofia self-healing: watchdog decision loop for the WhatsApp runtime.

``evaluate_health()`` inspects a health snapshot (live WhatsApp health endpoint
+ Hermes gateway freshness) and returns exactly one of:

- ``healthy``   — everything nominal; no action.
- ``degraded``  — something is wrong; a recommended recovery action is attached
                  (dispatch the existing "Hostinger Hermes Safe Clean"
                  workflow via ``gh workflow run``). Cooldown: recovery is not
                  re-triggered more than once per 30 minutes.
- ``critical``  — recovery was attempted 3 times without success, or the
                  failure is outside automatic recovery scope. Escalates to
                  Juan; automatic retries STOP.

``trigger_recovery()`` is a separate thin function so dispatch can be dry-run
tested without ever touching production. Every decision is recorded in a
structured in-memory decision log (``get_decision_log()``).

Hard rules:
- No infinite loops: this module only *evaluates*; scheduling (cron) lives
  outside and simply calls ``evaluate_health()`` once per run.
- After ``MAX_FAILED_RECOVERIES`` failed recoveries the watchdog escalates and
  stops auto-retrying — Juan decides the next step.
- Recovery reuses the existing dispatchable GitHub workflows; no new workflow
  files are created by this module.
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

HEALTH_URL = "https://www.sahjony.com/whatsapp/health"
HEALTH_TIMEOUT_SECONDS = 10

# Existing dispatchable workflow used for automatic recovery. Triggered via
# `gh workflow run` — never by creating new workflow files.
SAFE_CLEAN_WORKFLOW = "Hostinger Hermes Safe Clean"
WORKFLOW_REF = "main"

RECOVERY_COOLDOWN = timedelta(minutes=30)
MAX_FAILED_RECOVERIES = 3

STATE_HEALTHY = "healthy"
STATE_DEGRADED = "degraded"
STATE_CRITICAL = "critical"

# Module-level runtime state. A cron runner may pass its own dict instead.
STATE: dict[str, Any] = {
    "last_recovery_attempt": None,  # ISO timestamp or None
    "failed_recoveries": 0,
    "pending_recovery": False,
    "last_decision": None,
}

DECISION_LOG: list[dict[str, Any]] = []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def log_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Append a structured record of every watchdog decision."""
    entry = {
        "decided_at": _now().isoformat(),
        **decision,
    }
    DECISION_LOG.append(entry)
    return entry


def get_decision_log() -> list[dict[str, Any]]:
    return list(DECISION_LOG)


def reset_state(state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reset watchdog state (tests / manual recovery acknowledgement)."""
    target = state if state is not None else STATE
    target.update(
        {
            "last_recovery_attempt": None,
            "failed_recoveries": 0,
            "pending_recovery": False,
            "last_decision": None,
        }
    )
    return target


def _problems_in_snapshot(snapshot: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if not snapshot.get("ok", False):
        problems.append("health_endpoint_not_ok")
    if not snapshot.get("send_ready", False):
        problems.append("whatsapp_send_not_ready")
    if not snapshot.get("webhook_ready", False):
        problems.append("whatsapp_webhook_not_ready")
    if not snapshot.get("ai_auto_reply_enabled", False):
        problems.append("ai_auto_reply_disabled")
    if snapshot.get("gateway_fresh") is False:
        problems.append("hermes_gateway_stale")
    return problems


def evaluate_health(
    snapshot: dict[str, Any] | None,
    *,
    state: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate WhatsApp runtime health and decide the next step.

    ``snapshot`` keys: ok, send_ready, webhook_ready, ai_auto_reply_enabled,
    gateway_fresh (bool). ``None`` means the health endpoint was unreachable.
    Pure function of (snapshot, state, now) — fully testable offline.
    """
    state = state if state is not None else STATE
    now = now or _now()

    if snapshot is None:
        decision = {
            "state": STATE_DEGRADED,
            "reasons": ["health_snapshot_unavailable"],
            "recommended_action": {
                "type": "manual_check",
                "detail": (
                    "Health endpoint unreachable; verify network/VPS before "
                    "dispatching any recovery workflow."
                ),
            },
            "escalate_to_owner": False,
            "auto_recovery_dispatched": False,
        }
        state["last_decision"] = decision["state"]
        return log_decision(decision)

    problems = _problems_in_snapshot(snapshot)

    if not problems:
        if state.get("pending_recovery"):
            # A dispatched recovery resolved the problems: clear the flag.
            state["pending_recovery"] = False
            state["failed_recoveries"] = 0
        decision = {
            "state": STATE_HEALTHY,
            "reasons": [],
            "recommended_action": None,
            "escalate_to_owner": False,
            "auto_recovery_dispatched": False,
        }
        state["last_decision"] = decision["state"]
        return log_decision(decision)

    # Problems exist. First account for any previously dispatched recovery.
    if state.get("pending_recovery"):
        last_attempt = _parse_ts(state.get("last_recovery_attempt"))
        if last_attempt and now - last_attempt < RECOVERY_COOLDOWN:
            decision = {
                "state": STATE_DEGRADED,
                "reasons": problems + ["recovery_in_progress_within_cooldown"],
                "recommended_action": {
                    "type": "wait",
                    "detail": "Recovery dispatched recently; waiting for it to take effect.",
                },
                "escalate_to_owner": False,
                "auto_recovery_dispatched": False,
            }
            state["last_decision"] = decision["state"]
            return log_decision(decision)
        # Cooldown expired and problems persist: that recovery failed.
        state["failed_recoveries"] = int(state.get("failed_recoveries") or 0) + 1
        state["pending_recovery"] = False

    if int(state.get("failed_recoveries") or 0) >= MAX_FAILED_RECOVERIES:
        decision = {
            "state": STATE_CRITICAL,
            "reasons": problems
            + [f"max_failed_recoveries_reached ({MAX_FAILED_RECOVERIES})"],
            "recommended_action": {
                "type": "escalate",
                "detail": (
                    "Automatic recovery failed 3 times. Stop auto-retrying; "
                    "Juan must decide the next step."
                ),
            },
            "escalate_to_owner": True,
            "auto_recovery_dispatched": False,
        }
        state["last_decision"] = decision["state"]
        return log_decision(decision)

    last_attempt = _parse_ts(state.get("last_recovery_attempt"))
    if last_attempt and now - last_attempt < RECOVERY_COOLDOWN:
        decision = {
            "state": STATE_DEGRADED,
            "reasons": problems + ["recovery_cooldown_active"],
            "recommended_action": {
                "type": "wait",
                "detail": "Recovery attempted within the last 30 minutes; not re-triggering.",
            },
            "escalate_to_owner": False,
            "auto_recovery_dispatched": False,
        }
    else:
        decision = {
            "state": STATE_DEGRADED,
            "reasons": problems,
            "recommended_action": {
                "type": "dispatch_workflow",
                "workflow": SAFE_CLEAN_WORKFLOW,
                "ref": WORKFLOW_REF,
                "via": "gh workflow run",
                "detail": (
                    "Dispatch 'Hostinger Hermes Safe Clean' to reset the Hermes "
                    "session cache and restart the gateway."
                ),
            },
            "escalate_to_owner": False,
            "auto_recovery_dispatched": False,
        }
    state["last_decision"] = decision["state"]
    return log_decision(decision)


def trigger_recovery(
    *,
    dry_run: bool = True,
    workflow: str = SAFE_CLEAN_WORKFLOW,
    ref: str = WORKFLOW_REF,
    state: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Dispatch the Safe Clean recovery workflow (thin, dry-run testable).

    With ``dry_run=True`` (default) nothing executes: the exact command is
    returned. With ``dry_run=False`` the command runs via subprocess and the
    watchdog state is updated (pending_recovery=True on success).
    """
    state = state if state is not None else STATE
    now = now or _now()
    command = ["gh", "workflow", "run", workflow, "--ref", ref]
    if dry_run:
        return {
            "dry_run": True,
            "dispatched": False,
            "command": command,
            "workflow": workflow,
            "ref": ref,
        }
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except Exception as exc:
        return {
            "dry_run": False,
            "dispatched": False,
            "command": command,
            "error": f"{type(exc).__name__}: {exc}",
        }
    ok = proc.returncode == 0
    if ok:
        state["last_recovery_attempt"] = now.isoformat()
        state["pending_recovery"] = True
    return {
        "dry_run": False,
        "dispatched": ok,
        "command": command,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-2000:],
    }


def note_recovery_outcome(
    success: bool, *, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Record the verified outcome of a dispatched recovery.

    Call after re-evaluating health post-recovery. ``success=True`` clears the
    failure counter; ``success=False`` counts one failed recovery immediately.
    """
    state = state if state is not None else STATE
    if success:
        state["pending_recovery"] = False
        state["failed_recoveries"] = 0
    else:
        state["pending_recovery"] = False
        state["failed_recoveries"] = int(state.get("failed_recoveries") or 0) + 1
    return {
        "failed_recoveries": state["failed_recoveries"],
        "escalated": int(state["failed_recoveries"] or 0) >= MAX_FAILED_RECOVERIES,
    }


def fetch_live_snapshot(timeout: int = HEALTH_TIMEOUT_SECONDS) -> dict[str, Any] | None:
    """Fetch the live health snapshot (network). Returns None when unreachable.

    Combines the public ``/whatsapp/health`` endpoint with the local Hermes
    gateway freshness check from ``whatsapp_self_healing`` (lazy import so this
    module stays importable even if that stack is unavailable).
    """
    snapshot: dict[str, Any] = {
        "ok": False,
        "send_ready": False,
        "webhook_ready": False,
        "ai_auto_reply_enabled": False,
        "gateway_fresh": None,
    }
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        snapshot["ok"] = str(data.get("status") or "").lower() == "ok"
        snapshot["send_ready"] = bool(data.get("send_ready"))
        snapshot["webhook_ready"] = bool(data.get("webhook_ready"))
        snapshot["ai_auto_reply_enabled"] = bool(data.get("ai_auto_reply_enabled"))
    except Exception:
        return None
    try:
        from whatsapp_self_healing import _gateway_state  # lazy, optional

        import asyncio

        gw = asyncio.run(_gateway_state("hermes-hostinger"))
        snapshot["gateway_fresh"] = bool(gw.get("heartbeat_fresh"))
    except Exception:
        snapshot["gateway_fresh"] = None
    return snapshot
