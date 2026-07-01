# ExpertBoat AI

MVP Telegram-бота Expert Boat для ответов по Markdown-базе знаний. Бот принимает вопросы в Telegram, ищет ответ в `knowledge/*.md`, использует OpenAI при наличии ключа и fallback keyword matcher без OpenAI.

## Возможности

- Telegram-бот на `python-telegram-bot`.
- Ответы по Markdown-базе знаний из папки `knowledge/`.
- OpenAI API, модель из `OPENAI_MODEL`, по умолчанию `gpt-4.1-mini`.
- Если `OPENAI_API_KEY` не заполнен, используется простой keyword matcher по базе знаний.
- Если точного ответа нет, бот отвечает:

```text
Точный ответ передам специалисту Expert Boat.
```

- Avito API временно не участвует в обязательном запуске. Если `AVITO_CLIENT_ID`, `AVITO_CLIENT_SECRET` и `AVITO_USER_ID` не заполнены, Telegram MVP всё равно работает.
- SQLite хранит историю Telegram-диалогов.

## Команды Telegram

```text
/start   - приветствие
/status  - режим работы, OpenAI/keyword matcher, статус Avito
/reload  - перечитать Markdown-базу знаний
```

## Быстрый локальный запуск

1. Создайте `.env` на основе примера:

```bash
cp .env.example .env
```

2. Заполните минимум Telegram-токен:

```text
TELEGRAM_BOT_TOKEN=123456:telegram-token
```

3. При желании заполните OpenAI:

```text
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
```

Без `OPENAI_API_KEY` бот будет отвечать через keyword matcher по `knowledge/*.md`.

4. Запустите:

```bash
docker compose up -d --build
```

5. Проверьте логи:

```bash
docker compose logs -f
```

## Запуск на Ubuntu 24.04 VPS

1. Подключитесь к серверу:

```bash
ssh root@SERVER_IP
```

2. Установите Git:

```bash
apt-get update && apt-get install -y git
```

3. Склонируйте проект:

```bash
git clone https://github.com/evg-bot/expertboat-ai.git
cd expertboat-ai
```

4. Запустите установщик:

```bash
sudo ./install.sh
```

5. Заполните `.env`:

```bash
nano .env
```

Минимум для работы Telegram MVP:

```text
TELEGRAM_BOT_TOKEN=123456:telegram-token
```

6. Перезапустите контейнер:

```bash
docker compose up -d --build
```

## Обновление на VPS

```bash
./update.sh
```

## Переменные окружения

Обязательные для Telegram MVP:

| Переменная | Описание |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота от BotFather. |

Опциональные:

| Переменная | Описание |
| --- | --- |
| `OPENAI_API_KEY` | API ключ OpenAI. Если пустой, используется keyword matcher. |
| `OPENAI_MODEL` | Модель OpenAI, по умолчанию `gpt-4.1-mini`. |
| `DATABASE_PATH` | Путь к SQLite базе, по умолчанию `data/expertboat.db`. |
| `KNOWLEDGE_DIR` | Путь к Markdown-базе знаний, по умолчанию `knowledge`. |
| `AVITO_CLIENT_ID` | Необязателен для Telegram MVP. |
| `AVITO_CLIENT_SECRET` | Необязателен для Telegram MVP. |
| `AVITO_USER_ID` | Необязателен для Telegram MVP. |

## База знаний

Основная база знаний лежит в папке `knowledge/`. В проект добавлен файл:

```text
knowledge/faq.md
```

После изменения Markdown-файлов отправьте боту команду:

```text
/reload
```

## Docker volumes

```text
./data:/app/data
./knowledge:/app/knowledge:ro
```

SQLite сохраняется в `data/`, база знаний читается из `knowledge/`.

## Полезные команды

```bash
docker compose ps
docker compose logs -f
docker compose restart
docker compose down
```
