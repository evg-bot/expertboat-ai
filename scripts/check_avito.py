from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE_DIR = Path("data/chrome_profile")
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

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

    input("Войди в Авито, реши капчу если будет. Когда сообщения откроются — нажми ENTER.")
    context.close()