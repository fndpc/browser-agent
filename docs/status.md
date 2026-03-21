# Status

## Snapshot
- Current phase: M2 (Playwright browser engine)
- Plan file: `docs/plans.md`
- Status: yellow
- Last updated: 2026-03-21

## Done
- Инициализированы план/статус/тест‑план файлы.
- M1: создан scaffold проекта: `pyproject.toml`, `src/` layout, CLI entrypoint, базовые юнит‑тесты.

## In Progress
- Реализация M2-M7 в коде (Playwright engine + tools + snapshots + subagents + security), требуется валидация после установки зависимостей.
  - Терминал: серые “внутренние” логи + светлый финальный RESULT, файл логов `logs/run-*.log`.

## Next
- M2: Playwright browser engine (visible + persistent).

## Decisions Made
- Используем `src/` layout и `pyproject.toml` (современный packaging).
- Ввод задачи через CLI аргумент `--task` или интерактивно из stdin.
- Persistent context профиля хранится локально в `.browser_profile/` внутри репо (путь конфигурируемый).

## Assumptions In Force
- Python 3.11+ доступен локально.
- Окружение поддерживает GUI для видимого Chromium.

## Commands
```sh
# setup
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
pip install -r requirements-dev.txt
python3 -m playwright install chromium

# если были несовместимые версии (например ошибка про proxies)
pip install -U --force-reinstall -r requirements-dev.txt

# checks
python3 -m ruff check .
python3 -m ruff format . --check
python3 -m pytest -q
```

## Current Blockers
- None

## Audit Log
| Date | Milestone | Files | Commands | Result | Next |
| --- | --- | --- | --- | --- | --- |
| 2026-03-21 | planning | `docs/plans.md`, `docs/status.md`, `docs/test-plan.md` | - | pass | M1 |
| 2026-03-21 | M1 | `pyproject.toml`, `src/browser_agent/*`, `tests/*`, `README.md` | `python3 -m compileall -q src` | pass | M2 |

## Smoke / Demo Checklist
- [ ] CLI стартует и принимает задачу.
- [ ] Открывается видимый Chromium (не headless) с persistent context.
- [ ] В терминале видны tool‑calls и шаги агента.
- [ ] Агент может открыть `https://example.com` и кликнуть ссылку по описанию.
- [ ] Агент спрашивает подтверждение перед “опасными” действиями.
