# Project Constitution — VkAutoLiker

**Version**: 1.0.0 | **Ratified**: 2026-09-30 | **Last Amended**: 2026-09-30

## Preamble

Настоящая конституция формализует критичные инварианты проекта VkAutoLiker —
автоматизатора лайков ВКонтакте, работающего с реальным аккаунтом. Нарушение
инвариантов ведёт к бану аккаунта, утечке токена или потере данных. Конституция
имеет приоритет над AGENTS.md при конфликте.

## Article I: Account Safety (MUST)

Все автоматические действия MUST имитировать человеческое поведение.

- Все задержки MUST использовать `random.uniform(min, max)`. Фиксированные
  `time.sleep(...)` запрещены, кроме двух задокументированных исключений:
  `time.sleep(1)` при ретрае error 6 и `random.uniform(1, 3)` после клика.
- Лимиты MUST применяться на двух уровнях: дневные (`sessions_per_day`) до
  начала сессии и пер-сессионные (`likes_per_session_min`/`likes_per_session_max`, `target = random.randint(min, max)`) внутри цикла.
- `finally` MUST всегда закрывать сессию в БД, включая `KeyboardInterrupt`.
- При капче сессия MUST прерываться (`max_captcha_streak`), обход капчи запрещён.
- Любые изменения лимитов, задержек, антидетект-настроек или круга источников
  MUST требовать явного согласия пользователя.
- Stale Chrome-процессы MUST завершаться перед стартом (`pgrep` + `SIGTERM`),
  иначе `SessionNotCreatedException`.

**Rationale**: Нарушения ведут к перманентному бану аккаунта.

## Article II: API Boundary (MUST)

Все вызовы VK API MUST идти через `VKApiClient.call()`.

- Прямые `requests.*` в feature-коде запрещены.
- Rate-limit (~3 req/sec, `_min_interval = 0.34`) и обработка ошибок 6 (ретраи)
  / 14 (капча) — non-negotiable.
- `VKApiError` и `CaptchaError` — доменные исключения, голые `Exception` запрещены.
- Ошибка одного источника (закрытая стена, error 15/30) MUST логироваться и
  пропускаться, не роняя сессию.

**Rationale**: Централизует троттлинг, ретраи, классификацию ошибок.

## Article III: Authentication Boundary (MUST)

Аутентификация MUST выполняться только вручную в реальном браузере.

- Передача, хранение или ввод пароля программно — запрещены.
- Логин выполняется пользователем в Chrome (включая 2FA); скрипт управляет
  уже авторизованной сессией через персистентный профиль.
- Признак авторизации — cookie `remixsid`; `is_logged_in()` MUST навигировать
  на `vk.ru` перед проверкой (Selenium отдаёт cookie только текущего домена).

**Rationale**: Программная передача пароля отвергнута пользователем как
неприемлемый риск.

## Article IV: Data Integrity (MUST)

Каждый пост MUST дедуплицироваться по паре `(owner_id, item_id)`.

- Успешные, провальные и исключительные попытки MUST отмечаться
  `mark_processed` (`INSERT OR IGNORE`).
- `owner_id` для групп MUST быть отрицательным (`groups.get` → `-id`;
  `resolve_screen_name` для `group`/`page` → `-id`).
- URL постов MUST строиться на домене `vk.ru`; API — на `api.vk.ru/method`.
- `is_processed` MUST фильтроваться при сборе (`_collect_posts()`), не только
  в цикле лайков — ранний выход `enough = target_likes * 2` считает только
  необработанные посты.
- `Post.date` MUST приходить из VK API `date` (unix timestamp), не из
  `time.time()`.

**Rationale**: Предотвращает повторную обработку и обеспечивает корректную
фильтрацию по давности.

## Article V: Like Button Scoping (MUST)

Селектор лайка MUST ограничиваться контейнером поста.

- Селектор: `[data-post-id="{owner_id}_{item_id}"] [aria-label*="Лайк"]` —
  глобальные селекторы запрещены.
- `aria-label`: «Отправить реакцию «Лайк»» → «Убрать реакцию «Лайк»». После
  клика элемент MUST искаться заново (React перерисовывает DOM).
- Fallback: проверка по `class` (`active`/`liked`).
- Правки селекторов MUST проверяться через `pytest -m browser`.

**Rationale**: VK рендерит ленту с соседними постами; глобальный селектор
кликает чужой пост.

## Article VI: Source Priority & Randomization (MUST)

Сбор постов следует приоритетному порядку: queries → hashtags → groups →
accounts → auto_friends → auto_groups.

- Каждый следующий источник собирается только если предыдущие не набрали
  `enough` постов.
- Финальное перемешивание между источниками запрещено (приоритет сохраняется).
- Внутри каждого источника `random.shuffle` применяется до и после фильтрации.
- `get_friends()`/`get_groups()` ALWAYS запрашивают `count=1000` (один
  API-вызов); вызывающая сторона делает `shuffle` и итерирует по всем,
  проверяя `is_processed` + `FilterChain` inline до early-exit или safety-капа
  `max_*_to_collect` (кап на API-вызовы, не срез списка).

**Rationale**: Каждая сессия работает со случайным подмножеством, а не с одними
и теми же первыми N.

## Article VII: Testing (SHOULD)

Тесты MUST NOT обращаться к реальной сети или реальному браузеру без явной
маркировки.

- `@pytest.mark.browser` — тесты, требующие Chrome.
- `@pytest.mark.live` — тесты на реальном VK (с `--vk-post=URL`).
- Тесты MUST использовать `MagicMock` для `VKApiClient`, `VKBrowser`, `driver`.
- Все пути к БД в тестах MUST подменяться на `tmp_path`.
- Перед отчётом о готовности SHOULD запускаться
  `pytest -m "not browser and not live"`.
- HTML-фиксут `tests/fixtures/vk_post.html` MUST обновляться при изменении
  DOM-селекторов.

**Rationale**: Юнит-тесты должны работать без побочных эффектов.

## Article VIII: Configuration & Secrets (MUST)

- Секреты (токены) MUST загружаться из env vars (`VK_SERVICE_TOKEN`, `VK_LLM_API_KEY`),
  не из файлов в git.
- Тестовый код MUST использовать заглушку `"test_token"`.
- `chrome_profile/`, `*.db`, `*.log`, `.env` MUST быть в `.gitignore`.
- Новые настройки MUST добавляться в `settings.py` (поле `Settings` с дефолтом).
- Магические числа в бизнес-логике запрещены — всё из `Settings`.

**Rationale**: Утечка токена компрометирует аккаунт; отсутствие типа — источник
тихих ошибок.

## Article IX: Code Conventions (SHOULD)

- Все `def` SHOULD иметь аннотации типов (`-> None`, `-> List[Post]`).
- Контракты — через `dataclass`, не через словари.
- Docstrings на русском, объясняющие зачем, а не что.
- Один класс = один файл, PascalCase, `snake_case` для функций, `UPPER_SNAKE`
  для констант.
- DI через конструктор; инкапсуляция через `_`-префикс.
- Документация: class docstrings, обоснованные комментарии (не избыточные),
  config с пояснениями.

**Rationale**: Соглашения важнее общих предпочтений; консистентность снижает
риск ошибок.

## Article X: Operational Discipline (MUST)

- `run`, `test`, `login`, `reset` MUST NOT запускаться агентом без явного
  запроса пользователя.
- `run` ставит реальные лайки; `reset` безвозвратно очищает историю.
- Агент MUST читать затронутый модуль и его тест ДО изменений.
- Новую функциональность SHOULD оформлять как отдельный сервис в `src/`.

**Rationale**: Автоматизация реального аккаунта; необратимые действия требуют
контроля.

## Amendment Procedure

- Поправки требуют явного запуска `/skill:constitution`.
- Версионирование — SemVer: MAJOR (удалён MUST), MINOR (новый MUST),
  PATCH (формулировка).
- Соответствие проверяется через `/skill:sdd-analyze` и ревью кода.
