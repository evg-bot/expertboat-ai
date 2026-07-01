from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class KnowledgeFragment:
    source: str
    title: str
    text: str
    score: int


class KnowledgeBase:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._cache = self.load_documents()

    @property
    def document_count(self) -> int:
        return len(self._cache)

    def reload(self) -> None:
        self._cache = self.load_documents()

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

    def relevant_fragments(
        self,
        question: str,
        *,
        context: str = "",
        limit: int = 3,
    ) -> list[KnowledgeFragment]:
        query = f"{context}\n{question}".strip()
        normalized_query = _normalize(query)
        if not normalized_query:
            return []

        query_words = set(_words(normalized_query))
        query_phrases = _phrases(normalized_query)
        if not query_words and not query_phrases:
            return []

        fragments: list[KnowledgeFragment] = []
        for path, document in self._cache:
            source = str(path.relative_to(self.directory))
            for section in _sections(document):
                title = section.title
                normalized_title = _normalize(title)
                normalized_body = _normalize(section.body)
                normalized_text = _normalize(section.text)
                section_words = set(_words(normalized_text))
                if not section_words:
                    continue

                word_matches = query_words & section_words
                title_matches = query_words & set(_words(normalized_title))
                phrase_matches = [phrase for phrase in query_phrases if phrase in normalized_text]
                title_phrase_matches = [phrase for phrase in query_phrases if phrase in normalized_title]

                score = 0
                score += len(word_matches)
                score += len(title_matches) * 4
                score += len(phrase_matches) * 5
                score += len(title_phrase_matches) * 8
                if normalized_query and normalized_query in normalized_text:
                    score += 10
                if question and _normalize(question) in normalized_body:
                    score += 6

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
        return fragments[:limit]

    def keyword_answer(self, question: str, *, context: str = "") -> str | None:
        fragments = self.relevant_fragments(question, context=context, limit=1)
        if not fragments:
            return None
        return fragments[0].text


@dataclass(frozen=True)
class _Section:
    title: str
    body: str
    text: str


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
    lowered = text.casefold()
    cleaned = re.sub(r"[^0-9a-zа-яё@+]+", " ", lowered, flags=re.IGNORECASE)
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