import json
import tempfile
import unittest
from pathlib import Path

from scripts.import_avito import process_rows
from scripts.import_listings import (
    extract_title_fields,
    import_listings,
    load_jsonl,
    normalize_listing,
    parse_price,
    sqlite_path,
)
from scripts.build_faq import FAQ_FILES, write_faq_files


class ListingBuilderTests(unittest.TestCase):
    def test_parse_price(self):
        price, price_text, currency = parse_price("135 000 ₽")

        self.assertEqual(price, 135000)
        self.assertEqual(price_text, "135 000 ₽")
        self.assertEqual(currency, "RUB")

    def test_extract_elite_fs_9_fields(self):
        fields = extract_title_fields("Lowrance Elite FS 9 + датчик 3-in-1 26.2 RUS")

        self.assertEqual(fields["brand"], "Lowrance")
        self.assertEqual(fields["series"], "Elite FS")
        self.assertEqual(fields["model"], "Elite FS 9")
        self.assertEqual(fields["screen_size"], "9")
        self.assertEqual(fields["transducer"], "3-in-1")
        self.assertEqual(fields["firmware"], "26.2")
        self.assertEqual(fields["category"], "chartplotter")

    def test_extract_hds_pro_12_fields(self):
        fields = extract_title_fields("Lowrance HDS PRO 12 + AI 3-in-1")

        self.assertEqual(fields["brand"], "Lowrance")
        self.assertEqual(fields["series"], "HDS PRO")
        self.assertEqual(fields["model"], "HDS PRO 12")
        self.assertEqual(fields["screen_size"], "12")
        self.assertEqual(fields["transducer"], "AI 3-in-1")
        self.assertEqual(fields["category"], "chartplotter")

    def test_extract_active_target_2_fields(self):
        fields = extract_title_fields("ActiveTarget 2 System")

        self.assertEqual(fields["brand"], "Lowrance")
        self.assertEqual(fields["series"], "ActiveTarget")
        self.assertEqual(fields["model"], "ActiveTarget 2")
        self.assertEqual(fields["category"], "live_sonar")

    def test_fallback_from_avito_qa_creates_listings(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            data_dir = Path(tmp)
            qa_path = data_dir / "processed" / "avito_qa.jsonl"
            qa_path.parent.mkdir(parents=True)
            qa_path.write_text(
                json.dumps(
                    {
                        "chat_url": "https://www.avito.ru/profile/messenger/channel/1",
                        "listing_title": "Lowrance Elite FS 9 + датчик 3-in-1 26.2 RUS",
                        "listing_price": "89 900 ₽",
                        "question": "Цена?",
                        "answer": "Цена по объявлению — 89 900 ₽.",
                        "source": "avito",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            stats = import_listings(data_dir=data_dir)
            cleaned = load_jsonl(data_dir / "listings" / "listings_cleaned.jsonl")

            self.assertEqual(stats.fallback_listings_from_qa, 1)
            self.assertEqual(stats.inserted, 1)
            self.assertTrue(sqlite_path(data_dir).exists())
            self.assertEqual(cleaned[0]["title"], "Lowrance Elite FS 9 + датчик 3-in-1 26.2 RUS")
            self.assertEqual(cleaned[0]["price"], 89900)

    def test_fallback_merges_duplicate_title_price_chat_urls(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            data_dir = Path(tmp)
            qa_path = data_dir / "processed" / "avito_qa.jsonl"
            qa_path.parent.mkdir(parents=True)
            rows = [
                {
                    "chat_url": f"https://www.avito.ru/profile/messenger/channel/{index}",
                    "listing_title": "Lowrance Elite FS 9 + датчик 3-in-1 26.2 RUS",
                    "listing_price": "89 900 ₽",
                    "question": "Цена?",
                    "answer": "Цена по объявлению — 89 900 ₽.",
                    "source": "avito",
                }
                for index in range(1, 4)
            ]
            qa_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            stats = import_listings(data_dir=data_dir)
            cleaned = load_jsonl(data_dir / "listings" / "listings_cleaned.jsonl")
            attributes = json.loads(cleaned[0]["attributes_json"])

            self.assertEqual(stats.fallback_listings_from_qa, 1)
            self.assertEqual(stats.duplicate_fallback_rows_merged, 2)
            self.assertEqual(stats.unique_listings_exported, 1)
            self.assertEqual(len(cleaned), 1)
            self.assertEqual(cleaned[0]["url"], "")
            self.assertEqual(len(attributes["chat_urls"]), 3)

    def test_price_question_uses_listing_price_instead_of_short_seller_answer(self):
        rows = [
            {
                "source": "avito",
                "chat_url": "https://www.avito.ru/profile/messenger/channel/price",
                "text": (
                    "Lowrance Elite FS 10 + датчик AI 3-in-1 26.2 RUS 135 000 ₽ "
                    "13 мая 2026 г. 12:00 Какая актуальная цена? "
                    "12:01 Да"
                ),
            }
        ]

        _messages, pairs, _stats = process_rows(rows)

        self.assertEqual(len(pairs), 1)
        self.assertEqual(
            pairs[0]["answer"],
            "Цена по объявлению — 135 000 ₽. Актуальность и наличие лучше подтвердить перед заказом.",
        )

    def test_price_question_without_listing_price_is_skipped(self):
        rows = [
            {
                "source": "avito",
                "chat_url": "https://www.avito.ru/profile/messenger/channel/no-price",
                "text": "13 мая 2026 г. 12:00 Какая цена? 12:01 Да",
            }
        ]

        _messages, pairs, _stats = process_rows(rows)

        self.assertEqual(pairs, [])

    def test_listing_history_records_changed_price(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            data_dir = Path(tmp)
            raw = data_dir / "listings" / "listings_raw.jsonl"
            raw.parent.mkdir(parents=True)
            first = {
                "url": "https://www.avito.ru/samara/vodnyy_transport/lowrance_elite_fs_9_1234567890",
                "title": "Lowrance Elite FS 9 + датчик 3-in-1 26.2 RUS",
                "price": "89 900 ₽",
                "status": "active",
            }
            raw.write_text(json.dumps(first, ensure_ascii=False) + "\n", encoding="utf-8")
            import_listings(data_dir=data_dir)

            second = {**first, "price": "95 000 ₽"}
            raw.write_text(json.dumps(second, ensure_ascii=False) + "\n", encoding="utf-8")
            stats = import_listings(data_dir=data_dir)
            history = load_jsonl(data_dir / "listings" / "listing_history.jsonl")

            self.assertEqual(stats.updated, 1)
        self.assertTrue(any(row["field"] == "price" and row["old_value"] == "89900" and row["new_value"] == "95000" for row in history))

    def test_build_faq_adds_listing_price_review_file(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            data_dir = Path(tmp)
            raw = data_dir / "listings" / "listings_raw.jsonl"
            raw.parent.mkdir(parents=True)
            raw.write_text(
                json.dumps(
                    {
                        "title": "Lowrance Elite FS 10 + датчик AI 3-in-1 26.2 RUS",
                        "price": "135 000 ₽",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            import_listings(data_dir=data_dir)

            write_faq_files({key: [] for key in FAQ_FILES}, data_dir=data_dir)
            faq = (data_dir / "review" / "listings_price_faq.md").read_text(encoding="utf-8")

            self.assertIn("Сколько стоит Lowrance Elite FS 10 + датчик AI 3-in-1 26.2 RUS?", faq)
            self.assertIn("Цена по объявлению — 135 000 ₽.", faq)

    def test_listing_id_from_url_is_stable(self):
        record = normalize_listing(
            {
                "url": "https://www.avito.ru/samara/vodnyy_transport/lowrance_hds_pro_12_9876543210",
                "title": "Lowrance HDS PRO 12 + AI 3-in-1",
                "price": "220 000 ₽",
            }
        )

        self.assertEqual(record.listing_id, "9876543210")


if __name__ == "__main__":
    unittest.main()
