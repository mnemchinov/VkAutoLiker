---
name: testing-with-mocks
description: Перед написанием или правкой тестов.
---

# Тестирование с моками VkAutoLiker

## Когда загружать

- Написание новых тестов
- Правка существующих тестов
- Добавление тестового покрытия для нового модуля
- Правка кода, затрагивающая тесты (обновление моков, ассертов)

## Структура тестов

Один класс тестов на модуль. Файлы — `tests/test_<module>.py`:

| Класс | Файл | Что тестирует |
|---|---|---|
| `TestSettings` | `test_settings.py` | Env vars, дефолты, валидация, SecretStr |
| `TestVKApiClient` | `test_vk_api_client.py` | Rate-limit, ретраи, error 6/14, сетевые ошибки |
| `TestVkApiSearchService` | `test_vk_api_search_service.py` | newsfeed.search, wall.get, friends.get, groups.get, resolveScreenName |
| `TestDateFilter`, `TestEmptyTextFilter`, `TestStopWordsFilter`, `TestFilterChain` | `test_post_filter.py` | days_back, пустой текст, стоп-слова, композит |
| `TestLLMTopicFilter`, `TestLLMFilterStage` | `test_stage_llm_filter.py` | LLM-фильтрация: мок litellm, fallback, stage |
| `TestDatabase`, `TestPostsRepository`, `TestSessionsRepository`, `TestClosedWallsRepository`, `TestMigrations` | `test_database.py`, `test_posts_repository.py`, `test_sessions_repository.py`, `test_closed_walls_repository.py`, `test_migrations.py` | Database, репозитории, миграции (INSERT OR REPLACE, is_processed, сессии, closed-walls кэш) |
| `TestBrowserLikesMock` | `test_browser_likes.py` | Селекторы, клик, верификация (на моках) |
| `TestVKBrowserIsLoggedIn` | `test_vk_browser.py` | remixsid cookie, сетевой ретрай |
| `TestRun`, `TestPipelineComposition` | `test_liker.py` | цикл лайков (эффективный лимит, паузы, досрочное завершение), состав pipeline по `filter_mode` |

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
@patch("vk_api.vk_api_client.requests.get")
@patch("vk_api.vk_api_client.time.sleep")
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

- `@pytest.mark.browser` — тесты, требующие реальный Chrome (headless против фиксутуры)
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

### HTML-фиксутура

`tests/fixtures/vk_post.html` повторяет разметку кнопки лайка. **При изменении
DOM-селекторов — обновлять фиксут** и прогонять `pytest -m browser`.

### Логи — caplog

`mock_logger` — реальный логгер, а не `MagicMock`: проверять лог-вывод —
поиск строки в `caplog.text`, а не `mock_logger.info.assert_called_with(...)`
(второе никогда не проходит). Проверяемые строки логов — на русском.

### Реальный инцидент → регрессионный тест

Каждый реальный инцидент (пробой фильтра, краш, ложный лог) закрепляется
тестом на точных данных инцидента (например, текст поста-пробоя).

### Импорты

Тесты используют плоские импорты (`from vk_api import ...`), как и `src/`.
Путь в `sys.path` добавляет `tests/conftest.py`.

## Покрытие

После правки — прогон с покрытием:

```bash
pytest -m "not browser and not live" --cov=src --cov-report=term-missing
```

Цель: ≥70%. Текущий эталон — 81% (189 тестов).

## Паттерны тестирования AutoLiker и stages

`AutoLiker` — оркестратор: сбор постов — в `CollectStage` (`stages/`),
цикл лайков — в `run()`.

- **`CollectStage`** — мокаю методы `VKApiSearchService` (`search_posts`,
  `get_wall_posts`, `get_friends`, `get_groups`) и `PostsRepository`
  (`is_processed` → `False`). Проверяю: приоритет источников, early-exit на
  `enough`, `is_processed` раньше стоп-слов, shuffle, маркировку по режиму
  (`stop_words`: hard → FILTERED; `review`: метка SOFT/HARD + пост в пуле).
- **`run`** — мокаю `_pipeline` (`.run` → `PipelineContext`), `_browser`,
  `_likes_service`, `_sessions_repo`, `_posts_repo`. Проверяю: эффективный
  лимит `min(target, pool)`, пауза только перед реально существующим
  следующим постом, досрочное завершение с причиной, daily limit,
  like success count, already-liked skip, exception → continue.
