# ExpertBoat AI

AI-продавец для магазина морской электроники Expert Boat. MVP работает через официальный API Авито и Telegram-бота менеджера, хранит историю в SQLite и запускается в Docker Compose.

## Что внутри

- Python 3.12
- Docker Compose
- SQLite в `data/expertboat.db`
- официальный Avito API OAuth + Messenger API
- Telegram manager bot на `python-telegram-bot`
- Markdown-база знаний в `knowledge/`
- OpenAI SDK

## Быстрый запуск после git clone

Проект поднимается без ручных правок конфигурации:

```bash
docker compose up -d --build
```

Если реальные секреты ещё не заданы, контейнер стартует в безопасном режиме ожидания и создаёт SQLite-таблицы. Для рабочей интеграции заполните `.env` реальными значениями и перезапустите сервис.

## Установка на Ubuntu 24.04 VPS

1. Подключитесь к серверу:

```bash
ssh root@SERVER_IP
```

2. Установите Git, если его ещё нет:

```bash
apt-get update && apt-get install -y git
```

3. Склонируйте проект:

```bash
git clone <REPOSITORY_URL> expertboat-ai
cd expertboat-ai
```

4. Запустите установщик:

```bash
sudo ./install.sh
```

Скрипт установит Docker Engine и Docker Compose plugin, создаст папки `data/` и `knowledge/`, создаст `.env` из `.env.example`, соберёт и запустит контейнер.

5. Заполните `.env` реальными ключами:

```bash
nano .env
```

6. Перезапустите сервис:

```bash
docker compose up -d --build
```

## Обновление на VPS

```bash
./update.sh
```

Скрипт выполнит `git pull --ff-only`, пересоберёт контейнер и удалит неиспользуемые Docker-образы.

## Команды эксплуатации

Логи:

```bash
docker compose logs -f
```

Статус:

```bash
docker compose ps
```

Остановка:

```bash
docker compose down
```

Перезапуск:

```bash
docker compose restart
```

## Обязательные переменные `.env`

Для полноценной работы заполните:

```text
OPENAI_API_KEY
AVITO_CLIENT_ID
AVITO_CLIENT_SECRET
AVITO_USER_ID
TELEGRAM_BOT_TOKEN
TELEGRAM_MANAGER_CHAT_ID
```

Остальные переменные можно оставить по умолчанию:

```text
APP_ENV=production
LOG_LEVEL=INFO
DATABASE_PATH=data/expertboat.db
KNOWLEDGE_DIR=knowledge
OPENAI_MODEL=gpt-4.1-mini
AVITO_API_BASE_URL=https://api.avito.ru
AVITO_POLL_INTERVAL_SECONDS=5
```

## Docker Compose и тома

`docker-compose.yml` использует bind mounts:

```text
./data:/app/data
./knowledge:/app/knowledge:ro
```

Это означает:

- SQLite база сохраняется на хосте в `data/` и переживает пересборку контейнера.
- Markdown-база знаний читается из `knowledge/` без пересборки образа.
- Секреты берутся из `.env`, если он создан. Без `.env` используются безопасные placeholder-значения, и приложение стартует в режиме ожидания.

## Цикл обработки сообщений

1. Приложение каждые `AVITO_POLL_INTERVAL_SECONDS` секунд проверяет новые входящие сообщения Авито.
2. Новое сообщение сохраняется в SQLite.
3. Менеджеру отправляется Telegram-уведомление с inline-кнопками `Ответить` и `Игнорировать`.
4. После нажатия `Ответить` следующее сообщение менеджера отправляется в соответствующий чат Авито.
5. Успешный ответ сохраняется в SQLite.
6. Ошибка отправки приходит менеджеру в Telegram.
