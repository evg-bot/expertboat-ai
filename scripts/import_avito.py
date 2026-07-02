from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "data" / "raw" / "avito" / "dialogs_raw.jsonl"
CLEANED_PATH = ROOT / "data" / "cleaned" / "avito_dialogs_cleaned.jsonl"
PROCESSED_PATH = ROOT / "data" / "processed" / "avito_qa.jsonl"

NOISE_MESSAGES = {
    "ок",
    "окей",
    "понял",
    "поняла",
    "понятно",
    "ясно",
    "хорошо",
    "спасибо",
    "благодарю",
    "+",
}


@dataclass(frozen=True)
class AvitoMessage:
    chat_id: str
    role: str
    text: str
    created_at: str
    message_id: str


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compact_for_compare(text: str) -> str:
    text = normalize_text(text).lower()
    text = re.sub(r"[^\wа-яА-ЯёЁ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_noise_message(text: str) -> bool:
    compact = compact_for_compare(text)
    return compact in NOISE_MESSAGES or len(compact) <= 1


def load_jsonl(path: Path = INPUT_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def row_text(row: dict[str, Any]) -> str:
    value = row.get("text") or row.get("message") or row.get("content") or row.get("body") or ""
    if isinstance(value, dict):
        value = value.get("text") or value.get("content") or ""
    return normalize_text(str(value))


def row_chat_id(row: dict[str, Any]) -> str:
    for key in ("chat_id", "chatId", "dialog_id", "dialogId", "conversation_id"):
        value = row.get(key)
        if value:
            return str(value)
    return "unknown"


def row_created_at(row: dict[str, Any]) -> str:
    for key in ("created_at", "createdAt", "created", "date", "timestamp"):
        value = row.get(key)
        if value:
            return str(value)
    return ""


def row_role(row: dict[str, Any]) -> str:
    if bool(row.get("is_manager")):
        return "manager"
    direction = str(row.get("direction") or row.get("type") or row.get("author_type") or "").lower()
    sender = str(row.get("sender") or row.get("author") or row.get("from") or "").lower()
    marker = f"{direction} {sender}"
    if any(token in marker for token in ("out", "manager", "seller", "shop", "expertboat", "expert boat")):
        return "manager"
    if any(token in marker for token in ("in", "buyer", "customer", "client", "user")):
        return "customer"
    return "customer"


def row_message_id(row: dict[str, Any], role: str, text: str) -> str:
    for key in ("id", "message_id", "messageId", "external_id"):
        value = row.get(key)
        if value:
            return str(value)
    digest = hashlib.sha256(
        f"{row_chat_id(row)}|{role}|{row_created_at(row)}|{text}".encode("utf-8")
    ).hexdigest()
    return digest[:24]


def parse_message(row: dict[str, Any]) -> AvitoMessage | None:
    text = row_text(row)
    if not text or is_noise_message(text):
        return None
    role = row_role(row)
    return AvitoMessage(
        chat_id=row_chat_id(row),
        role=role,
        text=text,
        created_at=row_created_at(row),
        message_id=row_message_id(row, role, text),
    )


def dedupe_messages(messages: list[AvitoMessage]) -> list[AvitoMessage]:
    seen: set[str] = set()
    result: list[AvitoMessage] = []
    for message in messages:
        key = message.message_id
        if key in seen:
            continue
        seen.add(key)
        result.append(message)
    return result


def merge_consecutive(messages: list[AvitoMessage]) -> list[AvitoMessage]:
    merged: list[AvitoMessage] = []
    for message in messages:
        if (
            merged
            and merged[-1].chat_id == message.chat_id
            and merged[-1].role == message.role
        ):
            previous = merged[-1]
            merged[-1] = AvitoMessage(
                chat_id=previous.chat_id,
                role=previous.role,
                text=f"{previous.text}\n{message.text}",
                created_at=previous.created_at or message.created_at,
                message_id=previous.message_id,
            )
            continue
        merged.append(message)
    return merged


def detect_product(text: str) -> str:
    normalized = compact_for_compare(text)
    if "active target" in normalized or "activetarget" in normalized or "ат2" in normalized:
        return "ActiveTarget"
    if "elite fs" in normalized or "элит" in normalized or re.search(r"\b(?:9|10)\s*фс\b", normalized):
        return "Elite FS"
    if "hds" in normalized or "про" in normalized:
        return "HDS PRO"
    if "point 1" in normalized or "point1" in normalized or "поинт" in normalized:
        return "Point-1"
    if "c map" in normalized or "cmap" in normalized or "карта" in normalized:
        return "C-MAP"
    if "lowrance" in normalized or "лоуренс" in normalized:
        return "Lowrance"
    if "garmin" in normalized or "гармин" in normalized:
        return "Garmin"
    if "simrad" in normalized or "симрад" in normalized:
        return "Simrad"
    return ""


def detect_category(text: str) -> str:
    normalized = compact_for_compare(text)
    if any(word in normalized for word in ("доставка", "сдэк", "отправ", "транспортн", "тк")):
        return "delivery"
    if any(word in normalized for word in ("оплат", "купить", "счет", "счёт", "сбп", "qr")):
        return "payment"
    if any(word in normalized for word in ("гарант", "ремонт", "сервис")):
        return "support"
    if any(word in normalized for word in ("русик", "русиф", "прошив", "русский")):
        return "support"
    if detect_product(text):
        return "sales"
    return "sales"


def build_qa_pairs(messages: list[AvitoMessage]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for index, message in enumerate(messages[:-1]):
        next_message = messages[index + 1]
        if message.chat_id != next_message.chat_id:
            continue
        if message.role != "customer" or next_message.role != "manager":
            continue
        combined = f"{message.text}\n{next_message.text}"
        pairs.append(
            {
                "chat_id": message.chat_id,
                "question": message.text,
                "answer": next_message.text,
                "category": detect_category(combined),
                "product": detect_product(combined),
            }
        )
    return pairs


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def process_rows(rows: list[dict[str, Any]]) -> tuple[list[AvitoMessage], list[dict[str, str]]]:
    messages = [message for row in rows if (message := parse_message(row))]
    messages = dedupe_messages(messages)
    messages = merge_consecutive(messages)
    return messages, build_qa_pairs(messages)


def main() -> int:
    rows = load_jsonl()
    messages, qa_pairs = process_rows(rows)
    write_jsonl(CLEANED_PATH, [message.__dict__ for message in messages])
    write_jsonl(PROCESSED_PATH, qa_pairs)
    print(f"Loaded rows: {len(rows)}")
    print(f"Cleaned messages: {len(messages)}")
    print(f"QA pairs: {len(qa_pairs)}")
    print(f"Cleaned output: {CLEANED_PATH}")
    print(f"Processed output: {PROCESSED_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
