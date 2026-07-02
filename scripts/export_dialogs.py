from pathlib import Path
from playwright.sync_api import sync_playwright
import json
import time
import re

PROFILE_DIR = Path("data/chrome_profile")
OUT_DIR = Path("data/avito_export")
OUT_DIR.mkdir(parents=True, exist_ok=True)

RAW_FILE = OUT_DIR / "dialogs_raw.jsonl"

MAX_CHATS = 300


def clean_text(text: str) -> str:
    text = re.sub(r"\+?\d[\d\s\-\(\)]{8,}\d", "[PHONE]", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        viewport=None,
        args=[
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
        ],
    )

    page = context.pages[0] if context.pages else context.new_page()

    page.goto(
        "https://www.avito.ru/profile/messenger",
        wait_until="domcontentloaded",
        timeout=120000,
    )

    time.sleep(5)

    print("Собираю ссылки на чаты...")

    for n in range(120):
        page.keyboard.press("PageDown")
        time.sleep(0.5)
        print(f"Прокрутка списка чатов: {n + 1}/120")

    links = page.locator('a[href*="/profile/messenger/channel/"]').evaluate_all(
        """els => Array.from(new Set(els.map(a => a.href)))"""
    )

    links = links[:MAX_CHATS]

    print(f"Найдено чатов: {len(links)}")

    with RAW_FILE.open("w", encoding="utf-8") as f:
        for i, url in enumerate(links, start=1):
            print(f"[{i}/{len(links)}] {url}")

            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            time.sleep(4)

            for _ in range(15):
                page.mouse.wheel(0, -2000)
                time.sleep(0.7)

            time.sleep(2)

            body_text = page.locator("body").inner_text(timeout=60000)
            body_text = clean_text(body_text)

            record = {
                "source": "avito",
                "chat_url": url,
                "text": body_text,
            }

            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

            time.sleep(2)

    context.close()

print(f"Готово. Файл: {RAW_FILE}")