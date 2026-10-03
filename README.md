# VkAutoLiker

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python)
![Selenium](https://img.shields.io/badge/Selenium-4.15%2B-green?logo=selenium)
![Tests](https://img.shields.io/badge/tests-124%20passed-brightgreen?logo=pytest)
![Coverage](https://img.shields.io/badge/coverage-75%25-brightgreen?logo=pytest)
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
  → CollectStage (FilterChain: date + empty + stop_words + is_processed + ранний выход)
  → DedupStage (дедупликация по owner_id + item_id)
  → LLMFilterStage (опционально, filter_mode=="llm")
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

### 3. Заполнить `.env`

Минимум для работы — файл `.env` в корне проекта (в `.gitignore`):

```
VK_SERVICE_TOKEN=ваш_service_токен
VK_LLM_API_KEY=ваш_llm_ключ            # только при filter_mode: llm
VK_USER_ID=12345678                     # ваш VK ID (числовой)
VK_HASHTAGS=#вашХештег,#другойХештег    # comma-separated, хотя бы один источник
VK_AUTO_FRIENDS=true                    # собирать посты со стен друзей
VK_AUTO_GROUPS=true                     # собирать посты со стен подписок
```

Остальные параметры — см. [Параметры Settings](#параметры-settings).

### 4. Первичный вход в VK

```bash
python src/main.py login
```

Откроется Chrome с видимым окном. Войти вручную, пройти 2FA.
Сессия сохранится в `chrome_profile/` — повторный вход не требуется.

Команда `login` форсирует `headless=False` независимо от `Settings` — для 2FA
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

## Параметры Settings

Все параметры — поля класса `Settings` в `src/settings.py`. Значения задаются через env vars (префикс `VK_`) или файл `.env`; не указанные — используют дефолты класса.

### VK API

| Параметр | Env var | По умолч. | Описание |
|---|---|---|---|
| `service_token` | `VK_SERVICE_TOKEN` | — | Service-токен (`SecretStr`) |
| `api_version` | `VK_API_VERSION` | `5.131` | Версия VK API |
| `base_url` | `VK_BASE_URL` | `https://api.vk.ru/method` | Базовый URL для вызовов |

### Selenium Chrome

| Параметр | Env var | По умолч. | Описание |
|---|---|---|---|
| `profile_path` | `VK_PROFILE_PATH` | `./chrome_profile` | Каталог профиля Chrome |
| `headless` | `VK_HEADLESS` | `true` | Скрытый режим. `login` форсирует `false` |

### Источники и глубина сбора

| Параметр | Env var | По умолч. | Пример в `.env` | Описание |
|---|---|---|---|---|
| `user_id` | `VK_USER_ID` | `0` | `12345678` | VK ID пользователя (для `friends.get` / `groups.get`) |
| `queries` | `VK_QUERIES` | `[]` | `косметика,распродажа` | Текстовые запросы через `newsfeed.search` (comma-separated) |
| `hashtags` | `VK_HASHTAGS` | `[]` | `#СоздаюСвойМагнит,#яВыбираюМагнит` | Хештеги через `newsfeed.search` (comma-separated) |
| `groups` | `VK_GROUPS` | `[]` | `magnet,vkteam` | Короткие имена сообществ `screen_name` (comma-separated) |
| `accounts` | `VK_ACCOUNTS` | `[]` | `durov` | Короткие имена пользователей `screen_name` (comma-separated) |
| `auto_friends` | `VK_AUTO_FRIENDS` | `false` | `true` | Сбор постов со стен друзей |
| `auto_groups` | `VK_AUTO_GROUPS` | `false` | `true` | Сбор постов со стен подписок |
| `max_posts_per_query` | `VK_MAX_POSTS_PER_QUERY` | `100` | — | Лимит постов с одного текстового запроса |
| `max_posts_per_hashtag` | `VK_MAX_POSTS_PER_HASHTAG` | `100` | — | Лимит постов с одного хештега (пагинация через `start_time`) |
| `max_posts_per_group` | `VK_MAX_POSTS_PER_GROUP` | `100` | — | Лимит постов со стены одной группы |
| `max_posts_per_account` | `VK_MAX_POSTS_PER_ACCOUNT` | `100` | — | Лимит постов со стены одного пользователя |
| `max_posts_per_friend` | `VK_MAX_POSTS_PER_FRIEND` | `10` | — | Лимит постов со стены одного друга |
| `max_friends_to_collect` | `VK_MAX_FRIENDS_TO_COLLECT` | `200` | — | Макс. число API-вызовов `wall.get` к друзьям (из всех, случайно) |
| `max_groups_to_collect` | `VK_MAX_GROUPS_TO_COLLECT` | `200` | — | Макс. число API-вызовов `wall.get` к группам (из всех, случайно) |
| `days_back` | `VK_DAYS_BACK` | `30` | — | Не лайкать посты старше N дней |
| `stop_words` | `VK_STOP_WORDS` | `[]` | `18+,казино` | Стоп-слова inline (дополнительные к файлу, comma-separated) |
| `stop_words_file` | `VK_STOP_WORDS_FILE` | `""` | `stop_words.txt` | Файл стоп-слов: одно слово на строку, `#` — комментарий |
| `filter_mode` | `VK_FILTER_MODE` | `"stop_words"` | `llm` | Режим фильтрации: `"stop_words"` или `"llm"` |

### Лимиты и задержки

Все задержки рандомизируются через `random.uniform(min, max)`.

| Параметр | Env var | По умолч. | Описание |
|---|---|---|---|
| `likes_per_session_min` | `VK_LIKES_PER_SESSION_MIN` | `20` | Минимум лайков за сессию (`random.randint(min, max)`) |
| `likes_per_session_max` | `VK_LIKES_PER_SESSION_MAX` | `30` | Максимум лайков за сессию |
| `sessions_per_day` | `VK_SESSIONS_PER_DAY` | `3` | Лимит сессий в день (только `is_auto=1`) |
| `min_delay_sec` | `VK_MIN_DELAY_SEC` | `15` | Мин. пауза между лайками |
| `max_delay_sec` | `VK_MAX_DELAY_SEC` | `60` | Макс. пауза между лайками |
| `view_delay_min_sec` | `VK_VIEW_DELAY_MIN_SEC` | `5` | Мин. пауза «чтения» поста перед лайком |
| `view_delay_max_sec` | `VK_VIEW_DELAY_MAX_SEC` | `15` | Макс. пауза «чтения» поста |
| `max_captcha_streak` | `VK_MAX_CAPTCHA_STREAK` | `3` | Стоп после N капч подряд |

### Логирование и состояние

| Параметр | Env var | По умолч. | Описание |
|---|---|---|---|
| `log_level` | `VK_LOG_LEVEL` | `INFO` | Уровень логирования (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |
| `log_file` | `VK_LOG_FILE` | `vk_autoliker.log` | Файл логов |
| `db_path` | `VK_DB_PATH` | `vk_autoliker.db` | Путь к SQLite-базе |
| `closed_wall_ttl_days` | `VK_CLOSED_WALL_TTL_DAYS` | `7` | TTL кэша закрытых стен (дней) |
| `profile_max_size_mb` | `VK_PROFILE_MAX_SIZE_MB` | `500` | Лимит размера профиля Chrome (MB) — при превышении чистится кэш |

### LLM-фильтрация (опционально, `filter_mode: "llm"`)

| Параметр | Env var | По умолч. | Пример в `.env` | Описание |
|---|---|---|---|---|
| `llm_model` | `VK_LLM_MODEL` | `""` | `openai/gpt-4o-mini` | Идентификатор модели (через litellm; префикс `openai/` обязателен — определяет протокол) |
| `llm_api_base` | `VK_LLM_API_BASE` | `""` | `https://api.openai.com/v1` | Базовый URL API (пусто = default провайдера) |
| `llm_api_key` | `VK_LLM_API_KEY` | `""` | `sk-...` | API-ключ провайдера (`SecretStr`, НЕ коммитить; для Ollama — любая непустая строка) |
| `llm_system_prompt` | `VK_LLM_SYSTEM_PROMPT` | (встроенный промпт) | — | Системный промпт (переопределяет сборку из `llm_stop_topics`) |
| `llm_stop_topics` | `VK_LLM_STOP_TOPICS` | (8 тем по умолчанию) | `политика,религия` | Стоп-темы для LLM (comma-separated; встроенный промпт, если `llm_system_prompt` пуст) |
| `llm_timeout` | `VK_LLM_TIMEOUT` | `10` | `30` | Таймаут запроса к LLM (сек) |
| `llm_max_tokens` | `VK_LLM_MAX_TOKENS` | `1000` | `5` | Лимит токенов в ответе LLM (reasoning-моделям нужен запас на размышление + ответ) |
| `llm_max_text_length` | `VK_LLM_MAX_TEXT_LENGTH` | `500` | `1000` | Обрезка текста поста перед отправкой в LLM |
| `llm_ssl_verify` | `VK_LLM_SSL_VERIFY` | `true` | `false` | Проверка SSL-сертификата LLM-endpoint (`false` — для корпоративных CA) |

### Примеры конфигурации LLM-провайдеров

**Ollama** (локальная модель, не требует API-ключа):

```dotenv
VK_LLM_MODEL=openai/ministral-3:8b-64k
VK_LLM_API_BASE=http://localhost:11434/v1
VK_LLM_API_KEY=ollama
VK_LLM_SSL_VERIFY=true
```

**your-model-name** (корпоративный endpoint, reasoning-модель):

```dotenv
VK_LLM_MODEL=openai/your-model-name
VK_LLM_API_BASE=https://your-endpoint/v1
VK_LLM_API_KEY=sk-...
VK_LLM_SSL_VERIFY=false
```

> **Префикс `openai/`** в `llm_model` обязателен — litellm по нему определяет
> OpenAI-совместимый протокол. Без префикса litellm не найдёт провайдера.
>
> **Reasoning-модели** (your-model-name, o1, o3) тратят токены на `reasoning_content`
> перед ответом: ~200+ токенов на размышление + ~2 на ответ «SKIP»/«OK». Если
> `llm_max_tokens` слишком мал (5), все токены уйдут на reasoning, `content`
> останется пустым. Дефолт `500` — запас для reasoning + ответ.

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
- **Стоп-слова:** посты, содержащие слова из `stop_words` (inline) и `stop_words_file` (файл), отбрасываются. Списки объединяются. Регистронезависимо. Русские слова проходят лемматизацию через `pymorphy3`: стоп-слово «церковь» находит «церковью», «церкви», «церковного». Нерусские слова и аббревиатуры — substring-поиск.
- **Дедупликация:** `is_processed(owner_id, item_id)` в SQLite — пост помечается
  обработанным при успехе, ошибке или исключении
- **Пустой текст:** посты без текста пропускаются
- **Уже лайкнутые:** проверка `aria-label` в браузере (ловит посты, лайкнутые вручную
  вне инструмента, но не записанные в SQLite)
- **LLM-фильтрация (опционально):** при `filter_mode: "llm"` посты классифицируются через
  `litellm.completion()` — LLM определяет тематику и отсеивает нежелательные темы (политика,
  секс, религия, алкоголь, наркотики, азартные игры, оружие, экстремизм, крипта). Ошибка LLM →
  пост пропускается дальше (безопасный fallback). LLM-запросы идут к провайдеру, не к VK — бан-риск нулевой.

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
.env                   — env vars: секреты + не-дефолтные параметры (VK_SERVICE_TOKEN, VK_LLM_API_KEY, ...); в .gitignore
requirements.txt       — зависимости
src/                   — весь код (плоская структура, без __init__.py)
  main.py              — CLI: login | run | test | status | reset + fcntl file lock
  liker.py             — AutoLiker: оркестратор цикла
settings.py             — Settings(BaseSettings): env vars + .env + дефолты (pydantic-settings)
  vk_api_client.py     — VKApiClient: HTTP + rate-limit 3 req/sec + ретраи
  api_search.py        — ApiSearchService: newsfeed.search / wall.get / friends.get / groups.get
  post_filter.py       — FilterChain: DateFilter + EmptyTextFilter + StopWordsFilter + LLMTopicFilter
  stage_llm_filter.py  — LLMFilterStage: pipeline-стадия LLM-фильтрации (опц., после DedupStage)
  vk_browser.py        — VKBrowser: undetected-chromedriver + ActionChains + network retry
  browser_likes.py     — BrowserLikesService: клик по лайку + верификация (data-post-id)
  state_store.py       — StateStore: SQLite (processed_posts, sessions)
  pipeline.py          — Pipeline + PipelineContext + Stage Protocol
  stage_collect.py     — CollectStage: 6 источников, ранний выход, фильтрация inline
  stage_dedup.py       — DedupStage: дедупликация по (owner_id, item_id)
stop_words.txt         — словарь стоп-слов (одна тема — одна строка, # — комментарий)
tests/                 — pytest-тесты + HTML-фикстура для браузерных тестов
chrome_profile/        — профиль Chrome (в .gitignore)
vk_autoliker.db        — SQLite база (в .gitignore)
```

## Тесты

```bash
pytest                                  # 124 passed, 3 deselected (live-тесты пропускаются)
pytest -m "not browser and not live"    # только юнит-тесты, быстрый прогон
pytest -m browser                       # тесты с реальным Chrome (HTML-фикстура)
pytest -m live                          # e2e на живом посте VK (нужен --vk-post=URL)
pytest --cov=src --cov-report=term-missing  # с покрытием (75%)
```

Три уровня:
1. **Mock WebDriver** (116 тестов) — быстрые юнит-тесты, без браузера и сети
2. **HTML-фикстура** (1 тест, маркер `browser`) — локальный `http.server` + headless Chrome против `vk_post.html`
3. **Live** (2 теста, маркер `live`) — e2e на реальном посте VK; `pytest.skip` по умолчанию, запускаются только вручную после `login`

Все пути к БД в тестах подменяются на `tmp_path` — реальная база не затрагивается.
