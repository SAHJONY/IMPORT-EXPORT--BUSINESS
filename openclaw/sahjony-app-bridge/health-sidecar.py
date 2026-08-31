#!/usr/bin/env python3
"""Independent SAHJONY/OpenClaw WhatsApp health reporter.

Runs outside the OpenClaw plugin runtime so health reporting does not depend on
plugin subprocess semantics. It probes the real OpenClaw CLI, signs the same
HMAC heartbeat used by the application bridge, and posts authoritative channel
state to SAHJONY.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
STATE_DIR = Path(os.environ.get("OPENCLAW_STATE_DIR", HOME / ".openclaw"))
ENV_FILE = STATE_DIR / ".env"
OPENCLAW_BIN = os.environ.get("OPENCLAW_BIN", str(STATE_DIR / "bin" / "openclaw"))
APP_URL = os.environ.get("SAHJONY_APP_URL", "https://www.sahjony.com").rstrip("/")
ACCOUNT_ID = os.environ.get("SAHJONY_WHATSAPP_ACCOUNT_ID", "default")
BUSINESS_NUMBER = os.environ.get("SAHJONY_WHATSAPP_BUSINESS_NUMBER", "+12816628581")
BUSINESS_NAME = os.environ.get("SAHJONY_WHATSAPP_BUSINESS_NAME", "SAHJONY LLC")
MODEL = os.environ.get("SAHJONY_REASONING_MODEL", "gpt-5.6-sol")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def run_openclaw(*args: str, timeout: int = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [OPENCLAW_BIN, *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            env={**os.environ, "HOME": str(HOME)},
        )
        return proc.returncode, proc.stdout or ""
    except Exception as exc:
        return 127, f"{type(exc).__name__}: {exc}"


def probe() -> dict[str, object]:
    status_code, status_output = run_openclaw("channels", "status", "--probe")
    version_code, version_output = run_openclaw("--version", timeout=10)

    connected = bool(
        status_code == 0
        and (
            re.search(r"WhatsApp[^\n]*\bconnected\b", status_output, re.I)
            or re.search(r"linked,\s*running,\s*connected", status_output, re.I)
        )
    )
    healthy = bool(status_code == 0 and re.search(r"health:healthy", status_output, re.I))
    gateway_version = version_output.strip().splitlines()[0][:80] if version_code == 0 and version_output.strip() else None

    return {
        "connected": connected,
        "healthy": healthy,
        "gateway_version": gateway_version,
        "status_code": status_code,
        "status_excerpt": status_output[-1200:],
    }


def signed_post(secret: str, payload: dict[str, object]) -> tuple[int, str]:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    timestamp = str(int(time.time()))
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        f"{APP_URL}/whatsapp/openclaw/heartbeat",
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-SAHJONY-Timestamp": timestamp,
            "X-SAHJONY-Signature": f"sha256={digest}",
            "User-Agent": "SAHJONY-OpenClaw-Health-Sidecar/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return int(resp.status), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    env = read_env(ENV_FILE)
    secret = os.environ.get("SAHJONY_APP_BRIDGE_SECRET") or env.get("SAHJONY_APP_BRIDGE_SECRET", "")
    app_url = os.environ.get("SAHJONY_APP_URL") or env.get("SAHJONY_APP_URL")
    global APP_URL
    if app_url:
        APP_URL = app_url.rstrip("/")

    if len(secret) < 24:
        print(json.dumps({"ok": False, "error": "missing_or_short_bridge_secret", "env_file": str(ENV_FILE)}))
        return 2
    if not Path(OPENCLAW_BIN).exists():
        print(json.dumps({"ok": False, "error": "openclaw_binary_not_found", "openclaw_bin": OPENCLAW_BIN}))
        return 3

    state = probe()
    payload = {
        "gateway_id": "default",
        "account_id": ACCOUNT_ID,
        "channel_connected": bool(state["connected"] and state["healthy"]),
        "business_number": BUSINESS_NUMBER,
        "business_name": BUSINESS_NAME,
        "model": MODEL,
        "gateway_version": state["gateway_version"],
        "probe_source": "macos-health-sidecar-v1",
    }
    http_status, response = signed_post(secret, payload)
    result = {
        "ok": http_status == 200,
        "http_status": http_status,
        "payload": payload,
        "probe": state,
        "response_excerpt": response[:500],
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if http_status == 200 and payload["channel_connected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
