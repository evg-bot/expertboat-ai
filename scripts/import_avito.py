from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, replace
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
PRODUCT_KEY_PATTERN = (
    r"(?i)\b(?:lowrance|garmin|simrad|hds|elite|eagle|activetarget|active\s*target|"
    r"датчик|эхолот|картплоттер)\b"
)

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

FOOTER_MESSAGE_PHRASES = (
    "авито — сайт объявлений россии",
    "авито - сайт объявлений россии",
    "ооо «кех екоммерц»",
    "ооо кех екоммерц",
    "оплачивая услуги на авито",
    "авито использует рекомендательные технологии",
    "карта сайта",
    "свежие объявления",
)

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
    "добрый день",
    "здравствуйте",
    "наши контакты",
    "мы",
    "с какого",
    "заказ не видим",
    "заказ ни какой не видим",
    "заказ никакой не видим",
    "палитра и наложение",
    "регистрировать ничего не нужно",
    "хорошо, тогда подождем",
    "хорошо тогда подождем",
    "надеемся",
    "выставляем счет",
    "выставляем счёт",
    "выставим счет",
    "выставим счёт",
    "добрый день. палитра",
    "у нас",
    "да, хорошо",
    "без ндс",
    "нет в наличии",
    "ожидаем",
    "на днях ожидаем",
    "на днях",
    "пока ждём",
    "пока ждем",
    "ответить сможем",
    "оставьте свои контакты",
    "специалисты свяжутся",
)

BUYER_MARKERS = (
    "?",
    "скажите пожалуйста",
    "сообщите пожалуйста",
    "как оплатить",
    "когда",
    "появился",
    "напишите",
    "супер спасибо",
    "супер, спасибо",
    "заказали",
    "не получается оплатить",
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

PRICE_QUERY_MARKERS = (
    "цена",
    "стоимость",
    "сколько стоит",
    "по цене",
    "актуальная цена",
)

PRICE_ANSWER_TEMPLATE = (
    "Цена по объявлению — {listing_price}. "
    "Актуальность и наличие лучше подтвердить перед заказом."
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
    listing_title_detected: int = 0
    skipped_footer_messages: int = 0
    skipped_listing_metadata_messages: int = 0


@dataclass(frozen=True)
class DialogParseResult:
    messages: list[AvitoMessage]
    skipped_support: bool = False
    listing_title_detected: bool = False
    skipped_footer_messages: int = 0
    skipped_listing_metadata_messages: int = 0


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
    return text.strip(" -–—:;,")


def is_noise_message(text: str) -> bool:
    compact = compact_for_compare(text)
    return compact in NOISE_MESSAGES or len(compact) < 3


def is_price_question(text: str) -> bool:
    normalized = compact_for_compare(text)
    return any(marker in normalized for marker in PRICE_QUERY_MARKERS)


def is_footer_message(text: str) -> bool:
    normalized = normalize_text(text).casefold()
    compact = compact_for_compare(text)
    return any(phrase in normalized or compact_for_compare(phrase) in compact for phrase in FOOTER_MESSAGE_PHRASES)


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
        price_value = int("".join(re.findall(r"\d+", price)) or "0")
        if price_value < 1000:
            continue
        before = cleaned[max(0, price_match.start() - 260) : price_match.start()]
        if title_suffix:
            before = f"{before} {title_suffix}"
        title = title_before_price(before)
        if title and has_product_key(title) and not is_ignored_listing_title(title):
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
    product_match = re.search(PRODUCT_KEY_PATTERN, text)
    if product_match:
        text = text[product_match.start() :]
    else:
        return ""
    words = text.split()
    if len(words) > 18:
        text = " ".join(words[-18:])
    text = text.strip(" -–—:;,.")
    return "" if compact_for_compare(text) in TECHNICAL_PHRASES else text


def has_product_key(text: str) -> bool:
    return re.search(PRODUCT_KEY_PATTERN, text) is not None


def is_ignored_listing_title(text: str) -> bool:
    compact = compact_for_compare(text)
    ignored = ("кошелек", "аванс", "разместить объявление", "авто недвижимость работа услуги")
    return any(item in compact for item in ignored)


def is_listing_metadata_message(text: str, listing_title: str, listing_price: str) -> bool:
    compact = compact_for_compare(text)
    title_compact = compact_for_compare(listing_title)
    if title_compact and compact == title_compact:
        return True
    return bool(listing_price and has_product_key(text) and re.search(PRICE_PATTERN, text))


def split_dialog_messages(
    text: str, *, chat_url: str, listing_title: str, listing_price: str
) -> tuple[list[AvitoMessage], int, int]:
    tokens = re.split(f"({DATE_PATTERN}|{TIME_PATTERN})", text, flags=re.IGNORECASE)
    messages: list[AvitoMessage] = []
    current_date = ""
    current_time = ""
    buffer: list[str] = []
    skipped_footer_messages = 0
    skipped_listing_metadata_messages = 0

    def flush() -> None:
        nonlocal buffer, skipped_footer_messages, skipped_listing_metadata_messages
        if not current_time:
            buffer = []
            return
        message_text = clean_message_text(" ".join(buffer))
        buffer = []
        if not message_text or is_noise_message(message_text):
            return
        if is_footer_message(message_text):
            skipped_footer_messages += 1
            return
        if is_listing_metadata_message(message_text, listing_title, listing_price):
            skipped_listing_metadata_messages += 1
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
    return infer_senders_by_turn(messages), skipped_footer_messages, skipped_listing_metadata_messages


def detect_sender(text: str) -> str:
    normalized = compact_for_compare(text)
    generic_seller_markers = {"добрый день", "здравствуйте", "мы"}
    strong_seller_markers = tuple(marker for marker in SELLER_MARKERS if marker not in generic_seller_markers)
    if any(marker in normalized for marker in strong_seller_markers):
        return "seller"
    if any(marker in normalized for marker in BUYER_MARKERS):
        return "buyer"
    if any(marker in normalized for marker in generic_seller_markers):
        return "seller"
    if any(marker in normalized for marker in SELLER_MARKERS):
        return "seller"
    return "unknown"


def infer_senders_by_turn(messages: list[AvitoMessage]) -> list[AvitoMessage]:
    inferred: list[AvitoMessage] = []
    last_sender_by_chat: dict[str, str] = {}
    for message in messages:
        sender = message.sender
        if sender == "unknown" and not is_footer_message(message.text) and not is_listing_metadata_message(
            message.text, message.listing_title, message.listing_price
        ):
            previous = last_sender_by_chat.get(message.chat_url)
            if previous == "buyer":
                sender = "seller"
            elif previous == "seller":
                sender = "buyer"
        if sender in {"buyer", "seller"}:
            last_sender_by_chat[message.chat_url] = sender
        inferred.append(replace(message, sender=sender))
    return inferred


def parse_dialog_row(row: dict[str, Any]) -> DialogParseResult:
    raw_text = str(row.get("text") or "")
    chat_url = str(row.get("chat_url") or "")
    cleaned = strip_avito_noise(raw_text)
    if is_support_dialog(row, cleaned):
        return DialogParseResult(messages=[], skipped_support=True)
    listing_title, listing_price = extract_listing(cleaned)
    messages, skipped_footer, skipped_listing_metadata = split_dialog_messages(
        cleaned,
        chat_url=chat_url,
        listing_title=listing_title,
        listing_price=listing_price,
    )
    return DialogParseResult(
        messages=messages,
        listing_title_detected=bool(listing_title),
        skipped_footer_messages=skipped_footer,
        skipped_listing_metadata_messages=skipped_listing_metadata,
    )


def build_qa_pairs(messages: list[AvitoMessage]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    grouped: dict[str, list[AvitoMessage]] = {}
    for message in messages:
        grouped.setdefault(message.chat_url, []).append(message)

    for chat_messages in grouped.values():
        question_parts: list[str] = []
        answer_parts: list[str] = []
        question_meta: AvitoMessage | None = None

        def flush_pair() -> None:
            nonlocal question_parts, answer_parts, question_meta
            if not question_parts or question_meta is None:
                return
            question = " ".join(part.strip() for part in question_parts if part.strip()).strip()
            answer = " ".join(part.strip() for part in answer_parts if part.strip()).strip()
            if len(question) < 3:
                return
            if is_price_question(question):
                if not question_meta.listing_price:
                    return
                answer = PRICE_ANSWER_TEMPLATE.format(listing_price=question_meta.listing_price)
            elif not answer:
                return
            if is_support_dialog({"source": "avito", "chat_url": question_meta.chat_url}, f"{question} {answer}"):
                return
            pairs.append(
                {
                    "chat_url": question_meta.chat_url,
                    "listing_title": question_meta.listing_title,
                    "listing_price": question_meta.listing_price,
                    "question": question,
                    "answer": answer,
                    "source": "avito",
                }
            )

        for message in chat_messages:
            if message.sender == "buyer":
                if question_parts and answer_parts:
                    flush_pair()
                    question_parts = []
                    answer_parts = []
                    question_meta = None
                question_parts.append(message.text)
                question_meta = question_meta or message
                continue
            if message.sender == "seller":
                if question_parts:
                    answer_parts.append(message.text)
                continue

        flush_pair()
    return pairs


def process_rows(rows: list[dict[str, Any]]) -> tuple[list[AvitoMessage], list[dict[str, str]], AvitoImportStats]:
    messages: list[AvitoMessage] = []
    skipped_support = 0
    listing_title_detected = 0
    skipped_footer_messages = 0
    skipped_listing_metadata_messages = 0
    for row in rows:
        parsed = parse_dialog_row(row)
        if parsed.skipped_support:
            skipped_support += 1
            continue
        if parsed.listing_title_detected:
            listing_title_detected += 1
        skipped_footer_messages += parsed.skipped_footer_messages
        skipped_listing_metadata_messages += parsed.skipped_listing_metadata_messages
        messages.extend(parsed.messages)

    qa_pairs = build_qa_pairs(messages)
    stats = AvitoImportStats(
        loaded_rows=len(rows),
        parsed_messages=len(messages),
        buyer_messages=sum(1 for message in messages if message.sender == "buyer"),
        seller_messages=sum(1 for message in messages if message.sender == "seller"),
        unknown_messages=sum(1 for message in messages if message.sender == "unknown"),
        qa_pairs=len(qa_pairs),
        skipped_support_dialogs=skipped_support,
        listing_title_detected=listing_title_detected,
        skipped_footer_messages=skipped_footer_messages,
        skipped_listing_metadata_messages=skipped_listing_metadata_messages,
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
    print(f"Listing title detected: {stats.listing_title_detected}")
    print(f"Skipped footer messages: {stats.skipped_footer_messages}")
    print(f"Skipped listing metadata messages: {stats.skipped_listing_metadata_messages}")
    print(f"Cleaned output: {cleaned_output}")
    print(f"Processed output: {processed_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
