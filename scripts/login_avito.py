from pathlib import Path
from playwright.sync_api import sync_playwright

STATE_FILE = Path("data/avito_state.json")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        args=["--start-maximized"]
    )

    context = browser.new_context(viewport=None)
    page = context.new_page()

    page.set_default_timeout(120000)

    page.goto(
        "https://www.avito.ru/profile/messenger",
        wait_until="domcontentloaded",
        timeout=120000
    )

    print()
    print("=" * 60)
    print("Войдите в Авито в открывшемся окне.")
    print("Откройте Сообщения.")
    print("Когда список чатов будет виден — вернитесь сюда и нажмите ENTER.")
    print("Браузер руками НЕ закрывать.")
    print("=" * 60)
    print()

    input()

    context.storage_state(path=str(STATE_FILE))
    browser.close()

print(f"Сессия сохранена: {STATE_FILE}")