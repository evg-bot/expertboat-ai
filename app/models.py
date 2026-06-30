from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


MessageDirection = Literal["incoming", "outgoing"]
MessageChannel = Literal["avito", "telegram", "system"]


@dataclass(frozen=True)
class AvitoMessage:
    id: str
    chat_id: str
    author_id: str
    text: str
    created_at: datetime
    direction: str = "in"
    author_name: str = "Покупатель"


@dataclass(frozen=True)
class StoredMessage:
    id: int
    external_id: str | None
    channel: MessageChannel
    chat_id: str
    direction: MessageDirection
    text: str
    created_at: datetime
