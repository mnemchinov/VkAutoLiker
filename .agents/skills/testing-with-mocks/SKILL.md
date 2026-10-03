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
| `TestConfigLoader` | `test_config.py` | Чтение YAML, дефолты, валидация |
| `TestVKApiClient` | `test_api_client.py` | Rate-limit, ретраи, error 6/14, сетевые ошибки |
| `TestApiSearchService` | `test_api_search.py` | newsfeed.search, wall.get, friends.get, groups.get, resolveScreenName |
| `TestDateFilter`, `TestEmptyTextFilter`, `TestStopWordsFilter`, `TestFilterChain` | `test_post_filter.py` | days_back, пустой текст, стоп-слова, композит |
| `TestLLMTopicFilter`, `TestLLMFilterStage` | `test_stage_llm_filter.py` | LLM-фильтрация: мок litellm, fallback, stage |
| `TestStateStore` | `test_state_store.py` | INSERT OR IGNORE, is_processed, сессии |
| `TestBrowserLikesMock` | `test_browser_likes.py` | Селекторы, клик, верификация (на моках) |
| `TestVKBrowserIsLoggedIn` | `test_vk_browser.py` | remixsid cookie, сетевой ретрай |
| `TestAutoLiker` | `test_liker.py` | _collect_posts, приоритет источников, early-exit, цикл лайков |

## Моки вместо сети и браузера

### Базовый принцип

Тесты **не ходят в интернет** и **не запускают Chrome** (кроме `-m browser`/`-m live`).

### MagicMock для сервисов

```python
from unittest.mock import MagicMock, patch

# Для AutoLiker: создаём реальный объект, подменяем зависимости
liker = AutoLiker(mock_config, mock_logger)
liker._search_service = MagicMock()
liker._likes_service = MagicMock()
liker._state = MagicMock()
liker._filter = MagicMock()
liker._browser = MagicMock()
```

### patch для HTTP и sleep

```python
@patch("vk_api_client.requests.get")
@patch("vk_api_client.time.sleep")
def test_something(mock_sleep, mock_get):
    mock_get.return_value.json.return_value = {"response": {...}}
    # mock_sleep — тесты не спят
```

```python
@patch("vk_browser.time.sleep")
def test_browser_method(mock_sleep):
    # браузерные задержки не тормозят тесты
```

## Фикстуры из conftest.py

**Переиспользовать, не дублировать.** Фикстуры в `tests/conftest.py`:

| Фикстура | Назначение |
|---|---|
| `mock_config_data` | Словарь с конфигурацией (Python dict) |
| `mock_config_file` | Временный YAML-файл с конфигурацией |
| `mock_config` | `AppConfig` dataclass, готовый к использованию |
| `mock_logger` | `MagicMock` логгера |
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
    store = StateStore(tmp_db_path)
```

### Токен

В тестах — `"test_token"`, **никогда** реальный токен.

### Приватные методы

Доступ к приватным методам допустим: `svc._find_like_button(...)`,
`ApiSearchService._parse_newsfeed_item(...)` (как `staticmethod`).

### HTML-фиксутура

`tests/fixtures/vk_post.html` повторяет разметку кнопки лайка. **При изменении
DOM-селекторов — обновлять фиксут** и прогонять `pytest -m browser`.

### Язык

Логи и ассерты в тестах — на русском (соответствует #338).

### Импорты

Тесты используют плоские импорты (`from api_search import ...`), как и `src/`.
Путь в `sys.path` добавляет `tests/conftest.py`.

## Покрытие

После правки — прогон с покрытием:

```bash
pytest -m "not browser and not live" --cov=src --cov-report=term-missing
```

Цель: ≥70%. Текущий эталон — 71% (61 тест).

## Паттерны тестирования AutoLiker

`AutoLiker` — оркестратор, его тесты проверяют бизнес-логику:

- **`_collect_posts`** — мокаю `_search_service` методы (`search_posts`, `get_wall_posts`,
  `get_friends`, `get_groups`), `_state.is_processed` → `False`, `_filter.filter` → pass-through.
  Проверяю: приоритет источников, early-exit на `enough`, дедупликация, shuffle.
- **`run`** — мокаю `_collect_posts` напрямую (чтобы вернуть список `Post`), `_browser`
  и `_likes_service` — моки. Проверяю: daily limit, like success count, already-liked skip,
  exception → continue, likes_per_session_min/max limit.
