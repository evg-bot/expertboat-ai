from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import Settings
from app.database import Database
from app.models import AvitoMessage

if TYPE_CHECKING:
    from app.avito import AvitoClient

logger = logging.getLogger(__name__)

REPLY_PREFIX = "reply"
IGNORE_PREFIX = "ignore"


class ManagerTelegramBot:
    def __init__(self, settings: Settings, database: Database, avito: AvitoClient) -> None:
        self.settings = settings
        self.database = database
        self.avito = avito
        self.pending_replies: dict[int, str] = {}
        self.notification_actions: dict[str, str] = {}
        self.application = Application.builder().token(settings.telegram_bot_token).build()
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help))
        self.application.add_handler(CallbackQueryHandler(self.button))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await update.message.reply_text(
            "ExpertBoat AI запущен. Новые сообщения Авито будут приходить сюда."
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await update.message.reply_text(
            "Нажмите «Ответить» под сообщением Авито, затем отправьте текст ответа одним сообщением."
        )

    async def message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_chat is None:
            return

        telegram_chat_id = update.effective_chat.id
        text = update.message.text.strip()
        if str(telegram_chat_id) != self.settings.telegram_manager_chat_id:
            await update.message.reply_text("Этот бот принимает ответы только от менеджера Expert Boat.")
            return

        avito_chat_id = self.pending_replies.pop(telegram_chat_id, None)
        if avito_chat_id is None:
            await asyncio.to_thread(
                self.database.save_message,
                channel="telegram",
                chat_id=str(telegram_chat_id),
                direction="incoming",
                text=text,
            )
            await update.message.reply_text("Сообщение сохранено. Для ответа клиенту нажмите кнопку под уведомлением Авито.")
            return

        try:
            await self.avito.send_message(avito_chat_id, text)
        except Exception as exc:
            logger.exception("Failed to send manager reply to Avito chat_id=%s", avito_chat_id)
            self.pending_replies[telegram_chat_id] = avito_chat_id
            await update.message.reply_text(
                "Ошибка отправки ответа в Авито. Попробуйте отправить текст ещё раз.\n\n"
                f"Чат: {avito_chat_id}\n"
                f"Ошибка: {exc}"
            )
            return

        await asyncio.to_thread(
            self.database.save_message,
            channel="avito",
            chat_id=avito_chat_id,
            direction="outgoing",
            text=text,
        )
        await update.message.reply_text("Ответ отправлен в Авито и сохранён в истории.")

    async def button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return

        await query.answer()
        if query.message is None:
            return

        if str(query.message.chat_id) != self.settings.telegram_manager_chat_id:
            await query.edit_message_reply_markup(reply_markup=None)
            return

        data = query.data or ""
        action, _, token = data.partition(":")
        avito_chat_id = self.notification_actions.get(token)
        if avito_chat_id is None:
            await query.edit_message_text("Действие устарело. Новое уведомление придёт при следующем сообщении клиента.")
            return

        if action == REPLY_PREFIX:
            self.pending_replies[query.message.chat_id] = avito_chat_id
            await query.message.reply_text("Введите текст ответа")
            await query.edit_message_reply_markup(reply_markup=None)
            return

        if action == IGNORE_PREFIX:
            self.notification_actions.pop(token, None)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"Чат {avito_chat_id} проигнорирован.")
            return

    async def notify_new_avito_message(self, message: AvitoMessage) -> None:
        token = uuid.uuid4().hex[:16]
        self.notification_actions[token] = message.chat_id
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Ответить", callback_data=f"{REPLY_PREFIX}:{token}"),
                    InlineKeyboardButton("❌ Игнорировать", callback_data=f"{IGNORE_PREFIX}:{token}"),
                ]
            ]
        )
        text = (
            "🔔 Новое сообщение\n\n"
            "Покупатель:\n"
            f"{message.author_name}\n\n"
            "Чат:\n"
            f"{message.chat_id}\n\n"
            "Текст:\n"
            f"{message.text}\n\n"
            "===================="
        )
        await self.notify_manager(text, reply_markup=keyboard)

    async def notify_manager(self, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            await self.application.bot.send_message(
                chat_id=self.settings.telegram_manager_chat_id,
                text=text,
                reply_markup=reply_markup,
            )
        except Exception:
            logger.exception("Failed to notify Telegram manager")

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
