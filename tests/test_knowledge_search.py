from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.knowledge import KnowledgeBase, strip_markdown


ALIASES_YAML = '''
"Lowrance Elite FS 9":
  - "9фс"
"ActiveTarget 2":
  - "ат2"
"Доставка":
  - "сдэк"
"Русификация":
  - "русик"
"Point-1":
  - "point1"
'''


DOCS = {
    "elite-fs-9.md": "# Lowrance Elite FS 9\n\nИнформация про Lowrance Elite FS 9.",
    "active-target-2.md": "# ActiveTarget 2\n\nИнформация про ActiveTarget 2.",
    "delivery.md": "# Доставка\n\nИнформация про доставку.",
    "firmware.md": "# Русификация\n\nИнформация про русификацию.",
    "point-1.md": "# Point-1\n\nИнформация про Point-1.",
}


class KnowledgeAliasSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.knowledge_dir = Path(self.tmp.name)
        (self.knowledge_dir / "aliases.yaml").write_text(ALIASES_YAML, encoding="utf-8")
        for filename, content in DOCS.items():
            (self.knowledge_dir / filename).write_text(content, encoding="utf-8")
        self.kb = KnowledgeBase(self.knowledge_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def assert_alias_finds_title(self, query: str, expected_title: str) -> None:
        normalized = self.kb.normalize_query(query)
        self.assertIn(expected_title, [match.canonical for match in normalized.matches])
        fragments = self.kb.relevant_fragments(query, limit=1)
        self.assertTrue(fragments, f"No fragments found for {query!r}")
        self.assertEqual(expected_title, fragments[0].title)

    def test_elite_fs_9_alias(self) -> None:
        self.assert_alias_finds_title("9фс", "Lowrance Elite FS 9")

    def test_active_target_2_alias(self) -> None:
        self.assert_alias_finds_title("ат2", "ActiveTarget 2")

    def test_delivery_alias(self) -> None:
        self.assert_alias_finds_title("сдэк", "Доставка")

    def test_firmware_alias(self) -> None:
        self.assert_alias_finds_title("русик", "Русификация")

    def test_point_1_alias(self) -> None:
        self.assert_alias_finds_title("point1", "Point-1")

    def test_strip_markdown_removes_client_visible_markup(self) -> None:
        text = "# Заголовок\n\n***\n\n## Подзаголовок\n\n**Ответ** клиенту"
        cleaned = strip_markdown(text)
        self.assertNotIn("#", cleaned)
        self.assertNotIn("***", cleaned)
        self.assertEqual("Заголовок\nПодзаголовок\nОтвет клиенту", cleaned)


if __name__ == "__main__":
    unittest.main()

