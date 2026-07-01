from __future__ import annotations

from pathlib import Path
from typing import Iterable


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

    def keyword_answer(self, question: str) -> str | None:
        normalized_question = _normalize(question)
        if not normalized_question:
            return None

        question_words = set(_words(normalized_question))
        best_score = 0
        best_section: str | None = None

        for _, document in self._cache:
            for section in _sections(document):
                normalized_section = _normalize(section)
                section_words = set(_words(normalized_section))
                if not section_words:
                    continue
                score = len(question_words & section_words)
                if normalized_question in normalized_section:
                    score += 5
                if score > best_score:
                    best_score = score
                    best_section = section.strip()

        if best_score <= 0 or best_section is None:
            return None
        return best_section


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
    return [word.strip(".,:;!?()[]{}<>\"'«»") for word in text.split() if len(word.strip(".,:;!?()[]{}<>\"'«»")) >= 3]
