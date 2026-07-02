from pathlib import Path
from playwright.sync_api import sync_playwright
import time

PROFILE_DIR = Path("data/chrome_profile")
OUT_DIR = Path("data/avito_dump")
OUT_DIR.mkdir(parents=True, exist_ok=True)

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

    input("Открой любой чат с клиентом. Когда сообщения будут видны — нажми ENTER.")

    time.sleep(5)

    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass

    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    text = page.locator("body").inner_text(timeout=60000)
    html = page.evaluate("() => document.documentElement.outerHTML")

    (OUT_DIR / "current_chat.txt").write_text(text, encoding="utf-8")
    (OUT_DIR / "current_chat.html").write_text(html, encoding="utf-8")

    print("Сохранено:")
    print(OUT_DIR / "current_chat.txt")
    print(OUT_DIR / "current_chat.html")

    input("Нажми ENTER для выхода.")
    context.close()