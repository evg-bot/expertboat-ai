from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import expertboat_data_dir
from app.knowledge_import_status import ensure_external_data_directories


DATE_PATTERN = (
    r"\b(?:\d{1,2}\s+"
    r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
    r"(?:\s+\d{4}\s*г\.?)?|"
    r"(?:понедельник|вторник|среда|четверг|пятница|суббота|воскресенье),?\s+\d{1,2}\s+"
    r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря))(?=\s|$)"
)
TIME_PATTERN = r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b"
PRICE_PATTERN = r"\b\d{1,3}(?:[ \u00a0]\d{3})+\s*₽|\b\d+\s*₽"

TECHNICAL_PHRASES = {
    "для бизнеса",
    "карьера в авито",
    "мои объявления",
    "избранное",
    "уведомления",
    "сообщения",
    "корзина",
    "бизнес360",
    "главное",
    "настройки доставки",
    "помощь",
    "безопасность",
    "реклама на сайте",
    "о компании",
    "авито журнал",
    "блог",
    "регионы",
    "правила авито",
    "политика конфиденциальности",
    "защита данных",
    "как продавать и покупать",
    "мобильное приложение",
    "авито для бизнеса",
    "размещение объявлений",
    "прочитано",
    "сообщение удалено",
}

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

SELLER_MARKERS = (
    "наши контакты",
    "выставляем счет",
    "выставляем счёт",
    "выставим счет",
    "выставим счёт",
    "добрый день. палитра",
    "у нас",
    "да, хорошо",
    "на днях ожидаем",
    "пока ждём",
    "пока ждем",
    "ответить сможем",
)

BUYER_MARKERS = (
    "?",
    "есть",
    "актуально",
    "сколько",
    "цена",
    "купить",
    "можно",
    "нужен",
    "интересует",
    "доставка",
    "отправите",
    "счет",
    "счёт",
    "ип",
    "наличии",
)

SUPPORT_DIALOG_MARKERS = (
    "поддержка авито",
    "служба поддержки",
    "центр поддержки",
    "безопасность авито",
    "сообщение от авито",
)


@dataclass(frozen=True)
class AvitoMessage:
    chat_url: str
    listing_title: str
    listing_price: str
    date: str
    time: str
    text: str
    sender: str


@dataclass(frozen=True)
class AvitoImportStats:
    loaded_rows: int = 0
    parsed_messages: int = 0
    buyer_messages: int = 0
    seller_messages: int = 0
    unknown_messages: int = 0
    qa_pairs: int = 0
    skipped_support_dialogs: int = 0


def input_path(data_dir: Path | None = None) -> Path:
    return (data_dir or expertboat_data_dir()) / "avito" / "dialogs_raw.jsonl"


def cleaned_path(data_dir: Path | None = None) -> Path:
    return (data_dir or expertboat_data_dir()) / "processed" / "avito_dialogs_cleaned.jsonl"


def processed_path(data_dir: Path | None = None) -> Path:
    return (data_dir or expertboat_data_dir()) / "processed" / "avito_qa.jsonl"


def load_jsonl(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or input_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def compact_for_compare(text: str) -> str:
    text = normalize_text(text).lower()
    text = re.sub(r"[^\wа-яА-ЯёЁ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_avito_noise(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(DATE_PATTERN, lambda match: f"\n{match.group(0)}\n", text, flags=re.IGNORECASE)
    text = re.sub(TIME_PATTERN, lambda match: f"\n{match.group(0)}\n", text)
    for phrase in sorted(TECHNICAL_PHRASES, key=len, reverse=True):
        text = re.sub(rf"(?i)(?<!\w){re.escape(phrase)}(?!\w)", " ", text)
    text = re.sub(r"(?i)\b(?:был(?:а)?|был)\s+в\s+сети[^.\n]*", " ", text)
    text = re.sub(r"(?i)\b(?:online|offline|typing|timing)\b", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def clean_message_text(text: str) -> str:
    text = strip_avito_noise(text)
    text = re.sub(DATE_PATTERN, " ", text, flags=re.IGNORECASE)
    text = re.sub(TIME_PATTERN, " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -–—:;,.")


def is_noise_message(text: str) -> bool:
    compact = compact_for_compare(text)
    return compact in NOISE_MESSAGES or len(compact) < 3


def is_support_dialog(row: dict[str, Any], text: str) -> bool:
    source = str(row.get("source") or "").casefold()
    chat_url = str(row.get("chat_url") or "").casefold()
    normalized = compact_for_compare(text)
    if source and source != "avito":
        return True
    if "support" in chat_url or "help" in chat_url:
        return True
    return any(marker in normalized for marker in SUPPORT_DIALOG_MARKERS)


def extract_listing(text: str) -> tuple[str, str]:
    cleaned = normalize_text(text)
    for price_match in re.finditer(PRICE_PATTERN, cleaned):
        price, title_suffix = normalize_price_match(price_match.group(0))
        before = cleaned[max(0, price_match.start() - 220) : price_match.start()]
        if title_suffix:
            before = f"{before} {title_suffix}"
        title = title_before_price(before)
        if title:
            return title, price
    return "", ""


def normalize_price_match(raw_price: str) -> tuple[str, str]:
    groups = re.findall(r"\d+", raw_price)
    title_suffix = ""
    if len(groups) >= 3 and groups[0] in {"5", "7", "9", "10", "12", "16"}:
        title_suffix = groups[0]
        groups = groups[1:]
    return f"{' '.join(groups)} ₽", title_suffix


def title_before_price(text: str) -> str:
    text = re.sub(DATE_PATTERN, " ", text, flags=re.IGNORECASE)
    text = re.sub(TIME_PATTERN, " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -–—:;,.")
    product_match = None
    for match in re.finditer(r"(?i)\b(lowrance|garmin|simrad|flir|minn kota|minnkota|mercury|yamaha)\b", text):
        product_match = match
    if product_match:
        text = text[product_match.start() :]
    words = text.split()
    if len(words) > 18:
        text = " ".join(words[-18:])
    text = text.strip(" -–—:;,.")
    return "" if compact_for_compare(text) in TECHNICAL_PHRASES else text


def split_dialog_messages(text: str, *, chat_url: str, listing_title: str, listing_price: str) -> list[AvitoMessage]:
    tokens = re.split(f"({DATE_PATTERN}|{TIME_PATTERN})", text, flags=re.IGNORECASE)
    messages: list[AvitoMessage] = []
    current_date = ""
    current_time = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if not current_time:
            buffer = []
            return
        message_text = clean_message_text(" ".join(buffer))
        buffer = []
        if not message_text or is_noise_message(message_text):
            return
        messages.append(
            AvitoMessage(
                chat_url=chat_url,
                listing_title=listing_title,
                listing_price=listing_price,
                date=current_date,
                time=current_time,
                text=message_text,
                sender=detect_sender(message_text),
            )
        )

    for token in tokens:
        if not token or not token.strip():
            continue
        token = token.strip()
        if re.fullmatch(DATE_PATTERN, token, flags=re.IGNORECASE):
            flush()
            current_date = token
            current_time = ""
            continue
        if re.fullmatch(TIME_PATTERN, token):
            flush()
            current_time = token
            continue
        buffer.append(token)
    flush()
    return messages


def detect_sender(text: str) -> str:
    normalized = compact_for_compare(text)
    if any(marker in normalized for marker in SELLER_MARKERS):
        return "seller"
    if any(marker in normalized for marker in BUYER_MARKERS):
        return "buyer"
    return "unknown"


def parse_dialog_row(row: dict[str, Any]) -> tuple[list[AvitoMessage], bool]:
    raw_text = str(row.get("text") or "")
    chat_url = str(row.get("chat_url") or "")
    cleaned = strip_avito_noise(raw_text)
    if is_support_dialog(row, cleaned):
        return [], True
    listing_title, listing_price = extract_listing(cleaned)
    return (
        split_dialog_messages(
            cleaned,
            chat_url=chat_url,
            listing_title=listing_title,
            listing_price=listing_price,
        ),
        False,
    )


def build_qa_pairs(messages: list[AvitoMessage]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for index, message in enumerate(messages[:-1]):
        next_message = messages[index + 1]
        if message.chat_url != next_message.chat_url:
            continue
        if message.sender != "buyer" or next_message.sender != "seller":
            continue
        if len(message.text.strip()) < 3 or not next_message.text.strip():
            continue
        if is_support_dialog({"source": "avito", "chat_url": message.chat_url}, f"{message.text} {next_message.text}"):
            continue
        pairs.append(
            {
                "chat_url": message.chat_url,
                "listing_title": message.listing_title,
                "listing_price": message.listing_price,
                "question": message.text,
                "answer": next_message.text,
                "source": "avito",
            }
        )
    return pairs


def process_rows(rows: list[dict[str, Any]]) -> tuple[list[AvitoMessage], list[dict[str, str]], AvitoImportStats]:
    messages: list[AvitoMessage] = []
    skipped_support = 0
    for row in rows:
        parsed, skipped = parse_dialog_row(row)
        if skipped:
            skipped_support += 1
            continue
        messages.extend(parsed)

    qa_pairs = build_qa_pairs(messages)
    stats = AvitoImportStats(
        loaded_rows=len(rows),
        parsed_messages=len(messages),
        buyer_messages=sum(1 for message in messages if message.sender == "buyer"),
        seller_messages=sum(1 for message in messages if message.sender == "seller"),
        unknown_messages=sum(1 for message in messages if message.sender == "unknown"),
        qa_pairs=len(qa_pairs),
        skipped_support_dialogs=skipped_support,
    )
    return messages, qa_pairs, stats


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    data_dir = ensure_external_data_directories()
    rows = load_jsonl(input_path(data_dir))
    messages, qa_pairs, stats = process_rows(rows)
    cleaned_output = cleaned_path(data_dir)
    processed_output = processed_path(data_dir)
    write_jsonl(cleaned_output, [message.__dict__ for message in messages])
    write_jsonl(processed_output, qa_pairs)
    print(f"Loaded rows: {stats.loaded_rows}")
    print(f"Parsed messages: {stats.parsed_messages}")
    print(f"Buyer messages: {stats.buyer_messages}")
    print(f"Seller messages: {stats.seller_messages}")
    print(f"Unknown messages: {stats.unknown_messages}")
    print(f"QA pairs: {stats.qa_pairs}")
    print(f"Skipped support dialogs: {stats.skipped_support_dialogs}")
    print(f"Cleaned output: {cleaned_output}")
    print(f"Processed output: {processed_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
