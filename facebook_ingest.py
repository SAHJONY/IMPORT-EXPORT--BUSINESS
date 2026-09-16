#!/usr/bin/env python3
"""Facebook -> SAHJONY social inbox ingestion.

Read-only pull from Juan's Facebook presence (business Page, personal
profile, business group) into the app backend table `social_inbox_items`.

- Ingestion ONLY: never posts, comments, replies, reacts, or moderates.
  Every facebook-cli invocation below is a documented read command.
- Dedupe: rows carry `external_id`; the backend upserts on
  record_key `external_id:<value>`, so re-runs never duplicate.
- Incremental: per-source watermark (newest created_at seen) stored at
  $FACEBOOK_INGEST_STATE (default ~/.sahjony/facebook_ingest_state.json).
  Only items newer than the watermark are sent; pagination stops early
  once it reaches already-seen items.

Usage:
    ~/.venvs/fb-ingest/bin/python facebook_ingest.py [--limit-posts 20]
    # env: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (same as the app backend)
    #      FACEBOOK_INGEST_STATE (optional override for the watermark file)

Prints a JSON summary: counts per source, new items, errors.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

from insforge_backend import get_backend  # noqa: E402

PAGE_ID = "61593626378153"      # "Sahjony LLC" business Page
PROFILE_ID = "61592992839425"   # Juan Gonzalez personal profile
GROUP_ID = "1558873548822463"   # Importadores y Proveedores para Cuba | SAHJONY Global Trade

TABLE = "social_inbox_items"
TEXT_LIMIT = 2000
DEFAULT_STATE = os.path.expanduser("~/.sahjony/facebook_ingest_state.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value) -> str | None:
    """Normalize created_at (ISO string) or creation_time (unix) to ISO."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        s = str(value).strip()
        if not s:
            return None
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def _run_cli(*args: str) -> dict:
    """Run a read-only facebook-cli command; return parsed JSON ({} on failure)."""
    try:
        proc = subprocess.run(
            ["facebook-cli", *args], capture_output=True, text=True, timeout=90
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"_cli_error": f"exec failed: {exc}"}
    if proc.returncode != 0:
        return {"_cli_error": (proc.stderr or proc.stdout or "unknown error").strip()[:500]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_cli_error": "non-JSON output"[:500]}


def _fetch_timeline(profile_id: str, limit: int, since_iso: str | None) -> tuple[list[dict], str | None]:
    """Fetch timeline posts (newest first); stop at the watermark. Returns (posts, error)."""
    posts: list[dict] = []
    error: str | None = None
    after: str | None = None
    for _page in range(3):
        args = ["timeline", "fetch", "--profile-id", profile_id, "--limit", str(limit)]
        if after:
            args += ["--after", after]
        data = _run_cli(*args)
        if data.get("_cli_error"):
            error = data["_cli_error"]
            break
        batch = data.get("posts", []) or []
        for p in batch:
            ts = _parse_ts(p.get("created_at"))
            if since_iso and ts and ts <= since_iso:
                return posts, error  # reached already-synced items
            posts.append(p)
        after = data.get("next_cursor")
        if not data.get("has_next_page") or not after or not batch:
            break
    return posts, error


def _fetch_group_posts(limit: int, since_iso: str | None) -> tuple[list[dict], str | None]:
    data = _run_cli("groups", "posts", "--group-id", GROUP_ID)
    if data.get("_cli_error"):
        return [], data["_cli_error"]
    posts = []
    for p in data.get("data", []) or []:
        ts = _parse_ts(p.get("creation_time"))
        if since_iso and ts and ts <= since_iso:
            break
        posts.append(p)
    return posts, None


def _fetch_comments(post_id: str) -> tuple[list[dict], str | None]:
    comments: list[dict] = []
    error: str | None = None
    after: str | None = None
    for _page in range(3):
        args = ["post", "comments", "read", "--post-id", str(post_id), "--limit", "20"]
        if after:
            args += ["--after", after]
        data = _run_cli(*args)
        if data.get("_cli_error"):
            error = data["_cli_error"]
            break
        batch = data.get("data", []) or []
        comments.extend(batch)
        after = (data.get("paging", {}) or {}).get("cursors", {}).get("after")
        if not after or not batch:
            break
    return comments, error


def _excerpt(text: str | None) -> str:
    return (text or "").strip()[:TEXT_LIMIT]


def _normalize_post(p: dict, source: str, post_id: str, permalink: str,
                    author: str | None, created_iso: str | None, text: str) -> dict:
    return {
        "external_id": f"fb:post:{post_id}",
        "platform": "facebook",
        "source": source,  # page | profile | group
        "item_type": "post",
        "permalink": permalink or "",
        "author_name": (author or "").strip()[:200],
        "created_at": created_iso or "",
        "text": _excerpt(text),
        "parent_external_id": "",
        "synced_at": _now_iso(),
    }


def _normalize_comment(c: dict, source: str, parent_external_id: str) -> dict:
    cid = str(c.get("id", ""))
    return {
        "external_id": f"fb:comment:{cid}",
        "platform": "facebook",
        "source": source,
        "item_type": "comment",
        "permalink": c.get("comment_url", "") or "",
        "author_name": str(c.get("author_name", "") or "").strip()[:200],
        "created_at": _parse_ts(c.get("created_time")) or "",
        "text": _excerpt(c.get("text")),
        "parent_external_id": parent_external_id,
        "synced_at": _now_iso(),
    }


def _load_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


async def main() -> int:
    ap = argparse.ArgumentParser(description="Sync Facebook presence into social_inbox_items (read-only).")
    ap.add_argument("--limit-posts", type=int, default=20)
    ap.add_argument("--max-comments-per-post", type=int, default=20)
    ap.add_argument("--state", default=os.environ.get("FACEBOOK_INGEST_STATE", DEFAULT_STATE))
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and normalize from Facebook but do not write to the backend.")
    args = ap.parse_args()

    state = _load_state(args.state)
    backend = None if args.dry_run else get_backend()
    summary: dict = {"synced_at": _now_iso(), "sources": {}, "total_new": 0, "total_errors": 0}

    sources = [
        {"key": "page", "kind": "timeline", "profile_id": PAGE_ID, "label": "Sahjony LLC Page"},
        {"key": "profile", "kind": "timeline", "profile_id": PROFILE_ID, "label": "Juan Gonzalez profile"},
        {"key": "group", "kind": "group", "label": "Importadores y Proveedores para Cuba"},
    ]

    for src in sources:
        key = src["key"]
        since = (state.get(key) or {}).get("newest_created_at")
        ssum: dict = {"posts": 0, "comments": 0, "new_items": 0, "error": None}
        rows: list[dict] = []
        newest = since or ""

        try:
            if src["kind"] == "timeline":
                posts, err = _fetch_timeline(src["profile_id"], args.limit_posts, since)
                if err:
                    ssum["error"] = err
                for p in posts:
                    pid = str(p.get("post_id", ""))
                    created = _parse_ts(p.get("created_at"))
                    row = _normalize_post(p, key, pid, p.get("url", ""),
                                          p.get("author_name"), created,
                                          p.get("post_caption") or p.get("media_summary") or "")
                    rows.append(row)
                    ssum["posts"] += 1
                    if created and created > newest:
                        newest = created
                    comments, cerr = _fetch_comments(pid)
                    if cerr and not ssum["error"]:
                        ssum["error"] = f"comments: {cerr}"
                    for c in comments[: args.max_comments_per_post]:
                        rows.append(_normalize_comment(c, key, row["external_id"]))
                        ssum["comments"] += 1
                        cts = _parse_ts(c.get("created_time"))
                        if cts and cts > newest:
                            newest = cts
            else:
                posts, err = _fetch_group_posts(args.limit_posts, since)
                if err:
                    ssum["error"] = err
                for p in posts:
                    pid = str(p.get("id", ""))
                    created = _parse_ts(p.get("creation_time"))
                    row = _normalize_post(p, key, pid, p.get("post_url", ""),
                                          None, created, p.get("content"))
                    if not row["author_name"]:
                        row["author_name"] = src["label"]
                    rows.append(row)
                    ssum["posts"] += 1
                    if created and created > newest:
                        newest = created
                    if int(p.get("comment_count") or 0) > 0:
                        comments, cerr = _fetch_comments(pid)
                        if cerr and not ssum["error"]:
                            ssum["error"] = f"comments: {cerr}"
                        for c in comments[: args.max_comments_per_post]:
                            rows.append(_normalize_comment(c, key, row["external_id"]))
                            ssum["comments"] += 1
                            cts = _parse_ts(c.get("created_time"))
                            if cts and cts > newest:
                                newest = cts
        except Exception as exc:  # never let one source kill the run
            ssum["error"] = f"unexpected: {exc}"[:300]

        # Upsert (dedupe on external_id via backend record_key conflict handling).
        # Only send items newer than the watermark to keep runs incremental;
        # the upsert itself is idempotent for anything already stored.
        fresh = [r for r in rows if not since or not r["created_at"] or r["created_at"] > since]
        if fresh and backend is not None:
            await backend.insert(TABLE, fresh)
        ssum["new_items"] = len(fresh)
        summary["total_new"] += len(fresh)
        if ssum["error"]:
            # The business Page is server-side gated (403) for this CLI identity:
            # permanent platform limitation, not a sync failure. Surface it in the
            # summary but don't fail the run over it every time.
            if key == "page" and "403" in ssum["error"]:
                ssum["degraded"] = "page_not_readable_via_cli"
            else:
                summary["total_errors"] += 1
        if newest and newest != (since or ""):
            state[key] = {"newest_created_at": newest, "synced_at": _now_iso()}
        summary["sources"][key] = ssum

    _save_state(args.state, state)
    summary["state_file"] = args.state
    summary["dry_run"] = bool(args.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["total_errors"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
