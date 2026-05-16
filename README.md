# 🚗 Termin Monitor — Führerscheinstelle Gelsenkirchen

Telegram-бот для мониторинга записи на получение/расширение водительских прав.

## Запуск локально

```bash
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # заполнить токен и chat_id
python main.py
```

## Deploy на Fly.io

```bash
fly launch                  # только первый раз
fly secrets set TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... CHECK_INTERVAL=180
fly deploy
```

## Команды бота

| Команда     | Описание                            |
|-------------|-------------------------------------|
| `/start`    | Приветствие                         |
| `/check`    | Разовая проверка                    |
| `/monitor`  | Запустить автоматический мониторинг |
| `/stop`     | Остановить                          |
| `/status`   | Состояние бота                      |
| `/info`     | Как работает бот                    |

## Структура

```
├── main.py         — точка входа, автозапуск мониторинга
├── bot.py          — Telegram-бот, команды, UI
├── checker.py      — Playwright-автоматизация сайта
├── config.py       — конфигурация из .env
├── Dockerfile      — контейнер для Fly.io
├── fly.toml        — конфиг деплоя
└── requirements.txt
```
