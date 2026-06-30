from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.config import Settings
from app.database import Database
from app.models import AvitoMessage

logger = logging.getLogger(__name__)

AVITO_TOKEN_URL = "/token"
AVITO_CHATS_URL = "/messenger/v2/accounts/{user_id}/chats"
AVITO_MESSAGES_URL = "/messenger/v3/accounts/{user_id}/chats/{chat_id}/messages/"
AVITO_SEND_MESSAGE_URL = "/messenger/v1/accounts/{user_id}/chats/{chat_id}/messages"

MAX_RETRIES = 4
TOKEN_REFRESH_SKEW_SECONDS = 120
DEFAULT_PAGE_LIMIT = 100
MAX_OFFSET = 1000
MAX_TEXT_MESSAGE_LENGTH = 1000
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class AvitoAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AvitoAuthError(AvitoAPIError):
    pass


class AvitoPermissionError(AvitoAPIError):
    pass


class AvitoRateLimitError(AvitoAPIError):
    pass


class AvitoTemporaryError(AvitoAPIError):
    pass


class AvitoClient:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self.http = httpx.AsyncClient(
            base_url=settings.avito_api_base_url,
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
            headers={"Accept": "application/json"},
        )
        self._token_lock = asyncio.Lock()

    async def close(self) -> None:
        await self.http.aclose()

    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        async with self._token_lock:
            if not force_refresh:
                cached = await asyncio.to_thread(self.database.get_avito_token)
                if cached and self._token_is_valid(cached["expires_at"]):
                    return str(cached["access_token"])

            logger.info("Requesting Avito OAuth access token")
            response = await self._send_with_retries(
                "POST",
                AVITO_TOKEN_URL,
                authorized=False,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.avito_client_id,
                    "client_secret": self.settings.avito_client_secret,
                },
            )
            payload = response.json()

            access_token = str(payload.get("access_token") or "")
            if not access_token:
                raise AvitoAuthError("Avito OAuth response does not contain access_token")

            expires_in = int(payload.get("expires_in", 3600))
            token_type = str(payload.get("token_type") or "Bearer")
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            await asyncio.to_thread(
                self.database.save_avito_token,
                access_token=access_token,
                token_type=token_type,
                expires_at=expires_at,
            )
            logger.info("Avito OAuth access token updated")
            return access_token

    async def get_chats(
        self,
        *,
        unread_only: bool = True,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> list[dict[str, Any]]:
        limit = self._validated_limit(limit)
        logger.info("Fetching Avito chats: unread_only=%s", unread_only)
        chats: list[dict[str, Any]] = []
        offset = 0

        while offset <= MAX_OFFSET:
            response = await self._request(
                "GET",
                AVITO_CHATS_URL.format(user_id=self.settings.avito_user_id),
                params={
                    "unread_only": str(unread_only).lower(),
                    "limit": limit,
                    "offset": offset,
                },
            )
            payload = response.json()
            page = payload.get("chats") or []
            if not isinstance(page, list):
                raise AvitoAPIError("Avito chats response has unexpected format")

            chats.extend(page)
            if len(page) < limit:
                break
            offset += limit

        logger.info("Fetched %s Avito chats", len(chats))
        return chats

    async def get_chat_messages(
        self,
        chat_id: str,
        *,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> list[AvitoMessage]:
        limit = self._validated_limit(limit)
        logger.info("Fetching Avito messages for chat_id=%s", chat_id)
        messages: list[AvitoMessage] = []
        offset = 0

        while offset <= MAX_OFFSET:
            response = await self._request(
                "GET",
                AVITO_MESSAGES_URL.format(
                    user_id=self.settings.avito_user_id,
                    chat_id=chat_id,
                ),
                params={"limit": limit, "offset": offset},
            )
            page = response.json()
            if not isinstance(page, list):
                raise AvitoAPIError("Avito messages response has unexpected format")

            for item in page:
                text = self._message_text(item)
                if text:
                    messages.append(self._parse_message(chat_id, item, text))

            if len(page) < limit:
                break
            offset += limit

        messages.sort(key=lambda message: message.created_at)
        logger.info("Fetched %s Avito text messages for chat_id=%s", len(messages), chat_id)
        return messages

    async def get_new_messages(self) -> list[AvitoMessage]:
        logger.info("Fetching new Avito messages")
        new_messages: list[AvitoMessage] = []

        for chat in await self.get_chats(unread_only=True):
            chat_id = str(chat.get("id") or "")
            if not chat_id:
                logger.warning("Skipping Avito chat without id: %s", chat)
                continue

            for message in await self.get_chat_messages(chat_id):
                if message.direction != "in":
                    continue
                if not await asyncio.to_thread(self.database.has_message, "avito", message.id):
                    new_messages.append(self._message_with_author_name(message, chat))

        new_messages.sort(key=lambda message: message.created_at)
        logger.info("Found %s new Avito messages", len(new_messages))
        return new_messages

    async def send_message(self, chat_id: str, text: str) -> None:
        text = text.strip()
        if not text:
            raise ValueError("Avito text message must not be empty")
        if len(text) > MAX_TEXT_MESSAGE_LENGTH:
            raise ValueError(f"Avito text message must be at most {MAX_TEXT_MESSAGE_LENGTH} characters")

        logger.info("Sending Avito message to chat_id=%s", chat_id)
        await self._request(
            "POST",
            AVITO_SEND_MESSAGE_URL.format(
                user_id=self.settings.avito_user_id,
                chat_id=chat_id,
            ),
            json={"message": {"text": text}, "type": "text"},
        )
        logger.info("Avito message sent to chat_id=%s", chat_id)

    @staticmethod
    def _validated_limit(limit: int) -> int:
        if not 1 <= limit <= DEFAULT_PAGE_LIMIT:
            raise ValueError(f"Avito limit must be between 1 and {DEFAULT_PAGE_LIMIT}")
        return limit

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        token = await self.get_access_token()
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {token}"

        response = await self._send_with_retries(
            method,
            url,
            headers=headers,
            authorized=True,
            **kwargs,
        )

        if response.status_code == 401:
            logger.warning("Avito returned 401; refreshing token and retrying request")
            token = await self.get_access_token(force_refresh=True)
            headers["Authorization"] = f"Bearer {token}"
            response = await self._send_with_retries(
                method,
                url,
                headers=headers,
                authorized=True,
                **kwargs,
            )

        self._raise_for_status(response)
        return response

    async def _send_with_retries(
        self,
        method: str,
        url: str,
        *,
        authorized: bool,
        **kwargs: Any,
    ) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self.http.request(method, url, **kwargs)
            except (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt == MAX_RETRIES:
                    logger.exception("Avito request failed after retries: %s %s", method, url)
                    raise AvitoTemporaryError(f"Temporary Avito request failure: {exc}") from exc
                delay = self._retry_delay(attempt, None)
                logger.warning(
                    "Temporary Avito transport error on attempt %s/%s for %s %s; retrying in %.2fs",
                    attempt,
                    MAX_RETRIES,
                    method,
                    url,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code == 401 and authorized:
                return response

            if response.status_code == 403:
                self._raise_for_status(response)

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt == MAX_RETRIES:
                    self._raise_for_status(response)
                delay = self._retry_delay(attempt, response)
                logger.warning(
                    "Avito returned %s on attempt %s/%s for %s %s; retrying in %.2fs",
                    response.status_code,
                    attempt,
                    MAX_RETRIES,
                    method,
                    url,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            self._raise_for_status(response)
            return response

        raise AvitoTemporaryError(f"Temporary Avito request failure: {last_error}")

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return

        message = self._error_message(response)
        logger.error("Avito API error %s: %s", response.status_code, message)

        if response.status_code == 401:
            raise AvitoAuthError(message, status_code=response.status_code)
        if response.status_code == 403:
            raise AvitoPermissionError(message, status_code=response.status_code)
        if response.status_code == 429:
            raise AvitoRateLimitError(message, status_code=response.status_code)
        if response.status_code in RETRYABLE_STATUS_CODES:
            raise AvitoTemporaryError(message, status_code=response.status_code)

        raise AvitoAPIError(message, status_code=response.status_code)

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            for key in ("error_description", "message", "error"):
                value = payload.get(key)
                if value:
                    return str(value)
            return str(payload)

        text = response.text.strip()
        if text:
            return text
        return f"Avito API returned HTTP {response.status_code}"

    @staticmethod
    def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
        if response is not None and response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            parsed = AvitoClient._parse_retry_after(retry_after)
            if parsed is not None:
                return parsed

        base = min(2 ** (attempt - 1), 16)
        jitter = random.uniform(0.1, 0.5)
        return base + jitter

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if not value:
            return None

        try:
            return max(0.0, float(value))
        except ValueError:
            pass

        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())

    @staticmethod
    def _token_is_valid(expires_at_value: str) -> bool:
        try:
            expires_at = datetime.fromisoformat(expires_at_value)
        except ValueError:
            return False

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        refresh_at = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS)
        return expires_at > refresh_at

    def _parse_message(self, chat_id: str, payload: dict[str, Any], text: str) -> AvitoMessage:
        message_id = payload.get("id")
        if message_id is None:
            raise AvitoAPIError("Avito message response does not contain id")

        return AvitoMessage(
            id=str(message_id),
            chat_id=chat_id,
            author_id=self._author_id(payload),
            text=text,
            created_at=self._created_at(payload),
            direction=str(payload.get("direction") or ""),
        )

    def _message_with_author_name(self, message: AvitoMessage, chat: dict[str, Any]) -> AvitoMessage:
        return AvitoMessage(
            id=message.id,
            chat_id=message.chat_id,
            author_id=message.author_id,
            text=message.text,
            created_at=message.created_at,
            direction=message.direction,
            author_name=self._author_name(chat, message.author_id),
        )

    @staticmethod
    def _author_name(chat: dict[str, Any], author_id: str) -> str:
        users = chat.get("users")
        if isinstance(users, list):
            for user in users:
                if not isinstance(user, dict):
                    continue
                user_id = user.get("id")
                if user_id is not None and str(user_id) == author_id:
                    name = user.get("name")
                    if name:
                        return str(name)

        return "Покупатель"

    @staticmethod
    def _author_id(payload: dict[str, Any]) -> str:
        author_id = payload.get("author_id")
        if author_id is not None:
            return str(author_id)

        author = payload.get("author")
        if isinstance(author, dict) and author.get("id") is not None:
            return str(author["id"])

        return ""

    @staticmethod
    def _created_at(payload: dict[str, Any]) -> datetime:
        created = payload.get("created") or payload.get("created_at")
        if isinstance(created, int | float):
            return datetime.fromtimestamp(created, tz=timezone.utc)
        if isinstance(created, str):
            try:
                parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                logger.warning("Could not parse Avito message created_at=%s", created)
            else:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)

        return datetime.now(timezone.utc)

    @staticmethod
    def _message_text(payload: dict[str, Any]) -> str:
        content = payload.get("content")
        if isinstance(content, dict):
            text = content.get("text")
            if text is not None:
                return str(text).strip()

        text = payload.get("text")
        if text is not None:
            return str(text).strip()

        message = payload.get("message")
        if isinstance(message, dict) and message.get("text") is not None:
            return str(message["text"]).strip()

        return ""
