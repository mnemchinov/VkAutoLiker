# VkAutoLiker

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python)
![Selenium](https://img.shields.io/badge/Selenium-4.15%2B-green?logo=selenium)
![Tests](https://img.shields.io/badge/tests-164%20passed-brightgreen?logo=pytest)
![Coverage](https://img.shields.io/badge/coverage-80%25-brightgreen?logo=pytest)
![SQLite](https://img.shields.io/badge/SQLite-state%20storage-003B57?logo=sqlite)
![Scheduling](https://img.shields.io/badge/scheduling-launchd%20%2B%20Task%20Scheduler-lightgrey)
![Last Commit](https://img.shields.io/github/last-commit/mnemchinov/VkAutoLiker)
![License](https://img.shields.io/badge/license-MIT-blue)

**VkAutoLiker** — это консольная программа на Python, которая **ставит лайки от вашего имени в вашем аккаунте ВКонтакте**, заменяя рутинную ручную работу. Вы сами задаёте, что искать: текстовые запросы, хештеги, стены групп, пользователей, своих друзей и подписок. Программа находит свежие посты и ставит лайк так же, как это сделали бы вы руками — с паузами на «чтение», случайными задержками и дневными лимитами. Это **не сервис накрутки и не массовый лайкер**: никаких чужих аккаунтов, ботов и фейковых профилей — только ваша сессия и ваш обычный Chrome.

Инструмент рассчитан на одного пользователя и один аккаунт — ваш. Массовое лайканье чужих постов с разных аккаунтов не поддерживается и не является целью проекта.

## Отказ от ответственности

**VkAutoLiker** — неофициальный инструмент для автоматизации действий в социальной сети ВКонтакте. Проект не связан с VK, Google, OpenAI, Ollama, litellm или иными упомянутыми сервисами; все товарные знаки принадлежат их правообладателям.

Программа предоставляется **«как есть» (AS IS)**, без каких-либо явных или подразумеваемых гарантий, включая гарантии работоспособности, точности, бесперебойности, совместимости и пригодности для конкретных целей.

**Использование — на ваш риск.** Автоматизированные действия в социальных сетях могут нарушать правила VK, пользовательское соглашение и политики безопасности. Это может привести к капче, временным ограничениям, требованию верификации, снижению видимости, блокировке аккаунта или иным санкциям. Авторы не гарантируют, что аккаунт не будет ограничен.

**Ответственность пользователя.** Вы обязаны:

- соблюдать законодательство своей юрисдикции и правила VK;
- использовать только свои аккаунты, токены и Chrome-профиль либо иметь явное разрешение владельца;
- не применять инструмент для спама, накрутки, травли, мошенничества, распространения запрещённого контента или иных противоправных действий;
- самостоятельно оценивать допустимость автоматизации лайков и сбора данных.

**Секреты и данные.** Файл `.env`, service-токен, VK ID, профиль Chrome, SQLite-база, логи и LLM-ключи хранятся локально. Вы отвечаете за их защиту, резервное копирование и неразглашение. При включении LLM-фильтрации текст постов и сопутствующие данные могут передаваться выбранному вами провайдеру (например, OpenAI, Ollama или иному OpenAI-совместимому endpoint). Ознакомьтесь с политиками этих провайдеров; не отправляйте чувствительные данные.

**Отсутствие гарантий.** API VK, DOM-структура сайта, Selenium, Chrome, undetected-chromedriver и LLM-провайдеры могут меняться без предупреждения. Авторы не обязаны обновлять проект и не гарантируют, что он будет работать в будущем.

**Ограничение ответственности.** В максимально допустимой законом степени авторы и контрибьюторы не несут ответственности за любые прямые или косвенные убытки, потерю аккаунта, данных, прибыли, репутации, юридические последствия или иной вред, возникший из-за использования либо невозможности использования программы.

**Это не юридическая консультация.** Перед использованием проконсультируйтесь с юристом и проверьте актуальные правила VK. Если вы не согласны с условиями — не используйте программу.

**Лицензия MIT** сохраняется; данный отказ от ответственности дополняет её, но не заменяет.

## Архитектура

Гибрид двух каналов:

| Канал | Технология | Назначение |
|---|---|---|
| Чтение/поиск | VK REST API (service-токен) | Поиск постов, стены, друзья, подписки, расшифровка screen_name |
| Лайки | Selenium + Chrome (персистентный профиль) | Клик по кнопке лайка в DOM |

**Причина:** service-токен VK API не поддерживает `likes.add`, поэтому лайки ставятся
только через браузер, а весь поиск и фильтрация — через API.

**Цепочка данных:**
```
VK API (сбор постов)
  → Сбор и фильтрация:
      ├ отсеиваем: старые, пустые, свои посты
      ├ пропускаем уже обработанные (SQLite) — до проверки стоп-слов
      ├ отсеиваем по стоп-словам (если включено), помечаем FILTERED
      ├ 6 источников по приоритету (запросы → хештеги → группы → аккаунты → друзья → подписки)
      ├ случайный порядок внутри каждого источника
      ├ ранний выход: набрали достаточно — остальные источники пропускаем
      └ закрытые/приватные стены запоминаем и больше не запрашиваем (N дней)
  → Дедупликация (по автору + ID поста)
  → LLM-фильтрация (опционально)
  → Selenium (навигация → «чтение» → клик по лайку)
  → проверка в браузере, стоит ли уже лайк → запись в SQLite
```

## Быстрый старт

### Обязательные требования

1. **Google Chrome** — должен быть установлен в системе
2. **Service-токен VK API** — получить на https://dev.vk.ru/ru/admin/create-app,
   скопировать service-ключ в разделе «Ключи доступа».
   Лимит без верификации приложения: 10 000 вызовов/мес.
3. **VK ID пользователя** — числовой ID вашего аккаунта (для сбора постов друзей/подписок)

### Установка

```bash
git clone https://github.com/mnemchinov/VkAutoLiker.git
cd VkAutoLiker
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Заполнить `.env`

Файл `.env` в корне проекта (в `.gitignore`):

```
VK_SERVICE_TOKEN=ваш_service_токен
VK_USER_ID=12345678                     # ваш VK ID (числовой)
VK_HASHTAGS=#вашХештег,#другойХештег    # через запятую (необязательно)
VK_AUTO_FRIENDS=true                    # собирать посты со стен друзей
VK_AUTO_GROUPS=true                     # собирать посты со стен подписок
VK_LLM_API_KEY=ваш_llm_ключ            # только при filter_mode: llm
```

### Первичный вход в VK

```bash
python src/main.py login
```

Откроется Chrome с видимым окном. Войти вручную, пройти 2FA.
Сессия сохранится в `chrome_profile/` — повторный вход не требуется.

Команда `login` форсирует `headless=False` независимо от `Settings` — для 2FA
нужен видимый экран.

### Проверка (один пост)

```bash
python src/main.py test
```

Проверяет API-поиск и ставит один лайк через браузер. Убедитесь, что лайк
появился на стене.

### Боевая сессия

```bash
python src/main.py run             # запуск с учётом дневного лимита
python src/main.py run --no-limit  # ручной запуск без учёта лимита
```

## Команды

Все команды запускаются из корня проекта:

| Команда | Назначение |
|---|---|
| `python src/main.py login` | Первичный вход в VK (видимое окно, 2FA) |
| `python src/main.py run` | Основная сессия лайкинга (с дневным лимитом) |
| `python src/main.py run --no-limit` | Ручной запуск без дневного лимита |
| `python src/main.py test` | Диагностика: поиск + лайк на одном посте |
| `python src/main.py status` | Статистика: сессии/лайки за сегодня и всего |
| `python src/main.py reset` | Очистка SQLite (обработанные посты, сессии, кэш стен) |
| `pytest` | Запуск тестов |
| `pytest -m "not browser and not live"` | Только юнит-тесты (без браузера и сети) |
| `pytest --cov=src --cov-report=term-missing` | Тесты с покрытием |

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
| `max_posts_per_friend` | `VK_MAX_POSTS_PER_FRIEND` | `100` | — | Лимит постов со стены одного друга |
| `max_friends_to_collect` | `VK_MAX_FRIENDS_TO_COLLECT` | `200` | — | Макс. число API-вызовов `wall.get` к друзьям (из всех, случайно) |
| `min_friends_to_poll` | `VK_MIN_FRIENDS_TO_POLL` | `20` | — | Минимум друзей для опроса до раннего выхода по `enough` |
| `max_groups_to_collect` | `VK_MAX_GROUPS_TO_COLLECT` | `200` | — | Макс. число API-вызовов `wall.get` к группам (из всех, случайно) |
| `days_back` | `VK_DAYS_BACK` | `30` | — | Не лайкать посты старше N дней |
| `stop_words` | `VK_STOP_WORDS` | `[]` | `18+,казино` | Стоп-слова inline (дополнительные к файлу, comma-separated) |
| `stop_words_file` | `VK_STOP_WORDS_FILE` | `""` | `stop_words.txt` | Файл стоп-слов: одно слово на строку, `#` — комментарий |
| `filter_mode` | `VK_FILTER_MODE` | `"stop_words"` | `llm` | Режим фильтрации: `"stop_words"` или `"llm"` |

### Лимиты и задержки

Все основные задержки рандомизируются через `random.uniform(min, max)`. Исключения — фиксированные паузы при ретраях ошибок API (1 сек для error 6, 5 сек для сетевых ошибок).

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
| `closed_wall_ttl_days` | `VK_CLOSED_WALL_TTL_DAYS` | `7` | Сколько дней не запрашивать закрытые/приватные стены |
| `profile_max_size_mb` | `VK_PROFILE_MAX_SIZE_MB` | `500` | Лимит размера профиля Chrome (MB) — при превышении чистится кэш при старте и завершении |

### LLM-фильтрация (опционально, `filter_mode: "llm"`)

| Параметр | Env var | По умолч. | Пример в `.env` | Описание |
|---|---|---|---|---|
| `llm_model` | `VK_LLM_MODEL` | `""` | `openai/gpt-4o-mini` | Идентификатор модели (через litellm; префикс `openai/` обязателен — определяет протокол) |
| `llm_api_base` | `VK_LLM_API_BASE` | `""` | `https://api.openai.com/v1` | Базовый URL API (пусто = default провайдера) |
| `llm_api_key` | `VK_LLM_API_KEY` | `""` | `sk-...` | API-ключ провайдера (`SecretStr`, НЕ коммитить; для Ollama — любая непустая строка) |
| `llm_system_prompt` | `VK_LLM_SYSTEM_PROMPT` | (встроенный промпт) | — | Системный промпт (переопределяет сборку из `llm_stop_topics`) |
| `llm_stop_topics` | `VK_LLM_STOP_TOPICS` | (8 тем по умолчанию) | `политика,религия` | Стоп-темы для LLM (comma-separated; встроенный промпт, если `llm_system_prompt` пуст) |
| `llm_timeout` | `VK_LLM_TIMEOUT` | `60` | `10` | Таймаут запроса к LLM (сек; reasoning-модели отвечают за 15–20 сек, запас 60 сек) |
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

**Любая OpenAI-совместимая модель:**

```dotenv
VK_LLM_MODEL=openai/your-model-name
VK_LLM_API_BASE=https://your-endpoint/v1
VK_LLM_API_KEY=sk-...
VK_LLM_SSL_VERIFY=false
```

> **Префикс `openai/`** в `llm_model` обязателен — litellm по нему определяет
> OpenAI-совместимый протокол. Без префикса litellm не найдёт провайдера.
>
> **Reasoning-модели** (o1, o3 и подобные) тратят токены на размышление перед
> ответом: ~200+ токенов на reasoning + ~2 на ответ «SKIP»/«OK». Если
> `llm_max_tokens` слишком мал, все токены уйдут на размышление и ответ
> останется пустым. Дефолт `1000` — запас для reasoning + ответ.

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

**Закрытые стены:** недоступные, удалённые и приватные стены запоминаются в SQLite
и не запрашиваются повторно в течение `closed_wall_ttl_days` (7 дней по умолчанию).
Это экономит значительную часть API-вызовов к друзьям.

## Фильтрация

- **Давность:** посты старше `days_back` дней отбрасываются (дата из API)
- **Уже обработанные:** посты, записанные в SQLite как обработанные, пропускаются.
  Проверяется **до** стоп-слов, поэтому отсеянный по стоп-словам пост (помеченный `FILTERED`)
  не проверяется повторно при следующем сборе.
- **Стоп-слова:** посты, содержащие слова из `stop_words` (inline) и `stop_words_file`
  (файл), отбрасываются и помечаются `FILTERED`. Списки объединяются. Регистронезависимо.
  Русские слова проходят
  лемматизацию через `pymorphy3`: стоп-слово «церковь» находит «церковью», «церкви»,
  «церковного». Нерусские слова и аббревиатуры — substring-поиск.
- **Свои посты:** посты, написанные вашим аккаунтом на чужих стенах, не лайкаются
- **Дубликаты:** повторяющиеся посты (по паре автор + ID) пропускаются
- **Уже лайкнутые:** проверка в браузере — если лайк уже стоит, пост пропускается
  (ловит посты, лайкнутые вручную вне инструмента)
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
- Защита от двойного запуска (на macOS/Linux)
- Retry при сбоях сети в проверке авторизации и API-вызовах

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

**Примечание:** на Windows защита от двойного запуска недоступна — она работает
только на macOS/Linux. Task Scheduler не запускает процесс дважды, поэтому
это не критично.
