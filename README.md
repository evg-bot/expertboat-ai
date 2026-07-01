# ExpertBoat AI

MVP Telegram-бота Expert Boat для ответов по Markdown-базе знаний. Бот принимает вопросы в Telegram, сначала ищет релевантные фрагменты в `knowledge/*.md`, затем при наличии ключа отправляет только эти фрагменты в LLM. Если ключей LLM нет, работает локальный keyword matcher.

## Возможности

- Telegram-бот на `python-telegram-bot`.
- Markdown-база знаний из папки `knowledge/`.
- DeepSeek API как основной опциональный LLM-провайдер.
- OpenAI остаётся опциональным LLM-провайдером.
- Перед LLM всегда выполняется поиск релевантных фрагментов в базе знаний.
- Если фрагментов нет, бот строго отвечает:

```text
Точный ответ передам специалисту Expert Boat.
```

- LLM запрещено использовать знания вне переданных фрагментов.
- Если ключей LLM нет, используется keyword matcher по `knowledge/*.md`.
- Avito API временно не участвует в обязательном запуске.
- SQLite хранит историю Telegram-диалогов.

## Команды Telegram

```text
/start   - приветствие
/status  - режим работы, провайдер LLM, статус Avito
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

3. Для DeepSeek заполните:

```text
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

4. Для OpenAI вместо DeepSeek используйте:

```text
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
```

Без `DEEPSEEK_API_KEY` и `OPENAI_API_KEY` бот будет отвечать через keyword matcher.

5. Запустите:

```bash
docker compose up -d --build
```

6. Проверьте логи:

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

LLM-провайдеры:

| Переменная | Описание |
| --- | --- |
| `LLM_PROVIDER` | `deepseek` или `openai`. По умолчанию `deepseek`. |
| `LLM_MODEL` | Модель для DeepSeek, по умолчанию `deepseek-chat`. |
| `DEEPSEEK_API_KEY` | API ключ DeepSeek. Если пустой, LLM не используется для DeepSeek. |
| `DEEPSEEK_BASE_URL` | Base URL DeepSeek, по умолчанию `https://api.deepseek.com`. |
| `OPENAI_API_KEY` | API ключ OpenAI. Используется при `LLM_PROVIDER=openai`. |
| `OPENAI_MODEL` | Модель OpenAI, по умолчанию `gpt-4.1-mini`. |

Остальные переменные:

| Переменная | Описание |
| --- | --- |
| `DATABASE_PATH` | Путь к SQLite базе, по умолчанию `data/expertboat.db`. |
| `KNOWLEDGE_DIR` | Путь к Markdown-базе знаний, по умолчанию `knowledge`. |
| `AVITO_CLIENT_ID` | Необязателен для Telegram MVP. |
| `AVITO_CLIENT_SECRET` | Необязателен для Telegram MVP. |
| `AVITO_USER_ID` | Необязателен для Telegram MVP. |

## Как бот отвечает

1. Пользователь задаёт вопрос в Telegram.
2. Бот ищет релевантные секции в `knowledge/*.md`.
3. Если секций нет, сразу отвечает fallback-фразой.
4. Если секции есть и настроен LLM-провайдер, бот отправляет в LLM только найденные фрагменты и вопрос клиента.
5. Если LLM-ключей нет, бот возвращает лучший найденный фрагмент через keyword matcher.

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
