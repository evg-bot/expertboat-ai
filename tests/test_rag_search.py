from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import FALLBACK_ANSWER
from app.database import Database
from app.knowledge import KnowledgeBase
from app.rag import RagEngine


ALIASES_YAML = '''
"Lowrance Elite FS 9":
  - "9фс"
"ActiveTarget 2":
  - "ат2"
"Доставка":
  - "сдэк"
"Оплата":
  - "как оплатить"
"Русификация":
  - "русик"
'''


DOCS = {
    "lowrance/elite-fs.md": """---
product: Lowrance Elite FS
category: lowrance
tags:
  - Lowrance Elite FS 9
  - 9фс
priority: 10
---

# Lowrance Elite FS

Информация про Lowrance Elite FS 9.
""",
    "lowrance/active-target.md": """---
product: ActiveTarget 2
category: lowrance
tags:
  - ат2
  - active target 2
priority: 10
---

# ActiveTarget 2

Информация про ActiveTarget 2.
""",
    "payment.md": """---
product: Expert Boat
category: payment
tags:
  - оплата
  - как оплатить
priority: 10
---

# Покупка и оплата

Информация про оплату.
""",
    "delivery.md": """---
product: Expert Boat
category: delivery
tags:
  - доставка
  - сдэк
priority: 10
---

# Доставка

Информация про доставку СДЭК.
""",
    "firmware.md": """---
product: Expert Boat
category: firmware
tags:
  - русификация
  - русик
priority: 10
---

# Русификация

Информация про русификацию.
""",
}


class RagSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.knowledge_dir = self.root / "knowledge"
        self.knowledge_dir.mkdir()
        (self.knowledge_dir / "aliases.yaml").write_text(ALIASES_YAML, encoding="utf-8")
        for filename, content in DOCS.items():
            path = self.knowledge_dir / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        self.database = Database(self.root / "expertboat.db")
        self.database.init()
        self.kb = KnowledgeBase(self.knowledge_dir)
        self.rag = RagEngine(self.database, self.kb)
        self.rag.reindex()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def assert_top_contains(self, query: str, expected: str) -> None:
        result = self.rag.search(query, limit=5)
        self.assertTrue(result.has_answer, f"Expected answer for {query!r}, top score={result.top_score}")
        top = result.chunks[0]
        haystack = f"{top.source}\n{top.title}\n{top.content}"
        self.assertIn(expected, haystack)

    def test_elite_fs_9_alias(self) -> None:
        self.assert_top_contains("9фс", "Lowrance Elite FS 9")

    def test_active_target_2_alias(self) -> None:
        self.assert_top_contains("ат2", "ActiveTarget 2")

    def test_payment_query(self) -> None:
        self.assert_top_contains("как оплатить", "payment")

    def test_delivery_query(self) -> None:
        self.assert_top_contains("сдэк", "delivery")

    def test_firmware_query(self) -> None:
        self.assert_top_contains("русик", "firmware")

    def test_unknown_query_returns_fallback(self) -> None:
        result = self.rag.search("какая погода завтра на луне", limit=5)
        answer = FALLBACK_ANSWER if not result.has_answer else result.chunks[0].clean_content
        self.assertFalse(result.has_answer)
        self.assertEqual("Точный ответ передам специалисту Expert Boat.", answer)


if __name__ == "__main__":
    unittest.main()
