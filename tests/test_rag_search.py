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
  - "elite fs 9"
"Lowrance Elite FS 10":
  - "10фс"
  - "elite fs 10"
"ActiveTarget 2":
  - "ат2"
"Доставка":
  - "сдэк"
"Оплата":
  - "как оплатить"
"Гарантия":
  - "гарантия"
"Русификация":
  - "русик"
"C-MAP":
  - "карта вся россия"
  - "cmap"
'''


DOCS = {
    "lowrance/elite-fs.md": """---
product: Lowrance Elite FS
category: lowrance
tags:
  - Lowrance Elite FS 9
  - Lowrance Elite FS 10
  - 9фс
  - 10фс
priority: 10
---

# Lowrance Elite FS

Lowrance Elite FS — серия эхолотов-картплоттеров Lowrance.

## Lowrance Elite FS 9

Lowrance Elite FS 9 — модель Elite FS с диагональю 9 дюймов.

## Lowrance Elite FS 10

Lowrance Elite FS 10 — модель Elite FS с диагональю 10 дюймов. Если клиент уточняет "а десятка?", отвечать про Lowrance Elite FS 10.
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
    "warranty.md": """---
product: Expert Boat
category: warranty
tags:
  - гарантия
priority: 10
---

# Гарантия

Информация про гарантию.
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
    "maps.md": """---
product: C-MAP
category: maps
tags:
  - карта вся россия
  - C-MAP
priority: 10
---

# C-MAP

Информация про карты C-MAP.
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

    def test_elite_fs_9_availability_query(self) -> None:
        result = self.rag.search("Есть Elite FS 9?", limit=5)
        self.assertTrue(result.has_answer)
        self.assertIn("Lowrance Elite FS 9", result.chunks[0].content)

    def test_short_refinement_uses_history_for_elite_fs_10(self) -> None:
        result = self.rag.search("А десятка?", history=[{"role": "user", "text": "9фс"}], limit=5)
        self.assertTrue(result.has_answer)
        self.assertTrue(result.context.used_history)
        self.assertIn("Lowrance Elite FS 10", result.chunks[0].content)

    def test_search_command_history_does_not_enable_refinement(self) -> None:
        result = self.rag.search("А десятка?", history=[{"role": "user", "text": "/search 9фс"}], limit=5)
        self.assertFalse(result.has_answer)
        self.assertFalse(result.context.used_history)

    def test_off_topic_ignores_history_and_falls_back(self) -> None:
        result = self.rag.search(
            "Как заменить турбину на КамАЗе?",
            history=[{"role": "user", "text": "9фс"}],
            limit=5,
        )
        answer = FALLBACK_ANSWER if not result.has_answer else result.chunks[0].clean_content
        self.assertFalse(result.has_answer)
        self.assertFalse(result.context.used_history)
        self.assertEqual("off_topic", result.context.intent)
        self.assertEqual("Точный ответ передам специалисту Expert Boat.", answer)

    def test_delivery_query(self) -> None:
        result = self.rag.search("доставка сдэк", limit=5)
        self.assertTrue(result.has_answer)
        self.assertEqual("delivery", result.context.intent)
        self.assertIn("delivery", result.chunks[0].source)

    def test_warranty_query(self) -> None:
        result = self.rag.search("какая гарантия", limit=5)
        self.assertTrue(result.has_answer)
        self.assertEqual("warranty", result.context.intent)
        self.assertIn("warranty", result.chunks[0].source)

    def test_greeting_intent(self) -> None:
        result = self.rag.search("привет", limit=5)
        self.assertEqual("greeting", result.context.intent)

    def test_firmware_query(self) -> None:
        result = self.rag.search("русик есть?", limit=5)
        self.assertTrue(result.has_answer)
        self.assertEqual("firmware", result.context.intent)
        self.assertIn("firmware", result.chunks[0].source)

    def test_maps_query(self) -> None:
        result = self.rag.search("карта вся россия", limit=5)
        self.assertTrue(result.has_answer)
        self.assertEqual("maps", result.context.intent)
        self.assertIn("C-MAP", result.chunks[0].content)

    def test_active_target_2_alias(self) -> None:
        self.assert_top_contains("ат2", "ActiveTarget 2")

    def test_payment_query(self) -> None:
        self.assert_top_contains("как оплатить", "payment")


if __name__ == "__main__":
    unittest.main()
