from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from app.config import load_settings
from app.database import Database
from app.knowledge import KnowledgeBase
from app.telegram_bot import ExpertBoatTelegramBot


logger = logging.getLogger(__name__)


class ExpertBoatApp:
    def __init__(self) -> None:
        self.settings = load_settings()
        logging.basicConfig(
            level=self.settings.log_level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        self.database = Database(self.settings.database_path)
        self.knowledge_base = KnowledgeBase(self.settings.knowledge_dir)
        self.telegram: ExpertBoatTelegramBot | None = None
        self.stop_event = asyncio.Event()

    async def run(self) -> None:
        await asyncio.to_thread(self.database.init)

        loop = asyncio.get_running_loop()
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal.SIGTERM, self.stop_event.set)
            loop.add_signal_handler(signal.SIGINT, self.stop_event.set)

        if not self.settings.has_telegram:
            logger.warning(
                "ExpertBoat AI started without TELEGRAM_BOT_TOKEN. "
                "Set TELEGRAM_BOT_TOKEN in .env and restart the container."
            )
            await self.stop_event.wait()
            return

        self.telegram = ExpertBoatTelegramBot(self.settings, self.database, self.knowledge_base)
        await self.telegram.start_polling()

        logger.info("ExpertBoat Telegram knowledge bot started")
        try:
            await self.stop_event.wait()
        finally:
            if self.telegram is not None:
                await self.telegram.stop()


async def main() -> None:
    app = ExpertBoatApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())