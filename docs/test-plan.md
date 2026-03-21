# Test Plan

## Source
- Task: AI‑агент для автономной автоматизации браузера (Playwright + OpenAI tools).
- Plan file: `docs/plans.md`
- Status file: `docs/status.md`
- Repo context: `/home/fndpc/dev/browser-automation`
- Last updated: 2026-03-21

## Validation Scope
- In scope:
  - CLI ввод задачи и вывод логов;
  - Playwright persistent context + видимый Chromium;
  - Tools: навигация, клик, ввод, ожидание, snapshot;
  - DOM compression и управление контекстом (1–2 snapshot + step‑log);
  - sub‑агенты (Navigation/DOM) с JSON контрактами;
  - security‑layer (подтверждение опасных действий).
- Out of scope:
  - Полная “человеческая” устойчивость к любому сайту/антиботу/captcha.
  - Автоматическое решение CAPTCHA / 2FA.

## Environment / Fixtures
- Data fixtures:
  - Тестовые локальные HTML страницы (если добавим) для детерминированных e2e.
- External dependencies:
  - OpenAI API (ключ `OPENAI_API_KEY`).
  - Playwright browsers (`python -m playwright install chromium`).
- Setup assumptions:
  - GUI окружение.
  - Переменные окружения: `OPENAI_API_KEY`, опционально `OPENAI_MODEL`.

## Test Levels

### Unit
- DOM compression: размер/ограничения/детерминизм.
- Tool dispatch: валидация входных параметров, обработка исключений.
- Security: confirm flow (y/N) и “блокировка” выполнения без подтверждения.

### Integration
- BrowserEngine с реальным Playwright:
  - создание persistent context;
  - открытие страницы, получение snapshot;
  - обработка popup/new page.
- OpenAI tool‑calling:
  - корректный parse вызова tool и возврат результата.

### End-to-End / Smoke
- Ручной smoke (видимый браузер):
  - `Открой https://example.com`
  - `Нажми ссылку "More information"`
  - `Найди поле поиска (на любом сайте) и введи текст`
- Security smoke:
  - Любая задача, содержащая “удали/оплати/отправь” должна вызывать подтверждение.

## Negative / Edge Cases
- Нет `OPENAI_API_KEY` → понятная ошибка и выход.
- Модель недоступна/ошибка API → retry с backoff и диагностикой.
- Таймаут ожидания элемента → альтернативный план/уточнение у пользователя.
- Неожиданный popup/cookie banner → попытка закрыть и продолжить.
- Зацикливание (повтор шагов) → детект и stop с объяснением.

## Acceptance Gates
- [ ] `python -m ruff check .`
- [ ] `python -m ruff format . --check`
- [ ] `python -m pytest -q`
- [ ] `python -m mypy .` (если включим)
- [ ] Manual smoke: видимый Chromium + выполнение 2–3 задач.

## Release / Demo Readiness
- [ ] Core scenario работает end‑to‑end (от ввода задачи до результата).
- [ ] Логи tool‑calls читаемы и содержат args+результаты.
- [ ] Persistent профайл сохраняется и повторно используется.
- [ ] Security подтверждения не обходятся.
- [ ] README воспроизводим на чистом venv.

## Command Matrix
```sh
# setup (manual)
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
pip install -r requirements-dev.txt
python3 -m playwright install chromium

# checks
python3 -m ruff check .
python3 -m ruff format . --check
python3 -m pytest -q
python3 -m mypy .  # optional
```

## Open Risks
- Стабильность element‑matching по “описанию” зависит от качества snapshot и промптов.
- Видимый браузер может не запускаться в headless окружениях (CI/контейнер без X/Wayland).

## Deferred Coverage
- Автоматизированные e2e тесты с реальными сайтами (нестабильно/зависит от внешних сервисов).
- Полноценный tracer/recording (HAR/video) — можно добавить позже.
