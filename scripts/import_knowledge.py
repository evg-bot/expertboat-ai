from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import BASE_DIR, load_settings
from app.database import Database
from app.knowledge import KnowledgeBase
from app.knowledge_import_status import IMPORT_HISTORY_PATH, ensure_import_history, record_import_run
from app.rag import RagEngine

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".json", ".jsonl"}

CATEGORY_KEYWORDS = {
    "Lowrance": ("lowrance", "elite fs", "hds", "active target", "activetarget", "point-1", "c-map", "cmap"),
    "Garmin": ("garmin", "echomap", "gpsmap", "panoptix", "livescope"),
    "Simrad": ("simrad", "nss", "nso", "go series"),
    "FLIR": ("flir", "thermal", "тепловизор"),
    "Minn Kota": ("minn kota", "ultrex", "ulterra", "terrova"),
    "Mercury": ("mercury", "меркури", "vesselview"),
    "Sales": ("цена", "купить", "оплата", "скидка", "заказ"),
    "Support": ("гарантия", "сервис", "ремонт", "поддержка", "настройка"),
    "FAQ": ("вопрос", "ответ", "faq", "часто задаваемые"),
}


@dataclass(frozen=True)
class ImportResult:
    filename: str
    sha256: str
    document_type: str
    chunks_count: int
    status: str
    error: str = ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Import documents from knowledge/inbox into processed knowledge.")
    parser.add_argument("--no-rag", action="store_true", help="Do not rebuild SQLite RAG index after import.")
    args = parser.parse_args()

    ensure_directories()
    ensure_import_history()

    results = import_inbox(update_rag=not args.no_rag)
    print_summary(results)


def import_inbox(*, update_rag: bool = True) -> list[ImportResult]:
    inbox_dir = BASE_DIR / "knowledge" / "inbox"
    files = [path for path in sorted(inbox_dir.rglob("*")) if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS]

    results: list[ImportResult] = []
    for path in files:
        result = import_file(path)
        results.append(result)

    if update_rag and any(result.status == "processed" for result in results):
        settings = load_settings()
        database = Database(settings.database_path)
        database.init()
        knowledge_base = KnowledgeBase(settings.knowledge_dir)
        RagEngine(database, knowledge_base).reindex()

    counts = Counter(result.status for result in results)
    record_import_run(
        processed_count=counts.get("processed", 0),
        new_count=counts.get("processed", 0),
        skipped_count=counts.get("skipped", 0),
        errors_count=counts.get("error", 0),
    )

    return results


def import_file(path: Path) -> ImportResult:
    file_hash = sha256_file(path)
    document_type = path.suffix.lower().lstrip(".")

    if is_known_hash(file_hash):
        result = ImportResult(path.name, file_hash, document_type, 0, "skipped")
        record_import(result)
        return result

    try:
        raw_text = extract_text(path)
        cleaned_text = clean_text(raw_text)
        if not cleaned_text:
            raise ValueError("No text extracted")
        category = detect_category(cleaned_text, fallback="FAQ")
        markdown = build_markdown(path, file_hash, category, cleaned_text)
        processed_path = write_processed_markdown(path, category, markdown)
        chunks = split_chunks(cleaned_text)
        write_chunks(processed_path, category, chunks)
        result = ImportResult(path.name, file_hash, document_type, len(chunks), "processed")
        record_import(result)
        return result
    except Exception as exc:
        result = ImportResult(path.name, file_hash, document_type, 0, "error", str(exc))
        record_import(result)
        return result


def ensure_directories() -> None:
    directories = [
        BASE_DIR / "data" / "raw" / "avito",
        BASE_DIR / "data" / "raw" / "telegram",
        BASE_DIR / "data" / "raw" / "notebook",
        BASE_DIR / "data" / "cleaned",
        BASE_DIR / "data" / "faq",
        BASE_DIR / "data" / "processed",
        BASE_DIR / "knowledge" / "inbox",
        BASE_DIR / "knowledge" / "manuals",
        BASE_DIR / "knowledge" / "processed",
        BASE_DIR / "knowledge" / "chunks",
        BASE_DIR / "knowledge" / "review",
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix == ".docx":
        return extract_docx(path)
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return "\n".join(extract_json_strings(data))
    if suffix == ".jsonl":
        parts: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                parts.extend(extract_json_strings(json.loads(line)))
        return "\n".join(parts)
    raise ValueError(f"Unsupported file type: {suffix}")


def extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_docx(path: Path) -> str:
    from docx import Document

    document = Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_json_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, dict):
        parts: list[str] = []
        for item in value.values():
            parts.extend(extract_json_strings(item))
        return parts
    if isinstance(value, list):
        parts = []
        for item in value:
            parts.extend(extract_json_strings(item))
        return parts
    return []


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    lines = remove_repeated_headers_and_footers(lines)

    cleaned_lines: list[str] = []
    for line in lines:
        if not line:
            cleaned_lines.append("")
            continue
        if re.fullmatch(r"(page|стр\.?|страница)?\s*\d+\s*(of|из)?\s*\d*", line, flags=re.IGNORECASE):
            continue
        if is_ocr_garbage(line):
            continue
        cleaned_lines.append(line)

    cleaned = "\n".join(collapse_blank_lines(cleaned_lines))
    return cleaned.strip()


def remove_repeated_headers_and_footers(lines: list[str]) -> list[str]:
    candidates = [line for line in lines if line and len(line) <= 120]
    counts = Counter(candidates)
    repeated = {line for line, count in counts.items() if count >= 3}
    return [line for line in lines if line not in repeated]


def is_ocr_garbage(line: str) -> bool:
    if len(line) < 8:
        return False
    alpha_num = sum(char.isalnum() for char in line)
    punctuation = sum(not char.isalnum() and not char.isspace() for char in line)
    if alpha_num == 0:
        return True
    return punctuation / max(len(line), 1) > 0.45


def collapse_blank_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        result.append(line)
        previous_blank = blank
    return result


def detect_category(text: str, *, fallback: str = "FAQ") -> str:
    normalized = text.casefold()
    scores: dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        scores[category] = sum(1 for keyword in keywords if keyword in normalized)
    category, score = max(scores.items(), key=lambda item: item[1])
    return category if score > 0 else fallback


def build_markdown(path: Path, file_hash: str, category: str, text: str) -> str:
    title = guess_title(path, text)
    frontmatter = {
        "source_file": path.name,
        "sha256": file_hash,
        "category": category.lower().replace(" ", "-"),
        "tags": [category],
        "priority": 5,
    }
    return f"---\n{yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()}\n---\n\n# {title}\n\n{text}\n"


def guess_title(path: Path, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip("# ").strip()
        if 4 <= len(stripped) <= 120:
            return stripped
    return path.stem.replace("_", " ").replace("-", " ").title()


def write_processed_markdown(source_path: Path, category: str, markdown: str) -> Path:
    category_dir = BASE_DIR / "knowledge" / "processed" / slugify(category)
    category_dir.mkdir(parents=True, exist_ok=True)
    output_path = category_dir / f"{slugify(source_path.stem)}.md"
    if output_path.exists():
        output_path = category_dir / f"{slugify(source_path.stem)}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.md"
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def split_chunks(text: str, *, max_chars: int = 1400) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for block in blocks:
        if current and current_size + len(block) > max_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_size = 0
        current.append(block)
        current_size += len(block)
    if current:
        chunks.append("\n\n".join(current))
    return chunks or [text]


def write_chunks(processed_path: Path, category: str, chunks: list[str]) -> None:
    chunk_dir = BASE_DIR / "knowledge" / "chunks" / slugify(category) / processed_path.stem
    chunk_dir.mkdir(parents=True, exist_ok=True)
    for index, chunk in enumerate(chunks, start=1):
        chunk_path = chunk_dir / f"chunk-{index:03d}.md"
        chunk_path.write_text(f"# {processed_path.stem} chunk {index}\n\n{chunk}\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_known_hash(file_hash: str) -> bool:
    ensure_import_history()
    with sqlite3.connect(IMPORT_HISTORY_PATH) as db:
        row = db.execute(
            "SELECT 1 FROM import_history WHERE sha256 = ? AND status IN ('processed', 'new')",
            (file_hash,),
        ).fetchone()
    return row is not None


def record_import(result: ImportResult) -> None:
    ensure_import_history()
    with sqlite3.connect(IMPORT_HISTORY_PATH) as db:
        db.execute(
            """
            INSERT INTO import_history
                (filename, sha256, import_date, document_type, chunks_count, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.filename,
                result.sha256,
                datetime.now(timezone.utc).isoformat(),
                result.document_type,
                result.chunks_count,
                result.status,
                result.error,
            ),
        )


def slugify(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"[^0-9a-zа-яё]+", "-", value, flags=re.IGNORECASE)
    return value.strip("-") or "document"


def print_summary(results: list[ImportResult]) -> None:
    counts = Counter(result.status for result in results)
    print(
        "Import complete: "
        f"processed={counts.get('processed', 0)} "
        f"new={counts.get('processed', 0)} "
        f"skipped={counts.get('skipped', 0)} "
        f"errors={counts.get('error', 0)}"
    )


if __name__ == "__main__":
    main()
