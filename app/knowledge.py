from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml
from rapidfuzz import fuzz

FUZZY_THRESHOLD = 85


@dataclass(frozen=True)
class AliasMatch:
    canonical: str
    alias: str
    score: int
    kind: str


@dataclass(frozen=True)
class NormalizedQuery:
    original: str
    normalized: str
    expanded: str
    matches: list[AliasMatch]


@dataclass(frozen=True)
class KnowledgeFragment:
    source: str
    title: str
    text: str
    score: int

    @property
    def clean_text(self) -> str:
        return strip_markdown(self.text)


class KnowledgeBase:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.aliases_path = self.directory / "aliases.yaml"
        self.aliases = self.load_aliases()
        self._cache = self.load_documents()

    @property
    def document_count(self) -> int:
        return len(self._cache)

    @property
    def aliases_group_count(self) -> int:
        return len(self.aliases)

    def first_alias_groups(self, limit: int = 20) -> list[str]:
        return list(self.aliases.keys())[:limit]

    def reload(self) -> None:
        self.aliases = self.load_aliases()
        self._cache = self.load_documents()

    def load_aliases(self) -> dict[str, list[str]]:
        if not self.aliases_path.exists():
            return {}
        data = yaml.safe_load(self.aliases_path.read_text(encoding="utf-8")) or {}
        aliases: dict[str, list[str]] = {}
        for canonical, values in data.items():
            if not isinstance(values, list):
                continue
            all_values = [str(canonical), *[str(value) for value in values]]
            aliases[str(canonical)] = all_values
        return aliases

    def load_documents(self) -> list[tuple[Path, str]]:
        documents: list[tuple[Path, str]] = []
        for path in sorted(self.directory.rglob("*.md")):
            text = path.read_text(encoding="utf-8").strip()
            if text:
                documents.append((path, text))
        return documents

    def load_markdown(self) -> str:
        parts: list[str] = []
        for path, text in self._cache:
            parts.append(f"# {path.relative_to(self.directory)}\n\n{text}")
        return "\n\n---\n\n".join(parts)

    def is_empty(self) -> bool:
        return not self.load_markdown().strip()

    def append_learned(self, question: str, answer: str) -> Path:
        path = self.directory / "learned.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        block = (
            "\n\n"
            f"## {question.strip()}\n\n"
            f"Вопрос клиента: {question.strip()}\n\n"
            f"Правильный ответ: {answer.strip()}\n"
        )
        with path.open("a", encoding="utf-8") as file:
            file.write(block)
        self.reload()
        return path

    def normalize_query(self, text: str) -> NormalizedQuery:
        normalized = _normalize(text)
        matches = self._alias_matches(normalized)
        canonical_terms = []
        seen_terms: set[str] = set()
        for match in matches:
            canonical_normalized = _normalize(match.canonical)
            if canonical_normalized not in seen_terms:
                canonical_terms.append(match.canonical)
                seen_terms.add(canonical_normalized)
        expanded = _normalize(" ".join([normalized, *canonical_terms]))
        return NormalizedQuery(original=text, normalized=normalized, expanded=expanded, matches=matches)

    def relevant_fragments(
        self,
        question: str,
        *,
        context: str = "",
        limit: int = 3,
    ) -> list[KnowledgeFragment]:
        details = self.search(question, context=context, limit=limit)
        return details["fragments"]

    def search(self, question: str, *, context: str = "", limit: int = 5) -> dict[str, object]:
        query_text = f"{context}\n{question}".strip()
        normalized_query = self.normalize_query(query_text)
        if not normalized_query.expanded:
            return {"query": normalized_query, "fragments": []}

        query_words = set(_words(normalized_query.expanded))
        query_phrases = _phrases(normalized_query.expanded)
        if not query_words and not query_phrases:
            return {"query": normalized_query, "fragments": []}

        fragments: list[KnowledgeFragment] = []
        for path, document in self._cache:
            source = str(path.relative_to(self.directory))
            for section in _sections(document):
                title = section.title
                normalized_title = _normalize(title)
                normalized_body = _normalize(section.body)
                normalized_text = _normalize(section.text)
                expanded_text = _normalize(" ".join([normalized_text, source]))
                section_words = set(_words(expanded_text))
                if not section_words:
                    continue

                word_matches = query_words & section_words
                title_matches = query_words & set(_words(normalized_title))
                phrase_matches = [phrase for phrase in query_phrases if phrase in expanded_text]
                title_phrase_matches = [phrase for phrase in query_phrases if phrase in normalized_title]
                fuzzy_title = fuzz.partial_ratio(normalized_query.expanded, normalized_title) if normalized_title else 0

                score = 0
                score += len(word_matches) * 2
                score += len(title_matches) * 7
                score += len(phrase_matches) * 8
                score += len(title_phrase_matches) * 12
                if normalized_query.normalized and normalized_query.normalized in normalized_body:
                    score += 12
                if fuzzy_title >= FUZZY_THRESHOLD:
                    score += int(fuzzy_title // 5)

                if score > 0:
                    fragments.append(
                        KnowledgeFragment(
                            source=source,
                            title=title,
                            text=section.text.strip(),
                            score=score,
                        )
                    )

        fragments.sort(key=lambda fragment: fragment.score, reverse=True)
        return {"query": normalized_query, "fragments": fragments[:limit]}

    def keyword_answer(self, question: str, *, context: str = "") -> str | None:
        fragments = self.relevant_fragments(question, context=context, limit=1)
        if not fragments:
            return None
        return fragments[0].clean_text

    def _alias_matches(self, normalized_query: str) -> list[AliasMatch]:
        matches: list[AliasMatch] = []
        seen: set[tuple[str, str, str]] = set()
        for canonical, aliases in self.aliases.items():
            for alias in aliases:
                normalized_alias = _normalize(alias)
                if not normalized_alias:
                    continue
                if _contains_phrase(normalized_query, normalized_alias):
                    key = (canonical, alias, "direct")
                    if key not in seen:
                        matches.append(AliasMatch(canonical, alias, 100, "direct"))
                        seen.add(key)
                    continue
                score = fuzz.partial_ratio(normalized_query, normalized_alias)
                if score > FUZZY_THRESHOLD:
                    key = (canonical, alias, "fuzzy")
                    if key not in seen:
                        matches.append(AliasMatch(canonical, alias, int(score), "fuzzy"))
                        seen.add(key)
        matches.sort(key=lambda match: match.score, reverse=True)
        return matches


@dataclass(frozen=True)
class _Section:
    title: str
    body: str
    text: str


def strip_markdown(text: str) -> str:
    cleaned_lines: list[str] = []
    in_code_block = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            cleaned_lines.append(line)
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = line.replace("**", "").replace("__", "")
        line = line.replace("`", "")
        line = re.sub(r"^[-*+]\s+", "", line)
        if line:
            cleaned_lines.append(line)
    return "\n".join(_collapse_blank_lines(cleaned_lines)).strip()


def _sections(document: str) -> Iterable[_Section]:
    current_title = "Общая информация"
    current_lines: list[str] = []

    for line in document.splitlines():
        if line.startswith("#"):
            if current_lines:
                body = "\n".join(current_lines).strip()
                yield _Section(current_title, body, f"## {current_title}\n\n{body}")
                current_lines = []
            current_title = line.lstrip("#").strip() or current_title
        else:
            current_lines.append(line)

    if current_lines:
        body = "\n".join(current_lines).strip()
        yield _Section(current_title, body, f"## {current_title}\n\n{body}")


def _normalize(text: str) -> str:
    lowered = text.casefold().replace("ё", "е")
    cleaned = re.sub(r"[^0-9a-zа-яе@+]+", " ", lowered, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _words(text: str) -> list[str]:
    return [word for word in text.split() if len(word) >= 2]


def _phrases(text: str) -> list[str]:
    words = _words(text)
    phrases: list[str] = []
    for size in (2, 3):
        for index in range(0, max(len(words) - size + 1, 0)):
            phrases.append(" ".join(words[index : index + size]))
    return phrases


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        result.append(line)
        previous_blank = is_blank
    return result