from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import IncomingMessage


class StateStore:
    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    sender_open_id TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL,
                    source_url TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    content_id TEXT,
                    document_url TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS videos (
                    content_id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    document_url TEXT NOT NULL,
                    document_token TEXT NOT NULL,
                    wiki_node_token TEXT NOT NULL,
                    base_record_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status, created_at);
                """
            )

    def claim_message(self, message: IncomingMessage, source_url: str | None) -> bool:
        timestamp = int(time.time())
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO messages(message_id, chat_id, sender_open_id, text, source_url, status, "
                "created_at, updated_at) VALUES(?, ?, ?, ?, ?, 'queued', ?, ?)",
                (
                    message.message_id,
                    message.chat_id,
                    message.sender_open_id,
                    message.text,
                    source_url,
                    timestamp,
                    timestamp,
                ),
            )
        return cursor.rowcount == 1

    def update_message(self, message_id: str, status: str, **values: str | None) -> None:
        allowed = {"error", "content_id", "document_url"}
        changes = {key: value for key, value in values.items() if key in allowed}
        changes["status"] = status
        changes["updated_at"] = int(time.time())
        statement = ", ".join(f"{key} = ?" for key in changes)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE messages SET {statement} WHERE message_id = ?",
                (*changes.values(), message_id),
            )

    def get_video(self, content_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM videos WHERE content_id = ?", (content_id,)
            ).fetchone()

    def save_video(
        self,
        *,
        content_id: str,
        source_url: str,
        title: str,
        document_url: str,
        document_token: str,
        wiki_node_token: str,
        base_record_id: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO videos(content_id, source_url, title, document_url, document_token, "
                "wiki_node_token, base_record_id, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(content_id) DO UPDATE SET source_url=excluded.source_url, title=excluded.title, "
                "document_url=excluded.document_url, document_token=excluded.document_token, "
                "wiki_node_token=excluded.wiki_node_token, base_record_id=excluded.base_record_id",
                (
                    content_id,
                    source_url,
                    title,
                    document_url,
                    document_token,
                    wiki_node_token,
                    base_record_id,
                    int(time.time()),
                ),
            )

    def recoverable_messages(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE status IN ('queued', 'downloading', 'analyzing', 'archiving') "
                "ORDER BY created_at"
            ).fetchall()
        return list(rows)

