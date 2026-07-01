from __future__ import annotations

import asyncio
import logging
from enum import Enum

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.ai import ExpertBoatAI
from app.config import Settings
from app.database import Database
from app.knowledge import KnowledgeBase, KnowledgeFragment, NormalizedQuery
from app.rag import RAG_MIN_SCORE, RagEngine, RagSearchResult

logger = logging.getLogger(__name__)


class LearnStep(str, Enum):
    QUESTION = "question"
    ANSWER = "answer"


class ExpertBoatTelegramBot:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        knowledge_base: KnowledgeBase,
        rag: RagEngine,
    ) -> None:
        self.settings = settings
        self.database = database
        self.knowledge_base = knowledge_base
        self.rag = rag
        self.ai = ExpertBoatAI(settings, knowledge_base)
        self.learn_sessions: dict[int, dict[str, str]] = {}
        self.application = Application.builder().token(settings.telegram_bot_token).build()
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("reload", self.reload))
        self.application.add_handler(CommandHandler("stats", self.stats))
        self.application.add_handler(CommandHandler("learn", self.learn))
        self.application.add_handler(CommandHandler("search", self.search))
        self.application.add_handler(CommandHandler("aliases", self.aliases))
        self.application.add_handler(CommandHandler("reindex", self.reindex))
        self.application.add_handler(CommandHandler("ragstatus", self.ragstatus))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await update.message.reply_text(
            "Здравствуйте! Это бот Expert Boat. Задайте вопрос о морской электронике, покупке, доставке, гарантии или русификации."
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_admin(update):
            return
        mode = f"{self.settings.provider} / {self.settings.active_llm_model}" if self.settings.has_llm else "local RAG"
        sqlite = "доступна" if await asyncio.to_thread(self.database.is_available) else "недоступна"
        chunks_count = await asyncio.to_thread(self.rag.chunks_count)
        await update.message.reply_text(
            "ExpertBoat AI работает.\n"
            f"LLM provider: {mode}.\n"
            f"Knowledge docs count: {self.knowledge_base.document_count}.\n"
            f"Knowledge chunks count: {chunks_count}.\n"
            f"Aliases groups count: {self.knowledge_base.aliases_group_count}.\n"
            f"DB status: {sqlite}."
        )

    async def reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_admin(update):
            return
        self.knowledge_base.reload()
        chunks_count = await asyncio.to_thread(self.rag.reindex)
        await update.message.reply_text(
            "База знаний перечитана и RAG-индекс пересобран.\n"
            f"Документов: {self.knowledge_base.document_count}.\n"
            f"Chunks: {chunks_count}.\n"
            f"Алиасов: {self.knowledge_base.aliases_group_count}."
        )

    async def reindex(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_admin(update):
            return
        self.knowledge_base.reload()
        chunks_count = await asyncio.to_thread(self.rag.reindex)
        await update.message.reply_text(f"RAG-индекс пересобран. Chunks: {chunks_count}.")

    async def ragstatus(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_admin(update):
            return
        chunks_count = await asyncio.to_thread(self.rag.chunks_count)
        last_indexed_at = await asyncio.to_thread(self.rag.last_indexed_at)
        await update.message.reply_text(
            "RAG status:\n"
            f"Документов: {self.knowledge_base.document_count}\n"
            f"Chunks: {chunks_count}\n"
            f"Последняя индексация: {last_indexed_at or 'нет данных'}"
        )

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_admin(update):
            return
        stats = await asyncio.to_thread(self.database.get_stats)
        await update.message.reply_text(
            "Статистика ExpertBoat AI:\n"
            f"Сообщений: {stats.get('messages', 0)}\n"
            f"Найденных ответов: {stats.get('found_answers', 0)}\n"
            f"Fallback-ответов: {stats.get('fallback_answers', 0)}\n"
            f"LLM-ответов: {stats.get('llm_answers', 0)}"
        )

    async def learn(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_chat is None or not self._is_admin(update):
            return
        self.learn_sessions[update.effective_chat.id] = {"step": LearnStep.QUESTION.value}
        await update.message.reply_text("Введите вопрос.")

    async def aliases(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_admin(update):
            return
        groups = self.knowledge_base.first_alias_groups(20)
        text = "Групп алиасов: " + str(self.knowledge_base.aliases_group_count)
        if groups:
            text += "\nПервые 20 групп:\n" + "\n".join(f"- {group}" for group in groups)
        await update.message.reply_text(text)

    async def search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_admin(update):
            return
        query = " ".join(context.args).strip()
        if not query:
            await update.message.reply_text("Использование: /search <текст>")
            return
        result = await asyncio.to_thread(self.rag.search, query, limit=5)
        await update.message.reply_text(self._format_rag_search_debug(result))

    async def message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_chat is None:
            return

        telegram_chat_id = update.effective_chat.id
        chat_id = str(telegram_chat_id)
        text = update.message.text.strip()
        if not text:
            return

        if telegram_chat_id in self.learn_sessions:
            await self._handle_learning(update, telegram_chat_id, text)
            return

        await asyncio.to_thread(self.database.increment_stat, "messages")
        await asyncio.to_thread(self.database.save_memory, chat_id=chat_id, role="user", text=text)
        await asyncio.to_thread(
            self.database.save_message,
            channel="telegram",
            chat_id=chat_id,
            direction="incoming",
            text=text,
        )
        memory = await asyncio.to_thread(self.database.get_recent_memory, chat_id=chat_id, limit=10)
        search_context = "\n".join(item["text"] for item in memory[-6:])

        try:
            result = await asyncio.to_thread(self.rag.search, text, context=search_context, limit=5)
            if result.has_answer:
                answer, found, used_llm = await self.ai.answer(text, memory, result.chunks)
            else:
                answer, found, used_llm = self.settings.ai_fallback_answer, False, False
        except Exception:
            logger.exception("Failed to generate Telegram answer")
            answer, found, used_llm = self.settings.ai_fallback_answer, False, False

        if answer == self.settings.ai_fallback_answer:
            await asyncio.to_thread(self.database.increment_stat, "fallback_answers")
        elif found:
            await asyncio.to_thread(self.database.increment_stat, "found_answers")
        if used_llm:
            await asyncio.to_thread(self.database.increment_stat, "llm_answers")

        await asyncio.to_thread(self.database.save_memory, chat_id=chat_id, role="assistant", text=answer)
        await asyncio.to_thread(
            self.database.save_message,
            channel="telegram",
            chat_id=chat_id,
            direction="outgoing",
            text=answer,
        )
        await update.message.reply_text(answer)

    async def _handle_learning(self, update: Update, telegram_chat_id: int, text: str) -> None:
        if update.message is None:
            return
        session = self.learn_sessions[telegram_chat_id]
        step = session.get("step")

        if step == LearnStep.QUESTION.value:
            session["question"] = text
            session["step"] = LearnStep.ANSWER.value
            await update.message.reply_text("Введите правильный ответ.")
            return

        if step == LearnStep.ANSWER.value:
            question = session.get("question", "").strip()
            answer = text.strip()
            if question and answer:
                await asyncio.to_thread(self.knowledge_base.append_learned, question, answer)
                await asyncio.to_thread(self.rag.reindex)
                await update.message.reply_text("Готово, добавил в базу знаний.")
            else:
                await update.message.reply_text("Не удалось сохранить: вопрос или ответ пустой.")
            self.learn_sessions.pop(telegram_chat_id, None)

    def _is_admin(self, update: Update) -> bool:
        if not self.settings.telegram_manager_chat_id:
            return True
        if update.effective_chat is None:
            return False
        return str(update.effective_chat.id) == self.settings.telegram_manager_chat_id

    @staticmethod
    def _format_rag_search_debug(result: RagSearchResult) -> str:
        alias_lines = [
            f"- {match.canonical}: {match.alias} ({match.kind}, {match.score})"
            for match in result.query.matches[:20]
        ]
        chunk_lines: list[str] = []
        for index, chunk in enumerate(result.chunks[:5], start=1):
            snippet = chunk.clean_content[:700]
            chunk_lines.append(
                f"{index}. score: {chunk.score}\nsource: {chunk.source}\ntitle: {chunk.title}\nmethod: {chunk.method}\n{snippet}"
            )
        return (
            f"Исходный запрос:\n{result.query.original}\n\n"
            f"Нормализованный запрос:\n{result.query.expanded}\n\n"
            f"Найденные алиасы:\n{chr(10).join(alias_lines) if alias_lines else 'нет'}\n\n"
            f"Метод: {result.method}\n"
            f"Порог ответа: {RAG_MIN_SCORE}\n"
            f"Top score: {result.top_score}\n\n"
            f"Top 5 chunks:\n{chr(10).join(chunk_lines) if chunk_lines else 'ничего не найдено'}"
        )

    @staticmethod
    def _format_search_debug(query: NormalizedQuery, fragments: list[KnowledgeFragment]) -> str:
        alias_lines = [
            f"- {match.canonical}: {match.alias} ({match.kind}, {match.score})"
            for match in query.matches[:20]
        ]
        fragment_lines: list[str] = []
        for index, fragment in enumerate(fragments[:5], start=1):
            snippet = fragment.clean_text[:700]
            fragment_lines.append(
                f"{index}. {fragment.source} | {fragment.title}\nscore: {fragment.score}\n{snippet}"
            )
        return (
            f"Исходный запрос:\n{query.original}\n\n"
            f"Нормализованный запрос:\n{query.expanded}\n\n"
            f"Найденные алиасы:\n{chr(10).join(alias_lines) if alias_lines else 'нет'}\n\n"
            f"Top 5 документов:\n{chr(10).join(fragment_lines) if fragment_lines else 'ничего не найдено'}"
        )

    async def start_polling(self) -> None:
        await self.application.initialize()
        await self.application.start()
        if self.application.updater is None:
            raise RuntimeError("Telegram updater is not available")
        await self.application.updater.start_polling()

    async def stop(self) -> None:
        if self.application.updater:
            await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()
