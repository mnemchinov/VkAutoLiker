# VkAutoLiker

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python)
![Selenium](https://img.shields.io/badge/Selenium-4.15%2B-green?logo=selenium)
![Tests](https://img.shields.io/badge/tests-61%20passed-brightgreen?logo=pytest)
![Coverage](https://img.shields.io/badge/coverage-71%25-brightgreen?logo=pytest)
![SQLite](https://img.shields.io/badge/SQLite-state%20storage-003B57?logo=sqlite)
![launchd](https://img.shields.io/badge/scheduling-launchd-lightgrey)
![Last Commit](https://img.shields.io/github/last-commit/your-username/VkAutoLiker)
![License](https://img.shields.io/badge/license-MIT-blue)

Консольное Python-приложение для автоматической постановки лайков в постах ВКонтакте
по текстовым запросам, хештегам, стенам групп/пользователей, а также по стенам друзей
и подписок текущего аккаунта.

## Архитектура

Гибрид двух каналов:

| Канал | Технология | Назначение |
|---|---|---|
| Чтение/поиск | VK REST API (service-токен) | Поиск постов, стены, друзья, подписки, даты |
| Лайки | Selenium + Chrome (персистентный профиль) | Клик по кнопке лайка в DOM |

**Причина:** service-токен VK API не поддерживает метод `likes.add` (error 28).
Community-токены — error 27. Выдача user-токенов с правом `wall` отключена с июня 2024.
Поэтому лайки ставятся только через браузер, а весь поиск и фильтрация — через API.

**Цепочка данных:**
```
VK API (сбор постов с реальными датами)
  → PostFilter (давность / пустой текст)
  → SQLite (дедупликация is_processed)
  → Selenium (навигация → «чтение» → клик по лайку)
  → проверка aria-label → запись в SQLite
```

## Стек

- **Python 3.14** (venv `.venv/`)
- **Selenium 4.x** + Chrome (Selenium Manager подтягивает driver автоматически)
- **requests** — HTTP-клиент VK API
- **PyYAML** — конфигурация
- **SQLite** — состояние (стандартная `sqlite3`)
- **pytest 8.x** — тесты
- **fcntl** — file lock для защиты от двойного запуска (launchd)

## Установка

```bash
git clone <repo>
cd VkAutoLiker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Требуется установленный Google Chrome.

## Настройка

1. **Получить service-токен VK API:**
   - Создать приложение: https://dev.vk.ru/ru/admin/create-app
   - Скопировать service-ключ в разделе «Ключи доступа»
   - Лимит без верификации: 10 000 вызовов/мес

2. **Заполнить `config.yaml`:**
   - `api.service_token` — service-токен
   - `search.user_id` — ваш VK ID (числовой, для `friends.get`/`groups.get`)
   - `search.queries` / `search.hashtags` / `search.groups` / `search.accounts` — источники
   - Лимиты и задержки — разделы `limits` и `search`

3. **Первичный вход в VK (2FA):**
   ```bash
   python src/main.py login
   ```
   Откроется Chrome с видимым окном. Войти вручную, пройти 2FA.
   Сессия сохранится в `chrome_profile/`. Повторный вход не требуется.
   **Важно:** при первичном `login` параметр `browser.headless` должен быть `false`.

## Команды

Все команды запускаются из корня проекта:

```bash
python src/main.py login    # Первичный вход в VK (видимое окно, 2FA)
python src/main.py run      # Основная сессия лайкинга
python src/main.py test     # Диагностика: поиск + лайк на одном посте
python src/main.py status   # Статистика: сессии/лайки за сегодня и всего
python src/main.py reset    # Очистка SQLite (обработанные посты и сессии)
```

Если команда не указана — по умолчанию выполняется `run`.

## Источники постов

Посты собираются с приоритетом (лимит расходуется на источники в порядке):

1. **queries** — текстовые запросы через `newsfeed.search`
2. **hashtags** — хештеги через `newsfeed.search` (`#` → `%23`)
3. **groups** — стены сообществ через `wall.get` (по `screen_name`)
4. **accounts** — стены пользователей через `wall.get` (по `screen_name`)
5. **auto_friends** — стены друзей: `friends.get` → `wall.get` на каждого
6. **auto_groups** — стены подписок: `groups.get` → `wall.get` на каждую

Внутри каждого источника порядок рандомизируется. Ранний выход: если собрано
`likes_per_session × 2` свежих постов — остальные источники пропускаются.

Друзья и группы перетасовываются перед выборкой — каждая сессия берёт случайное
подмножество, а не одни и те же первые N.

## Фильтрация

- **Давность:** посты старше `days_back` дней отбрасываются (дата из API, не `time.time()`)
- **Дедупликация:** `is_processed(owner_id, item_id)` в SQLite — пост помечается
  обработанным при успехе, ошибке или исключении
- **Пустой текст:** посты без текста пропускаются
- **Уже лайкнутые:** проверка `aria-label` в браузере (ловит посты, лайкнутые вручную
  вне инструмента, но не записанные в SQLite)

## Антидетект

- Персистентный Chrome-профиль — VK видит того же пользователя, что и при ручном входе
- Реальный Chrome User-Agent и заголовки
- Все задержки рандомизируются через `random.uniform(min, max)`:
  - Пауза между лайками: 15–60 сек
  - «Чтение» поста перед лайком: 5–15 сек
- Порядок постов случайный внутри каждого источника
- Друзья/группы — случайная выборка каждую сессию
- `likes_per_session: 30`, `sessions_per_day: 3` — ~90 лайков/день (безопасный лимит)
- Стоп при `max_captcha_streak` капч подряд
- Закрытые стены (API error 15) и приватные профили (error 30) пропускаются без краша
- **Защита от двойного запуска:** `fcntl.flock` в `main.py` — второй процесс (от launchd) завершается сразу
- **Retry при сбоях сети:** `is_logged_in()` и `VKApiClient.call()` повторяют запрос 3 раза с паузой
- **Error 6 (rate limit):** цикл с max 3 ретраев вместо рекурсии

## Структура проекта

```
config.yaml                  — единственная точка настройки
pytest.ini                   — маркеры browser / live
requirements.txt             — зависимости
src/                         — весь код (плоская структура, без __init__.py)
  main.py                    — CLI: login | run | test | status | reset + fcntl file lock
  liker.py                   — AutoLiker: оркестратор цикла
  config.py                  — AppConfig + ConfigLoader (dataclass-модели)
  logger.py                  — AppLogger (обёртка над logging)
  post.py                    — Post dataclass (owner_id, item_id, text, date, url)
  vk_api_client.py           — VKApiClient: HTTP + rate-limit 3 req/sec + ретраи (error 6, network)
  api_search.py              — ApiSearchService: newsfeed.search / wall.get / friends.get / groups.get
  post_filter.py             — PostFilter: давность / дубли / пустой текст
  vk_browser.py              — VKBrowser: Selenium Chrome + антидетект + network retry
  browser_likes.py           — BrowserLikesService: клик по лайку + верификация (data-post-id)
  state_store.py             — StateStore: SQLite (processed_posts, sessions)
tests/                       — pytest-тесты
  conftest.py                — фикстуры (mock_config, mock_logger, tmp_db, …)
  fixtures/vk_post.html      — HTML-фикстура для браузерных тестов
  test_api_client.py         — тесты VKApiClient
  test_api_search.py         — тесты ApiSearchService
  test_browser_likes.py      — тесты BrowserLikesService (mock WebDriver)
  test_browser_fixture.py    — тесты против локального HTML (маркер browser)
  test_config.py             — тесты ConfigLoader
  test_post_filter.py        — тесты PostFilter
  test_state_store.py        — тесты StateStore
  test_vk_browser.py         — тесты VKBrowser.is_logged_in()
  test_e2e.py                — e2e на живом посте (маркер live, skip по умолчанию)
chrome_profile/              — профиль Chrome (в .gitignore)
vk_autoliker.db              — SQLite база (в .gitignore)
vk_autoliker.log             — логи (в .gitignore)
vk_autoliker.stderr.log      — stderr launchd (в .gitignore)
.autoliker.lock              — file lock от двойного запуска (в .gitignore)
AGENTS.md                    — инструкции для ИИ-агента
CONSTITUTION.md              — формализованные инварианты проекта
README.md                    — документация проекта
```

## Тесты

```bash
pytest                                  # все автотесты (без браузера и сети)
pytest -m "not browser and not live"    # только юнит-тесты, быстрый прогон
pytest -m browser                       # тесты с реальным Chrome (HTML-фикстура)
pytest -m live                          # e2e на живом посте VK (нужен --vk-post=URL)
pytest tests/test_config.py -v          # конкретный файл
```

Три уровня:
1. **Mock WebDriver** — быстрые юнит-тесты, без браузера и сети
2. **HTML-фикстура** — локальный `http.server` + headless Chrome против `vk_post.html`
3. **Live** — e2e на реальном посте VK, запускается только вручную с `--vk-post=URL`

Все пути к БД в тестах подменяются на `tmp_path` — реальная база не затрагивается.

## Автоматизация (launchd)

Файл `~/Library/LaunchAgents/ru.vkautoliker.plist` запускает `run` 3 раза в день:
10:00, 14:00, 19:00.

```bash
launchctl load ~/Library/LaunchAgents/ru.vkautoliker.plist      # включить
launchctl unload ~/Library/LaunchAgents/ru.vkautoliker.plist    # выключить
launchctl list | grep vkautoliker                               # статус
```

`RunAtLoad: false` — лишние запуски при логине исключены.
`sessions_per_day: 3` в коде — страховка от 4-й сессии.
`headless: true` — окно Chrome не появляется.

## Формат коммитов

```
<тип>: <описание>
```

- **тип** (по стандарту Conventional Commits):
    - `feat` — новая функциональность (новое поле, метод, endpoint)
    - `fix` — исправление бага
    - `docs` — документация
    - `refactor` — рефакторинг
    - `chore` — закрытые задачи, настройки, CI, зависимости
    - `test` — тесты
    - `perf` — улучшение производительности
- **описание**: с заглавной буквы, краткая суть на русском

Примеры:

```
feat: Переработка Dao с Criteria API на хранимую процедуру
fix: Исправлена ошибка с limit=0 при экспорте через gRPC
test: Добавлена стадия интеграционных тестов в CI с Testcontainers и DinD
chore: Прото
chore: upd proto
```

## Ограничения

- `likes.add` недоступен через VK API ни с одним типом токена — только браузер
- `wall.search` возвращает 0 результатов с service-токеном (нужен user-токен)
- Service-токен: 10 000 вызовов/мес без верификации (~9 360 при текущих настройках)
- При истёкшей сессии Chrome `run`/`test` выведут: «Нет авторизации. Сначала выполните команду 'login'.»
- VK — React SPA: селекторы лайка основаны на `aria-label` и `data-post-id`,
  могут измениться при обновлении фронтенда VK
