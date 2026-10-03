---
name: oop-design
description: Перед проектированием нового класса, сервиса, модуля; при рефакторинге архитектуры; при выборе между наследованием и композицией.
---

# OOP-дизайн VkAutoLiker

## Когда загружать

- Создание нового класса, сервиса или модуля в `src/`
- Рефакторинг архитектуры (изменение взаимодействия сервисов)
- Выбор между наследованием и композицией
- Добавление новой функциональности, требующей нового сервиса

## Архитектурный выбор: композиция

Проект использует **композицию**, не наследование. `AutoLiker` содержит сервисы
как атрибуты (`self._search_service`, `self._likes_service`, `self._state`,
`self._filter`, `self._browser`), каждый со своим `__init__`.

**Почему композиция:**

- Сервисы тестируются изолированно — меняю один на `MagicMock`, остальное работает
- `AutoLiker` — оркестратор, а не god-class: он делегирует, не наследует
- Нет конфликтов MRO при множественном наследовании
- Сервисы не знают друг о друге — слабая связанность

**Когда наследование уместно** (в этом проекте — редко):

- Базовый класс `BaseService` для общих атрибутов (`_config`, `_logger`) — опциональная
  оптимизация, не требование. Если вводится, `AutoLiker` всё равно остаётся на композиции.
- Никогда — множественное наследование `AutoLiker` от сервисов: ломает тестируемость и SRP.

## Чеклист перед созданием нового класса

1. **Прочитать 2-3 соседних файла** в `src/` — понять конвенции именования, импортов,
   обработки ошибок. Соседние файлы — образцы, не абстрактные правила.
2. **Проверить `AutoLiker.__init__`** — как сервисы подключаются (DI через конструктор).
   Новый сервис подключается так же: `self._my_service = MyService(config, logger)`.
3. **Проверить `config.py`** — какие `dataclass`-модели существуют. Новые параметры
   добавляются в `AppConfig` (или вложенный `SearchConfig`) + `config.yaml` с комментарием.
4. **Проверить `AGENTS.md`** — критичные инварианты (секция 3). Не ломать ни один.

## Правила дизайна

### Один класс = один файл

Каждый сервис — отдельный файл в `src/`. Имя файла = `snake_case` имени класса:
`ApiSearchService` → `api_search.py`, `BrowserLikesService` → `browser_likes.py`.

### DI через конструктор

```python
class MyService:
    def __init__(self, config: AppConfig, logger: AppLogger) -> None:
        self._config = config
        self._logger = logger
```

`AutoLiker.__init__` создаёт все сервисы. Тесты подменяют зависимости через `MagicMock`.

### Контракты через dataclass

Модели данных — `@dataclass`, не словари. Пример: `Post` в `post.py` с полями
`owner_id`, `item_id`, `text`, `date`, `url`. Новые модели — туда же, в `post.py`
или отдельный файл, если модель сложная.

### Инкапсуляция

Приватные атрибуты и методы — с подчёркиванием: `self._client`, `_newsfeed_search`,
`self._rate_limit`. Публичный интерфейс минимален.

### Доменные исключения

Не голые `Exception`. Доменные ошибки: `VKApiError`, `CaptchaError`.
Ошибки обработки одного поста логируются и не роняют сессию (`try/except` + `continue`).

### Типизированные сигнатуры

Все `def` аннотированы: `-> None`, `-> List[Post]`, `-> Optional[str]`.
`snake_case` для функций/атрибутов, `PascalCase` для классов, `UPPER_SNAKE` для констант.

### Документация на русском

Каждый модуль и каждый публичный метод имеет docstring на русском языке,
объясняющий *зачем*, а не *что*. Комментарии в теле кода — редкие, только про
неочевидные причины.

## Чеклист после создания

- [ ] Файл в `src/`, имя = `snake_case` класса
- [ ] Подключение в `AutoLiker.__init__` через DI
- [ ] Параметры в `AppConfig` + `config.yaml` с комментарием
- [ ] Docstrings на русском для модуля и публичных методов
- [ ] Импорт проверен: `sys.path.insert(0,'src')` — плоские импорты
- [ ] `pytest -m "not browser and not live"` проходит

## Образцы для изучения

| Класс | Файл | Ответственность |
|---|---|---|
| `VKApiClient` | `vk_api_client.py` | HTTP-клиент VK API: rate-limit, ретраи, ошибки 6/14 |
| `ApiSearchService` | `api_search.py` | Обёртка над VK API: newsfeed.search, wall.get, friends.get, groups.get |
| `BrowserLikesService` | `browser_likes.py` | Клик по лайку через Selenium + верификация |
| `VKBrowser` | `vk_browser.py` | Обёртка над Selenium + антидетект + stale Chrome cleanup |
| `StateStore` | `state_store.py` | SQLite: processed_posts, sessions |
| `FilterChain` | `post_filter.py` | Композит: DateFilter + EmptyTextFilter + StopWordsFilter |
| `LLMTopicFilter` | `post_filter.py` | LLM-фильтр тематики (PostFilterProtocol, litellm) |
| `LLMFilterStage` | `stage_llm_filter.py` | Pipeline-стадия: LLM-фильтрация после DedupStage (опц.) |
| `AutoLiker` | `liker.py` | Оркестратор: сбор → фильтрация → лайки → запись |
