from __future__ import annotations

from openai import AsyncOpenAI

from app.config import Settings
from app.knowledge import KnowledgeBase, KnowledgeFragment
from app.models import StoredMessage


class ExpertBoatAI:
    def __init__(self, settings: Settings, knowledge_base: KnowledgeBase) -> None:
        self.settings = settings
        self.knowledge_base = knowledge_base
        self.client = self._build_client()

    def _build_client(self) -> AsyncOpenAI | None:
        if not self.settings.has_llm:
            return None
        if self.settings.provider == "deepseek":
            return AsyncOpenAI(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
            )
        if self.settings.provider == "openai":
            return AsyncOpenAI(api_key=self.settings.openai_api_key)
        return None

    async def answer(self, question: str, history: list[StoredMessage] | None = None) -> str:
        fragments = self.knowledge_base.relevant_fragments(question)
        if not fragments:
            return self.settings.ai_fallback_answer

        if self.client is None:
            return self.knowledge_base.keyword_answer(question) or self.settings.ai_fallback_answer

        history = history or []
        history_text = "\n".join(
            f"{message.direction}: {message.text}" for message in history[-6:]
        )
        fragments_text = self._format_fragments(fragments)

        response = await self.client.chat.completions.create(
            model=self.settings.active_llm_model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты Telegram-бот магазина морской электроники Expert Boat. "
                        "Отвечай клиенту коротко, понятно и на русском языке. "
                        "Используй только переданные фрагменты базы знаний. "
                        "Запрещено использовать знания вне этих фрагментов, додумывать цены, наличие, сроки, гарантии или характеристики. "
                        "Если во фрагментах нет точного ответа, верни ровно эту фразу без дополнений: "
                        f"{self.settings.ai_fallback_answer}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"ФРАГМЕНТЫ БАЗЫ ЗНАНИЙ:\n{fragments_text}\n\n"
                        f"ИСТОРИЯ ДИАЛОГА:\n{history_text}\n\n"
                        f"ВОПРОС КЛИЕНТА:\n{question}"
                    ),
                },
            ],
        )

        answer = (response.choices[0].message.content or "").strip()
        return answer or self.settings.ai_fallback_answer

    @staticmethod
    def _format_fragments(fragments: list[KnowledgeFragment]) -> str:
        parts: list[str] = []
        for index, fragment in enumerate(fragments, start=1):
            parts.append(f"[{index}] {fragment.source}\n{fragment.text}")
        return "\n\n".join(parts)
