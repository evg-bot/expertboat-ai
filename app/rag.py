from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from app.database import Database
from app.knowledge import KnowledgeBase, NormalizedQuery, strip_markdown

RAG_MIN_SCORE = 18


@dataclass(frozen=True)
class RagChunk:
    id: int
    source: str
    title: str
    content: str
    content_hash: str
    score: int = 0
    method: str = "local-rag"

    @property
    def clean_content(self) -> str:
        return strip_markdown(_remove_frontmatter(self.content))


@dataclass(frozen=True)
class RagSearchResult:
    query: NormalizedQuery
    chunks: list[RagChunk]
    method: str
    top_score: int

    @property
    def has_answer(self) -> bool:
        return self.top_score >= RAG_MIN_SCORE and bool(self.chunks)


@dataclass(frozen=True)
class _Document:
    path: Path
    source: str
    metadata: dict[str, Any]
    body: str


@dataclass(frozen=True)
class _RawChunk:
    source: str
    title: str
    content: str
    metadata: dict[str, Any]


class RagEngine:
    def __init__(self, database: Database, knowledge_base: KnowledgeBase) -> None:
        self.database = database
        self.knowledge_base = knowledge_base

    def reindex(self) -> int:
        documents = self._load_documents()
        chunks: list[_RawChunk] = []
        for document in documents:
            chunks.extend(self._split_document(document))

        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as db:
            db.execute("DELETE FROM knowledge_chunks")
            for chunk in chunks:
                content_hash = self._content_hash(chunk.source, chunk.title, chunk.content)
                db.execute(
                    """
                    INSERT OR IGNORE INTO knowledge_chunks
                        (source, title, content, content_hash, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (chunk.source, chunk.title, chunk.content, content_hash, now),
                )
        return len(chunks)

    def search(self, question: str, *, context: str = "", limit: int = 5) -> RagSearchResult:
        query_text = f"{context}\n{question}".strip()
        normalized_query = self.knowledge_base.normalize_query(query_text)
        chunks = self._load_indexed_chunks()
        scored = [self._score_chunk(chunk, normalized_query) for chunk in chunks]
        matches = [chunk for chunk in scored if chunk.score > 0]
        matches.sort(key=lambda chunk: chunk.score, reverse=True)
        top_chunks = matches[:limit]
        top_score = top_chunks[0].score if top_chunks else 0
        self._save_search_stat(question, "local-rag", top_score)
        return RagSearchResult(
            query=normalized_query,
            chunks=top_chunks,
            method="local-rag",
            top_score=top_score,
        )

    def chunks_count(self) -> int:
        try:
            with self.database.connect() as db:
                row = db.execute("SELECT COUNT(*) AS count FROM knowledge_chunks").fetchone()
            return int(row["count"]) if row else 0
        except sqlite3.Error:
            return 0

    def last_indexed_at(self) -> str | None:
        try:
            with self.database.connect() as db:
                row = db.execute("SELECT MAX(created_at) AS value FROM knowledge_chunks").fetchone()
            return str(row["value"]) if row and row["value"] else None
        except sqlite3.Error:
            return None

    def _load_documents(self) -> list[_Document]:
        documents: list[_Document] = []
        for path in sorted(self.knowledge_base.directory.rglob("*.md")):
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            metadata, body = _extract_frontmatter(text)
            documents.append(
                _Document(
                    path=path,
                    source=str(path.relative_to(self.knowledge_base.directory)),
                    metadata=metadata,
                    body=body.strip(),
                )
            )
        return documents

    def _split_document(self, document: _Document) -> list[_RawChunk]:
        chunks: list[_RawChunk] = []
        current_title = _metadata_title(document.metadata) or document.path.stem.replace("-", " ").title()
        current_lines: list[str] = []

        def flush() -> None:
            body = "\n".join(current_lines).strip()
            current_lines.clear()
            if not body:
                return
            for paragraph in _split_paragraphs(body):
                content = _storage_content(document.metadata, current_title, paragraph)
                chunks.append(
                    _RawChunk(
                        source=document.source,
                        title=current_title,
                        content=content,
                        metadata=document.metadata,
                    )
                )

        for line in document.body.splitlines():
            if re.match(r"^#{1,6}\s+", line):
                flush()
                current_title = line.lstrip("#").strip() or current_title
                continue
            current_lines.append(line)
        flush()
        return chunks

    def _load_indexed_chunks(self) -> list[RagChunk]:
        try:
            with self.database.connect() as db:
                rows = db.execute(
                    """
                    SELECT id, source, title, content, content_hash
                    FROM knowledge_chunks
                    ORDER BY id ASC
                    """
                ).fetchall()
        except sqlite3.Error:
            return []

        return [
            RagChunk(
                id=int(row["id"]),
                source=str(row["source"]),
                title=str(row["title"]),
                content=str(row["content"]),
                content_hash=str(row["content_hash"]),
            )
            for row in rows
        ]

    def _score_chunk(self, chunk: RagChunk, query: NormalizedQuery) -> RagChunk:
        if not query.expanded:
            return chunk

        metadata = _extract_frontmatter(chunk.content)[0]
        searchable = " ".join(
            [
                chunk.source,
                chunk.title,
                chunk.content,
                _metadata_search_text(metadata),
            ]
        )
        normalized_text = _normalize(searchable)
        normalized_title = _normalize(chunk.title)
        normalized_source = _normalize(chunk.source)
        normalized_meta = _normalize(_metadata_search_text(metadata))
        query_words = set(_words(query.expanded))
        text_words = set(_words(normalized_text))
        title_words = set(_words(normalized_title))
        meta_words = set(_words(normalized_meta))
        phrases = _phrases(query.expanded)

        word_matches = query_words & text_words
        title_matches = query_words & title_words
        meta_matches = query_words & meta_words
        phrase_matches = [phrase for phrase in phrases if phrase in normalized_text]
        title_phrase_matches = [phrase for phrase in phrases if phrase in normalized_title]

        fuzzy_title = fuzz.partial_ratio(query.expanded, normalized_title) if normalized_title else 0
        fuzzy_source = fuzz.partial_ratio(query.expanded, normalized_source) if normalized_source else 0
        fuzzy_content = fuzz.partial_ratio(query.expanded, normalized_text) if normalized_text else 0

        score = 0
        score += len(word_matches) * 3
        score += len(title_matches) * 10
        score += len(meta_matches) * 12
        score += len(phrase_matches) * 10
        score += len(title_phrase_matches) * 15
        score += _alias_bonus(query, normalized_text, normalized_title, normalized_meta)
        score += _proximity_bonus(list(query_words), normalized_text)
        score += _priority_bonus(metadata)

        if query.normalized and query.normalized in normalized_text:
            score += 14
        if fuzzy_title >= 85:
            score += int(fuzzy_title // 4)
        if fuzzy_source >= 85:
            score += int(fuzzy_source // 6)
        if fuzzy_content >= 88:
            score += int(fuzzy_content // 8)

        return RagChunk(
            id=chunk.id,
            source=chunk.source,
            title=chunk.title,
            content=chunk.content,
            content_hash=chunk.content_hash,
            score=score,
        )

    def _save_search_stat(self, query: str, method: str, top_score: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.database.connect() as db:
                db.execute(
                    """
                    INSERT INTO search_stats (query, method, top_score, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (query, method, top_score, now),
                )
        except sqlite3.Error:
            return

    @staticmethod
    def _content_hash(source: str, title: str, content: str) -> str:
        raw = f"{source}\n{title}\n{content}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


def _extract_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        metadata = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(metadata, dict):
        metadata = {}
    return metadata, parts[2].strip()


def _remove_frontmatter(text: str) -> str:
    return _extract_frontmatter(text)[1]


def _storage_content(metadata: dict[str, Any], title: str, body: str) -> str:
    metadata_text = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=True).strip() if metadata else ""
    if metadata_text:
        return f"---\n{metadata_text}\n---\n\n## {title}\n\n{body.strip()}"
    return f"## {title}\n\n{body.strip()}"


def _metadata_title(metadata: dict[str, Any]) -> str | None:
    product = metadata.get("product")
    if isinstance(product, str) and product.strip():
        return product.strip()
    category = metadata.get("category")
    if isinstance(category, str) and category.strip():
        return category.strip().title()
    return None


def _metadata_search_text(metadata: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("product", "category"):
        value = metadata.get(key)
        if isinstance(value, str):
            values.append(value)
    tags = metadata.get("tags")
    if isinstance(tags, list):
        values.extend(str(tag) for tag in tags)
    return " ".join(values)


def _priority_bonus(metadata: dict[str, Any]) -> int:
    value = metadata.get("priority")
    if isinstance(value, int):
        return max(0, min(value, 20))
    try:
        return max(0, min(int(str(value)), 20))
    except (TypeError, ValueError):
        return 0


def _alias_bonus(query: NormalizedQuery, text: str, title: str, metadata: str) -> int:
    bonus = 0
    haystack = f" {text} {title} {metadata} "
    for match in query.matches:
        canonical = _normalize(match.canonical)
        alias = _normalize(match.alias)
        if canonical and canonical in haystack:
            bonus += 20
        if alias and alias in haystack:
            bonus += 10
    return bonus


def _proximity_bonus(query_words: list[str], text: str) -> int:
    useful_words = [word for word in query_words if len(word) >= 3]
    if len(useful_words) < 2:
        return 0
    positions: list[int] = []
    text_words = _words(text)
    for query_word in useful_words:
        try:
            positions.append(text_words.index(query_word))
        except ValueError:
            continue
    if len(positions) < 2:
        return 0
    spread = max(positions) - min(positions)
    if spread <= 4:
        return 10
    if spread <= 10:
        return 5
    return 0


def _split_paragraphs(text: str) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    result: list[str] = []
    current: list[str] = []
    current_length = 0
    for block in blocks:
        block_length = len(block)
        if current and current_length + block_length > 1400:
            result.append("\n\n".join(current))
            current = []
            current_length = 0
        current.append(block)
        current_length += block_length
    if current:
        result.append("\n\n".join(current))
    return result


def _normalize(text: str) -> str:
    lowered = text.casefold().replace("ё", "е")
    cleaned = re.sub(r"[^0-9a-zа-яе@+]+", " ", lowered, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _words(text: str) -> list[str]:
    return [word for word in text.split() if len(word) >= 2]


def _phrases(text: str) -> list[str]:
    words = _words(text)
    phrases: list[str] = []
    for size in (2, 3, 4):
        for index in range(0, max(len(words) - size + 1, 0)):
            phrases.append(" ".join(words[index : index + size]))
    return phrases
