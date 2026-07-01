from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os


BASE_DIR = Path(__file__).resolve().parent.parent
PLACEHOLDER_PREFIXES = ("your-", "sk-your-")
FALLBACK_ANSWER = "Точный ответ передам специалисту Expert Boat."


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str

    database_path: Path
    knowledge_dir: Path

    llm_provider: str
    llm_model: str
    deepseek_api_key: str
    deepseek_base_url: str

    openai_api_key: str
    openai_model: str

    avito_client_id: str
    avito_client_secret: str
    avito_user_id: str
    avito_api_base_url: str
    avito_poll_interval_seconds: int

    telegram_bot_token: str
    telegram_manager_chat_id: str

    ai_fallback_answer: str = FALLBACK_ANSWER

    @property
    def provider(self) -> str:
        return self.llm_provider.strip().casefold()

    @property
    def active_llm_model(self) -> str:
        if self.provider == "openai":
            return self.openai_model
        return self.llm_model

    @property
    def active_llm_api_key(self) -> str:
        if self.provider == "openai":
            return self.openai_api_key
        if self.provider == "deepseek":
            return self.deepseek_api_key
        return ""

    @property
    def has_llm(self) -> bool:
        return self.provider in {"deepseek", "openai"} and _is_real_value(self.active_llm_api_key)

    @property
    def has_openai(self) -> bool:
        return self.provider == "openai" and _is_real_value(self.openai_api_key)

    @property
    def has_deepseek(self) -> bool:
        return self.provider == "deepseek" and _is_real_value(self.deepseek_api_key)

    @property
    def has_avito(self) -> bool:
        return all(
            _is_real_value(value)
            for value in (self.avito_client_id, self.avito_client_secret, self.avito_user_id)
        )


def _is_real_value(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    return not normalized.startswith(PLACEHOLDER_PREFIXES)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


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

    llm_provider = _env("LLM_PROVIDER", "deepseek").strip().casefold()
    openai_model = _env("OPENAI_MODEL", "gpt-4.1-mini")
    llm_model = _env("LLM_MODEL") or (openai_model if llm_provider == "openai" else "deepseek-chat")

    return Settings(
        app_env=_env("APP_ENV", "production"),
        log_level=_env("LOG_LEVEL", "INFO"),
        database_path=BASE_DIR / _env("DATABASE_PATH", "data/expertboat.db"),
        knowledge_dir=BASE_DIR / _env("KNOWLEDGE_DIR", "knowledge"),
        llm_provider=llm_provider,
        llm_model=llm_model,
        deepseek_api_key=_env("DEEPSEEK_API_KEY"),
        deepseek_base_url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_model=openai_model,
        avito_client_id=_env("AVITO_CLIENT_ID"),
        avito_client_secret=_env("AVITO_CLIENT_SECRET"),
        avito_user_id=_env("AVITO_USER_ID"),
        avito_api_base_url=_env("AVITO_API_BASE_URL", "https://api.avito.ru"),
        avito_poll_interval_seconds=_int_env("AVITO_POLL_INTERVAL_SECONDS", 5),
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_manager_chat_id=_env("TELEGRAM_MANAGER_CHAT_ID"),
    )
