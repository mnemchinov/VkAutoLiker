# VkAutoLiker

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python)
![Selenium](https://img.shields.io/badge/Selenium-4.15%2B-green?logo=selenium)
![Tests](https://img.shields.io/badge/tests-75%20passed-brightgreen?logo=pytest)
![Coverage](https://img.shields.io/badge/coverage-74%25-brightgreen?logo=pytest)
![SQLite](https://img.shields.io/badge/SQLite-state%20storage-003B57?logo=sqlite)
![Scheduling](https://img.shields.io/badge/scheduling-launchd%20%2B%20Task%20Scheduler-lightgrey)
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

**Причина:** service-токен VK API не поддерживает `likes.add`, поэтому лайки ставятся
только через браузер, а весь поиск и фильтрация — через API.

**Цепочка данных:**
```
VK API (сбор постов с реальными датами)
  → CollectStage (PostFilter + is_processed + ранний выход)
  → DedupStage (дедупликация по owner_id + item_id)
  → Selenium (навигация → «чтение» → клик по лайку)
  → проверка aria-label → запись в SQLite
```

## Быстрый старт

### 1. Установка

```bash
git clone <repo>
cd VkAutoLiker
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Требуется установленный Google Chrome.

### 2. Получить service-токен VK API

1. Создать приложение: https://dev.vk.ru/ru/admin/create-app
2. Скопировать service-ключ в разделе «Ключи доступа»
3. Лимит без верификации приложения: 10 000 вызовов/мес

### 3. Заполнить `config.yaml`

Минимум для работы:

```yaml
api:
  service_token: "ваш_токен"       # service-ключ из кабинета разработчика

search:
  user_id: 12345678                # ваш VK ID (числовой)
  hashtags:                        # хотя бы один источник
    - "#вашХештег"
  auto_friends: true               # собирать посты со стен друзей
  auto_groups: true                # собирать посты со стен подписок
```

Остальные параметры — см. [Параметры config.yaml](#параметры-configyaml).

### 4. Первичный вход в VK

```bash
python src/main.py login
```

Откроется Chrome с видимым окном. Войти вручную, пройти 2FA.
Сессия сохранится в `chrome_profile/` — повторный вход не требуется.

Команда `login` форсирует `headless=False` независимо от `config.yaml` — для 2FA
нужен видимый экран.

### 5. Проверка (один пост)

```bash
python src/main.py test
```

Проверяет API-поиск и ставит один лайк через браузер. Убедитесь, что лайк
появился на стене.

### 6. Боевая сессия

```bash
python src/main.py run             # запуск с учётом дневного лимита
python src/main.py run --no-limit  # ручной запуск без учёта лимита
```

## Команды

Все команды запускаются из корня проекта:

| Команда | Назначение |
|---|---|
| `python src/main.py login` | Первичный вход в VK (видимое окно, 2FA) |
| `python src/main.py run` | Основная сессия лайкинга |
| `python src/main.py run --no-limit` | Ручной запуск без дневного лимита |
| `python src/main.py test` | Диагностика: поиск + лайк на одном посте |
| `python src/main.py status` | Статистика: сессии/лайки за сегодня и всего |
| `python src/main.py reset` | Очистка SQLite (обработанные посты и сессии) |

Если команда не указана — по умолчанию выполняется `run`.

## Параметры config.yaml

### `api` — доступ к VK API

| Параметр | По умолч. | Описание |
|---|---|---|
| `service_token` | — | Service-токен приложения VK |
| `api_version` | `5.131` | Версия VK API |
| `base_url` | `https://api.vk.ru/method` | Базовый URL для вызовов |

### `browser` — Selenium Chrome

| Параметр | По умолч. | Описание |
|---|---|---|
| `profile_path` | `./chrome_profile` | Каталог профиля Chrome (сохраняет сессию VK) |
| `headless` | `true` | Скрытый режим. `login` форсирует `false` |

### `search` — источники и глубина сбора

| Параметр | По умолч. | Пример | Описание |
|---|---|---|---|
| `user_id` | — | `12345678` | VK ID пользователя (для `friends.get` / `groups.get`) |
| `queries` | `[]` | `["косметика", "распродажа"]` | Текстовые запросы через `newsfeed.search` |
| `hashtags` | `[]` | `["#СоздаюСвойМагнит"]` | Хештеги через `newsfeed.search` |
| `groups` | `[]` | `["magnet", "vkteam"]` | Короткие имена сообществ (`screen_name`) |
| `accounts` | `[]` | `["durov"]` | Короткие имена пользователей (`screen_name`) |
| `auto_friends` | `true` | — | Сбор постов со стен друзей |
| `auto_groups` | `true` | — | Сбор постов со стен подписок |
| `max_posts_per_query` | `100` | — | Лимит постов с одного текстового запроса |
| `max_posts_per_hashtag` | `100` | — | Лимит постов с одного хештега (пагинация через `start_time`) |
| `max_posts_per_group` | `100` | — | Лимит постов со стены одной группы |
| `max_posts_per_account` | `100` | — | Лимит постов со стены одного пользователя |
| `max_posts_per_friend` | `10` | — | Лимит постов со стены одного друга |
| `max_friends_to_collect` | `200` | — | Макс. число API-вызовов `wall.get` к друзьям (из всех, случайно) |
| `max_groups_to_collect` | `200` | — | Макс. число API-вызовов `wall.get` к группам (из всех, случайно) |
| `days_back` | `30` | — | Не лайкать посты старше N дней |

### `limits` — лимиты и задержки

Все задержки рандомизируются через `random.uniform(min, max)`.

| Параметр | По умолч. | Описание |
|---|---|---|
| `likes_per_session_min` | `20` | Минимум лайков за сессию (`random.randint(min, max)`) |
| `likes_per_session_max` | `30` | Максимум лайков за сессию |
| `sessions_per_day` | `3` | Лимит сессий в день (только `is_auto=1`) |
| `min_delay_sec` | `15` | Мин. пауза между лайками |
| `max_delay_sec` | `60` | Макс. пауза между лайками |
| `view_delay_min_sec` | `5` | Мин. пауза «чтения» поста перед лайком |
| `view_delay_max_sec` | `15` | Макс. пауза «чтения» поста |
| `max_captcha_streak` | `3` | Стоп после N капч подряд |

### `logging` и `state`

| Параметр | По умолч. | Описание |
|---|---|---|
| `logging.level` | `INFO` | Уровень логирования (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |
| `logging.file` | `vk_autoliker.log` | Файл логов |
| `state.db_path` | `vk_autoliker.db` | Путь к SQLite-базе |

## Источники постов

Посты собираются с приоритетом (лимит расходуется в порядке):

1. **queries** — текстовые запросы через `newsfeed.search`
2. **hashtags** — хештеги через `newsfeed.search` (`#` → `%23`)
3. **groups** — стены сообществ через `wall.get` (по `screen_name`)
4. **accounts** — стены пользователей через `wall.get` (по `screen_name`)
5. **auto_friends** — стены друзей: `friends.get` → `wall.get` на каждого
6. **auto_groups** — стены подписок: `groups.get` → `wall.get` на каждую

Внутри каждого источника порядок рандомизируется. Ранний выход: если собрано
`target_likes × 2` свежих постов — остальные источники пропускаются.

Друзья и группы перетасовываются перед выборкой — каждая сессия берёт случайное
подмножество, а не одни и те же первые N.

## Фильтрация

- **Давность:** посты старше `days_back` дней отбрасываются (дата из API)
- **Дедупликация:** `is_processed(owner_id, item_id)` в SQLite — пост помечается
  обработанным при успехе, ошибке или исключении
- **Пустой текст:** посты без текста пропускаются
- **Уже лайкнутые:** проверка `aria-label` в браузере (ловит посты, лайкнутые вручную
  вне инструмента, но не записанные в SQLite)

## Антидетект

- **undetected-chromedriver** — патчи UA, `navigator.webdriver`, plugins, `window.chrome`, WebGL
- **ActionChains** — клик с реальной траекторией мыши (`move_to_element` + пауза + `click`)
- Персистентный Chrome-профиль — VK видит того же пользователя, что и при ручном входе
- Все задержки рандомизируются: пауза между лайками 15–60 сек, «чтение» 5–15 сек
- Jitter для launchd: 0–30 мин перед стартом (auto-режим)
- Burst-смягчение: каждые 5–10 лайков — пауза 60–180 сек
- Человеческое поведение: скролл, движение мыши, паузы «чтения»
- Друзья/группы — случайная выборка каждую сессию
- Рандомизация лайков за сессию: `random.randint(min, max)`
- Защита от двойного запуска через `fcntl.flock`
- Retry при сбоях сети в `is_logged_in()` и `VKApiClient.call()`

## Автоматизация

### macOS (launchd)

Файл `~/Library/LaunchAgents/ru.vkautoliker.plist` запускает `run` 3 раза в день:
10:00, 14:00, 19:00.

```bash
# Создать plist (пример — скорректируйте путь к проекту и Python)
cat > ~/Library/LaunchAgents/ru.vkautoliker.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>ru.vkautoliker</string>
    <key>ProgramArguments</key>
    <array>
        <string>/путь/к/.venv/bin/python</string>
        <string>/путь/к/VkAutoLiker/src/main.py</string>
        <string>run</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>10</integer></dict>
        <dict><key>Hour</key><integer>14</integer></dict>
        <dict><key>Hour</key><integer>19</integer></dict>
    </array>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key><string>/dev/null</string>
    <key>StandardErrorPath</key><string>/путь/к/VkAutoLiker/vk_autoliker.stderr.log</string>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/ru.vkautoliker.plist      # включить
launchctl unload ~/Library/LaunchAgents/ru.vkautoliker.plist    # выключить
launchctl list | grep vkautoliker                               # статус
```

`run` (без `--no-limit`) считается автозапуском (`is_auto=1`) и расходует дневной лимит.
`run --no-limit` — ручной запуск, лимит не тратится.

### Windows (Task Scheduler)

```powershell
# 3 задачи: 10:00, 14:00, 19:00 (скорректируйте пути)
schtasks /create /tn "VkAutoLiker_10" /tr "C:\VkAutoLiker\.venv\Scripts\python.exe C:\VkAutoLiker\src\main.py run" /sc daily /st 10:00 /f
schtasks /create /tn "VkAutoLiker_14" /tr "C:\VkAutoLiker\.venv\Scripts\python.exe C:\VkAutoLiker\src\main.py run" /sc daily /st 14:00 /f
schtasks /create /tn "VkAutoLiker_19" /tr "C:\VkAutoLiker\.venv\Scripts\python.exe C:\VkAutoLiker\src\main.py run" /sc daily /st 19:00 /f
```

Альтернатива — через GUI: Task Scheduler → Create Basic Task → Daily → Start a program.

```powershell
schtasks /query /tn "VkAutoLiker_*"       # статус
schtasks /delete /tn "VkAutoLiker_10" /f  # удалить задачу
```

**Примечание:** на Windows `fcntl.flock` недоступен — защита от двойного запуска
работает только на macOS/Linux. Task Scheduler не запускает процесс дважды, поэтому
это не критично.

## Структура проекта

```
config.yaml            — единственная точка настройки
requirements.txt       — зависимости
src/                   — весь код (плоская структура, без __init__.py)
  main.py              — CLI: login | run | test | status | reset + fcntl file lock
  liker.py             — AutoLiker: оркестратор цикла
  config.py            — AppConfig + ConfigLoader (dataclass-модели)
  vk_api_client.py     — VKApiClient: HTTP + rate-limit 3 req/sec + ретраи
  api_search.py        — ApiSearchService: newsfeed.search / wall.get / friends.get / groups.get
  post_filter.py       — PostFilter: давность / пустой текст
  vk_browser.py        — VKBrowser: undetected-chromedriver + ActionChains + network retry
  browser_likes.py     — BrowserLikesService: клик по лайку + верификация (data-post-id)
  state_store.py       — StateStore: SQLite (processed_posts, sessions)
  pipeline.py          — Pipeline + PipelineContext + Stage Protocol
  stage_collect.py     — CollectStage: 6 источников, ранний выход, фильтрация inline
  stage_dedup.py       — DedupStage: дедупликация по (owner_id, item_id)
tests/                 — pytest-тесты + HTML-фикстура для браузерных тестов
chrome_profile/        — профиль Chrome (в .gitignore)
vk_autoliker.db        — SQLite база (в .gitignore)
```

## Тесты

```bash
pytest                                  # 75 passed, 2 skipped (live-тесты пропускаются)
pytest -m "not browser and not live"    # только юнит-тесты, быстрый прогон
pytest -m browser                       # тесты с реальным Chrome (HTML-фикстура)
pytest -m live                          # e2e на живом посте VK (нужен --vk-post=URL)
pytest --cov=src --cov-report=term-missing  # с покрытием (74%)
```

Три уровня:
1. **Mock WebDriver** (74 теста) — быстрые юнит-тесты, без браузера и сети
2. **HTML-фикстура** (1 тест, маркер `browser`) — локальный `http.server` + headless Chrome против `vk_post.html`
3. **Live** (2 теста, маркер `live`) — e2e на реальном посте VK; `pytest.skip` по умолчанию, запускаются только вручную после `login`

Все пути к БД в тестах подменяются на `tmp_path` — реальная база не затрагивается.
