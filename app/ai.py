from __future__ import annotations

from openai import AsyncOpenAI

from app.config import Settings
from app.knowledge import KnowledgeBase, strip_markdown
from app.rag import RagChunk


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

        if self.client is None:
            return chunks[0].clean_content or self.settings.ai_fallback_answer, True, False

        response = await self.client.chat.completions.create(
            model=self.settings.active_llm_model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты консультант Expert Boat. "
                        "Отвечай только по переданным фрагментам базы знаний. "
                        "Не придумывай цены, наличие, сроки, характеристики, совместимость. "
                        "Если информации недостаточно, отвечай строго: "
                        f"{self.settings.ai_fallback_answer} "
                        "Ответ должен быть коротким, деловым, продающим. "
                        "В конце желательно задавать вопрос, который продолжает диалог. "
                        "Не используй Markdown-разметку в ответе клиенту."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"ФРАГМЕНТЫ БАЗЫ ЗНАНИЙ:\n{self._format_chunks(chunks)}\n\n"
                        f"ПОСЛЕДНИЕ СООБЩЕНИЯ:\n{self._format_memory_for_prompt(memory)}\n\n"
                        f"ВОПРОС КЛИЕНТА:\n{question}"
                    ),
                },
            ],
        )

        answer = strip_markdown((response.choices[0].message.content or "").strip())
        return answer or self.settings.ai_fallback_answer, True, True

    @staticmethod
    def _format_chunks(chunks: list[RagChunk]) -> str:
        parts: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            parts.append(
                f"[{index}] {chunk.source} | {chunk.title} | score={chunk.score}\n{chunk.clean_content}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _format_memory_for_prompt(memory: list[dict[str, str]]) -> str:
        if not memory:
            return "Нет предыдущих сообщений."
        return "\n".join(f"{item['role']}: {item['text']}" for item in memory[-10:])
