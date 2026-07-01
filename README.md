# ExpertBoat AI

MVP Telegram-бота Expert Boat для ответов по Markdown-базе знаний. Бот принимает вопросы в Telegram, нормализует запрос, расширяет его через словарь алиасов, ищет релевантные фрагменты в `knowledge/*.md`, использует DeepSeek/OpenAI при наличии ключа и не отвечает вне базы знаний.

## Возможности

- Telegram-бот на `python-telegram-bot`.
- Markdown-база знаний с отдельными файлами по темам.
- Словарь алиасов `knowledge/aliases.yaml` для разговорных названий товаров и тем.
- Fuzzy matching через `rapidfuzz`: score выше 85 считается совпадением.
- Улучшенный scoring-поиск: нормализация текста, `ё -> е`, удаление лишней пунктуации, совпадения слов, совпадения фраз, повышенный вес Markdown-заголовков.
- Top 3 релевантных фрагмента передаются в LLM.
- DeepSeek API как основной опциональный LLM-провайдер.
- OpenAI как опциональный LLM-провайдер.
- Без LLM-ключей бот отвечает лучшим найденным фрагментом без Markdown-разметки.
- Если фрагментов нет, бот строго отвечает:

```text
Точный ответ передам специалисту Expert Boat.
```

- SQLite хранит историю, последние 10 сообщений по каждому `chat_id`, статистику и служебные данные.
- `/learn` сохраняет новые пары вопрос-ответ в `knowledge/learned.md`.

## Структура базы знаний

```text
knowledge/
  aliases.yaml
  contacts.md
  payment.md
  delivery.md
  warranty.md
  firmware.md
  learned.md              # создаётся командой /learn
  lowrance/
    elite-fs.md
    hds-pro.md
    active-target.md
  sales/
    objections.md
    scripts.md
```

## Алиасы

`knowledge/aliases.yaml` хранит группы канонических терминов и разговорных вариантов. Например, запросы `9фс`, `fs9`, `элит 9`, `лоуренс фс 9` нормализуются и расширяются каноническим термином `Lowrance Elite FS 9`.

При поиске бот:

1. сохраняет исходный запрос для логов и `/search`;
2. приводит текст к lower-case;
3. заменяет `ё` на `е`;
4. удаляет лишнюю пунктуацию;
5. ищет прямые совпадения алиасов;
6. ищет fuzzy-совпадения по алиасам и заголовкам документов;
7. добавляет найденные канонические термины в запрос;
8. ранжирует фрагменты базы знаний.

## Команды Telegram

```text
/start            - приветствие
/status           - статус LLM, knowledge, aliases и SQLite
/reload           - перечитать Markdown-базу знаний и aliases.yaml
/stats            - статистика сообщений, найденных ответов, fallback и LLM
/learn            - интерактивное обучение: вопрос -> правильный ответ -> запись в learned.md
/search <текст>   - показать нормализацию, найденные алиасы и top 5 фрагментов
/aliases          - показать количество групп алиасов и первые 20 групп
```

Если `TELEGRAM_MANAGER_CHAT_ID` заполнен, команды администратора доступны только этому chat id. Если переменная пустая, команды доступны всем, что удобно для локального теста.

## Как работает /learn

1. Администратор отправляет `/learn`.
2. Бот отвечает: `Введите вопрос.`
3. Следующий текст сохраняется как вопрос.
4. Бот отвечает: `Введите правильный ответ.`
5. Следующий текст сохраняется в `knowledge/learned.md`.
6. Бот перечитывает knowledge и aliases.
7. Бот отвечает: `Готово, добавил в базу знаний.`

## Как бот отвечает

1. Пользователь задаёт вопрос.
2. Бот берёт последние 10 сообщений из SQLite, чтобы понимать уточнения вроде «а доставка?» или «а гарантия?».
3. По текущему вопросу и контексту последних сообщений ищутся top 3 релевантных фрагмента в `knowledge/*.md`.
4. Если фрагментов нет, бот отвечает fallback-фразой.
5. Если фрагменты есть и настроен LLM, бот отправляет только эти фрагменты, последние сообщения и вопрос клиента.
6. Если LLM-ключей нет, бот возвращает лучший найденный фрагмент без Markdown.

System prompt запрещает придумывать цены, наличие, сроки, характеристики и совместимость. Если информации недостаточно, LLM обязан вернуть fallback-фразу.

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

Без `DEEPSEEK_API_KEY` и `OPENAI_API_KEY` бот работает через улучшенный keyword/scoring matcher.

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

Минимум для Telegram MVP:

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
| `TELEGRAM_MANAGER_CHAT_ID` | Chat id администратора. Если пустой, admin-команды доступны всем. |
| `AVITO_CLIENT_ID` | Необязателен для Telegram MVP. |
| `AVITO_CLIENT_SECRET` | Необязателен для Telegram MVP. |
| `AVITO_USER_ID` | Необязателен для Telegram MVP. |

## Docker volumes

```text
./data:/app/data
./knowledge:/app/knowledge
```

SQLite сохраняется в `data/`, база знаний и aliases читаются из `knowledge/`. Запись в `knowledge/` нужна для команды `/learn`.

## Полезные команды

```bash
docker compose ps
docker compose logs -f
docker compose restart
docker compose down
```