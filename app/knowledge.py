from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class KnowledgeFragment:
    source: str
    text: str
    score: int


class KnowledgeBase:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._cache = self.load_documents()

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

    def relevant_fragments(self, question: str, *, limit: int = 4) -> list[KnowledgeFragment]:
        normalized_question = _normalize(question)
        if not normalized_question:
            return []

        question_words = set(_words(normalized_question))
        if not question_words:
            return []

        fragments: list[KnowledgeFragment] = []
        for path, document in self._cache:
            source = str(path.relative_to(self.directory))
            for section in _sections(document):
                normalized_section = _normalize(section)
                section_words = set(_words(normalized_section))
                if not section_words:
                    continue
                score = len(question_words & section_words)
                if normalized_question in normalized_section:
                    score += 5
                if score > 0:
                    fragments.append(KnowledgeFragment(source=source, text=section.strip(), score=score))

        fragments.sort(key=lambda fragment: fragment.score, reverse=True)
        return fragments[:limit]

    def keyword_answer(self, question: str) -> str | None:
        fragments = self.relevant_fragments(question, limit=1)
        if not fragments:
            return None
        return fragments[0].text


def _sections(document: str) -> Iterable[str]:
    current: list[str] = []
    for line in document.splitlines():
        if line.startswith("#") and current:
            yield "\n".join(current).strip()
            current = [line]
        else:
            current.append(line)
    if current:
        yield "\n".join(current).strip()


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _words(text: str) -> list[str]:
    return [
        word
        for raw_word in text.split()
        if len(word := raw_word.strip(".,:;!?()[]{}<>\"'«»")) >= 3
    ]
