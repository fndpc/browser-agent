# Plans

## Source
- Task: Python‑проект: AI‑агент для автономной автоматизации видимого браузера (Playwright persistent context + OpenAI tools/function calling).
- Canonical input: запрос пользователя в чате от 2026-03-21.
- Repo context: `/home/fndpc/dev/browser-automation` (пустой репозиторий, создаём проект с нуля).
- Last updated: 2026-03-21

## Assumptions
- Проект запускается локально на машине, где можно открыть видимый Chromium (не headless).
- Пользователь сам обеспечивает аккаунты/логины (почта и т.п.) и при необходимости вручную логинится в открытом persistent профиле.
- Доступ к OpenAI API и ключ `OPENAI_API_KEY` есть; модель задаётся через env (`OPENAI_MODEL`) и может отличаться от `gpt-4-turbo` в зависимости от аккаунта.
- Для поиска элементов по “описанию” используется LLM + эвристики по интерактивным элементам (role/name/label/placeholder/text), без хардкода селекторов/маршрутов.

## Validation Assumptions
- Репозиторий новый, поэтому вводим стандартные команды:
  - `python -m pytest`
  - `python -m ruff check .`
  - `python -m ruff format .`
  - `python -m mypy .` (если успеем/нужно)

## Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M1 | Scaffold проекта и CLI | - | [x] |
| M2 | Playwright browser engine (visible + persistent) | M1 | [~] |
| M3 | DOM snapshot + сжатие контекста | M2 | [~] |
| M4 | OpenAI tool-calling runtime + главный агент | M1, M3 | [~] |
| M5 | Sub‑agents: Navigation + DOM | M4 | [~] |
| M6 | Ошибки, retries, “ask for clarification” | M4, M5 | [~] |
| M7 | Security layer: подтверждения | M4 | [~] |
| M8 | Документация + smoke сценарии | M1..M7 | [~] |

## M1. Scaffold проекта и CLI `[x]`
### Goal
- Репозиторий превращён в устанавливаемый Python‑пакет с понятной точкой входа и минимальными дев‑инструментами.

### Tasks
- [ ] Создать структуру проекта (`src/`, `pyproject.toml`, `README.md`, `.gitignore`).
- [ ] Реализовать CLI (например `python -m browser_agent` или `browser-agent`), который:
  - читает задачу из stdin;
  - стартует браузер;
  - запускает агента.
- [ ] Добавить базовый логгер (уровни, формат, трейс tool‑calls).

### Definition of Done
- Проект устанавливается в venv и команда запуска выводит приглашение на ввод задачи.

### Validation
```sh
python -V
python -m ruff --version
python -m ruff check .
```

### Known Risks
- Нужна установка Playwright browsers (скачивание) — может потребовать сетевого доступа/прав.

### Stop-and-Fix Rule
- Если проект не запускается из чистого venv, фикс до перехода дальше.

## M2. Playwright browser engine (visible + persistent) `[ ]`
### Goal
- Есть “движок браузера” с устойчивым persistent context и удобными методами навигации/клика/ввода/ожиданий/поп‑апов.

### Tasks
- [ ] Подключить `playwright` и реализовать класс `BrowserEngine`:
  - запуск `chromium.launch_persistent_context(...)` с `headless=False`;
  - один активный `page`, авто‑создание/перехват `popup`/`new_page`;
  - методы tool‑API: `navigate_to_url`, `wait_for`, `click_by_locator`, `type_into`.
- [ ] Реализовать “умный” клик/ввод на основе `get_by_role`, `get_by_label`, `get_by_placeholder`, `get_by_text`, без прямых CSS селекторов.
- [ ] Включить “визуальность” (окно видно, замедление при необходимости через `slow_mo` опционально).

### Definition of Done
- Можно вручную открыть сайт, залогиниться, после чего агент продолжает в той же сессии (папка профиля сохраняется).

### Validation
```sh
python -m browser_agent --task "Открой https://example.com"
```

### Known Risks
- Различия платформ/дисплея (особенно в контейнере) могут мешать `headless=False`.

### Stop-and-Fix Rule
- Если не получается стабильно получить активную страницу/поп‑ап, фиксить до M3.

## M3. DOM snapshot + сжатие контекста `[ ]`
### Goal
- Есть “snapshot” страницы без передачи полного HTML: только видимый текст + интерактивные элементы и ключевые атрибуты.

### Tasks
- [ ] Реализовать `get_current_page_snapshot()`:
  - сбор интерактивных элементов (button/link/input/textarea/select/role=...);
  - ограничение размера (топ‑N, дедуп, обрезка текста);
  - включить viewport‑видимость (грубая фильтрация).
- [ ] Реализовать “память” агента: хранить 1–2 последних snapshot + краткий step‑log.

### Definition of Done
- Снапшот стабилен, детерминирован, ограничен по размеру, и полезен для выбора действий LLM.

### Validation
```sh
python -m pytest -q
```

### Known Risks
- Слишком агрессивная компрессия ухудшит поиск элементов; нужна балансировка.

### Stop-and-Fix Rule
- Если snap слишком большой/пустой/не помогает находить элементы — корректировать до M4.

## M4. OpenAI tool-calling runtime + главный агент `[ ]`
### Goal
- Главный агент принимает задачу, строит план, вызывает инструменты, логирует, и завершает/просит уточнение.

### Tasks
- [ ] Добавить клиент OpenAI (Python SDK) и слой `ToolDispatcher`.
- [ ] Описать tools (JSON schema) и маппинг в методы `BrowserEngine`.
- [ ] Реализовать цикл: план -> действие -> проверка -> следующий шаг:
  - ограничение по шагам/времени;
  - request‑for‑clarification протокол;
  - логирование каждого вызова tool + результата.

### Definition of Done
- На простых задачах (“открой сайт”, “найди кнопку”, “заполни поле”) агент делает шаги автономно.

### Validation
```sh
OPENAI_API_KEY=... python -m browser_agent --task "Открой https://example.com и нажми More information"
```

### Known Risks
- Разные версии OpenAI SDK и модели: нужно сделать конфиг и graceful ошибки.

### Stop-and-Fix Rule
- Если tool‑calling нестабилен/ломает формат — фиксить до добавления sub‑агентов.

## M5. Sub‑agents: Navigation + DOM `[ ]`
### Goal
- Главный агент координирует 2 под‑агента:
  - Navigation‑agent (стратегия переходов/страницы/следующий URL);
  - DOM‑agent (интерпретация snapshot и выбор целевого элемента/действия).

### Tasks
- [ ] Специфицировать строгие JSON‑контракты ответов sub‑агентов.
- [ ] Реализовать вызовы sub‑агентов как отдельные LLM вызовы с меньшим контекстом.
- [ ] Главный агент объединяет рекомендации и выбирает tool‑вызов.

### Definition of Done
- На странице с несколькими интерактивными элементами DOM‑агент выбирает корректное действие по описанию.

### Validation
```sh
OPENAI_API_KEY=... python -m browser_agent --task "Открой страницу входа и найди поле логина"
```

### Known Risks
- Стоимость/латентность: 2–3 LLM вызова на шаг. Нужны лимиты/кэш/сокращение.

### Stop-and-Fix Rule
- Если sub‑агенты ухудшают качество, сделать фоллбек на single‑agent режим.

## M6. Ошибки, retries, “ask for clarification” `[ ]`
### Goal
- Агент устойчив к типовым ошибкам: таймауты, неверный элемент, навигация не случилась, неожиданный поп‑ап.

### Tasks
- [ ] После каждого шага: проверка `url`, наличие ожидаемых изменений, лог ошибок.
- [ ] Retry‑стратегии: подождать/переснять snapshot/попробовать альтернативный locator.
- [ ] Чёткий протокол запроса уточнения у пользователя (в терминале).

### Definition of Done
- При сбое агент либо сам восстанавливается, либо задаёт конкретный вопрос.

### Validation
```sh
OPENAI_API_KEY=... python -m browser_agent --task "Перейди на сайт с cookie pop-up и закрой его"
```

### Known Risks
- Сложно универсально “проверять успех”, нужно ограничиться наблюдаемыми сигналами.

### Stop-and-Fix Rule
- Если агент зацикливается, добавить детект и останов с диагностикой.

## M7. Security layer: подтверждения `[ ]`
### Goal
- Перед потенциально деструктивными действиями агент обязан спросить подтверждение.

### Tasks
- [ ] Tool `confirm_destructive_action(action: str)`:
  - синхронный prompt в терминале `y/N`;
  - журналировать ответ.
- [ ] Политика: какие действия считаются деструктивными (оплата, удаление, отправка письма, изменение данных).
- [ ] Интеграция в главный агент (модель должна уметь “пометить” действие как risky).

### Definition of Done
- Без явного подтверждения пользовательских операций типа “удалить/оплатить/отправить” агент не продолжает.

### Validation
```sh
OPENAI_API_KEY=... python -m browser_agent --task "Удали первое письмо в папке Входящие"
```

### Known Risks
- Классификация риска может ошибаться: нужен conservative‑режим (лучше спросить лишний раз).

### Stop-and-Fix Rule
- Если обнаружится путь обхода подтверждения — исправить немедленно.

## M8. Документация + smoke сценарии `[ ]`
### Goal
- README с установкой/запуском и набором сценариев для ручного теста.

### Tasks
- [ ] Описать шаги установки зависимостей (`pip`, `playwright install`).
- [ ] Примеры задач, ограничения и советы (ручной логин, persistent profile path).
- [ ] Мини‑smoke чеклист в `docs/test-plan.md` и `docs/status.md`.

### Definition of Done
- Пользователь может по README развернуть и запустить демо за 5–10 минут.

### Validation
```sh
python -m browser_agent --help
```

### Known Risks
- В окружении без GUI окно браузера не откроется; надо явно указать.

### Stop-and-Fix Rule
- Если README не воспроизводится на чистой машине, фиксить документацию.
