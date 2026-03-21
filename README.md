# Browser Agent (Playwright + OpenAI tools)

Python 3.11+ проект: AI-агент для автономной автоматизации *видимого* браузера через Playwright (persistent context) и OpenAI API (tool/function calling).

## Возможности

- Принимает задачу текстом в терминале.
- Открывает реальный видимый Chromium (не headless) с persistent профилем: можно вручную залогиниться, агент продолжит в той же сессии.
- Работает автономно: планирует, делает шаги (navigate/click/type/wait), проверяет результат, делает retry или просит уточнение.
- В терминале видно логи действий + вызовы инструментов.
- В окне браузера видно, как агент кликает/печатает в реальном времени.
- Security layer: перед потенциально опасными действиями (оплата/удаление/отправка) спрашивает подтверждение.

## Установка

1. Создайте venv и поставьте зависимости:

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
pip install -r requirements-dev.txt
```

Если ранее уже ставили зависимости и видите ошибку вида `unexpected keyword argument 'proxies'`, переустановите pinned зависимости:

```sh
pip install -U --force-reinstall -r requirements-dev.txt
```

2. Установите браузер для Playwright:

```sh
python3 -m playwright install chromium
```

## Настройка OpenAI

Задайте переменные окружения:

```sh
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4-turbo"  # или аналог, который доступен в вашем аккаунте
export OPENAI_BASE_URL="https://ru-2.gateway.nekocode.app/alpha/v1"
```

Также можно положить эти значения в `.env` в корне проекта (файл будет автоматически подхвачен при запуске).

## Запуск

Интерактивно:

```sh
browser-agent
```

Или одной строкой:

```sh
browser-agent --task "Открой https://example.com и нажми More information"
```

По умолчанию persistent профиль хранится в `.browser_profile/` (можно сменить `--profile-dir`).

### Цвета и логи

- Все “внутренние” сообщения (логи, tool-calls, статус) печатаются тёмно‑серым, финальный `RESULT` — более светлым.
- Отключить ANSI-цвета: `--no-color` или env `NO_COLOR=1`.
- По умолчанию пишется файл логов `logs/run-<timestamp>.log` (можно задать `--log-file path.log`).

## Примеры задач

- `Открой https://example.com и нажми ссылку More information`
- `Открой почту, покажи список новых писем (без удаления/отправки)`
- `Перейди на сайт, закрой cookie popup и найди поле поиска`

## Важные ограничения

- CAPTCHA/2FA агент не решает.
- На некоторых сайтах антибот может блокировать автоматизацию.
- Чтобы “войти” в аккаунт, обычно нужно сделать это вручную в открытом persistent окне (агент продолжит дальше).

## Быстрый smoke

```sh
python3 -m ruff check .
python3 -m pytest -q
browser-agent --task "Открой https://example.com"
```
