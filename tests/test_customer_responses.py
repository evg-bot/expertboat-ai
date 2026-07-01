from __future__ import annotations

import unittest

from app.ai import GREETING_RESPONSE, build_local_customer_answer, sanitize_customer_answer
from app.rag import RagChunk


class CustomerResponseTest(unittest.TestCase):
    def test_greeting_response_text(self) -> None:
        self.assertEqual(
            "Здравствуйте! Это Expert Boat. Подскажите, какая модель оборудования вас интересует?",
            GREETING_RESPONSE,
        )

    def test_service_phrases_are_removed(self) -> None:
        text = (
            "Lowrance Elite FS 9 — 9-дюймовый эхолот-картплоттер. "
            "Если клиент пишет 9фс, нужно отвечать именно про Lowrance Elite FS 9. "
            "Нельзя обещать наличие без проверки."
        )
        cleaned = sanitize_customer_answer(text)
        self.assertIn("Lowrance Elite FS 9", cleaned)
        self.assertNotIn("Если клиент пишет", cleaned)
        self.assertNotIn("нужно отвечать", cleaned)
        self.assertNotIn("Нельзя обещать", cleaned)

    def test_elite_fs_9_seller_style_answer(self) -> None:
        chunk = RagChunk(
            id=1,
            source="lowrance/elite-fs.md",
            title="Lowrance Elite FS 9",
            content="## Lowrance Elite FS 9\n\nLowrance Elite FS 9 — модель Elite FS с диагональю 9 дюймов.",
            content_hash="hash",
        )
        self.assertEqual(
            (
                "Lowrance Elite FS 9 — 9-дюймовый эхолот-картплоттер. "
                "Актуальную цену, наличие и комплектацию лучше проверить перед заказом. "
                "Могу подсказать по комплекту, доставке и гарантии — интересует сам прибор или комплект с датчиком?"
            ),
            build_local_customer_answer(chunk),
        )

    def test_elite_fs_10_seller_style_answer(self) -> None:
        chunk = RagChunk(
            id=1,
            source="lowrance/elite-fs.md",
            title="Lowrance Elite FS 10",
            content="## Lowrance Elite FS 10\n\nLowrance Elite FS 10 — модель Elite FS с диагональю 10 дюймов.",
            content_hash="hash",
        )
        self.assertEqual(
            (
                "Lowrance Elite FS 10 — версия Elite FS с экраном 10 дюймов. "
                "По цене, наличию и комплектации лучше проверить актуальный комплект перед заказом. "
                "Рассматриваете 10-дюймовый экран вместо 9-дюймового?"
            ),
            build_local_customer_answer(chunk),
        )


if __name__ == "__main__":
    unittest.main()
