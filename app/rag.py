from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from app.config import RAG_MIN_DOMAIN_SCORE, RAG_MIN_SCORE, RAG_SHORT_QUERY_MAX_LEN
from app.database import Database
from app.knowledge import AliasMatch, KnowledgeBase, NormalizedQuery, strip_markdown

RAG_METHOD = "local-rag"
RAG_METHOD_HISTORY = "local-rag-history"

logger = logging.getLogger(__name__)


STOP_WORDS = {
    "а",
    "без",
    "бы",
    "в",
    "во",
    "где",
    "да",
    "для",
    "до",
    "его",
    "ее",
    "если",
    "есть",
    "же",
    "за",
    "и",
    "или",
    "из",
    "как",
    "ко",
    "ли",
    "на",
    "над",
    "не",
    "но",
    "о",
    "об",
    "от",
    "по",
    "под",
    "при",
    "про",
    "с",
    "со",
    "то",
    "у",
    "что",
    "это",
}

DOMAIN_VOCABULARY = {
    "marine",
    "electronics",
    "expert",
    "boat",
    "lowrance",
    "garmin",
    "simrad",
    "elite",
    "hds",
    "eagle",
    "active",
    "target",
    "activetarget",
    "point",
    "point1",
    "cmap",
    "c-map",
    "nmea2000",
    "nmea",
    "ethernet",
    "эхолот",
    "эхолоты",
    "картплоттер",
    "картплоттеры",
    "датчик",
    "датчики",
    "сонар",
    "морская",
    "морской",
    "электроника",
    "лодка",
    "рыбалка",
    "русификация",
    "русик",
    "прошивка",
    "доставка",
    "отправка",
    "сдэк",
    "гарантия",
    "гарантийный",
    "оплата",
    "оплатить",
    "купить",
    "карта",
    "карты",
    "совместимость",
    "подключить",
    "комплектация",
}

OFF_TOPIC_TERMS = {
    "авто",
    "автомобиль",
    "машина",
    "камаз",
    "газель",
    "лада",
    "двигатель",
    "мотор",
    "турбина",
    "тормоза",
    "коробка",
    "сцепление",
    "медицина",
    "врач",
    "таблетки",
    "лекарство",
    "давление",
    "больница",
    "холодильник",
    "стиралка",
    "стиральная",
    "пылесос",
    "микроволновка",
    "строительство",
    "стройка",
    "бетон",
    "кирпич",
    "ремонт",
    "квартира",
    "политика",
    "выборы",
    "президент",
}

INTENT_KEYWORDS = {
    "greeting": {"привет", "здравствуйте", "добрый", "день", "вечер", "утро", "hello", "hi"},
    "price": {"цена", "стоимость", "стоит", "сколько", "ценник", "прайс"},
    "availability": {"есть", "наличие", "наличии", "доступен", "доступна", "остался", "остались"},
    "delivery": {"доставка", "доставить", "отправка", "отправить", "сдэк", "тк", "город"},
    "warranty": {"гарантия", "гарантийный", "гарантийка", "ремонт", "сервис"},
    "payment": {"оплата", "оплатить", "купить", "счет", "счёт", "сбп", "qr", "перевод"},
    "firmware": {"русификация", "русик", "русский", "прошивка", "прошить", "меню"},
    "maps": {"карта", "карты", "cmap", "c-map", "c", "map", "россия"},
    "compatibility": {"совместимость", "совместим", "подойдет", "подойдёт", "подключить", "nmea", "ethernet"},
}

REFINEMENT_TERMS = {
    "девятка": "9",
    "девять": "9",
    "9": "9",
    "десятка": "10",
    "десять": "10",
    "10": "10",
    "двенашка": "12",
    "двенадцать": "12",
    "12": "12",
    "шестнадцать": "16",
    "16": "16",
}


@dataclass(frozen=True)
class QueryContext:
    raw_query: str
    normalized_query: str
    expanded_query: str
    aliases_found: list[str]
    intent: str
    domain_relevance: bool
    used_history: bool = False
    history_reason: str = ""
    top_score: int = 0
    fallback_reason: str = ""


@dataclass(frozen=True)
class RagChunk:
    id: int
    source: str
    title: str
    content: str
    content_hash: str
    score: int = 0
    method: str = RAG_METHOD

    @property
    def clean_content(self) -> str:
        return strip_markdown(_remove_frontmatter(self.content))


@dataclass(frozen=True)
class RagSearchResult:
    query: NormalizedQuery
    chunks: list[RagChunk]
    method: str
    top_score: int
    context: QueryContext

    @property
    def has_answer(self) -> bool:
        return not self.context.fallback_reason and self.top_score >= RAG_MIN_SCORE and bool(self.chunks)


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
        self.ready = False
        self.last_error: str | None = None

    def reindex(self) -> int:
        try:
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
            self.ready = bool(chunks)
            self.last_error = None
            logger.info("RAG index rebuilt successfully: documents=%s chunks=%s", len(documents), len(chunks))
            return len(chunks)
        except Exception as exc:
            self.ready = False
            self.last_error = str(exc)
            logger.exception("RAG index rebuild failed")
            raise

    def search(
        self,
        question: str,
        *,
        history: list[dict[str, str]] | None = None,
        limit: int = 5,
    ) -> RagSearchResult:
        normalized_query = self.knowledge_base.normalize_query(question)
        intent = classify_intent(normalized_query)
        domain_score = self._domain_score(normalized_query, intent)
        domain_relevance = domain_score >= RAG_MIN_DOMAIN_SCORE
        context = QueryContext(
            raw_query=question,
            normalized_query=normalized_query.normalized,
            expanded_query=normalized_query.expanded,
            aliases_found=_alias_labels(normalized_query.matches),
            intent=intent,
            domain_relevance=domain_relevance,
        )

        if intent == "off_topic":
            return self._fallback_result(normalized_query, context, "off_topic")
        if not domain_relevance:
            return self._fallback_result(normalized_query, context, "domain_relevance=false")

        chunks = self._load_indexed_chunks()
        if not chunks:
            logger.error("RAG search requested but knowledge_chunks index is empty")
            return self._fallback_result(normalized_query, context, "rag_index_empty")

        top_chunks, top_score = self._rank_chunks(chunks, normalized_query, limit=limit, method=RAG_METHOD)
        context = replace(context, top_score=top_score)
        history_expansion = self._history_expansion(question, normalized_query, history or [])
        if top_score >= RAG_MIN_SCORE and not _needs_product_history(normalized_query):
            self._save_search_stat(question, RAG_METHOD, top_score)
            return RagSearchResult(normalized_query, top_chunks, RAG_METHOD, top_score, context)

        if history_expansion:
            history_query_text = f"{question} {history_expansion}"
            history_query = self.knowledge_base.normalize_query(history_query_text)
            history_chunks, history_score = self._rank_chunks(
                chunks,
                history_query,
                limit=limit,
                method=RAG_METHOD_HISTORY,
            )
            history_context = replace(
                context,
                expanded_query=history_query.expanded,
                aliases_found=_alias_labels(history_query.matches),
                used_history=True,
                history_reason=f"short refinement resolved with previous relevant product: {history_expansion}",
                top_score=history_score,
            )
            if history_score >= RAG_MIN_SCORE:
                self._save_search_stat(question, RAG_METHOD_HISTORY, history_score)
                return RagSearchResult(history_query, history_chunks, RAG_METHOD_HISTORY, history_score, history_context)
            context = replace(
                history_context,
                fallback_reason=f"top_score_below_threshold:{history_score}",
            )
            self._save_search_stat(question, RAG_METHOD_HISTORY, history_score)
            return RagSearchResult(history_query, history_chunks, RAG_METHOD_HISTORY, history_score, context)

        return self._fallback_result(
            normalized_query,
            replace(context, top_score=top_score),
            f"top_score_below_threshold:{top_score}",
            chunks=top_chunks,
        )

    def is_ready(self) -> bool:
        return self.ready or self.chunks_count() > 0

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

    def _fallback_result(
        self,
        query: NormalizedQuery,
        context: QueryContext,
        reason: str,
        *,
        chunks: list[RagChunk] | None = None,
    ) -> RagSearchResult:
        context = replace(context, fallback_reason=reason)
        logger.info("RAG fallback: reason=%s query=%r", reason, context.raw_query)
        self._save_search_stat(context.raw_query, RAG_METHOD, context.top_score)
        return RagSearchResult(query, chunks or [], RAG_METHOD, context.top_score, context)

    def _rank_chunks(
        self,
        chunks: list[RagChunk],
        query: NormalizedQuery,
        *,
        limit: int,
        method: str,
    ) -> tuple[list[RagChunk], int]:
        scored = [self._score_chunk(chunk, query, method=method) for chunk in chunks]
        matches = [chunk for chunk in scored if chunk.score > 0]
        matches.sort(key=lambda chunk: chunk.score, reverse=True)
        top_chunks = matches[:limit]
        top_score = top_chunks[0].score if top_chunks else 0
        return top_chunks, top_score

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

    def _score_chunk(self, chunk: RagChunk, query: NormalizedQuery, *, method: str) -> RagChunk:
        if not query.expanded:
            return chunk

        metadata = _extract_frontmatter(chunk.content)[0]
        visible_content = _remove_frontmatter(chunk.content)
        searchable = " ".join([chunk.source, chunk.title, visible_content])
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
        score += len(meta_matches) * 4
        score += len(phrase_matches) * 10
        score += len(title_phrase_matches) * 15
        score += _alias_bonus(query, normalized_text, normalized_title)
        score += _proximity_bonus(list(query_words), normalized_text)

        if query.normalized and query.normalized in normalized_text:
            score += 14
        if fuzzy_title >= 85:
            score += int(fuzzy_title // 4)
        if fuzzy_source >= 85:
            score += int(fuzzy_source // 6)
        if fuzzy_content >= 92:
            score += int(fuzzy_content // 10)
        if score > 0:
            score += _priority_bonus(metadata)

        return RagChunk(
            id=chunk.id,
            source=chunk.source,
            title=chunk.title,
            content=chunk.content,
            content_hash=chunk.content_hash,
            score=score,
            method=method,
        )

    def _domain_score(self, query: NormalizedQuery, intent: str) -> int:
        if intent == "off_topic":
            return 0
        score = 0
        if query.matches:
            score += 2
        query_words = set(_words(query.expanded))
        score += len(query_words & DOMAIN_VOCABULARY)
        if intent in {
            "greeting",
            "price",
            "availability",
            "delivery",
            "warranty",
            "payment",
            "firmware",
            "maps",
            "compatibility",
            "product_lookup",
        }:
            score += 1
        if _is_refinement(query.normalized):
            score += 1
        return score

    def _history_expansion(
        self,
        question: str,
        current_query: NormalizedQuery,
        history: list[dict[str, str]],
    ) -> str | None:
        if len(question.strip()) > RAG_SHORT_QUERY_MAX_LEN:
            return None
        if not _is_refinement(current_query.normalized):
            return None

        previous_product = self._previous_relevant_product(question, history)
        if previous_product is None:
            return None

        diagonal = _refinement_diagonal(current_query.normalized)
        if diagonal and "elite fs" in _normalize(previous_product):
            return f"Lowrance Elite FS {diagonal}"
        if diagonal and "hds pro" in _normalize(previous_product):
            return f"Lowrance HDS PRO {diagonal}"
        if "доставка" in current_query.normalized:
            return "Доставка"
        if "гарантия" in current_query.normalized:
            return "Гарантия"
        if "оплата" in current_query.normalized:
            return "Оплата"
        if "русик" in current_query.normalized or "русификация" in current_query.normalized:
            return "Русификация"
        return previous_product

    def _previous_relevant_product(self, question: str, history: list[dict[str, str]]) -> str | None:
        normalized_current = _normalize(question)
        for item in reversed(history):
            text = str(item.get("text", "")).strip()
            if text.startswith("/"):
                continue
            if not text or _normalize(text) == normalized_current:
                continue
            query = self.knowledge_base.normalize_query(text)
            if classify_intent(query) == "off_topic":
                continue
            if query.matches:
                return _best_product_alias(query.matches)
            if self._domain_score(query, classify_intent(query)) >= RAG_MIN_DOMAIN_SCORE:
                chunks = self._load_indexed_chunks()
                top_chunks, top_score = self._rank_chunks(chunks, query, limit=1, method=RAG_METHOD)
                if top_chunks and top_score >= RAG_MIN_SCORE:
                    return top_chunks[0].title
        return None

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


def classify_intent(query: NormalizedQuery) -> str:
    words = set(_words(query.normalized))
    if _contains_term(words, OFF_TOPIC_TERMS):
        return "off_topic"
    if words & INTENT_KEYWORDS["greeting"]:
        return "greeting"
    for intent in ("delivery", "warranty", "payment", "firmware", "maps", "compatibility", "price", "availability"):
        if words & INTENT_KEYWORDS[intent]:
            return intent
    if query.matches or words & DOMAIN_VOCABULARY:
        return "product_lookup"
    return "unknown"


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


def _alias_bonus(query: NormalizedQuery, text: str, title: str) -> int:
    bonus = 0
    haystack = f" {text} {title} "
    for match in query.matches:
        canonical = _normalize(match.canonical)
        alias = _normalize(match.alias)
        if canonical and canonical in haystack:
            bonus += 22
        if alias and alias in haystack:
            bonus += 12
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
    cleaned = re.sub(r"[^0-9a-zа-яе@+.-]+", " ", lowered, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _words(text: str) -> list[str]:
    return [word for word in text.split() if len(word) >= 2 and word not in STOP_WORDS]


def _phrases(text: str) -> list[str]:
    words = _words(text)
    phrases: list[str] = []
    for size in (2, 3, 4):
        for index in range(0, max(len(words) - size + 1, 0)):
            phrases.append(" ".join(words[index : index + size]))
    return phrases


def _alias_labels(matches: list[AliasMatch]) -> list[str]:
    return [f"{match.canonical}: {match.alias} ({match.kind}, {match.score})" for match in matches[:20]]


def _best_product_alias(matches: list[AliasMatch]) -> str:
    for match in matches:
        normalized = _normalize(match.canonical)
        if any(product_word in normalized for product_word in ("lowrance", "elite", "hds", "active", "point", "c-map")):
            return match.canonical
    return matches[0].canonical


def _is_refinement(normalized_query: str) -> bool:
    words = set(_words(normalized_query))
    if words & set(REFINEMENT_TERMS):
        return True
    return bool(words & {"доставка", "гарантия", "оплата", "русик", "русификация"})


def _needs_product_history(query: NormalizedQuery) -> bool:
    return not query.matches and _refinement_diagonal(query.normalized) is not None


def _refinement_diagonal(normalized_query: str) -> str | None:
    words = set(_words(normalized_query))
    for term, diagonal in REFINEMENT_TERMS.items():
        if term in words:
            return diagonal
    return None


def _contains_term(words: set[str], terms: set[str]) -> bool:
    for word in words:
        for term in terms:
            if word == term or word.startswith(term):
                return True
    return False
