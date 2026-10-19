"""Оркестратор: сбор постов через Pipeline → лайки через браузер.

Конвейер (Pipeline) обрабатывает посты через стадии:
CollectStage (6 источников, фильтрация, ранний выход) → DedupStage (дедуп)
→ LLMFilterStage (только в режимах review/llm, после дедупликации).
StopWordsFilter подключается в режимах stop_words/review: жёсткое слово ('!')
отсекает пост в stop_words, в review любое совпадение помечает пост для
LLM-арбитража.
AutoLiker создаёт Pipeline в конструкторе и вызывает его в run().
"""

import random
import time
from dataclasses import asdict

from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

from api_client import CaptchaError, VKApiClient, VkApiSearchService
from browser import BrowserLikesService, LikeResult, VKBrowser
from database import Database
from logger import AppLogger
from post import Post, PostStatus
from post_filter import DateFilter, EmptyTextFilter, FilterChain, StopWordsFilter
from repositories import ClosedWallsRepository, PostsRepository, SessionsRepository
from settings import Settings
from stages import (
    CollectStage,
    DedupStage,
    LLMFilterStage,
    Pipeline,
    PipelineContext,
    SessionFunnel,
)
from stop_flag import StopFlag


class AutoLiker:
    """Главный оркестратор: связывает API-поиск, фильтрацию, лайки и состояние.

    Архитектура — гибрид: API (service-токен) ищет посты, Selenium кликает лайки.
    Зависимости создаются в конструкторе (DI через config + logger).
    """

    def __init__(self, config: Settings, logger: AppLogger):
        """Создаёт все сервисы (DI через config + logger): API, поиск, браузер, лайки, базу, репозитории."""
        self._config = config
        self._logger = logger

        self._api_client = VKApiClient(config, logger)
        self._search_service = VkApiSearchService(self._api_client, logger)
        self._browser = VKBrowser(config, logger)
        self._likes_service = BrowserLikesService(self._browser, config, logger)
        self._db = Database(config)
        self._posts_repo = PostsRepository(self._db)
        self._sessions_repo = SessionsRepository(self._db)
        self._walls_repo = ClosedWallsRepository(self._db, config)
        self._stop_flag = StopFlag()
        structural = FilterChain([DateFilter(config.days_back), EmptyTextFilter()])
        stop_words = None
        if config.filter_mode in ("stop_words", "review"):
            stop_words = StopWordsFilter(config, logger)
        stages: list = [
            CollectStage(
                self._search_service,
                config,
                self._posts_repo,
                self._walls_repo,
                structural,
                logger,
                stop_words_filter=stop_words,
            ),
            DedupStage(),
        ]
        if config.filter_mode in ("review", "llm"):
            stages.append(LLMFilterStage(config, logger, self._posts_repo))
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
        for query in self._config.queries[:1]:
            posts = self._search_service.search(query, max_posts=3)
            if posts:
                break

        if not posts:
            for hashtag in self._config.hashtags[:1]:
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
        no_limit=False — авто-запуск: дневной лимит проверяется и
        сессия записывается с is_auto=True.
        Порядок: лимит-чек → строка сессии в БД → старт браузера →
        проверка авторизации → jitter: сессия видна в «статусе» сразу
        после запуска, а не через 1-1,5 мин старт-фазы.
        """
        # Флаг остановки снимается в самом начале run() (до старта браузера):
        # позже (после start_session) свежий стоп, нажатый сразу после
        # «Сессия запущена», глотался 60–90 сек — старт браузера и
        # проверка авторизации
        self._stop_flag.clear()
        # Зомби-сессии (ended_at NULL, процесс мёртв) закрываем до start_session:
        # иначе «статус» и отчёт бота видели бы призрака «идущей» сессии
        closed = self._sessions_repo.close_zombie_sessions()
        if closed:
            self._logger.info(f"Зомби-сессий закрыто: {closed}")

        # Дневной лимит проверяем до создания строки сессии: сессия не
        # засчитывает сама себя, а auto-run сверх лимита выходит сразу —
        # без запуска Chrome, проверки авторизации и jitter
        if not no_limit:
            sessions_today, _likes_today = self._sessions_repo.get_daily_stats()
            if sessions_today >= self._config.sessions_per_day:
                self._logger.info(
                    f"Достигнут дневной лимит сессий ({sessions_today}/{self._config.sessions_per_day})"
                )
                return

        # Строка сессии создаётся до запуска браузера: старт Chrome и
        # проверка авторизации занимают 1-1,5 мин, и «статус» из бота,
        # нажатый сразу после «старт», должен видеть идущую сессию
        session_id = self._sessions_repo.start_session(is_auto=not no_limit)
        if no_limit:
            self._logger.info("=== Сессия AutoLiker запущена (без учёта лимита) ===")
        else:
            self._logger.info("=== Сессия AutoLiker запущена ===")

        # Отчёт сессии создаётся до старта браузера: сбой в старт-фазе
        # («нет авторизации») тоже записывается в строку с причиной
        funnel = SessionFunnel()
        self._browser.start()
        if not self._browser.is_logged_in():
            self._logger.error("Нет авторизации. Сначала выполните команду 'login'.")
            funnel.reason = "нет авторизации"
            self._sessions_repo.end_session(session_id, 0, report=asdict(funnel))
            return

        # Jitter для авто-запуска: размывает фиксированные времена запуска
        if not no_limit:
            jitter = random.uniform(0, 1800)
            self._logger.info(f"Случайная задержка перед стартом: {jitter:.0f} сек")
            time.sleep(jitter)
        likes_count = 0
        already_liked_count = 0
        captcha_streak = 0
        likes_since_break = 0
        next_break_at = random.randint(5, 10)
        target = random.randint(
            self._config.likes_per_session_min,
            self._config.likes_per_session_max,
        )

        try:
            ctx = PipelineContext(config=self._config, target_likes=target, funnel=funnel)
            ctx = self._pipeline.run(ctx)
            # Стадии пишут в funnel возвращённого контекста — перепривязываем:
            # конвейер может вернуть другой объект, и отчёт должен быть тем же
            funnel = ctx.funnel
            all_posts = ctx.posts
            if not all_posts:
                self._logger.info("Нет постов после фильтрации")
                funnel.reason = "постов для лайка не нашлось"
                return

            # Эффективный лимит: пул может быть меньше target (на стенах нет
            # свежих постов) — считаем по пулу, чтобы сессия не выглядела провальной
            limit = min(target, len(all_posts))
            if limit < target:
                self._logger.info(
                    f"Пул постов ({len(all_posts)}) меньше цели ({target}) — работаю с полным пулом"
                )

            self._logger.info(f"Обработка {len(all_posts)} постов")

            for index, post in enumerate(all_posts):
                if likes_count >= limit:
                    self._logger.info(f"Лимит лайков за сессию достигнут ({likes_count}/{limit})")
                    # Пул меньше цели — «достигнутый лимит» это просто конец пула
                    funnel.reason = (
                        "лимит лайков сессии" if limit == target else "посты закончились"
                    )
                    break

                # Стоп-условие: файловый флаг (кнопка/команда «стоп» из бота)
                if self._stop_flag.exists():
                    self._logger.info("Получен сигнал остановки — завершение сессии")
                    funnel.reason = "стоп по команде"
                    break

                # Стоп-условие: серия капч — VK заподозрил автоматизацию
                if captcha_streak >= self._config.max_captcha_streak:
                    self._logger.warning(
                        f"Превышен лимит капч ({captcha_streak}/{self._config.max_captcha_streak}) — остановка сессии"
                    )
                    funnel.reason = "капча — стоп"
                    break

                if self._posts_repo.is_processed(post.owner_id, post.item_id):
                    continue

                try:
                    self._logger.info(f"Лайкаю {post.owner_id}_{post.item_id}: {post.text[:80]}...")

                    result = self._likes_service.like(post.owner_id, post.item_id)

                    if result == LikeResult.LIKED:
                        likes_count += 1
                        funnel.liked = likes_count
                        # Промежуточный статус: текущее число лайков видно в status()
                        self._sessions_repo.update_session_likes(session_id, likes_count)
                        likes_since_break += 1
                        captcha_streak = 0
                        self._posts_repo.mark_processed(
                            post.owner_id, post.item_id, PostStatus.LIKED
                        )
                        self._logger.info(f"Лайкнут ({likes_count}/{limit})")
                    elif result == LikeResult.ALREADY_LIKED:
                        already_liked_count += 1
                        funnel.already_liked = already_liked_count
                        captcha_streak = 0
                        self._posts_repo.mark_processed(
                            post.owner_id, post.item_id, PostStatus.LIKED
                        )
                        skip_delay = random.uniform(2, 5)
                        time.sleep(skip_delay)
                        continue
                    elif result == LikeResult.CAPTCHA:
                        captcha_streak += 1
                        self._logger.warning(
                            f"Капча ({captcha_streak}/{self._config.max_captcha_streak}): {post.owner_id}_{post.item_id}"
                        )
                    else:  # FAILED
                        funnel.failed += 1
                        self._logger.warning(f"Лайк не удался: {post.owner_id}_{post.item_id}")

                except (WebDriverException, InvalidSessionIdException) as e:
                    self._logger.error(f"Крах браузера, остановка сессии: {e}")
                    funnel.reason = "крах браузера"
                    break
                except Exception as e:
                    funnel.failed += 1
                    self._logger.error(f"Ошибка обработки {post.owner_id}_{post.item_id}: {e}")
                    continue

                # Не засыпаем, если цикл не продолжится: последний пост пула,
                # лимит достигнут или сработал капча-стоп
                if (
                    index == len(all_posts) - 1
                    or likes_count >= limit
                    or captcha_streak >= self._config.max_captcha_streak
                ):
                    continue

                # Burst-смягчение: каждые 5-10 лайков — длинная пауза «отвлечения»
                if likes_since_break >= next_break_at:
                    long_pause = random.uniform(60, 180)
                    self._logger.info(
                        f"Длинная пауза для имитации отвлечения: {long_pause:.0f} сек"
                    )
                    time.sleep(long_pause)
                    likes_since_break = 0
                    next_break_at = random.randint(5, 10)
                else:
                    delay = random.uniform(self._config.min_delay_sec, self._config.max_delay_sec)
                    self._logger.info(f"Пауза {delay:.1f} сек перед следующим постом...")
                    time.sleep(delay)

            # Посты закончились или цикл прерван, а лимит не достигнут —
            # причина досрочного конца всегда видна в логе
            if likes_count < limit:
                self._logger.info(f"Досрочное завершение: лайков {likes_count}/{limit}")

            # Причина не установлена в break-ветках — нормальный выход цикла:
            # либо лимит цели достигнут на последнем посте (break не сработал),
            # либо посты закончились раньше лимита
            if not funnel.reason:
                if likes_count >= limit and limit == target:
                    funnel.reason = "лимит лайков сессии"
                else:
                    funnel.reason = "посты закончились"

        except CaptchaError as e:
            self._logger.warning(f"Капча от VK API при сборе постов: {e}")
            funnel.reason = "капча от API при сборе"
        except KeyboardInterrupt:
            self._logger.info("Прервано пользователем")
            funnel.reason = "прервано пользователем"
        finally:
            self._sessions_repo.end_session(session_id, likes_count, report=asdict(funnel))
            total_sessions, total_likes = self._sessions_repo.get_total_stats()
            if already_liked_count > 0:
                self._logger.info(f"Уже лайкнуты: {already_liked_count} постов пропущено")
            self._logger.info(
                f"=== Сессия завершена: лайков {likes_count}. "
                f"Всего: сессий {total_sessions}, лайков {total_likes} ==="
            )

    def reset(self) -> None:
        """Очищает SQLite-базу (обработанные посты, сессии, кэш стен)."""
        self._posts_repo.reset()
        self._sessions_repo.reset()
        self._walls_repo.reset()

    def close(self) -> None:
        """Закрывает браузер и базу данных.

        Без browser.close() Chrome остаётся висеть после завершения процесса
        и держит профиль — следующий запуск падает с SessionNotCreatedException.
        """
        self._browser.close()
        self._db.close()
