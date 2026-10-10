---
name: vk-autoliker-conventions
description: Перед любой правкой в src/ или созданием нового сервиса; при работе с VK API, Selenium, SQLite, settings.py.
---

# Конвенции VkAutoLiker

## Когда загружать

- Любая правка в `src/` (код, импорты, селекторы, логика)
- Создание нового сервиса или модуля
- Правка `settings.py`
- Работа с VK API, Selenium, SQLite, браузерными селекторами

## 15 критичных инвариантов (не ломать)

### 1. Рандомизация всех пауз

**Все задержки рандомизируются через `random.uniform(min, max)`.** Фиксированных пауз
в коде быть не должно — это осознанная имитация человека.

Исключения (явно обоснованные):
- `time.sleep(1)` при ретрае ошибки 6
- `time.sleep(5.0)` при сетевом ретрае в `VKApiClient.call()`
- `random.uniform(1, 3)` после клика
- `random.uniform(55, 65)` при сетевом ретрае в `is_logged_in()` (был `time.sleep(60)`,
  исправлено для соблюдения инварианта)

### 2. Rate-limit VK API ≈ 3 запроса/сек

`_min_interval = 0.34` в `VKApiClient`. **Любой новый вызов API обязан идти через
`VKApiClient.call()`** — иначе лимиты и обработка ошибок 6/14 теряются.

### 3. Селектор лайка: aria-label + data-post-id

VK — React-приложение. После клика `aria-label` меняется с
`«Отправить реакцию «Лайк»»` на `«Убрать реакцию «Лайк»»`, элемент нужно искать заново.

**Контейнер поста:** на странице `wall{owner_id}_{item_id}` рендерится лента
с соседними постами, у каждого — своя кнопка лайка. Селектор ограничен контейнером:

```
[data-post-id="{owner_id}_{item_id}"] [aria-label*="Лайк"]
```

Правки селекторов **обязательно** проверять через `pytest -m browser`.

### 4. Признак авторизации — cookie `remixsid`

`VKBrowser.is_logged_in()` перед чтением cookies **обязательно навигирует на `vk.ru`**
(Selenium отдаёт cookie только текущего домена). Без навигации `get_cookies()` вернёт
пустой список — ложное «не авторизован».

### 5. Дедупликация по паре `(owner_id, item_id)`

Первичный ключ в `processed_posts` и `INSERT OR REPLACE`. Помечаются:
успешный лайк (`status=LIKED`) и отфильтрованный пост (`status=FILTERED`).
Провальные попытки (капча, FAILED, исключение) и LLM-таймаут НЕ пишутся в
БД — пост повторяется в следующей сессии. Крах браузера
(`WebDriverException`/`InvalidSessionIdException`) — `break` без
`mark_processed`.

### 6. `owner_id` для групп отрицательный

`groups.get` возвращает положительные ID — они разворачиваются в `-id`.
`resolve_screen_name` для `group`/`page` тоже возвращает `-id`.

### 7. URL постов на домене `vk.ru`

- URL постов: `https://vk.ru/wall{owner_id}_{item_id}` (через `build_post_url()` в `post.py`)
- API: `https://api.vk.ru/method`

### 8. Двухуровневые лимиты

- Дневные (`sessions_per_day`) — проверка до начала сессии
- Пер-сессионные (`likes_per_session_min`/`likes_per_session_max`, `target = random.randint(min, max)`) — внутри цикла лайков
- `finally` всегда закрывает сессию в БД, включая `KeyboardInterrupt`

### 9. `is_processed` фильтруется при сборе

`CollectStage._accept()` в `stages/stage_collect.py` проверяет
`PostsRepository.is_processed()` до стоп-слов и **до** добавления в
`all_posts`. Ранний выход `enough = target_likes * 2` считает только
необработанные посты. `is_processed` стоит раньше стоп-слов намеренно: уже
помеченный `FILTERED` пост не должен повторно доходить до `StopWordsFilter`.

### 10. Друзья и группы перемешиваются, итерируются до early-exit или safety-капа

`get_friends()`/`get_groups()` всегда запрашивают `count=1000` (один API-вызов),
возвращают полный список. `CollectStage` делает `random.shuffle()` и итерирует по всем,
проверяя `is_processed` + `FilterChain` inline. Early-exit при `len(all_posts) >= enough`.
`max_friends_to_collect`/`max_groups_to_collect` — safety-кап на число API-вызовов
`wall.get` (не срез списка): достигнут → `break`.

### 11. Приоритет источников

```
queries → hashtags → groups → accounts → auto_friends → auto_groups
```

Каждый следующий источник собирается только если предыдущие не набрали `enough`
постов. **Финального перемешивания между источниками нет** — лимит лайков
расходуется в порядке приоритета.

### 12. Stale Chrome cleanup перед стартом

`VKBrowser.start()` завершает процессы Chrome, использующие `chrome_profile/`
(через `pgrep` + `SIGTERM`), удаляет lock-файлы (`Singleton*`) и при
превышении `profile_max_size_mb` чистит кэш-подкаталоги `Default/Cache`,
`Default/Code Cache`, `Default/GPUCache`, иначе `SessionNotCreatedException`.
`VKBrowser.close()` делает ту же очистку после `quit()`.

### 13. Конвейер фильтрации (`filter_mode`)

Три режима: `stop_words` (дефолт), `review`, `llm`.

- Словарь `stop_words.txt`: `!` в конце слова = жёсткое, без `!` = мягкое
  (роль — в самом слове; inline `VK_STOP_WORDS` — тот же парсер).
- `StopWordsFilter.matched(post) → StopMatch(words, hard)`: русские слова —
  леммы через pymorphy3, фразы/аббревиатуры — substring.
- `stop_words`: hard → `mark_processed(FILTERED)` при сборе; мягкие
  проходят; LLM не участвует.
- `review`: любое совпадение помечает пост (`PostReview` SOFT/HARD + леммы
  в `review_words`), пост остаётся в пуле; `LLMFilterStage` арбитражет
  только помеченные — единый путь: SKIP → FILTERED, OK → лайк, таймаут →
  непомеченный (повторится в следующей сессии), ошибка LLM → fail-open.
- `llm`: словарь не загружается, LLM проверяет все посты по темам
  `llm_stop_topics`.
- `review`/`llm` без обеих `VK_LLM_MODEL` + `VK_LLM_API_KEY` — ошибка
  валидации при старте (в `stop_words` полуконфигурация LLM не ошибка).

### 14. Кэш закрытых стен

Перед `wall.get` — проверка `ClosedWallsRepository.is_wall_closed(owner_id)`.
Ошибки VK 15/18/30 — `mark_wall_closed`, TTL — `closed_wall_ttl_days` (7).
Экономит ~36% API-вызовов. `CaptchaError` (код 14) НЕ кэшируется —
ре-рейзит наверх (капча-стоп), поэтому `except CaptchaError` в
`stage_collect.py` стоит **перед** `except VKApiError`.

### 15. Эффективный лимит и честные логи

Лимит цикла лайков — `min(target, len(pool))`: пул меньше цели — штатный
исход, не провал («Лайкнут (9/9)»). Лог-строки не должны врать: пауза
«перед следующим постом» — только когда следующий пост реально есть;
досрочное завершение — с причиной; сводки различают категории («отсеяно» /
«пропущено: таймаут»).

## Сеть и ретраи

### Двойной запуск (fcntl.flock)

`main.py` использует `fcntl.flock` exclusive file lock при старте. Второй процесс
(launchd двойной запуск) находит lock занятым и немедленно завершается.

### finally в main()

`liker.close()` в блоке `finally` — любая исключительная ситуация (включая
`KeyboardInterrupt`) закрывает Chrome и не утекает процесс.

### is_logged_in() — сетевой ретрай

3 попытки, пауза `random.uniform(55, 65)` сек между попытками. Возвращает `False`
при всех неудачах. Покрывает сценарий: Mac вышел из сна, WiFi ещё не подключён.

### VKApiClient.call() — сетевой ретрай

3 попытки на `RequestException`, пауза 5 сек. При всех неудачах —
`VKApiError(0, str(e))`.

### Error 6 — ретрай с счётчиком

Цикл с max 3 ретраев (не рекурсия — ранее была бесконечная рекурсия, исправлено).

## Конфигурация и секреты

- **Секреты загружаются из env vars** (`VK_SERVICE_TOKEN`, `VK_LLM_API_KEY`), не из файлов в git.
  Не выводить их в логи, ответы, комментарии, тесты и документацию. В тестах — заглушка `"test_token"`.
- `chrome_profile/`, `*.db`, `*.log`, `.env`, `.autoliker.lock` в `.gitignore`.
- Любые изменения в `Settings` (особенно лимиты и источники) — только с явного
  согласия пользователя: они напрямую влияют на риск блокировки аккаунта.

## Чеклист перед правкой

1. Прочитать затронутый модуль и его тест **до** изменений
2. Проверить, какие инварианты затрагивает правка
3. После правки — `pytest -m "not browser and not live"`
4. При правке DOM-селекторов — обновить `tests/fixtures/vk_post.html` + `pytest -m browser`
5. Не запускать `run`/`test`/`login`/`reset` без явного запроса пользователя
