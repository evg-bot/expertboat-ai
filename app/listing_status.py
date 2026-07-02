from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.config import expertboat_data_dir


def listings_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or expertboat_data_dir()) / "listings"


def listings_sqlite_path(data_dir: Path | None = None) -> Path:
    return listings_dir(data_dir) / "listings.sqlite"


@dataclass(frozen=True)
class ListingStatus:
    sqlite_path: Path
    sqlite_exists: bool
    listings_count: int
    active_count: int
    unknown_count: int
    last_updated: str
    recent: list[tuple[str, str]]


def read_listing_status(data_dir: Path | None = None) -> ListingStatus:
    db_path = listings_sqlite_path(data_dir)
    if not db_path.exists():
        return ListingStatus(
            sqlite_path=db_path,
            sqlite_exists=False,
            listings_count=0,
            active_count=0,
            unknown_count=0,
            last_updated="",
            recent=[],
        )

    with sqlite3.connect(db_path) as db:
        listings_count = db.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        active_count = db.execute("SELECT COUNT(*) FROM listings WHERE status = 'active'").fetchone()[0]
        unknown_count = db.execute("SELECT COUNT(*) FROM listings WHERE status = 'unknown'").fetchone()[0]
        last_updated = db.execute("SELECT MAX(updated_at) FROM listings").fetchone()[0] or ""
        recent = db.execute(
            """
            SELECT title, price_text
            FROM listings
            ORDER BY updated_at DESC, title ASC
            LIMIT 5
            """
        ).fetchall()

    return ListingStatus(
        sqlite_path=db_path,
        sqlite_exists=True,
        listings_count=int(listings_count),
        active_count=int(active_count),
        unknown_count=int(unknown_count),
        last_updated=str(last_updated),
        recent=[(str(title), str(price_text)) for title, price_text in recent],
    )
