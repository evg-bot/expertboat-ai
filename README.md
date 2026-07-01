# ExpertBoat AI

MVP Telegram-бота Expert Boat для ответов по Markdown-базе знаний. Бот запускается в Docker, хранит историю и RAG-индекс в SQLite, ищет ответы по локальному semantic-like scoring и, если есть ключ LLM, формулирует короткий ответ через DeepSeek или OpenAI строго по найденным фрагментам.

Если информации в базе знаний недостаточно, бот отвечает только:

```text
Точный ответ передам специалисту Expert Boat.
```

## Что умеет

- Telegram-бот на `python-telegram-bot`.
- Markdown-база знаний в `knowledge/**/*.md`.
- Локальный RAG без платных embeddings: Markdown режется на chunks и индексируется в SQLite.
- YAML frontmatter для метаданных документов: `product`, `category`, `tags`, `priority`.
- Алиасы и fuzzy search через `knowledge/aliases.yaml` и `rapidfuzz`.
- LLM получает только top chunks, а не весь документ.
- Без LLM-ключей бот отвечает лучшим найденным chunk без Markdown.
- SQLite хранит сообщения, последние 10 сообщений по каждому чату, статистику, chunks и search stats.
- `/learn` добавляет новые вопрос-ответ пары в `knowledge/learned.md` и пересобирает индекс.

## RAG

При старте приложение:

1. Создает SQLite-таблицы.
2. Загружает `knowledge/**/*.md`.
3. Читает YAML frontmatter.
4. Разбивает Markdown по заголовкам и абзацам.
5. Сохраняет chunks в `knowledge_chunks`.
6. Ищет по нормализованному запросу, алиасам, фразам, терминам, заголовкам, fuzzy match, близости слов и metadata.

Основные таблицы:

```text
knowledge_chunks(id, source, title, content, content_hash, created_at)
search_stats(id, query, method, top_score, created_at)
```

Пример frontmatter:

```yaml
---
product: Lowrance Elite FS 9
category: lowrance
tags:
  - 9фс
  - elite fs 9
  - эхолот
priority: 10
---
```

## Команды Telegram

```text
/start              - приветствие
/status             - статус LLM, docs, chunks, aliases и SQLite
/reload             - перечитать Markdown, aliases.yaml и пересобрать RAG-индекс
/reindex            - пересобрать RAG-индекс
/ragstatus          - docs count, chunks count, дата последней индексации
/stats              - статистика сообщений, найденных ответов, fallback и LLM
/learn              - обучение: вопрос -> правильный ответ -> запись в learned.md -> reindex
/search <запрос>    - диагностика RAG: top 5 chunks, score, source, title, method
/aliases            - количество групп алиасов и первые 20 групп
```

Если `TELEGRAM_MANAGER_CHAT_ID` заполнен, admin-команды доступны только этому chat id. Если переменная пустая, admin-команды доступны всем.

## Структура knowledge

```text
knowledge/
  aliases.yaml
  contacts.md
  payment.md
  delivery.md
  warranty.md
  firmware.md
  learned.md
  lowrance/
    elite-fs.md
    hds-pro.md
    active-target.md
  sales/
    objections.md
    scripts.md
```

## Локальный запуск

1. Создайте `.env`:

```bash
cp .env.example .env
```

2. Заполните минимум Telegram-токен:

```text
TELEGRAM_BOT_TOKEN=123456:telegram-token
```

3. Запустите:

```bash
docker compose up -d --build
```

4. Посмотрите логи:

```bash
docker compose logs -f
```

## LLM-провайдеры

DeepSeek:

```text
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

OpenAI:

```text
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
```

Если `DEEPSEEK_API_KEY` и `OPENAI_API_KEY` не заполнены, бот продолжает работать через локальный RAG и возвращает лучший найденный фрагмент.

## Ubuntu 24.04 VPS

```bash
ssh root@SERVER_IP
apt-get update && apt-get install -y git
git clone https://github.com/evg-bot/expertboat-ai.git
cd expertboat-ai
sudo ./install.sh
nano .env
docker compose up -d --build
```

Для обновления:

```bash
./update.sh
```

## Переменные окружения

Обязательная для Telegram MVP:

| Переменная | Описание |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота от BotFather. |

Опциональные:

| Переменная | Описание |
| --- | --- |
| `DATABASE_PATH` | Путь к SQLite, по умолчанию `data/expertboat.db`. |
| `KNOWLEDGE_DIR` | Путь к Markdown-базе, по умолчанию `knowledge`. |
| `TELEGRAM_MANAGER_CHAT_ID` | Chat id администратора. |
| `LLM_PROVIDER` | `deepseek` или `openai`, по умолчанию `deepseek`. |
| `LLM_MODEL` | Модель DeepSeek, по умолчанию `deepseek-chat`. |
| `DEEPSEEK_API_KEY` | API-ключ DeepSeek. |
| `DEEPSEEK_BASE_URL` | Base URL DeepSeek. |
| `OPENAI_API_KEY` | API-ключ OpenAI. |
| `OPENAI_MODEL` | Модель OpenAI, по умолчанию `gpt-4.1-mini`. |
| `AVITO_CLIENT_ID` | Не обязателен для Telegram MVP. |
| `AVITO_CLIENT_SECRET` | Не обязателен для Telegram MVP. |
| `AVITO_USER_ID` | Не обязателен для Telegram MVP. |

## Docker volumes

```text
./data:/app/data
./knowledge:/app/knowledge
```

SQLite хранится в `data/`, база знаний и aliases читаются из `knowledge/`. Команда `/learn` записывает новые знания в `knowledge/learned.md`.

## Проверка

```bash
python -m unittest tests.test_knowledge_search tests.test_rag_search
```
