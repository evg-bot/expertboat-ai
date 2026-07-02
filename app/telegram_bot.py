from __future__ import annotations

import asyncio
import logging
from enum import Enum

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.ai import GREETING_RESPONSE, ExpertBoatAI
from app.config import Settings
from app.database import Database
from app.knowledge import KnowledgeBase, strip_markdown
from app.knowledge_import_status import read_import_status
from app.rag import RAG_MIN_SCORE, RagEngine, RagSearchResult, classify_intent

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
        self.application.add_handler(CommandHandler("importstatus", self.importstatus))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message))
        self.application.add_error_handler(self.error_handler)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await update.message.reply_text(
            "Здравствуйте! Это бот Expert Boat. Задайте вопрос о морской электронике, покупке, доставке, гарантии или русификации."
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not await self._ensure_admin(update):
            return
        mode = (
            f"{self.settings.provider} / {self.settings.active_llm_model} / enabled"
            if self.settings.has_llm
            else f"{self.settings.provider} / {self.settings.active_llm_model} / disabled, local RAG fallback"
        )
        sqlite = "доступна" if await asyncio.to_thread(self.database.is_available) else "недоступна"
        chunks_count = await asyncio.to_thread(self.rag.chunks_count)
        rag_state = "active" if await asyncio.to_thread(self.rag.is_ready) else "inactive"
        await update.message.reply_text(
            "ExpertBoat AI работает.\n"
            f"LLM provider: {mode}.\n"
            f"Search: RAG {rag_state}.\n"
            f"Knowledge docs count: {self.knowledge_base.document_count}.\n"
            f"Knowledge chunks count: {chunks_count}.\n"
            f"Aliases groups count: {self.knowledge_base.aliases_group_count}.\n"
            f"DB status: {sqlite}.\n"
            f"RAG error: {self.rag.last_error or 'none'}."
        )

    async def reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not await self._ensure_admin(update):
            return
        self.knowledge_base.reload()
        try:
            chunks_count = await asyncio.to_thread(self.rag.reindex)
        except Exception:
            logger.exception("Failed to reload knowledge and rebuild RAG index")
            await update.message.reply_text("Не удалось пересобрать RAG-индекс. Ошибка записана в лог.")
            return
        await update.message.reply_text(
            "База знаний перечитана и RAG-индекс пересобран.\n"
            f"Документов: {self.knowledge_base.document_count}.\n"
            f"Chunks: {chunks_count}.\n"
            f"Алиасов: {self.knowledge_base.aliases_group_count}."
        )

    async def reindex(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not await self._ensure_admin(update):
            return
        self.knowledge_base.reload()
        try:
            chunks_count = await asyncio.to_thread(self.rag.reindex)
        except Exception:
            logger.exception("Failed to rebuild RAG index")
            await update.message.reply_text("Не удалось пересобрать RAG-индекс. Ошибка записана в лог.")
            return
        await update.message.reply_text(f"RAG-индекс пересобран. Chunks: {chunks_count}.")

    async def ragstatus(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not await self._ensure_admin(update):
            return
        try:
            chunks_count = await asyncio.to_thread(self.rag.chunks_count)
            last_indexed_at = await asyncio.to_thread(self.rag.last_indexed_at)
            rag_state = "active" if await asyncio.to_thread(self.rag.is_ready) else "inactive"
            await update.message.reply_text(
                "RAG status:\n"
                f"Состояние: {rag_state}\n"
                f"Документов: {self.knowledge_base.document_count}\n"
                f"Chunks: {chunks_count}\n"
                f"Последняя индексация: {last_indexed_at or 'нет данных'}\n"
                f"Ошибка: {self.rag.last_error or 'нет'}"
            )
        except Exception:
            logger.exception("Failed to build RAG status")
            await update.message.reply_text("Не удалось получить RAG status. Ошибка записана в лог.")

    async def importstatus(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not await self._ensure_admin(update):
            return
        try:
            status = await asyncio.to_thread(read_import_status)
            await update.message.reply_text(
                "Knowledge import status:\n"
                f"Обработано документов: {status.processed_documents}\n"
                f"Новых: {status.new_documents}\n"
                f"Пропущено: {status.skipped_documents}\n"
                f"Ошибок: {status.errors}"
            )
        except Exception:
            logger.exception("Failed to read import status")
            await update.message.reply_text("Не удалось получить import status. Ошибка записана в лог.")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not await self._ensure_admin(update):
            return
        try:
            stats = await asyncio.to_thread(self.database.get_stats)
            await update.message.reply_text(
                "Статистика ExpertBoat AI:\n"
                f"Сообщений: {stats.get('messages', 0)}\n"
                f"Найденных ответов: {stats.get('found_answers', 0)}\n"
                f"Fallback-ответов: {stats.get('fallback_answers', 0)}\n"
                f"LLM-ответов: {stats.get('llm_answers', 0)}"
            )
        except Exception:
            logger.exception("Failed to read bot stats")
            await update.message.reply_text("Не удалось получить статистику. Ошибка записана в лог.")

    async def learn(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_chat is None or not await self._ensure_admin(update):
            return
        self.learn_sessions[update.effective_chat.id] = {"step": LearnStep.QUESTION.value}
        await update.message.reply_text("Введите вопрос.")

    async def aliases(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not await self._ensure_admin(update):
            return
        groups = self.knowledge_base.first_alias_groups(20)
        text = "Групп алиасов: " + str(self.knowledge_base.aliases_group_count)
        if groups:
            text += "\nПервые 20 групп:\n" + "\n".join(f"- {group}" for group in groups)
        await update.message.reply_text(text)

    async def search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not await self._ensure_admin(update):
            return
        query = " ".join(context.args).strip()
        if not query:
            await update.message.reply_text("Использование: /search <текст>")
            return
        history: list[dict[str, str]] = []
        if update.effective_chat is not None:
            history = await asyncio.to_thread(
                self.database.get_recent_memory,
                chat_id=str(update.effective_chat.id),
                limit=10,
            )
        result = await asyncio.to_thread(self.rag.search, query, history=history, limit=5)
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

        try:
            current_query = self.knowledge_base.normalize_query(text)
            if classify_intent(current_query) == "greeting":
                answer, found, used_llm = GREETING_RESPONSE, True, False
            elif not await asyncio.to_thread(self.rag.is_ready):
                logger.error("RAG is not ready; refusing to answer through keyword matcher")
                answer, found, used_llm = self.settings.ai_fallback_answer, False, False
            else:
                result = await asyncio.to_thread(self.rag.search, text, history=memory, limit=5)
                if result.has_answer:
                    answer, found, used_llm = await self.ai.answer(text, memory, result.chunks)
                else:
                    answer, found, used_llm = self.settings.ai_fallback_answer, False, False
        except Exception:
            logger.exception("Failed to generate Telegram answer")
            answer, found, used_llm = self.settings.ai_fallback_answer, False, False

        answer = strip_markdown(answer) or self.settings.ai_fallback_answer
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

    async def _ensure_admin(self, update: Update) -> bool:
        if self._is_admin(update):
            return True
        if update.message is not None:
            await update.message.reply_text("Команда доступна администратору Expert Boat.")
        return False

    @staticmethod
    def _format_rag_search_debug(result: RagSearchResult) -> str:
        query_context = result.context
        alias_lines = [f"- {alias}" for alias in query_context.aliases_found]
        chunk_lines: list[str] = []
        for index, chunk in enumerate(result.chunks[:5], start=1):
            snippet = chunk.clean_content[:700]
            chunk_lines.append(
                f"{index}. score: {chunk.score}\nsource: {chunk.source}\ntitle: {chunk.title}\nmethod: {chunk.method}\n{snippet}"
            )
        return (
            "QueryContext:\n"
            f"raw_query: {query_context.raw_query}\n"
            f"normalized_query: {query_context.normalized_query}\n"
            f"expanded_query: {query_context.expanded_query}\n"
            f"intent: {query_context.intent}\n"
            f"domain_relevance: {query_context.domain_relevance}\n"
            f"used_history: {query_context.used_history}\n"
            f"history_reason: {query_context.history_reason or 'нет'}\n"
            f"top_score: {query_context.top_score}\n"
            f"fallback_reason: {query_context.fallback_reason or 'нет'}\n\n"
            f"Найденные алиасы:\n{chr(10).join(alias_lines) if alias_lines else 'нет'}\n\n"
            f"Метод: {result.method}\n"
            f"Порог ответа: {RAG_MIN_SCORE}\n"
            f"Top score: {result.top_score}\n\n"
            f"Top 5 chunks:\n{chr(10).join(chunk_lines) if chunk_lines else 'ничего не найдено'}"
        )

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Telegram handler failed", exc_info=context.error)

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
