from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os


BASE_DIR = Path(__file__).resolve().parent.parent
PLACEHOLDER_PREFIXES = ("your-", "sk-your-")


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str

    database_path: Path
    knowledge_dir: Path

    openai_api_key: str
    openai_model: str

    avito_client_id: str
    avito_client_secret: str
    avito_user_id: str
    avito_api_base_url: str
    avito_poll_interval_seconds: int

    telegram_bot_token: str
    telegram_manager_chat_id: str

    ai_fallback_answer: str = "Ваш вопрос передан специалисту Expert Boat."

    @property
    def is_configured(self) -> bool:
        required_values = (
            self.openai_api_key,
            self.avito_client_id,
            self.avito_client_secret,
            self.avito_user_id,
            self.telegram_bot_token,
            self.telegram_manager_chat_id,
        )
        return all(_is_real_value(value) for value in required_values)


def _is_real_value(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    return not normalized.startswith(PLACEHOLDER_PREFIXES)


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer") from exc


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")

    return Settings(
        app_env=os.getenv("APP_ENV", "production"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        database_path=BASE_DIR / os.getenv("DATABASE_PATH", "data/expertboat.db"),
        knowledge_dir=BASE_DIR / os.getenv("KNOWLEDGE_DIR", "knowledge"),
        openai_api_key=_required("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        avito_client_id=_required("AVITO_CLIENT_ID"),
        avito_client_secret=_required("AVITO_CLIENT_SECRET"),
        avito_user_id=_required("AVITO_USER_ID"),
        avito_api_base_url=os.getenv("AVITO_API_BASE_URL", "https://api.avito.ru"),
        avito_poll_interval_seconds=_int_env("AVITO_POLL_INTERVAL_SECONDS", 5),
        telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
        telegram_manager_chat_id=_required("TELEGRAM_MANAGER_CHAT_ID"),
    )
