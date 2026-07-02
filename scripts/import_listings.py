from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import expertboat_data_dir
from app.knowledge_import_status import ensure_external_data_directories


LISTING_FIELDS = (
    "listing_id",
    "url",
    "title",
    "price",
    "price_text",
    "currency",
    "status",
    "description",
    "brand",
    "series",
    "model",
    "screen_size",
    "transducer",
    "firmware",
    "category",
    "photos_json",
    "attributes_json",
    "content_hash",
    "first_seen",
    "last_seen",
    "updated_at",
)

HISTORY_FIELDS = (
    "title",
    "price",
    "price_text",
    "status",
    "description",
    "brand",
    "series",
    "model",
    "screen_size",
    "transducer",
    "firmware",
    "category",
    "photos_json",
    "attributes_json",
)


@dataclass(frozen=True)
class ListingRecord:
    listing_id: str
    url: str
    title: str
    price: int
    price_text: str
    currency: str
    status: str
    description: str
    brand: str
    series: str
    model: str
    screen_size: str
    transducer: str
    firmware: str
    category: str
    photos_json: str
    attributes_json: str
    content_hash: str
    first_seen: str
    last_seen: str
    updated_at: str


@dataclass(frozen=True)
class ListingImportStats:
    data_dir: Path
    input_source: str
    raw_listings_loaded: int
    fallback_listings_from_qa: int
    inserted: int
    updated: int
    unchanged: int
    history_changes: int
    unique_listings_exported: int
    duplicate_fallback_rows_merged: int
    sqlite_path: Path
    cleaned_output: Path


def listings_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or expertboat_data_dir()) / "listings"


def raw_path(data_dir: Path | None = None) -> Path:
    return listings_dir(data_dir) / "listings_raw.jsonl"


def cleaned_path(data_dir: Path | None = None) -> Path:
    return listings_dir(data_dir) / "listings_cleaned.jsonl"


def history_jsonl_path(data_dir: Path | None = None) -> Path:
    return listings_dir(data_dir) / "listing_history.jsonl"


def sqlite_path(data_dir: Path | None = None) -> Path:
    return listings_dir(data_dir) / "listings.sqlite"


def avito_qa_path(data_dir: Path | None = None) -> Path:
    return (data_dir or expertboat_data_dir()) / "processed" / "avito_qa.jsonl"


def ensure_listing_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS listings (
                listing_id TEXT PRIMARY KEY,
                url TEXT,
                title TEXT,
                price INTEGER,
                price_text TEXT,
                currency TEXT DEFAULT 'RUB',
                status TEXT,
                description TEXT,
                brand TEXT,
                series TEXT,
                model TEXT,
                screen_size TEXT,
                transducer TEXT,
                firmware TEXT,
                category TEXT,
                photos_json TEXT,
                attributes_json TEXT,
                content_hash TEXT,
                first_seen TEXT,
                last_seen TEXT,
                updated_at TEXT
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS listing_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT,
                changed_at TEXT,
                field TEXT,
                old_value TEXT,
                new_value TEXT
            )
            """
        )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_price(price_value: Any) -> tuple[int, str, str]:
    if price_value is None:
        return 0, "", "RUB"
    if isinstance(price_value, int):
        return price_value, f"{price_value:,}".replace(",", " ") + " ₽", "RUB"
    price_text = str(price_value).replace("\u00a0", " ").strip()
    digits = re.findall(r"\d+", price_text)
    price = int("".join(digits)) if digits else 0
    currency = "RUB" if "₽" in price_text or "руб" in price_text.casefold() else "RUB"
    return price, price_text, currency


def listing_id_from_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"_(\d{6,})(?:[/?#]|$)", url)
    if match:
        return match.group(1)
    match = re.search(r"/(\d{6,})(?:[/?#]|$)", url)
    return match.group(1) if match else ""


def stable_listing_id(title: str, price_text: str) -> str:
    digest = hashlib.sha1(f"{title}|{price_text}".encode("utf-8")).hexdigest()
    return f"sha1-{digest[:16]}"


def normalize_title(text: str) -> str:
    text = str(text or "").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip(" -–—:;,.")


def extract_title_fields(title: str) -> dict[str, str]:
    normalized = normalize_title(title)
    lower = normalized.casefold()
    fields = {
        "brand": "",
        "series": "",
        "model": "",
        "screen_size": "",
        "transducer": "",
        "firmware": "",
        "category": "",
    }

    if "lowrance" in lower or "activetarget" in lower or "active target" in lower:
        fields["brand"] = "Lowrance"
    elif "garmin" in lower:
        fields["brand"] = "Garmin"
    elif "simrad" in lower:
        fields["brand"] = "Simrad"

    if re.search(r"(?i)\belite\s*fs\b", normalized):
        fields["series"] = "Elite FS"
        match = re.search(r"(?i)\belite\s*fs\s*(\d{1,2})\b", normalized)
        if match:
            fields["screen_size"] = match.group(1)
            fields["model"] = f"Elite FS {match.group(1)}"
        else:
            fields["model"] = "Elite FS"
        fields["category"] = "chartplotter"
    elif re.search(r"(?i)\bhds\s*pro\b", normalized):
        fields["series"] = "HDS PRO"
        match = re.search(r"(?i)\bhds\s*pro\s*(\d{1,2})\b", normalized)
        if match:
            fields["screen_size"] = match.group(1)
            fields["model"] = f"HDS PRO {match.group(1)}"
        else:
            fields["model"] = "HDS PRO"
        fields["category"] = "chartplotter"
    elif re.search(r"(?i)\bactive\s*target\s*2|activetarget\s*2\b", normalized):
        fields["series"] = "ActiveTarget"
        fields["model"] = "ActiveTarget 2"
        fields["category"] = "live_sonar"
        if not fields["brand"]:
            fields["brand"] = "Lowrance"

    transducer_match = re.search(r"(?i)\b(?:AI\s*)?(?:3\s*[- ]?\s*in\s*[- ]?\s*1|2\s*[- ]?\s*in\s*[- ]?\s*1)\b", normalized)
    if transducer_match:
        fields["transducer"] = re.sub(r"\s+", " ", transducer_match.group(0)).replace(" - ", "-")

    firmware_match = re.search(r"\b(\d{2}\.\d)\b", normalized)
    if firmware_match:
        fields["firmware"] = firmware_match.group(1)

    return fields


def normalize_listing(raw: dict[str, Any], *, now: str | None = None) -> ListingRecord:
    now = now or datetime.now(timezone.utc).isoformat()
    url = str(raw.get("url") or raw.get("chat_url") or "").strip()
    title = normalize_title(raw.get("title") or raw.get("listing_title") or "")
    price, price_text, currency = parse_price(raw.get("price_text") or raw.get("price") or raw.get("listing_price"))
    listing_id = str(raw.get("listing_id") or "").strip() or listing_id_from_url(url) or stable_listing_id(title, price_text)
    photos = raw.get("photos") or []
    attributes = raw.get("attributes") or {}
    description = str(raw.get("description") or "").strip()
    status = str(raw.get("status") or "unknown").strip() or "unknown"
    fields = extract_title_fields(title)
    content_hash = content_hash_for_listing(
        {
            "title": title,
            "price": price,
            "price_text": price_text,
            "status": status,
            "description": description,
            "photos": photos,
            "attributes": attributes_for_content_hash(attributes),
            **fields,
        }
    )
    return ListingRecord(
        listing_id=listing_id,
        url=url,
        title=title,
        price=price,
        price_text=price_text,
        currency=currency,
        status=status,
        description=description,
        brand=fields["brand"],
        series=fields["series"],
        model=fields["model"],
        screen_size=fields["screen_size"],
        transducer=fields["transducer"],
        firmware=fields["firmware"],
        category=fields["category"],
        photos_json=json.dumps(photos, ensure_ascii=False),
        attributes_json=json.dumps(attributes, ensure_ascii=False, sort_keys=True),
        content_hash=content_hash,
        first_seen=now,
        last_seen=now,
        updated_at=now,
    )


def content_hash_for_listing(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def attributes_for_content_hash(attributes: Any) -> Any:
    if not isinstance(attributes, dict):
        return attributes
    return {key: value for key, value in attributes.items() if key != "chat_urls"}


def fallback_listings_from_qa(path: Path) -> list[dict[str, Any]]:
    rows = load_jsonl(path)
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        title = normalize_title(row.get("listing_title") or "")
        price_text = str(row.get("listing_price") or "").strip()
        chat_url = str(row.get("chat_url") or "").strip()
        if not title or not price_text:
            continue
        key = (title.casefold(), price_text)
        listing = grouped.setdefault(
            key,
            {
                "url": "",
                "title": title,
                "price": price_text,
                "status": "unknown",
                "photos": [],
                "attributes": {"source": "avito_qa_fallback", "chat_urls": []},
            },
        )
        if chat_url and chat_url not in listing["attributes"]["chat_urls"]:
            listing["attributes"]["chat_urls"].append(chat_url)
    return list(grouped.values())


def count_fallback_duplicate_rows(path: Path) -> int:
    rows = load_jsonl(path)
    total = 0
    unique: set[tuple[str, str]] = set()
    for row in rows:
        title = normalize_title(row.get("listing_title") or "")
        price_text = str(row.get("listing_price") or "").strip()
        if not title or not price_text:
            continue
        total += 1
        unique.add((title.casefold(), price_text))
    return max(total - len(unique), 0)


def existing_listing(db: sqlite3.Connection, listing_id: str) -> dict[str, Any] | None:
    row = db.execute("SELECT * FROM listings WHERE listing_id = ?", (listing_id,)).fetchone()
    if row is None:
        return None
    columns = [description[0] for description in db.execute("SELECT * FROM listings LIMIT 0").description]
    return dict(zip(columns, row))


def upsert_listings(db_path: Path, listings: list[ListingRecord]) -> tuple[int, int, int, list[dict[str, str]]]:
    ensure_listing_schema(db_path)
    inserted = updated = unchanged = 0
    history: list[dict[str, str]] = []
    with sqlite3.connect(db_path) as db:
        for listing in listings:
            current = existing_listing(db, listing.listing_id)
            data = asdict(listing)
            if current is None:
                placeholders = ", ".join("?" for _ in LISTING_FIELDS)
                db.execute(
                    f"INSERT INTO listings ({', '.join(LISTING_FIELDS)}) VALUES ({placeholders})",
                    [data[field] for field in LISTING_FIELDS],
                )
                inserted += 1
                continue

            changes = []
            for field in HISTORY_FIELDS:
                old_value = "" if current.get(field) is None else str(current.get(field))
                new_value = "" if data.get(field) is None else str(data.get(field))
                if old_value != new_value:
                    changes.append((field, old_value, new_value))

            if not changes:
                db.execute(
                    "UPDATE listings SET last_seen = ? WHERE listing_id = ?",
                    (listing.last_seen, listing.listing_id),
                )
                unchanged += 1
                continue

            for field, old_value, new_value in changes:
                history_row = {
                    "listing_id": listing.listing_id,
                    "changed_at": listing.updated_at,
                    "field": field,
                    "old_value": old_value,
                    "new_value": new_value,
                }
                db.execute(
                    """
                    INSERT INTO listing_history (listing_id, changed_at, field, old_value, new_value)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        history_row["listing_id"],
                        history_row["changed_at"],
                        history_row["field"],
                        history_row["old_value"],
                        history_row["new_value"],
                    ),
                )
                history.append(history_row)

            assignments = ", ".join(f"{field} = ?" for field in LISTING_FIELDS if field != "first_seen")
            db.execute(
                f"UPDATE listings SET {assignments} WHERE listing_id = ?",
                [data[field] for field in LISTING_FIELDS if field != "first_seen"] + [listing.listing_id],
            )
            updated += 1
    return inserted, updated, unchanged, history


def export_listings_from_sqlite(db_path: Path, output_path: Path) -> int:
    ensure_listing_schema(db_path)
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """
            SELECT *
            FROM listings
            ORDER BY updated_at DESC, title ASC
            """
        ).fetchall()
    write_jsonl(output_path, [dict(row) for row in rows])
    return len(rows)


def import_listings(*, data_dir: Path | None = None) -> ListingImportStats:
    data_root = ensure_external_data_directories(data_dir)
    listings_output_dir = listings_dir(data_root)
    listings_output_dir.mkdir(parents=True, exist_ok=True)
    db_path = sqlite_path(data_root)
    raw_input = raw_path(data_root)
    qa_input = avito_qa_path(data_root)

    if raw_input.exists():
        raw_rows = load_jsonl(raw_input)
        input_source = str(raw_input)
        fallback_count = 0
        duplicate_fallback_rows_merged = 0
    else:
        raw_rows = fallback_listings_from_qa(qa_input)
        input_source = str(qa_input)
        fallback_count = len(raw_rows)
        duplicate_fallback_rows_merged = count_fallback_duplicate_rows(qa_input)

    now = datetime.now(timezone.utc).isoformat()
    records = [normalize_listing(row, now=now) for row in raw_rows if normalize_title(row.get("title") or row.get("listing_title") or "")]
    inserted, updated, unchanged, history = upsert_listings(db_path, records)
    cleaned_output = cleaned_path(data_root)
    unique_exported = export_listings_from_sqlite(db_path, cleaned_output)
    if history:
        with history_jsonl_path(data_root).open("a", encoding="utf-8") as fh:
            for row in history:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    return ListingImportStats(
        data_dir=data_root,
        input_source=input_source,
        raw_listings_loaded=len(raw_rows) if raw_input.exists() else 0,
        fallback_listings_from_qa=fallback_count,
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        history_changes=len(history),
        unique_listings_exported=unique_exported,
        duplicate_fallback_rows_merged=duplicate_fallback_rows_merged,
        sqlite_path=db_path,
        cleaned_output=cleaned_output,
    )


def main() -> int:
    stats = import_listings()
    print(f"Data directory: {stats.data_dir}")
    print(f"Input source: {stats.input_source}")
    print(f"Raw listings loaded: {stats.raw_listings_loaded}")
    print(f"Fallback listings from QA: {stats.fallback_listings_from_qa}")
    print(f"Inserted: {stats.inserted}")
    print(f"Updated: {stats.updated}")
    print(f"Unchanged: {stats.unchanged}")
    print(f"History changes: {stats.history_changes}")
    print(f"Unique listings exported: {stats.unique_listings_exported}")
    print(f"Duplicate fallback rows merged: {stats.duplicate_fallback_rows_merged}")
    print(f"SQLite path: {stats.sqlite_path}")
    print(f"Cleaned output: {stats.cleaned_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
