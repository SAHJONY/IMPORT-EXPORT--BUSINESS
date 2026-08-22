from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def _database_path() -> Path:
    """Return a writable path for the legacy SQLite compatibility layer.

    InsForge is the production persistence target. SQLite remains only for legacy
    participant/submission endpoints while those routes are migrated. Vercel's
    deployed function bundle is read-only, so any temporary compatibility DB must
    live under /tmp and must never initialize at module import time.
    """
    configured = os.getenv("LEGACY_SQLITE_PATH")
    if configured:
        return Path(configured)
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return Path("/tmp/import-export-business.db")
    return Path(__file__).with_name("business.db")


DB_PATH = _database_path()
_initialized = False


def _initialize(conn: sqlite3.Connection) -> None:
    global _initialized
    if _initialized:
        return

    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id TEXT NOT NULL,
            participant_id TEXT NOT NULL,
            data_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS participants (
            participant_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    columns = {row[1] for row in cur.execute("PRAGMA table_info(participants)").fetchall()}
    if "token_hash" not in columns:
        cur.execute("ALTER TABLE participants ADD COLUMN token_hash TEXT")
    conn.commit()
    _initialized = True


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _initialize(conn)
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.close()
