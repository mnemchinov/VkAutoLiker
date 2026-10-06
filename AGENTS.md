# AGENTS.md — VkAutoLiker

Инструкционный контекст для ИИ-агента при работе в этом репозитории.

---

## 1. Обзор проекта

**VkAutoLiker** — консольное Python-приложение для автоматической постановки лайков
в постах ВКонтакте по заданным поисковым запросам, хештегам, стенам групп/пользователей,
а также по стенам друзей и подписок текущего аккаунта.

**Ключевая архитектурная особенность — гибрид двух каналов:**

| Канал | Технология | Для чего |
|---|---|---|
| Чтение/поиск | VK REST API (`requests` + service-токен) | Поиск постов, получение стен, друзей, подписок, расшифровка `screen_name` |
| Лайки | Selenium + Chrome (персистентный профиль) | Клик по кнопке лайка в DOM |

Причина: **service-токен VK API не поддерживает метод `likes.add`**, поэтому лайки
ставятся только через браузер. Вся логика поиска и фильтрации — через API.

**Цепочка данных:**
`VK API (сбор постов)` → `CollectStage (FilterChain: date + empty + stop_words + is_processed + ранний выход)` → `DedupStage (дедупликация)` → `LLMFilterStage (опционально, filter_mode=="llm")` → `Selenium (навигация → «чтение» → клик)` → `проверка aria-label` → `запись в SQLite`

### Стек

- **Язык:** Python 3.14 (venv: `.venv/`)
- **Зависимости** (`requirements.txt`): `selenium>=4.15.0`, `requests>=2.31.0`,
  `PyYAML>=6.0`, `pytest>=8.0.0`, `undetected-chromedriver`, `setuptools`, `pytest-cov`,
  `litellm`, `ruff>=0.6.0`, `pydantic-settings>=2.2.0`, `python-dotenv>=1.0.0`
- **Хранилище состояния:** SQLite (стандартная библиотека `sqlite3`), файл `vk_autoliker.db`
- **Конфигурация:** плоский `Settings(BaseSettings)` (pydantic-settings): env vars + `.env` + дефолты класса; без YAML
- **Логирование:** стандартный `logging`, консоль + файл `vk_autoliker.log`
- **Браузер:** Chrome через `undetected-chromedriver` (UC патчит антидетект:
  UA, navigator.webdriver, plugins, window.chrome, WebGL; `version_main` — авто-детект)
- **README.md:** документация проекта; CI/линтеры/setup.py отсутствуют, сборка как пакета не предусмотрена

### Структура

```
.env                   — env vars: секреты + не-дефолтные параметры (VK_SERVICE_TOKEN, VK_LLM_API_KEY, ...); в .gitignore
pytest.ini             — регистрация маркеров browser / live
requirements.txt       — зависимости
README.md              — документация проекта
.gitignore             — исключения (chrome_profile, *.db, *.log, .venv и т.д.)
src/                   — весь код, плоская структура БЕЗ __init__.py
  main.py              — CLI-точка входа (login|run|test|status|reset)
  file_lock.py         — FileLock: кроссплатформенная файловая блокировка (fcntl/msvcrt)
  liker.py             — AutoLiker: оркестратор всего цикла
  settings.py          — Settings(BaseSettings): плоский pydantic-settings, env vars + .env + дефолты
  logger.py            — AppLogger (обёртка над logging)
  post.py              — dataclass Post (owner_id, item_id, text, date, url)
  vk_api/              — пакет клиента VK API: VKApiClient, VkApiSearchService, VKApiError, CaptchaError
    vk_api_client.py     — HTTP-клиент VK API: rate-limit, ретраи, ошибки
    vk_api_search_service.py — VkApiSearchService: newsfeed.search / wall.get / friends.get / groups.get
  post_filter.py       — FilterChain: DateFilter + EmptyTextFilter + StopWordsFilter + LLMTopicFilter (декомпозиция PostFilter)
  stage_llm_filter.py  — LLMFilterStage: pipeline-стадия для LLM-фильтрации (после DedupStage)
  vk_browser.py        — VKBrowser: обёртка над Selenium + антидетект
  browser_likes.py     — BrowserLikesService: клик по лайку + верификация
  database.py          — Database: подключение SQLite, context manager
  migrations/          — миграции схемы через PRAGMA user_version (m001–m003)
  repositories/        — PostsRepository, SessionsRepository, ClosedWallsRepository
  pipeline.py          — Pipeline + PipelineContext + Stage Protocol
  stage_collect.py     — CollectStage: 6 источников, ранний выход, фильтрация inline через FilterChain
  stage_dedup.py       — DedupStage: дедупликация по (owner_id, item_id)
stop_words.txt         — словарь стоп-слов (одна тема — одна строка, # — комментарий)
tests/                 — pytest-тесты, conftest.py с фикстурами
tests/fixtures/        — статический HTML-фиксут vk_post.html для браузерных тестов
.idea/runConfigurations/ — PyCharm run-configs (Login/Run/Test/Status/Reset)
chrome_profile/        — профиль Chrome (в .gitignore), хранит сессию VK
~/Library/LaunchAgents/ru.vkautoliker.plist — launchd-расписание (3 запуска/день)
```

**Важно про импорты:** в `src/` нет `__init__.py`. Импорты плоские
(`from settings import ...`, а не `from src.settings import ...`). Путь в `sys.path`
добавляют вручную `src/main.py` и `tests/conftest.py`. Поэтому **все команды
запускаются с корня проекта**, а модули импортируются по имени файла.

---

## 2. Сборка, запуск, тесты

### Установка

```bash
cd VkAutoLiker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Требуется установленный Google Chrome (UC скачает совместимый ChromeDriver через `version_main`).

### Команды запуска

Все команды — `python src/main.py <команда>`.
Если команда не указана, по умолчанию выполняется `run`.

```bash
python src/main.py login    # 1-й шаг: открыть Chrome для ручного входа в VK (с 2FA), затем нажать Enter
python src/main.py run      # 2-й шаг: основная сессия лайкинга
python src/main.py run --no-limit  # ручной запуск без учёта дневного лимита (is_auto=0)
python src/main.py test     # диагностика: проверка API-поиска + лайк на одном посте
python src/main.py status   # статистика: сессии/лайки за сегодня и всего
python src/main.py reset    # полная очистка SQLite-базы (обработанные посты и сессии)
```

**Порядок обязательный:** сначала `login` (команда форсирует `headless=False` независимо
от `Settings.headless` — нужен видимый экран для 2FA), далее сессия сохраняется в
`chrome_profile/` и повторный вход не требуется.
При истёкшей сессии `run`/`test` выведут `Нет авторизации. Сначала выполните команду 'login'.`

### Готовые конфигурации запуска (PyCharm)

В `.idea/runConfigurations/` лежат `VkAutoLiker_Login.xml`, `VkAutoLiker_Run.xml`,
`VkAutoLiker_Test.xml`, `VkAutoLiker_Status.xml`, `VkAutoLiker_Reset.xml` — каждый содержит
подробный HTML-комментарий с описанием сценария и эквивалентной командой терминала.
Это самый быстрый способ свериться с ожидаемым поведением.

### Тесты

```bash
pytest                                  # 117 passed, 2 skipped (live пропускаются)
pytest -m "not browser and not live"    # только юнит-тесты, быстрый прогон
pytest -m browser                       # тесты, требующие реальный Chrome
pytest -m live                          # e2e-тесты на реальном посте VK
pytest tests/test_settings.py -v        # конкретный файл
pytest --cov=src --cov-report=term-missing  # с покрытием (75%)
```

- Маркеры `browser` и `live` объявлены в `pytest.ini`.
- Тесты `tests/test_e2e.py` (2 теста) помечены `pytest.skip` и запускаются **только вручную**
  после `login` (схема: `python src/main.py login && python src/main.py test`).
  При обычном `pytest` они отображаются как `2 skipped` — это нормально.
- `tests/test_browser_fixture.py` (1 тест, маркер `browser`) поднимает локальный
  `http.server` на каталоге `tests/fixtures/` и крутит headless-Chrome против `vk_post.html`
  — единственный способ проверить DOM-селекторы лайка без обращения к VK.
- Юнит-тесты на моках — ~115 тестов, маркер не нужен.
- Все пути к БД в тестах подменяются на `tmp_path` — реальный `vk_autoliker.db` не трогают.

### Проверка изменений (линтер: ruff)

```bash
ruff check src/ tests/                 # линтер (pyflakes, isort, pyupgrade, pycodestyle)
pytest -m "not browser and not live"    # базовая страховка после любой правки
.venv/bin/python -c "import sys; sys.path.insert(0,'src'); import liker, database, settings; from migrations import run_migrations; from repositories import PostsRepository, SessionsRepository, ClosedWallsRepository; print('OK')"
```

---

## 3. Правила разработки

### Стиль кода

- **Только типизированные сигнатуры:** все `def` аннотированы (`-> None`, `-> List[Post]`).
  Контракты описаны через `pydantic.BaseModel`, а не через словари.
- **Документация на русском.** Каждый модуль и каждый публичный метод имеет docstring на
  русском языке, объясняющий *зачем*, а не *что*. Комментарии в теле кода — редкие, только
  про неочевидные причины (пример: «После клика aria-label меняется — ищем селектор заново»).
- **Конфигурация — только pydantic-модели.** Новые настройки добавляются в
  `settings.py` (поле `Settings` с дефолтом). Магических чисел в бизнес-логике нет — всё из `Settings`.
- **DI через конструктор.** `AutoLiker.__init__` сам создаёт все сервисы из
  `(config, logger)`; тесты подменяют зависимости через `MagicMock`.
- **Инкапсуляция:** приватные атрибуты и методы с подчёркиванием (`self._client`,
  `_newsfeed_search`, `_rate_limit`).
- **Исключения:** доменные ошибки (`VKApiError`, `CaptchaError`), а не голые `Exception`.
  Ошибки обработки одного поста логируются и не роняют сессию (`try/except` + `continue`).
- **`main.py`** перехватывает только `FileNotFoundError` и `ValueError` → текст в `stderr`
  и `sys.exit(1)`.
- Пиковая длина строки — около 100 символов; `snake_case` для функций/атрибутов,
  `PascalCase` для классов, `UPPER_SNAKE` для констант.

### Сообщения комитов

Формат: `type: Краткое описание с большой буквы`
- **type:** `feat` / `fix` / `docs` / `refactor` / `test` / `chore`
- **Описание:** на русском, с большой буквы, без точки в конце
- **Один комит — одна логическая группа изменений**
- **Файлы не перечислять в сообщении — только заголовок**
- Без scope в скобках, без body, без footer

Примеры:
- `feat: Стоп-слова из файла — загрузка и объединение с inline-списком`
- `fix: Адаптивный сбор друзей/групп`
- `docs: Актуализация AGENTS.md`
- `chore: Подключение ruff`

### Критичные инварианты (не ломать)

1. **Все задержки рандомизируются через `random.uniform(min, max)`.** Фиксированных пауз
   в коде быть не должно — это осознанная имитация человека. Исключения: `time.sleep(1)`
   при ретрае ошибки 6, `time.sleep(5.0)` при сетевом ретрае в `vk_api/vk_api_client.py`,
   `random.uniform(1, 3)` после клика, `random.uniform(55, 65)` в `is_logged_in()`.
2. **Rate-limit VK API ≈ 3 запроса/сек** (`_min_interval = 0.34`). Любой новый вызов API
   обязан идти через `VKApiClient.call()` — иначе лимиты и обработка ошибок 6/14 теряются.
3. **Селектор лайка завязан на `aria-label`:** `«Отправить реакцию «Лайк»»` →
   `«Убрать реакцию «Лайк»»`. VK — React-приложение, поэтому после клика элемент нужно
   искать заново; есть fallback-проверка по `class` (`active`/`liked`).
   **Контейнер поста:** на странице `wall{owner_id}_{item_id}` рендерится лента
   с соседними постами, у каждого — своя кнопка лайка. Селектор ограничен контейнером:
   `[data-post-id="{owner_id}_{item_id}"] [aria-label*="Лайк"]`. Правки селекторов
   обязательно проверяйте через `-m browser`.
4. **Признак авторизации — cookie `remixsid`.** `VKBrowser.is_logged_in()` перед чтением
   cookies обязательно навигирует на `vk.ru` (Selenium отдаёт cookie только текущего домена).
5. **Дедупликация по паре `(owner_id, item_id)`** — первичный ключ в `processed_posts`
   и `INSERT OR REPLACE`. Пост помечается обработанным только при успехе (LIKED/ALREADY_LIKED →
   `status=LIKED`). Провальные лайки (CAPTCHA/FAILED/Exception) НЕ записываются в БД —
   пост повторяется в следующей сессии.
   Исключение: `WebDriverException`/`InvalidSessionIdException` — крах браузера → `break`
   без `mark_processed`, чтобы оставшиеся посты можно было повторить в следующей сессии.
   Отсеянные посты (стоп-слова/LLM) маркируются `status=FILTERED` — не повторяются.
   `PostStatus(IntEnum)` в `post.py`: UNKNOWN=0 (миграция), LIKED=1, FILTERED=2.
   Столбец `status` — для отчётности и возможной повторной проверки ценза, не для логики
   фильтрации. `is_processed` — без изменений, проверка существования записи.
6. **`owner_id` для групп отрицательный.** `groups.get` возвращает положительные ID —
   они разворачиваются в `-id`; `resolve_screen_name` для `group`/`page` тоже возвращает `-id`.
7. **URL постов строятся на домене `vk.ru`** (`https://vk.ru/wall{owner_id}_{item_id}`),
   а API — `https://api.vk.ru/method`.
8. **Лимиты применяются на двух уровнях:** дневные (`sessions_per_day`) до начала сессии и
   пер-сесссионные (`likes_per_session_min`/`likes_per_session_max`) внутри цикла. `--no-limit` обходит дневной лимит:
   сессия записывается с `is_auto=0`, `get_daily_stats()` считает только `is_auto=1`.
   `finally` всегда закрывает сессию в БД, включая `KeyboardInterrupt`.
   **Jitter выполняется после проверки авторизации:** `is_logged_in()` — до `random.uniform(0, 1800)`,
   чтобы истёкшая сессия не ждала до 30 минут зря.
9. **`is_processed` фильтруется при сборе, не только в цикле лайков.** `CollectStage.process()`
    в `stage_collect.py` проверяет `PostsRepository.is_processed()` после `FilterChain.filter()` и **до**
   добавления в `all_posts` — ранний выход `enough = target_likes * 2` считает только
   необработанные посты, иначе нижестоящие источники пропускались бы зря.
    `FilterChain` не зависит от `PostsRepository` — проверяет только `days_back`, пустой текст и стоп-слова.
10. **Друзья и группы перемешиваются, итерируются до early-exit или safety-капа.**
    `get_friends()`/`get_groups()` всегда запрашивают `count=1000` (один API-вызов),
    возвращают полный список; `CollectStage` делает `random.shuffle()` и итерирует по всем,
    проверяя `is_processed` + `FilterChain` inline. Early-exit при `len(all_posts) >= enough`,
    но не раньше `min_friends_to_poll` опрошенных друзей — гарантирует разнообразие источников.
    `max_friends_to_collect`/`max_groups_to_collect` — safety-кап на число API-вызовов
    `wall.get` (не срез списка): достигнут → `break`. Каждая сессия работает со случайным
    подмножеством, а не с одними и теми же первыми N.
    **Кэш закрытых стен:** перед `wall.get` проверяется `ClosedWallsRepository.is_wall_closed(owner_id)`;
    при `VKApiError` с кодами 15 (access denied), 18 (deleted/banned), 30 (profile private)
    стена помечается через `mark_wall_closed`. `get_wall_posts()` re-raise'ит эти ошибки,
    вызывающий код в `CollectStage` ловит и кэширует. TTL — `closed_wall_ttl_days`
    (дефолт 7, env `VK_CLOSED_WALL_TTL_DAYS`). Предотвращает ~38% пустых API-вызовов на закрытые стены друзей.
11. **Источник лайков в приоритетном порядке:** queries → hashtags → groups → accounts →
    auto_friends → auto_groups. Каждый следующий источник собирается только если
    предыдущие не набрали `enough` постов. Финального перемешивания между источниками нет.
12. **Stale Chrome cleanup перед стартом.** `VKBrowser.start()` завершает процессы Chrome,
    использующие `chrome_profile/` (`pgrep` + `SIGTERM` на POSIX, PowerShell CIM + `SIGTERM`
    на Windows), удаляет lock-файлы (`SingletonLock`, `SingletonCookie`, `SingletonSocket`)
    и проверяет размер профиля: при превышении `profile_max_size_mb` (дефолт 500) чистит
    кэш-подкаталоги (`Cache`, `Code Cache`, `GPUCache`, `Service Worker/CacheStorage`).
    Размер считается рекурсивным обходом (`rglob`) — утилиты `du` на Windows нет.
    `AutoLiker.close()` вызывает `VKBrowser.close()` (`driver.quit()`), иначе Chrome
    остаётся висеть и держит профиль для следующего запуска.
13. **Клик через ActionChains.** `click_element` использует `move_to_element + pause + click`
    (мышиная траектория), а не синтетический `element.click()`.
14. **Капча-стоп.** `_detect_captcha()` в `browser_likes.py` проверяет CSS-селектор капчи;
    `_captcha_streak` счётчик сбрасывается при успехе, стоп при `>= max_captcha_streak`.
    `CaptchaError` от API ловится в `liker.run()`.
15. **Burst-смягчение.** Каждые `random.randint(5, 10)` лайков — длинная пауза
    `random.uniform(60, 180)` сек для имитации отвлечения.
16. **`like()` возвращает `LikeResult`** (LIKED / ALREADY_LIKED / CAPTCHA / FAILED) —
    отдельный `is_liked()` не нужен, двойная навигация устранена.
17. **Chrome version auto-detect.** `vk_browser.py` определяет версию Chrome: на Windows
    читает реестр (`HK{CU,LM}\Software\Google\Chrome\BLBeacon` — `chrome.exe --version`
    там ничего не печатает), на остальных ОС — `subprocess`. Передаёт `version_main`
    в `uc.Chrome()` — иначе UC скачает несовместимый ChromeDriver.
18. **Config validation.** `@model_validator` в `Settings` проверяет `min <= max` для всех
    пар задержек/лимитов, `days_back > 0`, `user_id > 0` при `auto_friends`/`auto_groups`,
    `filter_mode` и `llm_model` при `filter_mode=="llm"`.
21. **Секреты через env vars.** `service_token` и `llm_api_key` — `SecretStr`, загружаются
    из env vars `VK_SERVICE_TOKEN` и `VK_LLM_API_KEY`.
    `SecretStr` маскирует значение в `repr()` и логах; получить строку — `.get_secret_value()`.
    `.env` в `.gitignore`.
19. **Декомпозиция PostFilter.** `post_filter.py` содержит `PostFilterProtocol` (Protocol),
    `DateFilter`, `EmptyTextFilter`, `StopWordsFilter`, `LLMTopicFilter` (один класс — одна проверка) и
    `FilterChain` (композит structural: `DateFilter` + `EmptyTextFilter`, без стоп-слов и LLM).
    `FilterChain.should_skip(post)` — per-post проверка structural-фильтров.
    `StopWordsFilter` передаётся в `CollectStage` отдельно от `FilterChain` — отсеянные посты
    маркируются `FILTERED`. `LLMTopicFilter` вызывается только через `LLMFilterStage`.
    `CollectStage._accept()` перебирает посты построчно: structural → continue (без метки),
    stop_words → `mark_processed(FILTERED)` + continue, `is_processed` → continue, свои посты → continue.
    **StopWordsFilter** использует `pymorphy3` для лемматизации русских слов: стоп-слово «церковь»
    находит «церковью», «церкви», «церковного». Три группы: `_stop_lemmas` (русские слова через
    лемматизацию), `_stop_substrings` (нерусские/аббревиатуры через substring), `_stop_phrases`
    (многословные фразы через substring). `MorphAnalyzer` — class-level singleton (словарь ~5MB грузится один раз).
    Каждый результат `should_skip()` логируется: совпадения — на INFO (с указанием слова/леммы),
    OK — на DEBUG. В конце сбора `CollectStage` вызывает `FilterChain.log_summaries()` →
    `StopWordsFilter.log_summary()` логирует сводку `Стоп-слова: проверено N, отсеяно M (X%)`.
20. **LLM-фильтрация опциональна.** `filter_mode` в `Settings`: `"stop_words"` (по умолчанию)
    или `"llm"`. При `"llm"` в конвейер добавляется `LLMFilterStage` (после `DedupStage`) —
    каждый пост классифицируется через `litellm.completion()`. Ошибка LLM → пост не отсеивается
    (безопасный fallback). **Таймаут LLM** (`litellm.Timeout`) → `LLMTimeoutError` → пост
    пропускается без маркировки (не LIKED, не FILTERED) → попадёт в следующую выборку.
    LLM-запросы идут к провайдеру, не к VK — бан-риск нулевой.
    Отсеянные посты (стоп-слова в `CollectStage._accept()`, LLM в `LLMFilterStage`) маркируются
    `mark_processed(..., PostStatus.FILTERED)` — не повторяются в следующих сессиях.
    `LLMFilterStage` принимает `PostsRepository` в конструктор для маркировки.
    `llm_timeout=60` (env `VK_LLM_TIMEOUT`) — таймаут LLM-запроса; reasoning-модели отвечают
    за 15–20 сек, 60 сек — запас. `max_retries=0` передаётся в litellm — отключает ретраи
    OpenAI-клиента (default 2), один таймаут = 60 сек вместо 180.
    `llm_max_tokens=1000` (env `VK_LLM_MAX_TOKENS`) — лимит токенов ответа; `max_tokens=1`
    недостаточно для токенизации «SKIP», `5` недостаточно для reasoning-моделей (токены
    уходят на `reasoning_content`, `content` остаётся пустым). `1000` — запас на reasoning + ответ.
    Каждый ответ логируется на INFO.
    Системный промпт: «не углубляйся в рассуждения, не переходи по ссылкам, определяй тему
    только по тексту поста» — сокращает reasoning MagnitCopilot. Собирается из `llm_stop_topics`
    (список стоп-тем в `Settings`, переопределяется через `VK_LLM_STOP_TOPICS`);
    `llm_system_prompt` полностью заменяет сборку, если задан.
    `llm_ssl_verify=False` (env `VK_LLM_SSL_VERIFY=false`) отключает
    проверку SSL через `litellm.client_session = httpx.Client(verify=False)` — для
    корпоративных endpoint'ов с CA, отсутствующим в `certifi`.
22. **Фильтрация своих постов.** `Post.from_id` — автор поста (VK API `from_id`).
    Парсится в `_parse_wall_item()` и `_parse_newsfeed_item()`.
    `CollectStage._accept()` исключает посты где `from_id == config.user_id` —
    лайкать собственные посты на стенах групп и друзей не нужно.

### Практики тестирования

- Один класс тестов на модуль: `TestSettings`, `TestVKApiClient`, `TestVkApiSearchService`,
  `TestDateFilter`, `TestEmptyTextFilter`, `TestStopWordsFilter`, `TestFilterChain`,
  `TestLLMTopicFilter`, `TestLLMFilterStage`, `TestDatabase`, `TestPostsRepository`, `TestSessionsRepository`, `TestClosedWallsRepository`, `TestMigrations`, `TestBrowserLikesMock`, `TestVKBrowserIsLoggedIn`.
- **Моки вместо сети и браузера:** `MagicMock` для `VKApiClient`, `VKBrowser`, `driver`;
  `patch("vk_api.vk_api_client.requests.get")` и `patch("vk_api.vk_api_client.time.sleep")` — тесты
  не должны спать и не должны ходить в интернет.
- **Фикстуры в `tests/conftest.py`** — переиспользовать их, не дублировать:
  `mock_config_data` / `mock_config` (готовый `Settings` с дефолтами),
  `mock_logger`, `mock_driver`, `tmp_db_path`, `http_fixture_server`.
- Реальные данные VK в тестах не используются; HTML-разметку кнопки лайка повторяет
  `tests/fixtures/vk_post.html` — при изменении селекторов обновлять и фиксут.
- Тесты обращаются к приватным методам (`svc._find_like_button`) и к
  `_parse_newsfeed_item` как к `staticmethod` — это допустимая в проекте практика.

### Конфигурация и секреты

- **Секреты загружаются из env vars** (`VK_SERVICE_TOKEN`, `VK_LLM_API_KEY`), не из YAML.
  `SecretStr` маскирует значение в `repr()` и логах.
  Не выводить секреты в логи, ответы, комментарии, тесты и документацию. В `requirements`/тестах используется
  только заглушка `"test_token"`.
- Для лайков токен не поможет — `likes.add` через API недоступен, нужен браузер.
- `chrome_profile/`, `*.db`, `*.log` уже в `.gitignore` —
  не добавлять их в индекс и не коммитить.
- Любые изменения в `Settings` (особенно лимиты и источники) — только с явного
  согласия пользователя: они напрямую влияют на риск блокировки аккаунта.

### Эксплуатационные ограничения

Проект автоматизирует реальный аккаунт VK. Дефолт (`20–30 лайков/сессия`, `3 сессии/день`,
паузы 15–60 сек) выбран для снижения риска бана. Прежде чем повышать лимиты, убирать
задержки, отключать антидетект-настройки Chrome или расширять круг источников, —
остановиться и спросить пользователя. `max_captcha_streak` заложен как стоп-условие:
при капче сессию правильнее прервать, чем пытаться её обойти.

---

## 4. Что делать агенту при правках

1. Прочитать затронутый модуль и его тест **до** изменений — соглашения здесь важнее
   общих предпочтений.
2. Новую функциональность оформлять как отдельный сервис в `src/` (один класс = один файл),
   подключать его в `AutoLiker.__init__`, а параметры — в `Settings` (`settings.py`).
3. Обновлять docstrings на русском, включая пояснение *почему* выбран такой подход.
4. Писать юнит-тесты на моках; при правках DOM-селекторов — фиксут + `-m browser`.
5. Прогонять `pytest -m "not browser and not live"` перед отчётом о готовности.
6. Не запускать `run`/`test`/`login` и `reset` без явного запроса: `run` ставит реальные
   лайки с аккаунта, `reset` безвозвратно очищает историю.

---

## 5. Скиллы

В проекте 11 скиллов в `.agents`. Все физически существуют как файлы
`SKILL.md`. SDD-скиллы вызываются командой `/имя-скилла` в чате; автозагружаемые
вызываются агентом через `skill` tool.

### Автозагрузка (агент подтягивает сам)

Все 5 скилов физически существуют в `.agents` и **обязательно** загружаются
через `skill` tool перед началом работы, если задача подходит под описание:

- **`oop-design`** — перед проектированием нового класса, сервиса, модуля; при рефакторинге архитектуры; при выборе между наследованием и композицией.
- **`vk-autoliker-conventions`** — перед любой правкой в `src/` или созданием нового сервиса; при работе с VK API, Selenium, SQLite, `settings.py`.
- **`testing-with-mocks`** — перед написанием или правкой тестов.
- **`code-review`** — при запросе code review, ревью кода, проверке изменений или кода по критериям.
- **`implementation-cycle`** — перед любой задачей реализации, правки кода или фикса; стандартизированный цикл: коммит незакоммиченного → очистка контекста → реализация → ревью → сообщения для комитов.

### Ручной вызов (по решению пользователя)

SDD-цикл для новых фич — артефакты в `specs/NNN-slug/`:

| Команда | Назначение |
|---|---|
| `/constitution` | Создать или обновить `CONSTITUTION.md` (редко) |
| `/sdd-specify` | Создать spec новой фичи |
| `/sdd-clarify` | Уточнить неоднозначности spec |
| `/sdd-plan` | Технический дизайн |
| `/sdd-tasks` | Декомпозиция на задачи |
| `/sdd-analyze` | Кросс-проверка spec/plan/tasks (read-only) |

### Правила SDD

- Не создавать `.specify/` — его нет в этой конфигурации.
- Конституция проекта — `CONSTITUTION.md` в корне.
- Активная фича — директория с максимальным NNN в `specs/`, если не указана явно.
- SDD-цикл предлагать при **нетривиальных** изменениях (новый сервис, изменение контрактов,
  изменение лимитов или задержек, рефакторинг с ломающими изменениями). Для мелких правок
  (опечатка, поле в конфиге, один метод) — не предлагать.
- После `sdd-analyze` — реализация основным агентом, потом `@python-oop-reviewer` для
  ревью ООП.