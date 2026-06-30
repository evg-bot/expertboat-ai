from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from app.avito import AvitoClient
from app.config import load_settings
from app.database import Database
from app.telegram_bot import ManagerTelegramBot


logger = logging.getLogger(__name__)


class ExpertBoatApp:
    def __init__(self) -> None:
        self.settings = load_settings()
        logging.basicConfig(
            level=self.settings.log_level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )

        self.database = Database(self.settings.database_path)
        self.avito = AvitoClient(self.settings, self.database)
        self.telegram = ManagerTelegramBot(self.settings, self.database, self.avito)
        self.stop_event = asyncio.Event()

    async def run(self) -> None:
        await asyncio.to_thread(self.database.init)

        loop = asyncio.get_running_loop()
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal.SIGTERM, self.stop_event.set)
            loop.add_signal_handler(signal.SIGINT, self.stop_event.set)

        if not self.settings.is_configured:
            logger.warning(
                "ExpertBoat AI started without production credentials. "
                "Create .env from .env.example and fill real Avito, Telegram and OpenAI values."
            )
            await self.stop_event.wait()
            await self.avito.close()
            return

        await self.telegram.start_polling()
        worker = asyncio.create_task(self.avito_worker())
        logger.info("ExpertBoat AI started")

        try:
            await self.stop_event.wait()
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            await self.telegram.stop()
            await self.avito.close()

    async def avito_worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self.process_avito_messages()
            except Exception:
                logger.exception("Avito message processing failed")
            await asyncio.sleep(self.settings.avito_poll_interval_seconds)

    async def process_avito_messages(self) -> None:
        for message in await self.avito.get_new_messages():
            await asyncio.to_thread(
                self.database.save_message,
                channel="avito",
                chat_id=message.chat_id,
                direction="incoming",
                text=message.text,
                external_id=message.id,
                created_at=message.created_at,
            )
            logger.info(
                "Saved incoming Avito message: chat_id=%s author_id=%s message_id=%s",
                message.chat_id,
                message.author_id,
                message.id,
            )
            await self.telegram.notify_new_avito_message(message)


async def main() -> None:
    app = ExpertBoatApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
