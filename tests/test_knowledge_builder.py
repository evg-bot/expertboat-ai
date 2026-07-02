import unittest

from scripts.build_faq import group_pairs, render_faq_markdown, target_key_for_pair
from scripts.import_avito import AvitoMessage, build_qa_pairs, merge_consecutive, process_rows
from scripts.import_knowledge import clean_text, detect_category, split_chunks


class KnowledgeBuilderTests(unittest.TestCase):
    def test_clean_text_removes_page_numbers_and_repeated_headers(self):
        raw = "\n".join(
            [
                "Expert Boat Manual",
                "Lowrance Elite FS 9",
                "Page 1 of 3",
                "Expert Boat Manual",
                "ActiveTarget support",
                "2",
                "Expert Boat Manual",
            ]
        )

        cleaned = clean_text(raw)

        self.assertNotIn("Expert Boat Manual", cleaned)
        self.assertNotIn("Page 1 of 3", cleaned)
        self.assertIn("Lowrance Elite FS 9", cleaned)
        self.assertIn("ActiveTarget support", cleaned)

    def test_detect_category(self):
        self.assertEqual(detect_category("Lowrance Elite FS 9 эхолот"), "Lowrance")
        self.assertEqual(detect_category("Как купить и оплатить заказ"), "Sales")

    def test_split_chunks_keeps_content(self):
        chunks = split_chunks("A" * 900 + "\n\n" + "B" * 900, max_chars=1000)

        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].startswith("A"))
        self.assertTrue(chunks[1].startswith("B"))

    def test_avito_processing_merges_and_builds_qa(self):
        rows = [
            {"id": "1", "chat_id": "c1", "direction": "incoming", "text": "Есть 9фс?"},
            {"id": "2", "chat_id": "c1", "direction": "outgoing", "text": "Да, проверим наличие."},
            {"id": "3", "chat_id": "c1", "direction": "incoming", "text": "спасибо"},
        ]

        messages, pairs = process_rows(rows)

        self.assertEqual(len(messages), 2)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["product"], "Elite FS")
        self.assertEqual(pairs[0]["category"], "sales")

    def test_merge_consecutive_same_author(self):
        messages = [
            AvitoMessage("c1", "customer", "Добрый день", "1", "1"),
            AvitoMessage("c1", "customer", "Нужен датчик", "2", "2"),
            AvitoMessage("c1", "manager", "Подскажем", "3", "3"),
        ]

        merged = merge_consecutive(messages)
        pairs = build_qa_pairs(merged)

        self.assertEqual(len(merged), 2)
        self.assertIn("Нужен датчик", merged[0].text)
        self.assertEqual(len(pairs), 1)

    def test_build_faq_review_markdown(self):
        pair = {
            "question": "Как оплатить?",
            "answer": "Можно согласовать удобный способ оплаты с менеджером.",
            "category": "payment",
            "product": "",
        }

        self.assertEqual(target_key_for_pair(pair), "payment")
        grouped = group_pairs([pair])
        markdown = render_faq_markdown("FAQ: оплата", grouped["payment"])

        self.assertIn("review_status: pending", markdown)
        self.assertIn("## Как оплатить?", markdown)


if __name__ == "__main__":
    unittest.main()
