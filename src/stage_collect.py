"""Стадия сбора постов: 6 источников с приоритетом и ранним выходом.

Источники в порядке приоритета: queries → hashtags → groups → accounts →
auto_friends → auto_groups. Каждый следующий источник подключается только
если предыдущие не набрали enough постов.

Внутри каждого источника посты шафлятся (random.shuffle) перед добавлением.
Фильтрация: PostFilter (days_back + пустой текст) + StateStore (is_processed).
"""

import random
from typing import List

from api_search import ApiSearchService
from config import AppConfig
from logger import AppLogger
from pipeline import PipelineContext
from post import Post
from post_filter import PostFilter
from state_store import StateStore
from vk_api_client import VKApiError


class CollectStage:
    """Собирает необработанные посты с приоритетом источников.

    Порядок сбора = порядок лайков: лимит расходуется на queries сначала.
    Внутри каждого источника порядок рандомизируется.
    Ранний выход при достижении enough = likes_per_session * 2.
    """

    def __init__(
        self,
        search_service: ApiSearchService,
        config: AppConfig,
        state_store: StateStore,
        post_filter: PostFilter,
        logger: AppLogger,
    ):
        """Инициализирует стадию сбора с сервисами и конфигурацией."""
        self._search = search_service
        self._config = config
        self._state = state_store
        self._filter = post_filter
        self._logger = logger

    def process(self, ctx: PipelineContext) -> PipelineContext:
        """Собирает посты из 6 источников с приоритетом и ранним выходом."""
        all_posts: List[Post] = []
        enough = self._config.limits.likes_per_session * 2

        def _accept(posts: List[Post]) -> None:
            """Фильтрует (PostFilter + is_processed), шафлит, добавляет в all_posts."""
            filtered = self._filter.filter(posts)
            fresh = [
                p for p in filtered
                if not self._state.is_processed(p.owner_id, p.item_id)
            ]
            random.shuffle(fresh)
            all_posts.extend(fresh)

        for query in self._config.search.queries:
            posts = self._search.search(
                query, max_posts=self._config.search.max_posts_per_query
            )
            _accept(posts)

        for hashtag in self._config.search.hashtags:
            posts = self._search.search_hashtag(
                hashtag, max_posts=self._config.search.max_posts_per_hashtag
            )
            _accept(posts)

        if len(all_posts) < enough:
            for screen_name in self._config.search.groups:
                owner_id = self._search.resolve_screen_name(screen_name)
                if owner_id is None:
                    self._logger.warning(f"Не удалось определить ID группы: {screen_name}")
                    continue
                try:
                    posts = self._search.get_wall_posts(
                        owner_id, max_posts=self._config.search.max_posts_per_group
                    )
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов группы {screen_name}: {e}")
                    continue
                _accept(posts)

        if len(all_posts) < enough:
            for screen_name in self._config.search.accounts:
                owner_id = self._search.resolve_screen_name(screen_name)
                if owner_id is None:
                    self._logger.warning(f"Не удалось определить ID пользователя: {screen_name}")
                    continue
                try:
                    posts = self._search.get_wall_posts(
                        owner_id, max_posts=self._config.search.max_posts_per_account
                    )
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов пользователя {screen_name}: {e}")
                    continue
                _accept(posts)

        if len(all_posts) < enough and self._config.search.auto_friends and self._config.search.user_id:
            try:
                friend_ids = self._search.get_friends(
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
                    posts = self._search.get_wall_posts(
                        fid, max_posts=self._config.search.max_posts_per_friend
                    )
                    _accept(posts)
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов друга {fid}: {e}")
                    continue

        if len(all_posts) < enough and self._config.search.auto_groups and self._config.search.user_id:
            try:
                group_ids = self._search.get_groups(
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
                    posts = self._search.get_wall_posts(
                        gid, max_posts=self._config.search.max_posts_per_group
                    )
                    _accept(posts)
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов группы {gid}: {e}")
                    continue

        self._logger.info(f"Собрано {len(all_posts)} необработанных постов")
        ctx.posts = all_posts
        return ctx
