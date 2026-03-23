# Browser Agent (Playwright + OpenAI tools)

Python 3.11+ проект: AI-агент для автономной автоматизации *видимого* браузера через Playwright (persistent context) и OpenAI API (tool/function calling).

## Возможности

- Принимает задачу текстом в терминале.
- Открывает реальный видимый Chromium (не headless) с persistent профилем: можно вручную залогиниться, агент продолжит в той же сессии.
- Работает автономно: планирует, делает шаги (navigate/click/type/wait), проверяет результат, делает retry или просит уточнение.
- В терминале — диалог и краткие статусы; детальные логи действий/запросов пишутся в файлы.
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
# Optional. If not set, the official OpenAI endpoint is used.
# export OPENAI_BASE_URL="https://api.openai.com/v1"
#
# Example gateway (OpenAI-compatible):
# export OPENAI_BASE_URL="https://ru-2.gateway.nekocode.app/alpha/v1"
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

### Параметры CLI

Посмотреть актуальную справку:

```sh
browser-agent --help
```

Доступные параметры запуска:
- `--task "<текст>"` — выполнить одну задачу сразу после старта (после этого всё равно останется REPL и можно вводить новые команды).
- `--profile-dir <path>` — директория persistent профиля Chromium (сессии/куки/логины сохраняются между запусками).
- `--slowmo-ms <int>` — задержка Playwright (в мс) между действиями, полезно для дебага.
- `--fixed-viewport` — включить фиксированную эмуляцию viewport (может приводить к “обрезанию” в маленьком окне).
- `--no-maximize` — не разворачивать окно при старте.
- `--window-width <int>` — ширина окна (используется если задан `--no-maximize`).
- `--window-height <int>` — высота окна (используется если задан `--no-maximize`).
- `--viewport-width <int>` — ширина viewport (используется только с `--fixed-viewport`).
- `--viewport-height <int>` — высота viewport (используется только с `--fixed-viewport`).
- `--max-steps <int>` — лимит шагов агента на одну задачу.
- `--max-seconds <int>` — лимит времени (в секундах) на одну задачу.
- `--model <str>` — переопределить `OPENAI_MODEL` только для этого запуска.
- `--no-subagents` — отключить под‑агентов (NavigationAgent/DOMAgent).
- `--verbose` — печатать больше логов в терминал. По умолчанию подробности идут только в файл логов.
- `--no-color` — отключить ANSI‑цвета в терминале.
- `--log-file <path>` — путь к файлу логов (по умолчанию `logs/run-<timestamp>.log`).

Команды внутри REPL:
- `:help` — короткая помощь.
- `:exit` (или `exit`, `quit`) — выйти.

### Base URL (OpenAI vs gateway)

- По умолчанию используется официальный OpenAI endpoint: `https://api.openai.com/v1`.
- Чтобы использовать OpenAI-compatible gateway, задайте `OPENAI_BASE_URL`. Можно указывать как с `/v1`, так и без него — приложение автоматически добавит `/v1`, если нужно.

### Размер окна / адаптивность

По умолчанию мы запускаем Chromium так, чтобы **верстка соответствовала реальному размеру окна** (без фиксированной эмуляции viewport) и окно стартует maximized. Это предотвращает ситуацию “маленькое окно, но сайт думает что он wide/desktop и всё обрезается”.

Полезные флаги:
- `--no-maximize` + `--window-width/--window-height` — задать размер окна.
- `--fixed-viewport` + `--viewport-width/--viewport-height` — включить фиксированный viewport (обычно не нужно).

После выполнения задачи приложение **не закрывается**: браузер остаётся открытым, и можно вводить следующую команду в том же терминале. Выйти: `:exit`.

### Цвета и логи

- В терминале по умолчанию нет “шумных” логов (HTTP/tool и т.п.) — только общение и краткие статусы/индикатор работы.
- По умолчанию логи пишутся в папку сессии `logs/<дд.мм.гггг - ч:м:с>/`:
- `requests.log` — HTTP запросы + метаданные OpenAI запросов.
- `agent.log` — инструменты/действия/под‑агенты.
- `chat.log` — переписка (пользователь/ассистент/статусы).
- Можно принудительно писать всё в один файл: `--log-file path.log`.
- Базовую папку для сессий можно сменить: `--log-dir some_dir`.
- Отключить ANSI-цвета: `--no-color` или env `NO_COLOR=1`.
- Для вывода логов в терминал используйте `--verbose`.

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
