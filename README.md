# ExpertBoat AI

Telegram-бот Expert Boat для ответов по Markdown-базе знаний. Проект запускается в Docker, хранит историю и RAG-индекс в SQLite, ищет ответы локально без платных embeddings и при наличии ключа LLM формулирует ответ через OpenAI строго по найденным chunks. DeepSeek остается опциональным провайдером.

Если вопрос не относится к Expert Boat или информации недостаточно, бот отвечает:

```text
Точный ответ передам специалисту Expert Boat.
```

## Возможности

- Telegram-бот на `python-telegram-bot`.
- Markdown-база знаний в `knowledge/**/*.md`.
- Локальный guarded RAG pipeline без embeddings.
- SQLite-таблицы для истории, памяти чата, статистики, chunks и search stats.
- YAML frontmatter: `product`, `category`, `tags`, `priority`.
- Алиасы из `knowledge/aliases.yaml` и fuzzy matching через `rapidfuzz`.
- Intent classifier без LLM.
- Off-topic guardrails для машин, медицины, бытовой техники, строительства, политики и других нерелевантных тем.
- OpenAI по умолчанию использует `gpt-4.1-mini` и получает только top chunks, а не весь документ.
- Greeting, off-topic, fallback и готовые seller-style ответы не отправляются в LLM.
- Клиентские ответы очищаются от Markdown: без `#`, `##`, `**`, backticks и frontmatter.

## RAG Pipeline

Поиск построен так, чтобы история диалога не загрязняла первичную релевантность:

1. Нормализуется только текущий запрос.
2. Алиасы раскрываются только для текущего запроса.
3. Intent и `domain_relevance` считаются только по текущему запросу.
4. Chunks ищутся только по текущему запросу.
5. Если `domain_relevance=false`, intent `off_topic` или `top_score` ниже порога, бот возвращает fallback.
6. История используется только вторым шагом для коротких уточнений вроде `а десятка?`, если предыдущий релевантный запрос был про товар.

Intents:

```text
greeting
product_lookup
price
availability
delivery
warranty
payment
firmware
maps
compatibility
off_topic
unknown
```

Domain vocabulary включает морскую электронику, Lowrance, Garmin, Simrad, эхолоты, картплоттеры, датчики, ActiveTarget, HDS, Elite FS, Eagle, Point-1, C-MAP, NMEA2000, Ethernet, русификацию, доставку, гарантию и оплату.

Thresholds заданы в [app/config.py](app/config.py):

```python
RAG_MIN_SCORE = 18
RAG_MIN_DOMAIN_SCORE = 1
RAG_SHORT_QUERY_MAX_LEN = 20
```

## QueryContext

Команда `/search <запрос>` показывает полный диагностический контекст:

```text
raw_query
normalized_query
expanded_query
aliases_found
intent
domain_relevance
used_history
history_reason
top_score
fallback_reason
```

## SQLite

Основные RAG-таблицы:

```text
knowledge_chunks(id, source, title, content, content_hash, created_at)
search_stats(id, query, method, top_score, created_at)
```

## Knowledge

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

## Telegram Commands

```text
/start              - приветствие
/status             - статус LLM, RAG, docs, chunks, aliases и SQLite
/reload             - перечитать Markdown и aliases, затем пересобрать RAG-индекс
/reindex            - пересобрать RAG-индекс
/ragstatus          - состояние RAG, docs count, chunks count, дата индексации
/stats              - статистика сообщений, найденных ответов, fallback и LLM
/learn              - обучение: вопрос -> правильный ответ -> learned.md -> reindex
/search <запрос>    - диагностика QueryContext и top 5 chunks
/aliases            - количество групп алиасов и первые 20 групп
```

Если `TELEGRAM_MANAGER_CHAT_ID` заполнен, admin-команды доступны только этому chat id. Если переменная пустая, admin-команды доступны всем.

## Локальный запуск

```bash
cp .env.example .env
```

Минимально заполните:

```text
TELEGRAM_BOT_TOKEN=123456:telegram-token
```

Запуск:

```bash
docker compose up -d --build
docker compose logs -f
```

## LLM Providers

OpenAI используется по умолчанию:

```text
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
```

DeepSeek:

```text
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

Если LLM-ключи не заполнены, бот продолжает работать через локальный guarded RAG и возвращает лучший найденный chunk.

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

Обновление:

```bash
./update.sh
```

## Environment

Обязательная переменная для Telegram MVP:

| Переменная | Описание |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота от BotFather. |

Опциональные переменные:

| Переменная | Описание |
| --- | --- |
| `DATABASE_PATH` | Путь к SQLite, по умолчанию `data/expertboat.db`. |
| `KNOWLEDGE_DIR` | Путь к Markdown-базе, по умолчанию `knowledge`. |
| `TELEGRAM_MANAGER_CHAT_ID` | Chat id администратора. |
| `LLM_PROVIDER` | `openai` или `deepseek`, по умолчанию `openai`. |
| `OPENAI_API_KEY` | API-ключ OpenAI. |
| `OPENAI_MODEL` | Модель OpenAI, по умолчанию `gpt-4.1-mini`. |
| `LLM_MODEL` | Модель DeepSeek, по умолчанию `deepseek-chat`. |
| `DEEPSEEK_API_KEY` | API-ключ DeepSeek. |
| `DEEPSEEK_BASE_URL` | Base URL DeepSeek. |
| `AVITO_CLIENT_ID` | Не обязателен для Telegram MVP. |
| `AVITO_CLIENT_SECRET` | Не обязателен для Telegram MVP. |
| `AVITO_USER_ID` | Не обязателен для Telegram MVP. |

## Docker Volumes

```text
./data:/app/data
./knowledge:/app/knowledge
```

SQLite хранится в `data/`, база знаний и aliases читаются из `knowledge/`. Команда `/learn` записывает новые знания в `knowledge/learned.md`.

## Tests

```bash
python -m unittest tests.test_knowledge_search tests.test_rag_search
```
