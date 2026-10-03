"""Оркестратор: сбор постов через Pipeline → лайки через браузер.

Конвейер (Pipeline) обрабатывает посты через стадии:
CollectStage (6 источников, фильтрация, ранний выход) → DedupStage (дедуп).
AutoLiker создаёт Pipeline в конструкторе и вызвает его в run().
"""

import random
import time

from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

from api_search import ApiSearchService
from browser_likes import BrowserLikesService, LikeResult
from config import AppConfig
from logger import AppLogger
from pipeline import Pipeline, PipelineContext
from post import Post
from post_filter import DateFilter, EmptyTextFilter, FilterChain, StopWordsFilter
from stage_collect import CollectStage
from stage_dedup import DedupStage
from state_store import StateStore
from vk_api_client import CaptchaError, VKApiClient
from vk_browser import VKBrowser


class AutoLiker:
    """Главный оркестратор: связывает API-поиск, фильтрацию, лайки и состояние.

    Архитектура — гибрид: API (service-токен) ищет посты, Selenium кликает лайки.
    Зависимости создаются в конструкторе (DI через config + logger).
    """

    def __init__(self, config: AppConfig, logger: AppLogger):
        """Создает все сервисы (DI через config + logger): API-клиент, поиск, браузер, лайки, состояние."""
        self._config = config
        self._logger = logger

        self._api_client = VKApiClient(config, logger)
        self._search_service = ApiSearchService(self._api_client, logger)
        self._browser = VKBrowser(config, logger)
        self._likes_service = BrowserLikesService(self._browser, config, logger)
        self._state = StateStore(config, logger)
        self._filter = FilterChain([
            DateFilter(config.search.days_back),
            EmptyTextFilter(),
            StopWordsFilter(config, logger),
        ])
        stages: list = [
            CollectStage(self._search_service, config, self._state, self._filter, logger),
            DedupStage(),
        ]
        if config.search.filter_mode == "llm":
            from stage_llm_filter import LLMFilterStage
            stages.append(LLMFilterStage(config, logger))
        self._pipeline = Pipeline(stages)

    def login(self) -> None:
        """Открывает браузер для ручного логина в VK (включая 2FA)."""
        self._browser.login()

    def test(self) -> None:
        """Диагностика: проверяет API-поиск и постановку лайка на одном посте."""
        self._logger.info("=== Тестовый режим ===")

        self._browser.start()
        if not self._browser.is_logged_in():
            self._logger.error("Нет авторизации. Сначала выполните команду 'login'.")
            return

        self._logger.info("Авторизация: OK")

        self._logger.info("Проверка API-поиска...")
        posts: list[Post] = []
        for query in self._config.search.queries[:1]:
            posts = self._search_service.search(query, max_posts=3)
            if posts:
                break

        if not posts:
            for hashtag in self._config.search.hashtags[:1]:
                posts = self._search_service.search_hashtag(hashtag, max_posts=3)
                if posts:
                    break

        if not posts:
            self._logger.warning("Посты не найдены в поиске")
            self._logger.info("=== Тест завершён ===")
            return

        self._logger.info(f"Поиск: найдено {len(posts)} постов")

        test_post = posts[0]
        self._logger.info(f"Проверка лайка на {test_post.owner_id}_{test_post.item_id}")

        result = self._likes_service.like(test_post.owner_id, test_post.item_id)
        if result == LikeResult.LIKED:
            self._logger.info("Тест лайка: OK")
        elif result == LikeResult.ALREADY_LIKED:
            self._logger.info("Лайк уже стоит, путь лайка работает")
        else:
            self._logger.error("Тест лайка: НЕ УДАЛСЯ")

        self._logger.info("=== Тест завершён ===")

    def run(self, no_limit: bool = False) -> None:
        """Основной цикл: сбор постов → лайки с рандомными задержками и лимитами.

        no_limit=True — ручной запуск (--no-limit): дневной лимит не проверяется,
        сессия записывается с is_auto=False и не расходует дневной лимит.
        no_limit=False — авто-запуск (launchd): дневной лимит проверяется и
        сессия записывается с is_auto=True.
        """
        # Jitter для авто-запуска: размывает фиксированные слоты launchd (10:00, 14:00, 19:00)
        if not no_limit:
            jitter = random.uniform(0, 1800)
            self._logger.info(f"Случайная задержка перед стартом: {jitter:.0f} сек")
            time.sleep(jitter)

        if no_limit:
            self._logger.info("=== Сессия AutoLiker запущена (без учёта лимита) ===")
        else:
            self._logger.info("=== Сессия AutoLiker запущена ===")

        self._browser.start()
        if not self._browser.is_logged_in():
            self._logger.error("Нет авторизации. Сначала выполните команду 'login'.")
            return

        if not no_limit:
            sessions_today, _likes_today = self._state.get_daily_stats()
            if sessions_today >= self._config.limits.sessions_per_day:
                self._logger.info(
                    f"Достигнут дневной лимит сессий ({sessions_today}/{self._config.limits.sessions_per_day})"
                )
                return

        session_id = self._state.start_session(is_auto=not no_limit)
        likes_count = 0
        already_liked_count = 0
        captcha_streak = 0
        likes_since_break = 0
        next_break_at = random.randint(5, 10)
        target = random.randint(
            self._config.limits.likes_per_session_min,
            self._config.limits.likes_per_session_max,
        )

        try:
            ctx = PipelineContext(config=self._config, target_likes=target)
            ctx = self._pipeline.run(ctx)
            all_posts = ctx.posts
            if not all_posts:
                self._logger.info("Нет постов после фильтрации")
                return

            self._logger.info(f"Обработка {len(all_posts)} постов")

            for post in all_posts:
                if likes_count >= target:
                    self._logger.info(f"Лимит лайков за сессию достигнут ({likes_count}/{target})")
                    break

                # Стоп-условие: серия капч — VK заподозрил автоматизацию
                if captcha_streak >= self._config.limits.max_captcha_streak:
                    self._logger.warning(
                        f"Превышен лимит капч ({captcha_streak}/{self._config.limits.max_captcha_streak}) — остановка сессии"
                    )
                    break

                if self._state.is_processed(post.owner_id, post.item_id):
                    continue

                try:
                    self._logger.info(f"Лайкаю {post.owner_id}_{post.item_id}: {post.text[:80]}...")

                    result = self._likes_service.like(post.owner_id, post.item_id)

                    if result == LikeResult.LIKED:
                        likes_count += 1
                        likes_since_break += 1
                        captcha_streak = 0
                        self._state.mark_processed(post.owner_id, post.item_id)
                        self._logger.info(
                            f"Лайкнут ({likes_count}/{target})"
                        )
                    elif result == LikeResult.ALREADY_LIKED:
                        already_liked_count += 1
                        captcha_streak = 0
                        self._state.mark_processed(post.owner_id, post.item_id)
                        skip_delay = random.uniform(2, 5)
                        time.sleep(skip_delay)
                        continue
                    elif result == LikeResult.CAPTCHA:
                        captcha_streak += 1
                        self._state.mark_processed(post.owner_id, post.item_id)
                        self._logger.warning(
                            f"Капча ({captcha_streak}/{self._config.limits.max_captcha_streak}): {post.owner_id}_{post.item_id}"
                        )
                    else:  # FAILED
                        self._state.mark_processed(post.owner_id, post.item_id)
                        self._logger.warning(f"Лайк не удался: {post.owner_id}_{post.item_id}")

                except (WebDriverException, InvalidSessionIdException) as e:
                    self._logger.error(f"Крах браузера, остановка сессии: {e}")
                    break
                except Exception as e:
                    self._logger.error(f"Ошибка обработки {post.owner_id}_{post.item_id}: {e}")
                    self._state.mark_processed(post.owner_id, post.item_id)
                    continue

                # Burst-смягчение: каждые 5-10 лайков — длинная пауза «отвлечения»
                if likes_since_break >= next_break_at:
                    long_pause = random.uniform(60, 180)
                    self._logger.info(f"Длинная пауза для имитации отвлечения: {long_pause:.0f} сек")
                    time.sleep(long_pause)
                    likes_since_break = 0
                    next_break_at = random.randint(5, 10)
                else:
                    delay = random.uniform(
                        self._config.limits.min_delay_sec, self._config.limits.max_delay_sec
                    )
                    self._logger.info(f"Пауза {delay:.1f} сек перед следующим постом...")
                    time.sleep(delay)

        except CaptchaError as e:
            self._logger.warning(f"Капча от VK API при сборе постов: {e}")
        except KeyboardInterrupt:
            self._logger.info("Прервано пользователем")
        finally:
            self._state.end_session(session_id, likes_count)
            total_sessions, total_likes = self._state.get_total_stats()
            if already_liked_count > 0:
                self._logger.info(f"Уже лайкнуты: {already_liked_count} постов пропущено")
            self._logger.info(
                f"=== Сессия завершена: лайков {likes_count}. "
                f"Всего: сессий {total_sessions}, лайков {total_likes} ==="
            )

    def status(self) -> None:
        """Выводит статистику сессий и лайков (за сегодня и всего).

        Авто-сессии (launchd) и ручные (--no-limit) показываются раздельно.
        """
        total_sessions, total_likes = self._state.get_total_stats()
        auto_today, auto_likes_today = self._state.get_daily_stats()
        manual_sessions, manual_likes = self._state.get_manual_stats()
        self._logger.info(
            f"Статус: авто сегодня={auto_today}/{self._config.limits.sessions_per_day} "
            f"сессий/{auto_likes_today} лайков, "
            f"ручных={manual_sessions} сессий/{manual_likes} лайков, "
            f"всего={total_sessions} сессий/{total_likes} лайков"
        )

    def reset(self) -> None:
        """Очищает SQLite-базу (обработанные посты и сессии)."""
        self._state.reset()

    def close(self) -> None:
        """Закрывает браузер и базу данных."""
        self._state.close()
        self._browser.close()
