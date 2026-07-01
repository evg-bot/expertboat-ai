from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.ai import ExpertBoatAI
from app.config import Settings
from app.database import Database
from app.knowledge import KnowledgeBase

logger = logging.getLogger(__name__)


class ExpertBoatTelegramBot:
    def __init__(self, settings: Settings, database: Database, knowledge_base: KnowledgeBase) -> None:
        self.settings = settings
        self.database = database
        self.knowledge_base = knowledge_base
        self.ai = ExpertBoatAI(settings, knowledge_base)
        self.application = Application.builder().token(settings.telegram_bot_token).build()
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("reload", self.reload))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await update.message.reply_text(
            "Здравствуйте! Это бот Expert Boat. Задайте вопрос о морской электронике, покупке, доставке или гарантии."
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        mode = f"LLM ({self.settings.provider}, {self.settings.active_llm_model})" if self.settings.has_llm else "keyword matcher"
        avito = "настроен" if self.settings.has_avito else "не настроен, отключён из обязательного запуска"
        await update.message.reply_text(
            "ExpertBoat AI работает.\n"
            f"Режим ответов: {mode}.\n"
            f"Avito API: {avito}.\n"
            f"Модель: {self.settings.openai_model}."
        )

    async def reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        self.knowledge_base.reload()
        await update.message.reply_text("База знаний перезагружена.")

    async def message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_chat is None:
            return

        chat_id = str(update.effective_chat.id)
        question = update.message.text.strip()
        if not question:
            return

        await asyncio.to_thread(
            self.database.save_message,
            channel="telegram",
            chat_id=chat_id,
            direction="incoming",
            text=question,
        )
        history = await asyncio.to_thread(
            self.database.get_history,
            channel="telegram",
            chat_id=chat_id,
        )

        try:
            answer = await self.ai.answer(question, history)
        except Exception:
            logger.exception("Failed to generate Telegram answer")
            answer = self.settings.ai_fallback_answer

        await asyncio.to_thread(
            self.database.save_message,
            channel="telegram",
            chat_id=chat_id,
            direction="outgoing",
            text=answer,
        )
        await update.message.reply_text(answer)

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
