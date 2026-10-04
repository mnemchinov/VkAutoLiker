"""Стадия сбора постов: 6 источников с приоритетом и ранним выходом.

Источники в порядке приоритета: queries → hashtags → groups → accounts →
auto_friends → auto_groups. Каждый следующий источник подключается только
если предыдущие не набрали enough постов.

Внутри каждого источника посты перемешиваются (random.shuffle) перед добавлением.
Фильтрация: structural (days_back + пустой текст) + stop_words (стоп-слова,
маркировка FILTERED) + PostsRepository (is_processed) + свои посты (from_id).
"""

import random

from api import ApiSearchService, VKApiError
from logger import AppLogger
from post import Post, PostStatus
from post_filter import FilterChain, StopWordsFilter
from repositories import ClosedWallsRepository, PostsRepository
from settings import Settings

from .pipeline import PipelineContext


class CollectStage:
    """Собирает необработанные посты с приоритетом источников.

    Порядок сбора = порядок лайков: лимит расходуется на queries сначала.
    Внутри каждого источника порядок рандомизируется.
    Ранний выход при достижении enough = target_likes * 2.
    """

    def __init__(
        self,
        search_service: ApiSearchService,
        config: Settings,
        posts_repo: PostsRepository,
        walls_repo: ClosedWallsRepository,
        structural_filter: FilterChain,
        logger: AppLogger,
        stop_words_filter: StopWordsFilter | None = None,
    ):
        """Инициализирует стадию сбора с сервисами и конфигурацией.

        structural_filter — дата + пустой текст (без маркировки).
        stop_words_filter — стоп-слова (отсеянные посты маркируются FILTERED).
        """
        self._search = search_service
        self._config = config
        self._posts_repo = posts_repo
        self._walls_repo = walls_repo
        self._structural = structural_filter
        self._stop_words = stop_words_filter
        self._logger = logger

    def process(self, ctx: PipelineContext) -> PipelineContext:
        """Собирает посты из 6 источников с приоритетом и ранним выходом."""
        if ctx.target_likes <= 0:
            self._logger.warning("target_likes <= 0 — сбор постов пропущен")
            ctx.posts = []
            return ctx

        all_posts: list[Post] = []
        enough = ctx.target_likes * 2

        def _accept(posts: list[Post]) -> None:
            """Фильтрует построчно: structural → stop_words (FILTERED) → is_processed → свои посты."""
            fresh: list[Post] = []
            for p in posts:
                if self._structural.should_skip(p):
                    continue
                if self._stop_words is not None and self._stop_words.should_skip(p):
                    self._posts_repo.mark_processed(p.owner_id, p.item_id, PostStatus.FILTERED)
                    continue
                if self._posts_repo.is_processed(p.owner_id, p.item_id):
                    continue
                if p.from_id == self._config.user_id:
                    continue
                fresh.append(p)
            random.shuffle(fresh)
            all_posts.extend(fresh)

        for query in self._config.queries:
            posts = self._search.search(query, max_posts=self._config.max_posts_per_query)
            _accept(posts)

        if len(all_posts) >= enough:
            self._logger.info(f"Достаточно постов ({len(all_posts)}), пропуск hashtags")
        else:
            for hashtag in self._config.hashtags:
                posts = self._search.search_hashtag(
                    hashtag, max_posts=self._config.max_posts_per_hashtag
                )
                _accept(posts)

        if len(all_posts) < enough:
            for screen_name in self._config.groups:
                owner_id = self._search.resolve_screen_name(screen_name)
                if owner_id is None:
                    self._logger.warning(f"Не удалось определить ID группы: {screen_name}")
                    continue
                if self._walls_repo.is_wall_closed(owner_id):
                    self._logger.info(f"Стена группы {screen_name} закрыта (кэш), пропуск")
                    continue
                try:
                    posts = self._search.get_wall_posts(
                        owner_id, max_posts=self._config.max_posts_per_group
                    )
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов группы {screen_name}: {e}")
                    self._walls_repo.mark_wall_closed(owner_id)
                    continue
                _accept(posts)

        if len(all_posts) < enough:
            for screen_name in self._config.accounts:
                owner_id = self._search.resolve_screen_name(screen_name)
                if owner_id is None:
                    self._logger.warning(f"Не удалось определить ID пользователя: {screen_name}")
                    continue
                if self._walls_repo.is_wall_closed(owner_id):
                    self._logger.info(f"Стена пользователя {screen_name} закрыта (кэш), пропуск")
                    continue
                try:
                    posts = self._search.get_wall_posts(
                        owner_id, max_posts=self._config.max_posts_per_account
                    )
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов пользователя {screen_name}: {e}")
                    self._walls_repo.mark_wall_closed(owner_id)
                    continue
                _accept(posts)

        if len(all_posts) < enough and self._config.auto_friends and self._config.user_id:
            try:
                friend_ids = self._search.get_friends(self._config.user_id)
            except VKApiError as e:
                self._logger.warning(f"Не удалось получить список друзей: {e}")
                friend_ids = []
            random.shuffle(friend_ids)
            api_calls = 0
            for fid in friend_ids:
                if len(all_posts) >= enough:
                    self._logger.info(
                        f"Достаточно постов ({len(all_posts)}), пропуск остальных друзей"
                    )
                    break
                if api_calls >= self._config.max_friends_to_collect:
                    self._logger.info(f"Достигнут лимит API-вызовов к друзьям ({api_calls})")
                    break
                api_calls += 1
                if self._walls_repo.is_wall_closed(fid):
                    continue
                try:
                    posts = self._search.get_wall_posts(
                        fid, max_posts=self._config.max_posts_per_friend
                    )
                    _accept(posts)
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов друга {fid}: {e}")
                    self._walls_repo.mark_wall_closed(fid)
                    continue

        if len(all_posts) < enough and self._config.auto_groups and self._config.user_id:
            try:
                group_ids = self._search.get_groups(self._config.user_id)
            except VKApiError as e:
                self._logger.warning(f"Не удалось получить список групп: {e}")
                group_ids = []
            random.shuffle(group_ids)
            api_calls = 0
            for gid in group_ids:
                if len(all_posts) >= enough:
                    self._logger.info(
                        f"Достаточно постов ({len(all_posts)}), пропуск остальных групп"
                    )
                    break
                if api_calls >= self._config.max_groups_to_collect:
                    self._logger.info(f"Достигнут лимит API-вызовов к группам ({api_calls})")
                    break
                api_calls += 1
                if self._walls_repo.is_wall_closed(gid):
                    continue
                try:
                    posts = self._search.get_wall_posts(
                        gid, max_posts=self._config.max_posts_per_group
                    )
                    _accept(posts)
                except VKApiError as e:
                    self._logger.warning(f"Ошибка получения постов группы {gid}: {e}")
                    self._walls_repo.mark_wall_closed(gid)
                    continue

        self._logger.info(f"Собрано {len(all_posts)} необработанных постов")
        self._structural.log_summaries()
        if self._stop_words is not None:
            self._stop_words.log_summary()
        ctx.posts = all_posts
        return ctx
