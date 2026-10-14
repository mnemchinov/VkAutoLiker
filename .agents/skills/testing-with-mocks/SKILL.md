---
name: testing-with-mocks
description: Перед написанием или правкой тестов.
---

# Тестирование с моками VkAutoLiker

## TL;DR

Один класс тестов на модуль, файл `tests/test_<module>.py`. Не ходим в сеть и не
запускаем Chrome (кроме `-m browser` / `-m live`). Мокаем сервисы через
`MagicMock`, HTTP/sleep — через `@patch`. БД — только `tmp_path`. Токены —
`"test_token"`. Лог-вывод проверяем через `caplog` и **реальный** логгер
(`mock_logger`), не через `MagicMock`. Прогон: `pytest -m "not browser and not
live"`.

**Не загружать, если:**
- Задача — реализовать код без тестов (это `implementation-cycle`, который сам
  загрузит `testing-with-mocks` при необходимости).
- Задача — прогнать существующие тесты, а не писать/править (это `pytest` напрямую).
- Правка только в `conftest.py` без новых тестов — минимальный контекст, скил
  не обязателен.

**Маршруты:** при правке кода, затрагивающей тесты, — `implementation-cycle`.
При появлении нового класса — `oop-design`. При ревью тестов — `code-review`.

**Источники правды:** `pytest --collect-only -q` (список тестов), `pytest --cov`
(покрытие), `tests/conftest.py` (фикстуры), `settings.py` (дефолты для
`mock_config_data`).

**Версия:** 1.1.0 | **Обновлён:** 2026-10-14
- 1.1.0 — TL;DR, anti-triggers, карта маршрутов, формат вывода, частые ошибки,
  источники правды, one-liners (без устаревших счётчиков).
- 1.0.0 — базовые практики и таблица тестов.

## Когда загружать

- Написание новых тестов
- Правка существующих тестов
- Добавление тестового покрытия для нового модуля
- Правка кода, затрагивающая тесты (обновление моков, ассертов)

## Структура тестов

Один класс тестов на модуль. Файлы — `tests/test_<module>.py`:

| Класс | Файл | Что тестирует |
|---|---|---|
| `TestSettings`, `TestEnvVars`, `TestValidation`, `TestGetSettings` | `test_settings.py` | Env vars, дефолты, валидация, SecretStr, get_settings |
| `TestVKApiClient` | `test_vk_api_client.py` | Rate-limit, ретраи, error 6/14, сетевые ошибки |
| `TestVkApiSearchService` | `test_vk_api_search_service.py` | newsfeed.search, wall.get, friends.get, groups.get, resolveScreenName |
| `TestDateFilter`, `TestEmptyTextFilter`, `TestStopWordsFilter`, `TestFilterChain` | `test_post_filter.py` | days_back, пустой текст, стоп-слова, композит |
| `TestLLMTopicFilter`, `TestLLMFilterStage` | `test_stage_llm_filter.py` | LLM-фильтрация: мок litellm, fallback, stage |
| `TestCollectStage`, `TestDedupStage`, `TestPipeline` | `test_stage_collect.py`, `test_stage_dedup.py`, `test_pipeline.py` | сбор (приоритет, early-exit, режимы), дедупликация, конвейер |
| `TestRun`, `TestPipelineComposition`, `TestClose` | `test_liker.py` | цикл лайков (лимит, паузы, стоп, зомби), состав pipeline, close |
| `TestDatabase`, `TestPostsRepository`, `TestSessionsRepository`, `TestClosedWallsRepository`, `TestMigrations` | `test_database.py`, `test_posts_repository.py`, `test_sessions_repository.py`, `test_closed_walls_repository.py`, `test_migrations.py` | Database, репозитории, миграции (INSERT OR REPLACE, is_processed, сессии + зомби, closed-walls кэш) |
| `TestCommands`, `TestVkBot`, `TestStopFlag`, `TestFileLock`, `TestMain` | `test_commands.py`, `test_vk_bot.py`, `test_stop_flag.py`, `test_file_lock.py`, `test_main.py` | команды, бот (клавиатура, ack), стоп-флаг, lock, CLI-ветки |
| `TestBrowserLikesMock` | `test_browser_likes.py` | Селекторы, клик, верификация (на моках) |
| `TestBrowserLikesFixture` | `test_browser_fixture.py` | DOM-селекторы на реальном Chrome + фикстур-страница (marker browser) |
| `TestVKBrowserIsLoggedIn`, `TestVKBrowserClose`, `TestVKBrowserCleanup` | `test_vk_browser.py` | remixsid cookie, сетевой ретрай, close, cleanup |
| `TestE2E` | `test_e2e.py` | e2e на реальном посте (marker live, skip по умолчанию) |

> Таблица поддерживается вручную. **Сверка:** `pytest --collect-only -q`.
> При добавлении/удалении тест-класса — обновлять таблицу.

## Моки вместо сети и браузера

### Базовый принцип

Тесты **не ходят в интернет** и **не запускают Chrome** (кроме `-m browser`/`-m live`).

### MagicMock для сервисов

```python
from unittest.mock import MagicMock, patch

# Для AutoLiker: создаём реальный объект, подменяем зависимости
liker = AutoLiker(mock_config, mock_logger)
liker._pipeline = MagicMock()
liker._browser = MagicMock()
liker._likes_service = MagicMock()
liker._sessions_repo = MagicMock()
liker._posts_repo = MagicMock()
```

### patch для HTTP и sleep

```python
@patch("api_client.vk_api_client.requests.get")
@patch("api_client.vk_api_client.time.sleep")
def test_something(mock_sleep, mock_get):
    mock_get.return_value.json.return_value = {"response": {...}}
    # mock_sleep — тесты не спят
```

```python
@patch("browser.vk_browser.time.sleep")
def test_browser_method(mock_sleep):
    # браузерные задержки не тормозят тесты
```

## Фикстуры из conftest.py

**Переиспользовать, не дублировать.** Фикстуры в `tests/conftest.py`:

| Фикстура | Назначение |
|---|---|
| `_clean_vk_env` | autouse: чистит `VK_*` из `os.environ` перед каждым тестом — `litellm` грузит `.env` при импорте, тесты не должны зависеть от его содержимого |
| `mock_config_data` | Словарь с конфигурацией (Python dict) |
| `mock_config` | `Settings` instance, готовый к использованию |
| `mock_logger` | **Реальный** логгер (не `MagicMock`) — проверка лог-вывода через `caplog` |
| `mock_driver` | `MagicMock` Selenium WebDriver |
| `tmp_db_path` | Путь к временной SQLite-БД (через `tmp_path`) |
| `http_fixture_server` | Локальный `http.server` на `tests/fixtures/` |

## Маркеры pytest

Объявлены в `pytest.ini`:

- `@pytest.mark.browser` — тесты, требующие реальный Chrome (headless против фикстуры)
- `@pytest.mark.live` — e2e-тесты на реальном посте VK (запускаются только вручную после `login`)

**Дефолтный прогон:**

```bash
pytest -m "not browser and not live"
```

## Практики

### База данных

Все пути к БД → `tmp_path` (pytest fixture). Реальный `vk_autoliker.db` **не трогать**.

```python
def test_something(tmp_db_path):
    from database import Database
    from settings import Settings

    config = Settings(db_path=tmp_db_path, service_token="test_token")
    db = Database(config)
```

### Токен

В тестах — `"test_token"`, **никогда** реальный токен.

### Приватные методы

Доступ к приватным методам допустим: `svc._find_like_button(...)`,
`VkApiSearchService._parse_newsfeed_item(...)` (как `staticmethod`).

### HTML-фикстура

`tests/fixtures/vk_post.html` повторяет разметку кнопки лайка. **При изменении
DOM-селекторов — обновлять фикстуру** и прогонять `pytest -m browser`.

### Логи — caplog

`mock_logger` — реальный логгер, а не `MagicMock`: проверять лог-вывод —
поиск строки в `caplog.text`, а не `mock_logger.info.assert_called_with(...)`
(второе никогда не проходит). Проверяемые строки логов — на русском.

### Реальный инцидент → регрессионный тест

Каждый реальный инцидент (пробой фильтра, краш, ложный лог) закрепляется
тестом на точных данных инцидента (например, текст поста-пробоя).

### Импорты

Тесты используют плоские импорты (`from api_client import ...`), как и `src/`.
Путь в `sys.path` добавляет `tests/conftest.py`.

## Покрытие

```bash
pytest -m "not browser and not live" --cov=src --cov-report=term-missing
```

Цель — **≥70%**. Актуальный эталон — по выводу команды (не хранить число в
этом скиле: устаревает после первого коммита). При изменении тестов обновлять
бейдж и счётчики в `README.md` / `AGENTS.md`, а не здесь.

## Паттерны тестирования AutoLiker и stages

`AutoLiker` — оркестратор: сбор постов — в `CollectStage` (`stages/`),
цикл лайков — в `run()`.

- **`CollectStage`** — мокаю методы `VKApiSearchService` (`search`,
  `search_hashtag`, `get_wall_posts`, `get_friends`, `get_groups`,
  `resolve_screen_name`) и `PostsRepository`
  (`is_processed` → `False`). Проверяю: приоритет источников, early-exit на
  `enough`, `is_processed` раньше стоп-слов, shuffle, маркировку по режиму
  (`stop_words`: hard → FILTERED; `review`: метка SOFT/HARD + пост в пуле).
- **`run`** — мокаю `_pipeline` (`.run` → `PipelineContext`), `_browser`,
  `_likes_service`, `_sessions_repo`, `_posts_repo`. Проверяю: эффективный
  лимит `min(target, pool)`, пауза только перед реально существующим
  следующим постом, досрочное завершение с причиной, daily limit,
  like success count, already-liked skip, exception → continue.

## Формат вывода

После правки тестов — отчёт:

```
## Тесты
- **Новые:** <файл::Класс::тест>
- **Изменённые:** <файл::Класс::тест>
- **Прогон:** pytest -m "not browser and not live" → <passed/failed>
- **Покрытие:** <из --cov, актуальное число>
- **Marker-тесты:** <прогнаны или нет>
```

## Частые ошибки агента

- **Мокать `mock_logger` как `MagicMock`** → `caplog` пуст, проверка лога не
  работает. `mock_logger` — реальный логгер.
- **Забыть `tmp_path`** → тест трогает боевую `vk_autoliker.db`.
- **Использовать реальный токен** вместо `"test_token"`.
- **Зависеть от сети/времени/порядка.** Тесты должны быть детерминированы.
- **Не обновить `tests/fixtures/vk_post.html`** при правке DOM-селекторов.
- **Писать ассерты на английские строки логов** — в проекте русский.

## Примеры из истории

- `test: Тесты Pipeline, CollectStage, DedupStage + адаптация
  test_liker/test_post_filter` — рефакторинг тестов вслед за архитектурой.
- Регрессионные тесты на инциденты (пробой фильтра на конкретном тексте) —
  пример привязки к реальным данным.

## Проверка

```bash
pytest -m "not browser and not live" -q
pytest -m "not browser and not live" --cov=src --cov-report=term-missing
pytest --collect-only -q
```
