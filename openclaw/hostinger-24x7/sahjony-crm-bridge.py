#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

SIGNATURE_VERSION = "crm-v1"
DEFAULT_APP_URL = "https://www.sahjony.com"
MUTATING_ACTIONS = {"sync", "note", "intake", "outreach-pilot"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str]) -> str:
    try:
        completed = subprocess.run(cmd, text=True, capture_output=True, timeout=15, check=False)
    except Exception:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def parse_env_text(text: str, key: str) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip("\"'")
    return ""


def host_env_file_value(key: str) -> str:
    for path in (
        pathlib.Path("/opt/sahjony-openclaw/.env"),
        pathlib.Path("/opt/sahjony/openclaw/.env"),
    ):
        try:
            if path.is_file():
                value = parse_env_text(path.read_text(errors="ignore"), key)
                if value:
                    return value
        except Exception:
            pass
    return ""


def find_openclaw_container() -> str:
    output = run(["docker", "ps", "-a", "--format", "{{.ID}}|{{.Names}}|{{.Image}}"])
    for line in output.splitlines():
        lowered = line.lower()
        if "openclaw" in lowered or "claw" in lowered:
            return line.split("|", 1)[0].strip()
    return ""


def container_env_value(container: str, key: str) -> str:
    if not container:
        return ""
    output = run(["docker", "inspect", container, "--format", "{{range .Config.Env}}{{println .}}{{end}}"])
    value = parse_env_text(output, key)
    if value:
        return value
    for path in ("$HOME/.openclaw/.env", "/root/.openclaw/.env", "/home/node/.openclaw/.env"):
        text = run(["docker", "exec", container, "sh", "-lc", f"cat {path} 2>/dev/null || true"])
        value = parse_env_text(text, key)
        if value:
            return value
    return ""


def discover_value(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    for key in keys:
        value = host_env_file_value(key)
        if value:
            return value
    container = find_openclaw_container()
    for key in keys:
        value = container_env_value(container, key)
        if value:
            return value
    return ""


def bridge_secret() -> str:
    value = discover_value("OPENCLAW_APP_BRIDGE_SECRET", "SAHJONY_APP_BRIDGE_SECRET")
    if len(value) < 24:
        raise RuntimeError("authorized_bridge_secret_unavailable")
    return value


def app_url() -> str:
    return (discover_value("SAHJONY_APP_URL") or DEFAULT_APP_URL).rstrip("/")


def state_dir() -> pathlib.Path:
    requested = os.getenv("SAHJONY_CRM_BRIDGE_STATE_DIR", "").strip()
    candidates = [pathlib.Path(requested)] if requested else [pathlib.Path("/var/lib/sahjony-crm-bridge")]
    candidates.append(pathlib.Path.home() / ".local" / "state" / "sahjony-crm-bridge")
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, 0o700)
            return path
        except Exception:
            continue
    raise RuntimeError("crm_bridge_state_directory_unavailable")


def queue_file() -> pathlib.Path:
    return state_dir() / "pending.jsonl"


def status_file() -> pathlib.Path:
    return state_dir() / "status.json"


def json_bytes(payload: dict[str, Any] | None) -> bytes:
    if payload is None:
        return b""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def signature(secret: str, *, timestamp: str, nonce: str, method: str, path: str, raw: bytes) -> str:
    body_hash = hashlib.sha256(raw).hexdigest()
    material = f"{SIGNATURE_VERSION}\n{timestamp}\n{nonce}\n{method.upper()}\n{path}\n{body_hash}".encode("utf-8")
    return "sha256=" + hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()


def request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = json_bytes(payload)
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    secret = bridge_secret()
    headers = {
        "Accept": "application/json",
        "X-SAHJONY-Timestamp": timestamp,
        "X-SAHJONY-Nonce": nonce,
        "X-SAHJONY-CRM-Signature": signature(
            secret,
            timestamp=timestamp,
            nonce=nonce,
            method=method,
            path=path,
            raw=raw,
        ),
    }
    del secret
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        app_url() + path,
        data=raw if payload is not None else None,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            body = response.read().decode("utf-8", errors="replace")
            data = json.loads(body) if body else {}
            if not isinstance(data, dict):
                return {"status": "error", "error": "invalid_json_response"}
            return data
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        try:
            detail = json.loads(body)
        except Exception:
            detail = body
        raise RuntimeError(f"crm_bridge_http_{exc.code}:{detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"crm_bridge_unreachable:{type(exc).__name__}") from exc


def ensure_operation_id(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.setdefault("operation_id", f"oc_{uuid.uuid4().hex}")
    return result


def spool(action: str, payload: dict[str, Any], error: str) -> None:
    path = queue_file()
    row = {
        "queue_id": f"q_{uuid.uuid4().hex}",
        "action": action,
        "payload": payload,
        "queued_at": now_iso(),
        "last_error": error[:500],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)


def pending_count() -> int:
    path = queue_file()
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip())
    except Exception:
        return 0


def endpoint(action: str) -> tuple[str, str]:
    mapping = {
        "health": ("GET", "/whatsapp/crm/health"),
        "contact": ("POST", "/whatsapp/crm/contact"),
        "sync": ("POST", "/whatsapp/crm/sync"),
        "note": ("POST", "/whatsapp/crm/note"),
        "intake": ("POST", "/whatsapp/crm/intake"),
        "outreach-pilot": ("POST", "/whatsapp/crm/outreach-pilot"),
        "outreach-status": ("POST", "/whatsapp/crm/outreach-pilot/status"),
    }
    return mapping[action]


def perform(action: str, payload: dict[str, Any] | None = None, *, queue_on_failure: bool = True) -> dict[str, Any]:
    method, path = endpoint(action)
    body = ensure_operation_id(payload or {}) if action in MUTATING_ACTIONS else payload
    try:
        return request_json(method, path, body)
    except Exception as exc:
        if queue_on_failure and action in MUTATING_ACTIONS and body is not None:
            spool(action, body, str(exc))
            return {
                "status": "deferred",
                "action": action,
                "operation_id": body.get("operation_id"),
                "queued_locally": True,
                "pending_count": pending_count(),
                "error": str(exc).split(":", 1)[0],
            }
        raise


def flush_queue() -> dict[str, Any]:
    path = queue_file()
    if not path.exists():
        return {"status": "ok", "flushed": 0, "remaining": 0}
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except Exception:
            continue

    remaining: list[dict[str, Any]] = []
    flushed = 0
    for item in rows:
        action = str(item.get("action") or "")
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if action not in MUTATING_ACTIONS:
            continue
        try:
            result = perform(action, payload, queue_on_failure=False)
            if result.get("status") in {"synced", "recorded", "created", "duplicate"}:
                flushed += 1
            else:
                item["last_error"] = f"unexpected_status:{result.get('status')}"
                remaining.append(item)
        except Exception as exc:
            item["last_error"] = str(exc)[:500]
            item["last_attempt_at"] = now_iso()
            remaining.append(item)

    tmp = path.with_suffix(".tmp")
    if remaining:
        tmp.write_text(
            "".join(json.dumps(item, separators=(",", ":"), ensure_ascii=False) + "\n" for item in remaining),
            encoding="utf-8",
        )
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return {"status": "ok" if not remaining else "degraded", "flushed": flushed, "remaining": len(remaining)}


def write_status(data: dict[str, Any]) -> None:
    path = status_file()
    safe = dict(data)
    safe["updated_at"] = now_iso()
    path.write_text(json.dumps(safe, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def doctor() -> dict[str, Any]:
    flush = flush_queue()
    try:
        health = perform("health", None, queue_on_failure=False)
    except Exception as exc:
        health = {"status": "degraded", "error": str(exc).split(":", 1)[0]}
    result = {
        "status": "ok" if health.get("status") == "ok" and flush.get("remaining", 0) == 0 else "degraded",
        "health": health,
        "queue": flush,
        "pending_count": pending_count(),
    }
    write_status(result)
    return result


def payload_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "json", None):
        raw = sys.stdin.read() if args.json == "-" else args.json
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("payload_must_be_json_object")
        return data
    if args.action == "contact":
        return {"phone": args.phone}
    return {}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Authorized SAHJONY OpenClaw CRM bridge")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("health")
    contact = sub.add_parser("contact")
    contact.add_argument("phone")
    for action in ("sync", "note", "intake", "outreach-pilot", "outreach-status"):
        item = sub.add_parser(action)
        item.add_argument("--json", required=True, help="JSON object, or '-' to read JSON from stdin")
    sub.add_parser("flush")
    sub.add_parser("doctor")
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        if args.action == "flush":
            result = flush_queue()
        elif args.action == "doctor":
            result = doctor()
        else:
            payload = payload_from_args(args)
            result = perform(args.action, payload if args.action != "health" else None)
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
        return 0 if result.get("status") != "error" else 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc).split(":", 1)[0]}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
