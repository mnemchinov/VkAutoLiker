"""Unit-тесты стадии сбора постов CollectStage.

Все зависимости (VkApiSearchService, PostsRepository, ClosedWallsRepository, FilterChain) — MagicMock.
"""

import time
from unittest.mock import MagicMock

import pytest

from post import Post, PostReview, PostStatus, build_post_url
from post_filter import StopMatch
from stages import CollectStage, PipelineContext


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
    posts_repo = MagicMock()
    posts_repo.is_processed = MagicMock(return_value=False)
    posts_repo.mark_processed = MagicMock()
    walls_repo = MagicMock()
    walls_repo.is_wall_closed = MagicMock(return_value=False)
    structural = MagicMock()
    structural.should_skip = MagicMock(return_value=False)
    structural.log_summaries = MagicMock()
    stop_words = MagicMock()
    stop_words.matched = MagicMock(return_value=None)
    stop_words.log_summary = MagicMock()

    return CollectStage(
        search,
        mock_config,
        posts_repo,
        walls_repo,
        structural,
        mock_logger,
        stop_words_filter=stop_words,
    )


class TestCollectStage:
    def test_queries_enough_skips_other_sources(self, collect_stage, mock_config):
        """Если queries дают enough постов — groups/accounts/friends не вызываются."""
        mock_config.queries = ["тест"]
        posts = [_make_post(1, i) for i in range(20)]
        collect_stage._search.search = MagicMock(return_value=posts)
        collect_stage._search.search_hashtag = MagicMock(return_value=[])

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        assert len(result.posts) == 20
        collect_stage._search.resolve_screen_name.assert_not_called()
        collect_stage._search.get_friends.assert_not_called()

    def test_hashtags_fill_when_queries_empty(self, collect_stage, mock_config):
        """Если queries пусты — hashtags собираются, groups не вызываются."""
        mock_config.queries = []
        mock_config.hashtags = ["#тест"]
        collect_stage._search.search = MagicMock(return_value=[])
        hashtag_posts = [_make_post(2, i) for i in range(20)]
        collect_stage._search.search_hashtag = MagicMock(return_value=hashtag_posts)

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        assert len(result.posts) == 20
        collect_stage._search.resolve_screen_name.assert_not_called()

    def test_early_exit_on_friends(self, collect_stage, mock_config):
        """Ранний выход: enough постов на друзьях → остальные друзья пропускаются."""
        mock_config.auto_friends = True
        mock_config.auto_groups = False
        mock_config.queries = []
        mock_config.hashtags = []
        mock_config.groups = []
        mock_config.accounts = []

        friend_ids = [100 + i for i in range(10)]
        collect_stage._search.get_friends = MagicMock(return_value=friend_ids)

        def wall_side_effect(owner_id, max_posts=10):
            return [_make_post(owner_id, j) for j in range(3)]

        collect_stage._search.get_wall_posts = MagicMock(side_effect=wall_side_effect)

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        # enough = target_likes * 2 = 5 * 2 = 10
        # 4 друга × 3 поста = 12 ≥ 10 → early exit
        assert len(result.posts) >= 10
        assert collect_stage._search.get_wall_posts.call_count <= 5

    def test_is_processed_filters_during_collection(self, collect_stage, mock_config):
        """Посты, уже обработанные в SQLite, исключаются из результата."""
        posts = [_make_post(1, 1), _make_post(1, 2), _make_post(1, 3)]
        collect_stage._search.search = MagicMock(return_value=posts)
        collect_stage._search.search_hashtag = MagicMock(return_value=[])
        collect_stage._posts_repo.is_processed = MagicMock(
            side_effect=lambda owner_id, item_id: (owner_id == 1 and item_id == 2)
        )

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        result_ids = [(p.owner_id, p.item_id) for p in result.posts]
        assert (1, 2) not in result_ids
        assert (1, 1) in result_ids
        assert (1, 3) in result_ids

    def test_hard_stop_word_filters_post(self, collect_stage, mock_config):
        """Жёсткое стоп-слово (stop_words-режим) → mark_processed(FILTERED), не повторится."""
        mock_config.queries = ["тест"]
        good_post = _make_post(1, 1, "хороший пост")
        bad_post = _make_post(1, 2, "пост про политика")
        collect_stage._search.search = MagicMock(return_value=[good_post, bad_post])
        collect_stage._search.search_hashtag = MagicMock(return_value=[])
        collect_stage._stop_words.matched = MagicMock(
            side_effect=lambda p: StopMatch(words=["политика"], hard=True)
            if "политика" in p.text
            else None
        )

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        result_ids = [(p.owner_id, p.item_id) for p in result.posts]
        assert (1, 1) in result_ids
        assert (1, 2) not in result_ids
        collect_stage._posts_repo.mark_processed.assert_called_once_with(1, 2, PostStatus.FILTERED)

    def test_soft_stop_word_passes(self, collect_stage, mock_config):
        """Мягкое стоп-слово (stop_words-режим) — пост проходит, без маркировки."""
        mock_config.queries = ["тест"]
        soft_post = _make_post(1, 2, "пост про карабин")
        collect_stage._search.search = MagicMock(return_value=[soft_post])
        collect_stage._search.search_hashtag = MagicMock(return_value=[])
        collect_stage._stop_words.matched = MagicMock(
            return_value=StopMatch(words=["карабин"], hard=False)
        )

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        result_ids = [(p.owner_id, p.item_id) for p in result.posts]
        assert (1, 2) in result_ids
        collect_stage._posts_repo.mark_processed.assert_not_called()

    def test_review_mode_marks_post(self, collect_stage, mock_config):
        """review-режим: совпадение помечает пост (review + review_words), без mark_processed."""
        mock_config.queries = ["тест"]
        mock_config.filter_mode = "review"
        marked_post = _make_post(1, 2, "пост про карабин")
        collect_stage._search.search = MagicMock(return_value=[marked_post])
        collect_stage._search.search_hashtag = MagicMock(return_value=[])
        collect_stage._stop_words.matched = MagicMock(
            return_value=StopMatch(words=["карабин"], hard=False)
        )

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        assert len(result.posts) == 1
        assert result.posts[0].review == PostReview.SOFT
        assert result.posts[0].review_words == ["карабин"]
        collect_stage._posts_repo.mark_processed.assert_not_called()

    def test_is_processed_checked_before_stop_words(self, collect_stage, mock_config):
        """Уже обработанный пост не доходит до stop_words — стоп-слова не вызываются.

        Регрессия: при проверке стоп-слов ДО is_processed пост, помеченный FILTERED,
        снова доходил до StopWordsFilter и снова маркировался при следующем сборе.
        """
        mock_config.queries = ["тест"]
        processed_post = _make_post(1, 2, "пост про политика")
        collect_stage._search.search = MagicMock(return_value=[processed_post])
        collect_stage._search.search_hashtag = MagicMock(return_value=[])
        collect_stage._posts_repo.is_processed = MagicMock(return_value=True)
        collect_stage._stop_words.matched = MagicMock(
            return_value=StopMatch(words=["политика"], hard=True)
        )

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        assert result.posts == []
        collect_stage._stop_words.matched.assert_not_called()
        collect_stage._posts_repo.mark_processed.assert_not_called()

    def test_structural_filter_not_marked(self, collect_stage, mock_config):
        """Пост отсеян structural (дата/пустой текст) → БЕЗ mark_processed."""
        mock_config.queries = ["тест"]
        good_post = _make_post(1, 1, "хороший пост")
        old_post = _make_post(1, 2, "старый пост")
        collect_stage._search.search = MagicMock(return_value=[good_post, old_post])
        collect_stage._search.search_hashtag = MagicMock(return_value=[])
        collect_stage._structural.should_skip = MagicMock(side_effect=lambda p: p.item_id == 2)

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        result_ids = [(p.owner_id, p.item_id) for p in result.posts]
        assert (1, 1) in result_ids
        assert (1, 2) not in result_ids
        collect_stage._posts_repo.mark_processed.assert_not_called()

    def test_own_posts_filtered(self, collect_stage, mock_config):
        """Посты, где from_id == user_id, исключаются — лайкать свои посты не нужно."""
        mock_config.queries = ["тест"]
        own_post = _make_post(-111, 1, "свой пост")
        own_post.from_id = mock_config.user_id
        other_post = _make_post(-111, 2, "чужой пост")
        other_post.from_id = 99999
        collect_stage._search.search = MagicMock(return_value=[own_post, other_post])
        collect_stage._search.search_hashtag = MagicMock(return_value=[])

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        result_ids = [(p.owner_id, p.item_id) for p in result.posts]
        assert (-111, 1) not in result_ids
        assert (-111, 2) in result_ids

    def test_resolve_screen_name_none_skips_group(self, collect_stage, mock_config):
        """Если resolve_screen_name возвращает None — группа пропускается."""
        mock_config.queries = []
        mock_config.hashtags = []
        mock_config.groups = ["bad_group"]
        mock_config.accounts = []
        mock_config.auto_friends = False
        mock_config.auto_groups = False

        collect_stage._search.resolve_screen_name = MagicMock(return_value=None)
        collect_stage._search.get_wall_posts = MagicMock()

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        assert result.posts == []
        collect_stage._search.get_wall_posts.assert_not_called()

    def test_vkapierror_on_wall_get_skips_source(self, collect_stage, mock_config):
        """VKApiError на get_wall_posts — источник пропускается, сбор продолжается."""
        from vk_api import VKApiError

        mock_config.queries = []
        mock_config.hashtags = []
        mock_config.groups = ["group1", "group2"]
        mock_config.accounts = []
        mock_config.auto_friends = False
        mock_config.auto_groups = False

        collect_stage._search.resolve_screen_name = MagicMock(side_effect=[-111, -222])
        collect_stage._search.get_wall_posts = MagicMock(
            side_effect=[VKApiError(15, "denied"), [_make_post(-222, 1)]]
        )

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        assert len(result.posts) == 1
        assert result.posts[0].owner_id == -222

    def test_captcha_from_wall_get_stops_session(self, collect_stage, mock_config):
        """CaptchaError от get_wall_posts — пробрасывается, сессия останавливается."""
        from vk_api import CaptchaError

        mock_config.queries = []
        mock_config.hashtags = []
        mock_config.groups = ["group1"]
        mock_config.accounts = []
        mock_config.auto_friends = False
        mock_config.auto_groups = False

        collect_stage._search.resolve_screen_name = MagicMock(return_value=-111)
        collect_stage._search.get_wall_posts = MagicMock(
            side_effect=CaptchaError("captcha required")
        )

        ctx = PipelineContext(config=mock_config, target_likes=5)
        with pytest.raises(CaptchaError):
            collect_stage.process(ctx)

    def test_captcha_from_friends_get_stops_session(self, collect_stage, mock_config):
        """CaptchaError от get_friends — пробрасывается, сессия останавливается."""
        from vk_api import CaptchaError

        mock_config.auto_friends = True
        mock_config.auto_groups = False
        mock_config.queries = []
        mock_config.hashtags = []
        mock_config.groups = []
        mock_config.accounts = []

        collect_stage._search.get_friends = MagicMock(side_effect=CaptchaError("captcha required"))

        ctx = PipelineContext(config=mock_config, target_likes=5)
        with pytest.raises(CaptchaError):
            collect_stage.process(ctx)

    def test_dedup_not_here(self, collect_stage, mock_config):
        """CollectStage не дедуплицирует — это работа DedupStage."""
        posts1 = [_make_post(1, 1), _make_post(1, 2)]
        posts2 = [_make_post(1, 2), _make_post(1, 3)]
        collect_stage._search.search = MagicMock(return_value=posts1)
        collect_stage._search.search_hashtag = MagicMock(return_value=posts2)

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        # Дубликат (1, 2) остаётся — DedupStage уберёт
        keys = [(p.owner_id, p.item_id) for p in result.posts]
        assert (1, 2) in keys

    def test_groups_fill_when_queries_hashtags_empty(self, collect_stage, mock_config):
        """Если queries и hashtags пусты — groups собираются."""
        mock_config.queries = []
        mock_config.hashtags = []
        mock_config.groups = ["group1"]
        mock_config.accounts = []
        mock_config.auto_friends = False
        mock_config.auto_groups = False

        collect_stage._search.resolve_screen_name = MagicMock(return_value=-111)
        collect_stage._search.get_wall_posts = MagicMock(
            return_value=[_make_post(-111, i) for i in range(5)]
        )

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        assert len(result.posts) == 5

    def test_target_likes_zero_skips_collection(self, collect_stage, mock_config):
        """target_likes=0 — сбор пропускается, возвращается пустой список."""
        mock_config.queries = ["тест"]
        collect_stage._search.search = MagicMock(return_value=[_make_post(1, 1)])

        ctx = PipelineContext(config=mock_config, target_likes=0)
        result = collect_stage.process(ctx)

        assert result.posts == []
        collect_stage._search.search.assert_not_called()

    def test_friends_early_exit_before_safety_cap(self, collect_stage, mock_config):
        """Early-exit срабатывает до safety-капа — не все друзья опрашиваются."""
        mock_config.auto_friends = True
        mock_config.auto_groups = False
        mock_config.queries = []
        mock_config.hashtags = []
        mock_config.groups = []
        mock_config.accounts = []
        mock_config.max_friends_to_collect = 100

        friend_ids = list(range(100, 200))  # 100 друзей
        collect_stage._search.get_friends = MagicMock(return_value=friend_ids)

        def wall_side_effect(owner_id, max_posts=10):
            return [_make_post(owner_id, j) for j in range(5)]

        collect_stage._search.get_wall_posts = MagicMock(side_effect=wall_side_effect)

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        # enough = 5 * 2 = 10; 2 друга × 5 постов = 10 → early-exit после 2
        assert collect_stage._search.get_wall_posts.call_count <= 3
        assert len(result.posts) >= 10

    def test_friends_safety_cap_limits_api_calls(self, collect_stage, mock_config):
        """max_friends_to_collect — safety-кап на число API-вызовов, не срез списка."""
        mock_config.auto_friends = True
        mock_config.auto_groups = False
        mock_config.queries = []
        mock_config.hashtags = []
        mock_config.groups = []
        mock_config.accounts = []
        mock_config.max_friends_to_collect = 3

        friend_ids = list(range(100, 200))  # 100 друзей
        collect_stage._search.get_friends = MagicMock(return_value=friend_ids)

        def wall_side_effect(owner_id, max_posts=10):
            return []  # все стены пустые — early-exit не сработает

        collect_stage._search.get_wall_posts = MagicMock(side_effect=wall_side_effect)

        ctx = PipelineContext(config=mock_config, target_likes=5)
        result = collect_stage.process(ctx)

        assert collect_stage._search.get_wall_posts.call_count == 3
        assert result.posts == []

    def test_min_friends_to_poll_prevents_early_exit(self, collect_stage, mock_config):
        """min_friends_to_poll — ранний выход не срабатывает, пока не опрошено N друзей."""
        mock_config.auto_friends = True
        mock_config.auto_groups = False
        mock_config.queries = []
        mock_config.hashtags = []
        mock_config.groups = []
        mock_config.accounts = []
        mock_config.min_friends_to_poll = 5

        friend_ids = list(range(100, 110))  # 10 друзей
        collect_stage._search.get_friends = MagicMock(return_value=friend_ids)

        def wall_side_effect(owner_id, max_posts=10):
            return [_make_post(owner_id, j) for j in range(3)]

        collect_stage._search.get_wall_posts = MagicMock(side_effect=wall_side_effect)

        ctx = PipelineContext(config=mock_config, target_likes=5)
        collect_stage.process(ctx)

        # enough = 5 * 2 = 10; 4 друга × 3 поста = 12 ≥ 10, но min_friends_to_poll=5
        # → early-exit не срабатывает до 5-го друга
        assert collect_stage._search.get_wall_posts.call_count >= 5
