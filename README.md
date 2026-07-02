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
  inbox/
  manuals/
  processed/
  chunks/
  review/
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

## Knowledge Builder

Большие PDF, DOCX, сырые Avito/Telegram-выгрузки и черновики FAQ не хранятся в Git. Для них используется внешнее хранилище `EXPERTBOAT_DATA_DIR`.

Значения по умолчанию:

```text
Windows: D:\expertboat-data
Linux/VPS: /data/expertboat-data
```

Структура внешнего хранилища:

```text
D:\expertboat-data\
  manuals\
    lowrance\
    garmin\
    simrad\
    flir\
    minnkota\
    mercury\
    yamaha\
  avito\
  telegram\
  processed\
  review\
  faq\
  chunks\
  import_history.sqlite
```

Создать папки на Windows:

```powershell
New-Item -ItemType Directory -Force `
  D:\expertboat-data\manuals\lowrance, `
  D:\expertboat-data\manuals\garmin, `
  D:\expertboat-data\manuals\simrad, `
  D:\expertboat-data\manuals\flir, `
  D:\expertboat-data\manuals\minnkota, `
  D:\expertboat-data\manuals\mercury, `
  D:\expertboat-data\manuals\yamaha, `
  D:\expertboat-data\avito, `
  D:\expertboat-data\telegram, `
  D:\expertboat-data\processed, `
  D:\expertboat-data\review, `
  D:\expertboat-data\faq, `
  D:\expertboat-data\chunks, `
  D:\expertboat-data\listings
```

Создать папки на VPS:

```bash
sudo mkdir -p /data/expertboat-data/{avito,telegram,processed,review,faq,chunks,listings}
sudo mkdir -p /data/expertboat-data/manuals/{lowrance,garmin,simrad,flir,minnkota,mercury,yamaha}
sudo chown -R "$USER":"$USER" /data/expertboat-data
```

Импорт документов из внешней папки `manuals/**/*`:

```bash
python scripts/import_knowledge.py --source manuals
```

Поддерживаются `pdf`, `docx`, `txt`, `md`, `json`, `jsonl`. Результаты пишутся во внешние папки:

```text
{EXPERTBOAT_DATA_DIR}/processed
{EXPERTBOAT_DATA_DIR}/chunks
{EXPERTBOAT_DATA_DIR}/import_history.sqlite
```

Повторно одинаковые документы не индексируются: используется SHA256 исходного файла.

Публикация проверенных Markdown в рабочую базу бота:

```bash
python scripts/import_knowledge.py --source manuals --publish
```

Без `--publish` скрипт не пишет в `knowledge/`.

Импорт сырых Avito-диалогов:

```bash
python scripts/import_avito.py
```

Вход:

```text
{EXPERTBOAT_DATA_DIR}/avito/dialogs_raw.jsonl
```

Выход:

```text
{EXPERTBOAT_DATA_DIR}/processed/avito_qa.jsonl
```

Сборка FAQ из обработанных диалогов:

```bash
python scripts/build_faq.py
```

FAQ создается во внешних папках:

```text
{EXPERTBOAT_DATA_DIR}/faq
{EXPERTBOAT_DATA_DIR}/review
```

Это review-режим: автоматически созданные ответы сначала проверяются человеком. Только подтвержденные Markdown-файлы публикуются в рабочую `knowledge/`-базу.

Все источники сразу:

```bash
python scripts/import_knowledge.py --source all
```

Файлы FAQ:

```text
sales.md
delivery.md
payment.md
support.md
elite_fs.md
hds_pro.md
active_target.md
```

## Listing Builder

Listing Builder хранит актуальные карточки объявлений Авито отдельно от старой переписки. Это нужно, чтобы цена, название, статус, описание и характеристики брались из объявления, а не из устаревшего диалога.

Внешние файлы:

```text
{EXPERTBOAT_DATA_DIR}/listings/
{EXPERTBOAT_DATA_DIR}/listings/listings.sqlite
{EXPERTBOAT_DATA_DIR}/listings/listings_raw.jsonl
{EXPERTBOAT_DATA_DIR}/listings/listings_cleaned.jsonl
{EXPERTBOAT_DATA_DIR}/listings/listing_history.jsonl
```

Основной импорт:

```bash
python scripts/import_listings.py
```

В Docker:

```bash
docker compose exec expertboat-ai python scripts/import_listings.py
```

Если есть файл `{EXPERTBOAT_DATA_DIR}/listings/listings_raw.jsonl`, скрипт читает его. Формат строки:

```json
{"url":"...","title":"Lowrance Elite FS 10 + датчик AI 3-in-1 26.2 RUS","price":"135 000 ₽","description":"...","status":"active","photos":[],"attributes":{}}
```

Если `listings_raw.jsonl` отсутствует, включается временный fallback: скрипт читает `{EXPERTBOAT_DATA_DIR}/processed/avito_qa.jsonl` и создает минимальные карточки из `listing_title`, `listing_price`, `chat_url`.

Скрипт нормализует:

```text
price_text: "135 000 ₽"
price: 135000
brand / series / model / screen_size / transducer / firmware / category
```

При изменении цены, статуса, описания или характеристик изменения пишутся в `listing_history` и `listing_history.jsonl`.

FAQ по ценам строится из `listings.sqlite`: `python scripts/build_faq.py` добавляет в review файл `listings_price_faq.md`.

## Telegram Commands

```text
/start              - приветствие
/status             - статус LLM, RAG, docs, chunks, aliases и SQLite
/reload             - перечитать Markdown и aliases, затем пересобрать RAG-индекс
/reindex            - пересобрать RAG-индекс
/ragstatus          - состояние RAG, docs count, chunks count, дата индексации
/importstatus       - статус внешнего Knowledge Builder storage
/importhelp         - куда класть PDF и Avito-историю
/listingstatus      - статус Listing Builder и последние 5 объявлений
/listinghelp        - куда класть listings_raw.jsonl и как работает fallback
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
EXPERTBOAT_DATA_DIR=D:\expertboat-data
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
mkdir -p /data/expertboat-data/{avito,telegram,processed,review,faq,chunks,listings}
mkdir -p /data/expertboat-data/manuals/{lowrance,garmin,simrad,flir,minnkota,mercury,yamaha}
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
| `EXPERTBOAT_DATA_DIR` | Внешнее хранилище больших данных. Windows: `D:\expertboat-data`, VPS: `/data/expertboat-data`. |
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
${EXPERTBOAT_DATA_DIR:-./external-data}:/data/expertboat-data
```

SQLite бота хранится в `data/`, рабочая база знаний и aliases читаются из `knowledge/`. Большие manuals, Avito/Telegram exports, review, FAQ, chunks и `import_history.sqlite` лежат во внешнем storage. В контейнере он доступен как `/data/expertboat-data`. Команда `/learn` записывает новые знания в `knowledge/learned.md`.

## Tests

```bash
python -m unittest tests.test_knowledge_search tests.test_rag_search tests.test_customer_responses tests.test_knowledge_builder
```
