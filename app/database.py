from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.models import MessageChannel, MessageDirection, StoredMessage


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    external_id TEXT,
                    channel TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(channel, external_id)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_chat
                    ON messages(channel, chat_id, created_at);

                CREATE TABLE IF NOT EXISTS avito_tokens (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    access_token TEXT NOT NULL,
                    token_type TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def has_message(self, channel: MessageChannel, external_id: str) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM messages WHERE channel = ? AND external_id = ?",
                (channel, external_id),
            ).fetchone()
            return row is not None

    def save_message(
        self,
        *,
        channel: MessageChannel,
        chat_id: str,
        direction: MessageDirection,
        text: str,
        external_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self.connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO messages
                    (external_id, channel, chat_id, direction, text, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (external_id, channel, chat_id, direction, text, timestamp.isoformat()),
            )

    def get_history(
        self,
        *,
        channel: MessageChannel,
        chat_id: str,
        limit: int = 20,
    ) -> list[StoredMessage]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM messages
                WHERE channel = ? AND chat_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (channel, chat_id, limit),
            ).fetchall()

        return [
            StoredMessage(
                id=row["id"],
                external_id=row["external_id"],
                channel=row["channel"],
                chat_id=row["chat_id"],
                direction=row["direction"],
                text=row["text"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in reversed(rows)
        ]

    def save_avito_token(
        self,
        *,
        access_token: str,
        token_type: str,
        expires_at: datetime,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO avito_tokens
                    (id, access_token, token_type, expires_at, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    access_token = excluded.access_token,
                    token_type = excluded.token_type,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (access_token, token_type, expires_at.astimezone(timezone.utc).isoformat(), now),
            )

    def get_avito_token(self) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM avito_tokens WHERE id = 1").fetchone()
