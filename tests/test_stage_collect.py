"""Unit-тесты стадии сбора постов CollectStage.

Все зависимости (ApiSearchService, StateStore, PostFilter) — MagicMock.
"""

import time
from unittest.mock import MagicMock

import pytest

from pipeline import PipelineContext
from post import Post, build_post_url
from stage_collect import CollectStage


def _make_post(owner_id: int, item_id: int, text: str = "текст поста") -> Post:
    """Создаёт тестовый Post с указанными идентификаторами."""
    return Post(
        owner_id=owner_id,
        item_id=item_id,
        text=text,
        date=int(time.time()),
        url=build_post_url(owner_id, item_id),
    )


@pytest.fixture
def collect_stage(mock_config, mock_logger):
    """CollectStage с мок-зависимостями."""
    search = MagicMock()
    state = MagicMock()
    state.is_processed = MagicMock(return_value=False)
    post_filter = MagicMock()
    post_filter.filter = lambda posts: list(posts)

    return CollectStage(search, mock_config, state, post_filter, mock_logger)


class TestCollectStage:
    def test_queries_enough_skips_other_sources(self, collect_stage, mock_config):
        """Если queries дают enough постов — groups/accounts/friends не вызываются."""
        mock_config.search.queries = ["тест"]
        posts = [_make_post(1, i) for i in range(20)]
        collect_stage._search.search = MagicMock(return_value=posts)
        collect_stage._search.search_hashtag = MagicMock(return_value=[])

        ctx = PipelineContext(config=mock_config)
        result = collect_stage.process(ctx)

        assert len(result.posts) == 20
        collect_stage._search.resolve_screen_name.assert_not_called()
        collect_stage._search.get_friends.assert_not_called()

    def test_hashtags_fill_when_queries_empty(self, collect_stage, mock_config):
        """Если queries пусты — hashtags собираются, groups не вызываются."""
        mock_config.search.queries = []
        mock_config.search.hashtags = ["#тест"]
        collect_stage._search.search = MagicMock(return_value=[])
        hashtag_posts = [_make_post(2, i) for i in range(20)]
        collect_stage._search.search_hashtag = MagicMock(return_value=hashtag_posts)

        ctx = PipelineContext(config=mock_config)
        result = collect_stage.process(ctx)

        assert len(result.posts) == 20
        collect_stage._search.resolve_screen_name.assert_not_called()

    def test_early_exit_on_friends(self, collect_stage, mock_config):
        """Ранний выход: enough постов на друзьях → остальные друзья пропускаются."""
        mock_config.search.auto_friends = True
        mock_config.search.auto_groups = False
        mock_config.search.queries = []
        mock_config.search.hashtags = []
        mock_config.search.groups = []
        mock_config.search.accounts = []

        friend_ids = [100 + i for i in range(10)]
        collect_stage._search.get_friends = MagicMock(return_value=friend_ids)

        def wall_side_effect(owner_id, max_posts=10):
            return [_make_post(owner_id, j) for j in range(3)]

        collect_stage._search.get_wall_posts = MagicMock(side_effect=wall_side_effect)

        ctx = PipelineContext(config=mock_config)
        result = collect_stage.process(ctx)

        # enough = likes_per_session * 2 = 5 * 2 = 10
        # 4 друга × 3 поста = 12 ≥ 10 → early exit
        assert len(result.posts) >= 10
        assert collect_stage._search.get_wall_posts.call_count <= 5

    def test_is_processed_filters_during_collection(self, collect_stage, mock_config):
        """Посты, уже обработанные в SQLite, исключаются из результата."""
        posts = [_make_post(1, 1), _make_post(1, 2), _make_post(1, 3)]
        collect_stage._search.search = MagicMock(return_value=posts)
        collect_stage._search.search_hashtag = MagicMock(return_value=[])
        collect_stage._state.is_processed = MagicMock(
            side_effect=lambda owner_id, item_id: (owner_id == 1 and item_id == 2)
        )

        ctx = PipelineContext(config=mock_config)
        result = collect_stage.process(ctx)

        result_ids = [(p.owner_id, p.item_id) for p in result.posts]
        assert (1, 2) not in result_ids
        assert (1, 1) in result_ids
        assert (1, 3) in result_ids

    def test_resolve_screen_name_none_skips_group(self, collect_stage, mock_config):
        """Если resolve_screen_name возвращает None — группа пропускается."""
        mock_config.search.queries = []
        mock_config.search.hashtags = []
        mock_config.search.groups = ["bad_group"]
        mock_config.search.accounts = []
        mock_config.search.auto_friends = False
        mock_config.search.auto_groups = False

        collect_stage._search.resolve_screen_name = MagicMock(return_value=None)
        collect_stage._search.get_wall_posts = MagicMock()

        ctx = PipelineContext(config=mock_config)
        result = collect_stage.process(ctx)

        assert result.posts == []
        collect_stage._search.get_wall_posts.assert_not_called()

    def test_vkapierror_on_wall_get_skips_source(self, collect_stage, mock_config):
        """VKApiError на get_wall_posts — источник пропускается, сбор продолжается."""
        from vk_api_client import VKApiError

        mock_config.search.queries = []
        mock_config.search.hashtags = []
        mock_config.search.groups = ["group1", "group2"]
        mock_config.search.accounts = []
        mock_config.search.auto_friends = False
        mock_config.search.auto_groups = False

        collect_stage._search.resolve_screen_name = MagicMock(side_effect=[-111, -222])
        collect_stage._search.get_wall_posts = MagicMock(
            side_effect=[VKApiError(15, "denied"), [_make_post(-222, 1)]]
        )

        ctx = PipelineContext(config=mock_config)
        result = collect_stage.process(ctx)

        assert len(result.posts) == 1
        assert result.posts[0].owner_id == -222

    def test_dedup_not_here(self, collect_stage, mock_config):
        """CollectStage не дедуплицирует — это работа DedupStage."""
        posts1 = [_make_post(1, 1), _make_post(1, 2)]
        posts2 = [_make_post(1, 2), _make_post(1, 3)]
        collect_stage._search.search = MagicMock(return_value=posts1)
        collect_stage._search.search_hashtag = MagicMock(return_value=posts2)

        ctx = PipelineContext(config=mock_config)
        result = collect_stage.process(ctx)

        # Дубликат (1, 2) остаётся — DedupStage уберёт
        keys = [(p.owner_id, p.item_id) for p in result.posts]
        assert (1, 2) in keys

    def test_groups_fill_when_queries_hashtags_empty(self, collect_stage, mock_config):
        """Если queries и hashtags пусты — groups собираются."""
        mock_config.search.queries = []
        mock_config.search.hashtags = []
        mock_config.search.groups = ["group1"]
        mock_config.search.accounts = []
        mock_config.search.auto_friends = False
        mock_config.search.auto_groups = False

        collect_stage._search.resolve_screen_name = MagicMock(return_value=-111)
        collect_stage._search.get_wall_posts = MagicMock(
            return_value=[_make_post(-111, i) for i in range(5)]
        )

        ctx = PipelineContext(config=mock_config)
        result = collect_stage.process(ctx)

        assert len(result.posts) == 5
