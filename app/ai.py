from __future__ import annotations

from openai import AsyncOpenAI

from app.config import Settings
from app.knowledge import KnowledgeBase
from app.models import StoredMessage


class ExpertBoatAI:
    def __init__(self, settings: Settings, knowledge_base: KnowledgeBase) -> None:
        self.settings = settings
        self.knowledge_base = knowledge_base
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def answer(self, question: str, history: list[StoredMessage]) -> str:
        knowledge = self.knowledge_base.load_markdown()
        if not knowledge.strip():
            return self.settings.ai_fallback_answer

        history_text = "\n".join(
            f"{message.direction}: {message.text}" for message in history[-10:]
        )

        response = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты AI-продавец магазина морской электроники Expert Boat. "
                        "Отвечай только на русском языке и только на основании базы знаний ниже. "
                        "Если в базе знаний нет точного ответа, верни ровно эту фразу без дополнений: "
                        f"{self.settings.ai_fallback_answer}\n\n"
                        "Не выдумывай характеристики, цены, наличие, сроки доставки, гарантии или условия. "
                        "Не используй знания вне базы знаний."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"БАЗА ЗНАНИЙ:\n{knowledge}\n\n"
                        f"ИСТОРИЯ ПЕРЕПИСКИ:\n{history_text}\n\n"
                        f"ВОПРОС КЛИЕНТА:\n{question}"
                    ),
                },
            ],
        )

        answer = (response.choices[0].message.content or "").strip()
        if not answer:
            return self.settings.ai_fallback_answer
        return answer
