"""SQLite event-log storage primitives."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def database_path() -> Path:
    """Resolve the SQLite path without requiring configuration."""
    return Path(os.environ.get("DATABASE_PATH", "data/events.sqlite3"))


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(path: Path | None = None) -> None:
    """Create the session event-log schema if it does not exist."""
    with connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS events_by_session ON events(session_id, id)"
        )


def append_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
    path: Path | None = None,
) -> int:
    """Append one JSON event and return its row id."""
    created_at = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO events (session_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, event_type, json.dumps(payload, separators=(",", ":")), created_at),
        )
        return int(cursor.lastrowid)
