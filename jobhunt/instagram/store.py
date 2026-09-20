"""SQLite-backed dedupe/audit store for Instagram webhook events."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class WebhookStore:
    def __init__(self, path: str | Path = "instagram_webhook.sqlite3"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS webhook_events (
                    event_key TEXT PRIMARY KEY,
                    comment_id TEXT NOT NULL,
                    media_id TEXT,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    processed_at TEXT
                )"""
            )
            db.commit()

    def claim(self, event_key: str, comment_id: str, media_id: str, payload_json: str, created_at: str) -> bool:
        with sqlite3.connect(self.path) as db:
            cur = db.execute(
                """INSERT OR IGNORE INTO webhook_events
                (event_key, comment_id, media_id, payload_json, status, created_at)
                VALUES (?, ?, ?, ?, 'RECEIVED', ?)""",
                (event_key, comment_id, media_id, payload_json, created_at),
            )
            db.commit()
            return cur.rowcount == 1

    def update(self, event_key: str, status: str, *, error: str | None = None, processed_at: str | None = None) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE webhook_events SET status=?, error=?, processed_at=? WHERE event_key=?",
                (status, error, processed_at, event_key),
            )
            db.commit()

    def has_event(self, event_key: str) -> bool:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT 1 FROM webhook_events WHERE event_key=?", (event_key,)).fetchone()
        return row is not None
