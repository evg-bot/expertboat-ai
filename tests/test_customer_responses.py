from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.ai import GREETING_RESPONSE, ExpertBoatAI, build_local_customer_answer, sanitize_customer_answer
from app.config import Settings, load_settings
from app.knowledge import KnowledgeBase
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


class _FakeMessage:
    content = "Короткий ответ по переданным chunks."


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    choices = [_FakeChoice()]


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls = 0
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return _FakeResponse()


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()


class _TestAI(ExpertBoatAI):
    def __init__(self, settings: Settings, knowledge_base: KnowledgeBase, client: _FakeOpenAIClient) -> None:
        self.fake_client = client
        super().__init__(settings, knowledge_base)

    def _build_client(self):
        return self.fake_client


class OpenAIRoutingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.knowledge_base = KnowledgeBase(Path(self.tmp.name))
        self.settings = Settings(
            app_env="test",
            log_level="INFO",
            database_path=Path(self.tmp.name) / "db.sqlite",
            knowledge_dir=Path(self.tmp.name),
            llm_provider="openai",
            llm_model="deepseek-chat",
            deepseek_api_key="",
            deepseek_base_url="https://api.deepseek.com",
            openai_api_key="sk-test",
            openai_model="gpt-4.1-mini",
            avito_client_id="",
            avito_client_secret="",
            avito_user_id="",
            avito_api_base_url="https://api.avito.ru",
            avito_poll_interval_seconds=5,
            telegram_bot_token="token",
            telegram_manager_chat_id="",
        )
        self.client = _FakeOpenAIClient()
        self.ai = _TestAI(self.settings, self.knowledge_base, self.client)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_ready_made_answer_does_not_call_openai(self) -> None:
        chunk = RagChunk(
            id=1,
            source="lowrance/elite-fs.md",
            title="Lowrance Elite FS 9",
            content="## Lowrance Elite FS 9\n\nLowrance Elite FS 9 — модель Elite FS с диагональю 9 дюймов.",
            content_hash="hash",
        )
        answer, found, used_llm = await self.ai.answer("9фс", chunks=[chunk])
        self.assertIn("Lowrance Elite FS 9", answer)
        self.assertTrue(found)
        self.assertFalse(used_llm)
        self.assertEqual(0, self.client.chat.completions.calls)

    async def test_relevant_non_ready_chunk_calls_openai_once(self) -> None:
        chunk = RagChunk(
            id=2,
            source="delivery.md",
            title="Доставка",
            content="## Доставка\n\nExpert Boat организует доставку по согласованию с покупателем.",
            content_hash="hash2",
        )
        answer, found, used_llm = await self.ai.answer("доставка сдэк", chunks=[chunk])
        self.assertEqual("Короткий ответ по переданным chunks.", answer)
        self.assertTrue(found)
        self.assertTrue(used_llm)
        self.assertEqual(1, self.client.chat.completions.calls)
        messages = self.client.chat.completions.last_kwargs["messages"]
        self.assertIn("Expert Boat организует доставку", messages[1]["content"])

    async def test_empty_chunks_fallback_does_not_call_openai(self) -> None:
        answer, found, used_llm = await self.ai.answer("не по теме", chunks=[])
        self.assertEqual(self.settings.ai_fallback_answer, answer)
        self.assertFalse(found)
        self.assertFalse(used_llm)
        self.assertEqual(0, self.client.chat.completions.calls)


class SettingsDefaultTest(unittest.TestCase):
    def test_openai_is_default_provider(self) -> None:
        with patch("app.config.load_dotenv", lambda *_args, **_kwargs: None):
            with patch.dict("os.environ", {}, clear=True):
                settings = load_settings()
        self.assertEqual("openai", settings.provider)
        self.assertEqual("gpt-4.1-mini", settings.openai_model)


if __name__ == "__main__":
    unittest.main()
