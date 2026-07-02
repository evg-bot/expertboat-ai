import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import BASE_DIR, default_expertboat_data_dir, expertboat_data_dir
from scripts.build_faq import group_pairs, load_qa, render_faq_markdown, target_key_for_pair, write_faq_files
from scripts.import_avito import load_jsonl, process_rows
from scripts.import_knowledge import clean_text, detect_category, import_sources, split_chunks


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

    def test_avito_page_text_lowrance_elite_fs_9_genesis_live(self):
        rows = [
            {
                "source": "avito",
                "chat_url": "https://www.avito.ru/profile/messenger/channel/1",
                "text": (
                    "Еще Разместить объявление 4 Авто Недвижимость Работа Услуги Еще Василий Сазанов "
                    "Кошелек 20 ₽ Для бизнеса Карьера в Авито Мои объявления Избранное Уведомления Сообщения "
                    "Lowrance Elite FS 9 + датчик 3-in-1 26.2 RUS 89 900 ₽ "
                    "13 мая 2026 г. 10:15 Добрый день, скажите пожалуйста, что имеется в виду под настройкой genesis live, "
                    "ее надо регистрировать? Прочитано "
                    "10:17 Добрый день. Палитра и наложение. Регистрировать ничего не нужно. "
                    "10:18 Авито — сайт объявлений России ООО «КЕХ еКоммерц» Карта сайта Свежие объявления "
                    "Помощь Безопасность Реклама на сайте О компании Авито Журнал"
                ),
            }
        ]

        messages, pairs, stats = process_rows(rows)

        self.assertEqual(stats.loaded_rows, 1)
        self.assertEqual(stats.parsed_messages, 2)
        self.assertEqual(stats.buyer_messages, 1)
        self.assertEqual(stats.seller_messages, 1)
        self.assertEqual(stats.listing_title_detected, 1)
        self.assertEqual(stats.skipped_footer_messages, 1)
        self.assertEqual(stats.qa_pairs, 1)
        self.assertEqual(messages[0].listing_title, "Lowrance Elite FS 9 + датчик 3-in-1 26.2 RUS")
        self.assertEqual(messages[0].listing_price, "89 900 ₽")
        self.assertEqual(messages[0].date, "13 мая 2026 г.")
        self.assertEqual(messages[0].time, "10:15")
        self.assertEqual(messages[0].sender, "buyer")
        self.assertEqual(messages[1].sender, "seller")
        self.assertEqual(
            pairs[0]["question"],
            "Добрый день, скажите пожалуйста, что имеется в виду под настройкой genesis live, ее надо регистрировать?",
        )
        self.assertEqual(pairs[0]["answer"], "Добрый день. Палитра и наложение. Регистрировать ничего не нужно.")
        self.assertEqual(pairs[0]["listing_title"], "Lowrance Elite FS 9 + датчик 3-in-1 26.2 RUS")
        self.assertEqual(pairs[0]["source"], "avito")
        self.assertFalse(any("Авито — сайт объявлений России" in message.text for message in messages))

    def test_avito_page_text_lowrance_elite_fs_10_invoice_unavailable(self):
        rows = [
            {
                "source": "avito",
                "chat_url": "https://www.avito.ru/profile/messenger/channel/2",
                "text": (
                    "Главное Настройки доставки Корзина Бизнес360 "
                    "Lowrance Elite FS 10 119 900 ₽ "
                    "Вторник, 30 июня 11:01 Добрый день, выставите счет ИП? "
                    "11:05 У нас сейчас нет в наличии. На днях ожидаем, счет выставляем после подтверждения. "
                    "Правила Авито Политика конфиденциальности Регионы"
                ),
            }
        ]

        messages, pairs, stats = process_rows(rows)

        self.assertEqual(stats.parsed_messages, 2)
        self.assertEqual(stats.buyer_messages, 1)
        self.assertEqual(stats.seller_messages, 1)
        self.assertEqual(stats.unknown_messages, 0)
        self.assertEqual(messages[0].listing_title, "Lowrance Elite FS 10")
        self.assertEqual(messages[0].listing_price, "119 900 ₽")
        self.assertEqual(messages[0].date, "Вторник, 30 июня")
        self.assertEqual(pairs[0]["question"], "Добрый день, выставите счет ИП?")
        self.assertIn("нет в наличии", pairs[0]["answer"])

    def test_avito_s_kakogo_order_not_seen_is_seller(self):
        rows = [
            {
                "source": "avito",
                "chat_url": "https://www.avito.ru/profile/messenger/channel/3",
                "text": (
                    "Lowrance Elite FS 10 + датчик AI 3-in-1 26.2 RUS 135 000 ₽ "
                    "13 мая 2026 г. 12:00 Я оплатил заказ, он появился? "
                    "12:02 С какого? Мы заказ ни какой не видим"
                ),
            }
        ]

        messages, pairs, stats = process_rows(rows)

        self.assertEqual(stats.seller_messages, 1)
        self.assertEqual(messages[1].sender, "seller")
        self.assertEqual(pairs[0]["answer"], "С какого? Мы заказ ни какой не видим")

    def test_avito_listing_metadata_message_is_skipped(self):
        rows = [
            {
                "source": "avito",
                "chat_url": "https://www.avito.ru/profile/messenger/channel/4",
                "text": (
                    "Lowrance Elite FS 10 + датчик AI 3-in-1 26.2 RUS 135 000 ₽ "
                    "13 мая 2026 г. 12:00 Lowrance Elite FS 10 + датчик AI 3-in-1 26.2 RUS 135 000 ₽ "
                    "12:01 Когда будет в наличии? "
                    "12:02 На днях ожидаем"
                ),
            }
        ]

        messages, pairs, stats = process_rows(rows)

        self.assertEqual(stats.skipped_listing_metadata_messages, 1)
        self.assertEqual(len(messages), 2)
        self.assertFalse(any(message.text == "Lowrance Elite FS 10 + датчик AI 3-in-1 26.2 RUS 135 000 ₽" for message in messages))
        self.assertEqual(pairs[0]["listing_title"], "Lowrance Elite FS 10 + датчик AI 3-in-1 26.2 RUS")

    def test_avito_support_dialog_is_skipped(self):
        rows = [
            {
                "source": "avito",
                "chat_url": "https://www.avito.ru/support",
                "text": "Поддержка Авито 12:00 Сообщение от Авито",
            }
        ]

        messages, pairs, stats = process_rows(rows)

        self.assertEqual(messages, [])
        self.assertEqual(pairs, [])
        self.assertEqual(stats.skipped_support_dialogs, 1)

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

    def test_expertboat_data_dir_reads_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"EXPERTBOAT_DATA_DIR": tmp}, clear=False):
                self.assertEqual(expertboat_data_dir(), Path(tmp))

    def test_default_data_dir_depends_on_os(self):
        with patch("platform.system", return_value="Windows"):
            self.assertEqual(default_expertboat_data_dir(), Path(r"D:\expertboat-data"))
        with patch("platform.system", return_value="Linux"):
            self.assertEqual(default_expertboat_data_dir(), Path("/data/expertboat-data"))

    def test_import_knowledge_writes_to_external_storage_only(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            data_dir = Path(tmp)
            manual = data_dir / "manuals" / "lowrance" / "elite-fs.txt"
            manual.parent.mkdir(parents=True)
            manual.write_text("Lowrance Elite FS 9\n\nОписание эхолота.", encoding="utf-8")

            results = import_sources(source="manuals", data_dir=data_dir, publish=False, update_rag=False)

            self.assertEqual(results[0].status, "processed")
            self.assertTrue((data_dir / "processed" / "lowrance" / "elite-fs.md").exists())
            self.assertFalse((BASE_DIR / "knowledge" / "processed" / "lowrance" / "elite-fs.md").exists())

    def test_import_avito_reads_external_dialogs(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            avito_file = data_dir / "avito" / "dialogs_raw.jsonl"
            avito_file.parent.mkdir(parents=True)
            avito_file.write_text(
                json.dumps(
                    {
                        "source": "avito",
                        "chat_url": "https://www.avito.ru/profile/messenger/channel/1",
                        "text": "Lowrance Elite FS 9 89 900 ₽ 10:15 Есть Genesis Live?",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"EXPERTBOAT_DATA_DIR": str(data_dir)}, clear=False):
                rows = load_jsonl()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["chat_url"], "https://www.avito.ru/profile/messenger/channel/1")

    def test_build_faq_writes_external_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            processed = data_dir / "processed" / "avito_qa.jsonl"
            processed.parent.mkdir(parents=True)
            processed.write_text(
                json.dumps(
                    {
                        "question": "Как доставка?",
                        "answer": "Доставку согласуем с менеджером.",
                        "category": "delivery",
                        "product": "",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            rows = load_qa(processed)
            written = write_faq_files(group_pairs(rows), data_dir=data_dir)

            self.assertTrue((data_dir / "review" / "delivery.md").exists())
            self.assertTrue((data_dir / "faq" / "delivery.md").exists())
            self.assertTrue(all(data_dir in path.parents for path in written))


if __name__ == "__main__":
    unittest.main()
