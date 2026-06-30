from __future__ import annotations

from pathlib import Path


class KnowledgeBase:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def load_markdown(self) -> str:
        documents: list[str] = []
        for path in sorted(self.directory.rglob("*.md")):
            text = path.read_text(encoding="utf-8").strip()
            if text:
                documents.append(f"# {path.relative_to(self.directory)}\n\n{text}")
        return "\n\n---\n\n".join(documents)

    def is_empty(self) -> bool:
        return not self.load_markdown().strip()
