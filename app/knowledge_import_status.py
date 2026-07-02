from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import expertboat_data_dir

MANUALS_CATEGORIES = ("lowrance", "garmin", "simrad", "flir", "minnkota", "mercury", "yamaha")
SUPPORTED_IMPORT_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".json", ".jsonl"}


def import_history_path(data_dir: Path | None = None) -> Path:
    return (data_dir or expertboat_data_dir()) / "import_history.sqlite"


IMPORT_HISTORY_PATH = import_history_path()


@dataclass(frozen=True)
class ImportStatus:
    data_dir: Path
    processed_documents: int
    new_documents: int
    skipped_documents: int
    errors: int
    manuals_files: int
    processed_markdown: int
    review_files: int
    faq_files: int
    import_history_path: Path
    import_history_exists: bool


def ensure_external_data_directories(data_dir: Path | None = None) -> Path:
    root = data_dir or expertboat_data_dir()
    directories = [
        root / "manuals",
        root / "avito",
        root / "telegram",
        root / "processed",
        root / "review",
        root / "faq",
        root / "chunks",
        root / "listings",
    ]
    directories.extend(root / "manuals" / category for category in MANUALS_CATEGORIES)
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    return root


def ensure_import_history(db_path: Path | None = None) -> Path:
    db_path = db_path or import_history_path()
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
    return db_path


def count_files(root: Path, extensions: set[str] | None = None) -> int:
    if not root.exists():
        return 0
    files = [path for path in root.rglob("*") if path.is_file()]
    if extensions is None:
        return len(files)
    return sum(1 for path in files if path.suffix.casefold() in extensions)


def read_import_status(db_path: Path | None = None, data_dir: Path | None = None) -> ImportStatus:
    data_root = ensure_external_data_directories(data_dir)
    db_path = db_path or import_history_path(data_root)
    history_existed = db_path.exists()
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
        data_dir=data_root,
        processed_documents=int(processed_total),
        new_documents=int(new_count),
        skipped_documents=int(skipped_count),
        errors=int(errors_count),
        manuals_files=count_files(data_root / "manuals", SUPPORTED_IMPORT_EXTENSIONS),
        processed_markdown=count_files(data_root / "processed", {".md"}),
        review_files=count_files(data_root / "review", {".md"}),
        faq_files=count_files(data_root / "faq", {".md"}),
        import_history_path=db_path,
        import_history_exists=history_existed or db_path.exists(),
    )


def record_import_run(
    *,
    processed_count: int,
    new_count: int,
    skipped_count: int,
    errors_count: int,
    db_path: Path | None = None,
) -> None:
    db_path = db_path or import_history_path()
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
