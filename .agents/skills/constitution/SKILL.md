---
name: constitution
description: Create or amend CONSTITUTION.md — project-wide invariants and governance. Use when formalizing rules or amending principles. Never for feature implementation.
---

# Constitution

## TL;DR

Пишем только `CONSTITUTION.md`. Собираем инварианты из `AGENTS.md`, классифицируем
(MUST / SHOULD / MAY), присваиваем SemVer (MAJOR — удалён MUST, MINOR — новый
MUST, PATCH — формулировка), пишем по шаблону, отчитываемся: версия + rationale +
TODO + предлагаемое сообщение коммита.

**Не загружать, если:**
- Задача — реализовать фичу/фикс — это `implementation-cycle`.
- Правится README/AGENTS, не CONSTITUTION — это `docs:`-коммит без этого скила.
- Нужно ревью существующего CONSTITUTION — это `code-review` (раздел «Ревью
  документации»).

**Маршруты:** входной источник — `AGENTS.md` (инварианты) и `CONSTITUTION.md`
(если существует). Выходной артефакт — `CONSTITUTION.md`. Валидация — через
`code-review` по чек-листу документации.

**Источники правды:** `AGENTS.md` (инварианты), `settings.py` (дефолты,
имена env), `CONSTITUTION.md` (предыдущая версия).

**Версия скила:** 1.1.0 | **Обновлён:** 2026-10-14
- 1.1.0 — TL;DR, anti-triggers, карта маршрутов, формат вывода, частые ошибки,
  источники правды, one-liners.
- 1.0.0 — базовый шаблон и процедура амендмента.

## User Input

```text
$ARGUMENTS
```

Consider the input before proceeding.

## Scope Guard

Only write `CONSTITUTION.md`. Do NOT touch source code, tests, or feature artifacts.
If the input mixes constitution content with feature work — extract feature work into a
`## Next Actions` section, but do NOT execute it.

## Outline

1. Read `CONSTITUTION.md` if it exists. Read `AGENTS.md` for project invariants.

2. Extract governance principles. Classify:
   - Non-negotiable invariants → MUST / MUST NOT
   - Operational rules → SHOULD / SHOULD NOT
   - Recommendations → MAY

3. Assign version:
   - No file exists → `1.0.0`
   - Else SemVer bump: MAJOR (removed MUST) / MINOR (new MUST) / PATCH (wording).

4. Draft using the template below.

5. Validate:
   - No `[PLACEHOLDER]` tokens remain
   - Every article has a name + MUST/SHOULD statements
   - Dates are ISO YYYY-MM-DD

6. Write `CONSTITUTION.md`.

7. Report: version, bump rationale, TODO items, suggested commit message.

## Template

```markdown
# Project Constitution — VkAutoLiker

**Version**: X.Y.Z | **Ratified**: YYYY-MM-DD | **Last Amended**: YYYY-MM-DD

## Preamble

<1-2 sentences: what this governs, why it exists>

## Article I: Account Safety (MUST)

All automated actions MUST imitate human behavior.

- All delays MUST use `random.uniform(min, max)`. Fixed `time.sleep(...)` forbidden,
  except the few documented fixed delays (see AGENTS invariant 1).
- Daily and per-session limits MUST be enforced at two levels.
- Captcha MUST abort the session (`max_captcha_streak`), never bypassed.

**Rationale**: Violations risk permanent account ban.

## Article II: API Boundary (MUST)

All VK API calls MUST go through `VKApiClient.call()`.

- Direct `requests.*` in feature code forbidden.
- Rate limit (~3 req/sec) and error handling (codes 6, 14) non-negotiable.

**Rationale**: Centralizes throttling, retries, error classification.

## Article III: Data Integrity (MUST)

Every post MUST be deduplicated by `(owner_id, item_id)`.

- A post is marked processed only on success (LIKED/ALREADY_LIKED); failed attempts (CAPTCHA/FAILED/Exception) are NOT marked — they are retried in the next session.
- `owner_id` for groups MUST be negative.

**Rationale**: Prevents repeated processing.

## Article IV: Testing (SHOULD)

Tests MUST NOT hit real network or real browser unless explicitly marked.

- `@pytest.mark.browser` for Chrome-dependent tests.
- `@pytest.mark.live` for real VK API.

**Rationale**: Unit tests must run without side effects.

## Article V: Configuration & Secrets (MUST)

- Secrets MUST be loaded from env vars (`VK_SERVICE_TOKEN`, `VK_LLM_API_KEY`), not from files in git.
- Test code MUST use placeholder values (`"test_token"`).

**Rationale**: Token leak compromises the account.

## Amendment Procedure

- Amendments require an explicit `/skill:constitution` run.
- Version bumps follow SemVer.
- Compliance verified by `code-review` (раздел «Ревью документации»).
```

Adapt article set to actual invariants from AGENTS.md.

## Формат вывода

После записи файла — отчёт ровно в таком виде:

```
## Отчёт
- **Версия:** X.Y.Z (bump: MAJOR|MINOR|PATCH)
- **Rationale:** <почему такой bump>
- **Файл:** CONSTITUTION.md
- **TODO (не выполнено):** <список или «нет»>
- **Предлагаемое сообщение коммита:** docs: <...> (НЕ коммитить без разрешения)
```

## Частые ошибки агента

- **Писать код/тесты по ходу амендмента.** Scope Guard запрещает — только
  `CONSTITUTION.md`.
- **Оставлять `[PLACEHOLDER]` / `<...>` в готовом файле.** Проверять grep-ом.
- **Присваивать MINOR при удалении MUST.** Удаление — всегда MAJOR.
- **Копировать инварианты из AGENTS дословно.** Конституция — про governance,
  не про детали реализации.
- **Выходить за пределы версии.** Если меняется только формулировка — PATCH,
  не MINOR.

## Примеры из истории

- `f7dcc1d docs: Конституция 1.1.0 — рабочие соглашения и актуализация
  инвариантов` — 1.0.0 → 1.1.0, MINOR bump (новая MUST-статья: рабочие
  соглашения).
- Формулировочные правки (без изменения смысла) — PATCH.

## Проверка

```bash
grep -nE "PLACEHOLDER|<[^>]+>" CONSTITUTION.md      # не должно быть
grep -n "^\*\*Version\*\*" CONSTITUTION.md         # SemVer
grep -nE "\*\*Ratified\*\*.*[0-9]{4}-[0-9]{2}-[0-9]{2}" CONSTITUTION.md
```
