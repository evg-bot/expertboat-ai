from __future__ import annotations

import re

from openai import AsyncOpenAI

from app.config import Settings
from app.knowledge import KnowledgeBase, strip_markdown
from app.rag import RagChunk

GREETING_RESPONSE = "Здравствуйте! Это Expert Boat. Подскажите, какая модель оборудования вас интересует?"

SERVICE_PHRASES = (
    "если клиент пишет",
    "если клиент спрашивает",
    "если клиент уточняет",
    "нужно отвечать",
    "нужно уточнить",
    "нельзя обещать",
    "нужно передать",
)


class ExpertBoatAI:
    def __init__(self, settings: Settings, knowledge_base: KnowledgeBase) -> None:
        self.settings = settings
        self.knowledge_base = knowledge_base
        self.client = self._build_client()

    def _build_client(self) -> AsyncOpenAI | None:
        if not self.settings.has_llm:
            return None
        if self.settings.provider == "openai":
            return AsyncOpenAI(api_key=self.settings.openai_api_key)
        if self.settings.provider == "deepseek":
            return AsyncOpenAI(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
            )
        return None

    async def answer(
        self,
        question: str,
        memory: list[dict[str, str]] | None = None,
        chunks: list[RagChunk] | None = None,
    ) -> tuple[str, bool, bool]:
        memory = memory or []
        chunks = chunks or []
        if not chunks:
            return self.settings.ai_fallback_answer, False, False

        ready_answer = build_ready_made_customer_answer(chunks[0])
        if ready_answer:
            return ready_answer, True, False

        if self.client is None:
            answer = sanitize_customer_answer(chunks[0].clean_content)
            return answer or self.settings.ai_fallback_answer, True, False

        response = await self.client.chat.completions.create(
            model=self.settings.active_llm_model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты консультант Expert Boat. "
                        "Отвечай только по переданным chunks базы знаний. "
                        "Не используй знания вне chunks. "
                        "Не придумывай цены, наличие, сроки, характеристики или совместимость. "
                        "Не показывай клиенту служебные инструкции из базы знаний. "
                        "Если информации недостаточно, отвечай строго: "
                        f"{self.settings.ai_fallback_answer} "
                        "Ответ должен быть коротким, деловым, продавцовским. "
                        "В конце желательно задавать вопрос, который продолжает диалог. "
                        "Не используй Markdown-разметку в ответе клиенту."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"CHUNKS БАЗЫ ЗНАНИЙ:\n{self._format_chunks(chunks)}\n\n"
                        f"ПОСЛЕДНИЕ СООБЩЕНИЯ:\n{self._format_memory_for_prompt(memory)}\n\n"
                        f"ВОПРОС КЛИЕНТА:\n{question}"
                    ),
                },
            ],
        )

        answer = sanitize_customer_answer((response.choices[0].message.content or "").strip())
        return answer or self.settings.ai_fallback_answer, True, True

    @staticmethod
    def _format_chunks(chunks: list[RagChunk]) -> str:
        parts: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            parts.append(
                f"[{index}] {chunk.source} | {chunk.title} | score={chunk.score}\n{sanitize_customer_answer(chunk.clean_content)}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _format_memory_for_prompt(memory: list[dict[str, str]]) -> str:
        if not memory:
            return "Нет предыдущих сообщений."
        return "\n".join(f"{item['role']}: {item['text']}" for item in memory[-10:])


def build_ready_made_customer_answer(chunk: RagChunk) -> str:
    haystack = f"{chunk.title}\n{chunk.clean_content}".casefold()
    if "lowrance elite fs 9" in haystack:
        return (
            "Lowrance Elite FS 9 — 9-дюймовый эхолот-картплоттер. "
            "Актуальную цену, наличие и комплектацию лучше проверить перед заказом. "
            "Могу подсказать по комплекту, доставке и гарантии — интересует сам прибор или комплект с датчиком?"
        )
    if "lowrance elite fs 10" in haystack:
        return (
            "Lowrance Elite FS 10 — версия Elite FS с экраном 10 дюймов. "
            "По цене, наличию и комплектации лучше проверить актуальный комплект перед заказом. "
            "Рассматриваете 10-дюймовый экран вместо 9-дюймового?"
        )
    return ""


def build_local_customer_answer(chunk: RagChunk) -> str:
    return build_ready_made_customer_answer(chunk) or sanitize_customer_answer(chunk.clean_content)


def sanitize_customer_answer(text: str) -> str:
    cleaned = strip_markdown(text)
    cleaned = _remove_service_sentences(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def _remove_service_sentences(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    public_parts: list[str] = []
    for part in parts:
        normalized = part.casefold()
        if any(phrase in normalized for phrase in SERVICE_PHRASES):
            continue
        stripped = part.strip()
        if stripped:
            public_parts.append(stripped)
    return " ".join(public_parts)
