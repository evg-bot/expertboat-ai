from __future__ import annotations

import asyncio
import logging
from enum import Enum

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.ai import ExpertBoatAI
from app.config import Settings
from app.database import Database
from app.knowledge import KnowledgeBase

logger = logging.getLogger(__name__)


class LearnStep(str, Enum):
    QUESTION = "question"
    ANSWER = "answer"


class ExpertBoatTelegramBot:
    def __init__(self, settings: Settings, database: Database, knowledge_base: KnowledgeBase) -> None:
        self.settings = settings
        self.database = database
        self.knowledge_base = knowledge_base
        self.ai = ExpertBoatAI(settings, knowledge_base)
        self.learn_sessions: dict[int, dict[str, str]] = {}
        self.application = Application.builder().token(settings.telegram_bot_token).build()
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("reload", self.reload))
        self.application.add_handler(CommandHandler("stats", self.stats))
        self.application.add_handler(CommandHandler("learn", self.learn))
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
        mode = f"LLM ({self.settings.provider}, {self.settings.active_llm_model})" if self.settings.has_llm else "keyword matcher"
        avito = "настроен" if self.settings.has_avito else "не настроен, отключён из обязательного запуска"
        sqlite = "доступна" if await asyncio.to_thread(self.database.is_available) else "недоступна"
        await update.message.reply_text(
            "ExpertBoat AI работает.\n"
            f"Режим ответов: {mode}.\n"
            f"Документов knowledge: {self.knowledge_base.document_count}.\n"
            f"SQLite: {sqlite}.\n"
            f"Avito API: {avito}."
        )

    async def reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_admin(update):
            return
        self.knowledge_base.reload()
        await update.message.reply_text(
            f"База знаний перезагружена. Документов: {self.knowledge_base.document_count}."
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
        await update.message.reply_text("Введите вопрос, которому нужно научить бота.")

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
            answer, found, used_llm = await self.ai.answer(text, memory)
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
            await update.message.reply_text("Теперь введите правильный ответ.")
            return

        if step == LearnStep.ANSWER.value:
            question = session.get("question", "").strip()
            answer = text.strip()
            if question and answer:
                await asyncio.to_thread(self.knowledge_base.append_learned, question, answer)
                await update.message.reply_text("Готово. Пара сохранена в knowledge/learned.md, база знаний перечитана.")
            else:
                await update.message.reply_text("Не удалось сохранить обучение: вопрос или ответ пустой.")
            self.learn_sessions.pop(telegram_chat_id, None)

    def _is_admin(self, update: Update) -> bool:
        if not self.settings.telegram_manager_chat_id:
            return True
        if update.effective_chat is None:
            return False
        return str(update.effective_chat.id) == self.settings.telegram_manager_chat_id

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