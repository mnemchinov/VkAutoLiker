"""Оркестратор: сбор постов через API → фильтрация → лайки через браузер."""

import random
import time
from typing import List

from config import AppConfig
from logger import AppLogger
from post import Post
from post_filter import PostFilter
from state_store import StateStore
from vk_browser import VKBrowser
from vk_api_client import VKApiClient, VKApiError
from api_search import ApiSearchService
from browser_likes import BrowserLikesService


class AutoLiker:
    """Главный оркестратор: связывает API-поиск, фильтрацию, лайки и состояние.

    Архитектура — гибрид: API (service-токен) ищет посты, Selenium кликает лайки.
    Зависимости создаются в конструкторе (DI через config + logger).
    """

    def __init__(self, config: AppConfig, logger: AppLogger):
        self._config = config
        self._logger = logger

        self._api_client = VKApiClient(config, logger)
        self._search_service = ApiSearchService(self._api_client, logger)
        self._browser = VKBrowser(config, logger)
        self._likes_service = BrowserLikesService(self._browser, config, logger)
        self._state = StateStore(config, logger)
        self._filter = PostFilter(config, self._state, logger)

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
        posts: List[Post] = []
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

        liked = self._likes_service.is_liked(test_post.owner_id, test_post.item_id)
        self._logger.info(f"Лайк уже стоит: {liked}")

        if not liked:
            success = self._likes_service.like(test_post.owner_id, test_post.item_id)
            if success:
                self._logger.info("Тест лайка: OK")
            else:
                self._logger.error("Тест лайка: НЕ УДАЛСЯ")
        else:
            self._logger.info("Лайк уже стоит, путь лайка работает")

        self._logger.info("=== Тест завершён ===")

    def run(self) -> None:
        """Основной цикл: сбор постов → лайки с рандомными задержками и лимитами."""
        self._logger.info("=== Сессия AutoLiker запущена ===")

        self._browser.start()
        if not self._browser.is_logged_in():
            self._logger.error("Нет авторизации. Сначала выполните команду 'login'.")
            return

        sessions_today, likes_today = self._state.get_daily_stats()
        if sessions_today >= self._config.limits.sessions_per_day:
            self._logger.info(
                f"Достигнут дневной лимит сессий ({sessions_today}/{self._config.limits.sessions_per_day})"
            )
            return

        session_id = self._state.start_session()
        likes_count = 0
        already_liked_count = 0

        try:
            all_posts = self._collect_posts()
            if not all_posts:
                self._logger.info("Нет постов после фильтрации")
                return

            self._logger.info(f"Обработка {len(all_posts)} постов")

            for post in all_posts:
                if likes_count >= self._config.limits.likes_per_session:
                    self._logger.info(f"Лимит лайков за сессию достигнут ({likes_count})")
                    break

                if self._state.is_processed(post.owner_id, post.item_id):
                    continue

                try:
                    liked = self._likes_service.is_liked(post.owner_id, post.item_id)
                    if liked:
                        self._state.mark_processed(post.owner_id, post.item_id)
                        already_liked_count += 1
                        self._logger.info(f"Уже лайкнут: {post.owner_id}_{post.item_id}")
                        continue

                    self._logger.info(f"Лайкаю {post.owner_id}_{post.item_id}: {post.text[:80]}...")

                    success = self._likes_service.like(post.owner_id, post.item_id)
                    if success:
                        likes_count += 1
                        self._state.mark_processed(post.owner_id, post.item_id)
                        self._logger.info(
                            f"Лайкнут ({likes_count}/{self._config.limits.likes_per_session})"
                        )
                    else:
                        self._state.mark_processed(post.owner_id, post.item_id)
                        self._logger.warning(f"Лайк не удался: {post.owner_id}_{post.item_id}")

                except Exception as e:
                    self._logger.error(f"Ошибка обработки {post.owner_id}_{post.item_id}: {e}")
                    self._state.mark_processed(post.owner_id, post.item_id)
                    continue

                delay = random.uniform(
                    self._config.limits.min_delay_sec, self._config.limits.max_delay_sec
                )
                self._logger.info(f"Пауза {delay:.1f} сек перед следующим постом...")
                time.sleep(delay)

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
        """Выводит статистику сессий и лайков (за сегодня и всего)."""
        total_sessions, total_likes = self._state.get_total_stats()
        sessions_today, likes_today = self._state.get_daily_stats()
        self._logger.info(
            f"Статус: сегодня={sessions_today} сессий/{likes_today} лайков, "
            f"всего={total_sessions} сессий/{total_likes} лайков"
        )

    def reset(self) -> None:
        """Очищает SQLite-базу (обработанные посты и сессии)."""
        self._state.reset()

    def close(self) -> None:
        """Закрывает браузер и базу данных."""
        self._state.close()
        self._browser.close()

    def _collect_posts(self) -> List[Post]:
        """Собирает необработанные посты с приоритетом: queries → hashtags →
        groups → accounts → auto_friends → auto_groups.

        Порядок сбора = порядок лайков: лимит расходуется на queries сначала.
        Внутри каждого источника порядок рандомизируется.
        Фильтр: PostFilter (давность/пустой текст) + SQLite (is_processed).
        Дедупликация по (owner_id, item_id). Ранний выход при достижении enough.
        """
        all_posts: List[Post] = []
        enough = self._config.limits.likes_per_session * 2

        def _accept(posts: List[Post]) -> None:
            """Фильтрует (PostFilter + SQLite is_processed), шафлит, добавляет в all_posts."""
            filtered = self._filter.filter(posts)
            fresh = [p for p in filtered if not self._state.is_processed(p.owner_id, p.item_id)]
            random.shuffle(fresh)
            all_posts.extend(fresh)

        for query in self._config.search.queries:
            posts = self._search_service.search(
                query, max_posts=self._config.search.max_posts_per_query
            )
            _accept(posts)

        for hashtag in self._config.search.hashtags:
            posts = self._search_service.search_hashtag(
                hashtag, max_posts=self._config.search.max_posts_per_hashtag
            )
            _accept(posts)

        if len(all_posts) < enough:
            for screen_name in self._config.search.groups:
                owner_id = self._search_service.resolve_screen_name(screen_name)
                if owner_id is None:
                    self._logger.warning(f"Не удалось определить ID группы: {screen_name}")
                    continue
                try:
                    posts = self._search_service.get_wall_posts(
                        owner_id, max_posts=self._config.search.max_posts_per_group
                    )
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов группы {screen_name}: {e}")
                    continue
                _accept(posts)

        if len(all_posts) < enough:
            for screen_name in self._config.search.accounts:
                owner_id = self._search_service.resolve_screen_name(screen_name)
                if owner_id is None:
                    self._logger.warning(f"Не удалось определить ID пользователя: {screen_name}")
                    continue
                try:
                    posts = self._search_service.get_wall_posts(
                        owner_id, max_posts=self._config.search.max_posts_per_account
                    )
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов пользователя {screen_name}: {e}")
                    continue
                _accept(posts)

        if len(all_posts) < enough and self._config.search.auto_friends and self._config.search.user_id:
            try:
                friend_ids = self._search_service.get_friends(
                    self._config.search.user_id,
                    max_count=self._config.search.max_friends_to_collect,
                )
            except VKApiError as e:
                self._logger.warning(f"Не удалось получить список друзей: {e}")
                friend_ids = []
            random.shuffle(friend_ids)
            for fid in friend_ids[:self._config.search.max_friends_to_collect]:
                if len(all_posts) >= enough:
                    self._logger.info(f"Достаточно постов ({len(all_posts)}), пропуск остальных друзей")
                    break
                try:
                    posts = self._search_service.get_wall_posts(
                        fid, max_posts=self._config.search.max_posts_per_friend
                    )
                    _accept(posts)
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов друга {fid}: {e}")
                    continue

        if len(all_posts) < enough and self._config.search.auto_groups and self._config.search.user_id:
            try:
                group_ids = self._search_service.get_groups(
                    self._config.search.user_id,
                    max_count=self._config.search.max_groups_to_collect,
                )
            except VKApiError as e:
                self._logger.warning(f"Не удалось получить список групп: {e}")
                group_ids = []
            random.shuffle(group_ids)
            for gid in group_ids[:self._config.search.max_groups_to_collect]:
                if len(all_posts) >= enough:
                    self._logger.info(f"Достаточно постов ({len(all_posts)}), пропуск остальных групп")
                    break
                try:
                    posts = self._search_service.get_wall_posts(
                        gid, max_posts=self._config.search.max_posts_per_group
                    )
                    _accept(posts)
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов группы {gid}: {e}")
                    continue

        unique: dict = {}
        for p in all_posts:
            key = (p.owner_id, p.item_id)
            if key not in unique:
                unique[key] = p

        self._logger.info(f"Собрано {len(unique)} необработанных постов")
        return list(unique.values())
