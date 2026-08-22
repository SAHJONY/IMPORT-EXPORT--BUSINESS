import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("business.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
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
    conn.close()


init_db()
