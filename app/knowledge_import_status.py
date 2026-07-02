from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import BASE_DIR

IMPORT_HISTORY_PATH = BASE_DIR / "data" / "import_history.sqlite"


@dataclass(frozen=True)
class ImportStatus:
    processed_documents: int
    new_documents: int
    skipped_documents: int
    errors: int


def ensure_import_history(db_path: Path = IMPORT_HISTORY_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS import_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                import_date TEXT NOT NULL,
                document_type TEXT NOT NULL,
                chunks_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        db.execute("DROP INDEX IF EXISTS idx_import_history_sha256")
        db.execute("CREATE INDEX IF NOT EXISTS idx_import_history_sha256 ON import_history(sha256)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_import_history_status ON import_history(status)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_date TEXT NOT NULL,
                processed_count INTEGER NOT NULL,
                new_count INTEGER NOT NULL,
                skipped_count INTEGER NOT NULL,
                errors_count INTEGER NOT NULL
            )
            """
        )


def read_import_status(db_path: Path = IMPORT_HISTORY_PATH) -> ImportStatus:
    ensure_import_history(db_path)
    with sqlite3.connect(db_path) as db:
        processed_total = db.execute(
            "SELECT COUNT(*) FROM import_history WHERE status = 'processed'"
        ).fetchone()[0]
        last_run = db.execute(
            """
            SELECT new_count, skipped_count, errors_count
            FROM import_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    new_count, skipped_count, errors_count = last_run if last_run else (0, 0, 0)
    return ImportStatus(
        processed_documents=int(processed_total),
        new_documents=int(new_count),
        skipped_documents=int(skipped_count),
        errors=int(errors_count),
    )


def record_import_run(
    *,
    processed_count: int,
    new_count: int,
    skipped_count: int,
    errors_count: int,
    db_path: Path = IMPORT_HISTORY_PATH,
) -> None:
    ensure_import_history(db_path)
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT INTO import_runs
                (import_date, processed_count, new_count, skipped_count, errors_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                processed_count,
                new_count,
                skipped_count,
                errors_count,
            ),
        )
