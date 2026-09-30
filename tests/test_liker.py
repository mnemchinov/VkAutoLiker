"""Unit-тесты оркестратора AutoLiker.

Все зависимости заменяются на MagicMock — ни API, ни браузер, ни SQLite
не задействуются. PostFilter мокается как pass-through.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from post import Post, build_post_url


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
def liker(mock_config, mock_logger):
    """AutoLiker с мок-зависимостями: search, likes, state, filter, browser."""
    from liker import AutoLiker

    obj = AutoLiker(mock_config, mock_logger)

    # Закрываем реальные подключения, созданные в AutoLiker.__init__
    obj._state.close()
    obj._api_client = MagicMock()
    obj._search_service = MagicMock()
    obj._likes_service = MagicMock()
    obj._state = MagicMock()
    obj._browser = MagicMock()
    obj._filter = MagicMock()

    # PostFilter — pass-through: возвращает вход без фильтрации
    obj._filter.filter = lambda posts: list(posts)

    # is_processed по умолчанию False (пост не обработан)
    obj._state.is_processed = MagicMock(return_value=False)

    return obj


class TestCollectPosts:
    """Тесты _collect_posts: приоритет источников, ранний выход, дедупликация."""

    def test_queries_enough_skips_other_sources(self, liker, mock_config):
        """Если queries дают enough постов — groups/accounts/friends не вызываются."""
        posts = [_make_post(1, i) for i in range(20)]
        liker._search_service.search = MagicMock(return_value=posts)
        liker._search_service.search_hashtag = MagicMock(return_value=[])

        result = liker._collect_posts()

        assert len(result) == 20
        liker._search_service.resolve_screen_name.assert_not_called()
        liker._search_service.get_friends.assert_not_called()

    def test_hashtags_fill_when_queries_empty(self, liker, mock_config):
        """Если queries пусты — hashtags собираются, groups не вызываются."""
        liker._search_service.search = MagicMock(return_value=[])
        hashtag_posts = [_make_post(2, i) for i in range(20)]
        liker._search_service.search_hashtag = MagicMock(return_value=hashtag_posts)

        result = liker._collect_posts()

        assert len(result) == 20
        liker._search_service.resolve_screen_name.assert_not_called()

    def test_early_exit_on_friends(self, liker, mock_config):
        """Ранний выход: enough постов на друзьях → остальные друзья пропускаются."""
        mock_config.search.auto_friends = True
        mock_config.search.auto_groups = False
        mock_config.search.queries = []
        mock_config.search.hashtags = []
        mock_config.search.groups = []
        mock_config.search.accounts = []

        friend_ids = [100 + i for i in range(10)]
        liker._search_service.get_friends = MagicMock(return_value=friend_ids)
        # Каждый друг даёт 3 поста — enough=10 достигается на 4-м друге
        liker._search_service.get_wall_posts = MagicMock(
            return_value=[_make_post(fid, j) for fid in [friend_ids[0]] for j in range(3)]
        )
        # Разные посты для каждого друга
        def wall_side_effect(owner_id, max_posts=10):
            return [_make_post(owner_id, j) for j in range(3)]

        liker._search_service.get_wall_posts = MagicMock(side_effect=wall_side_effect)

        result = liker._collect_posts()

        # enough = likes_per_session * 2 = 5 * 2 = 10
        # 4 друга × 3 поста = 12 ≥ 10 → early exit
        assert len(result) >= 10
        assert liker._search_service.get_wall_posts.call_count <= 5

    def test_is_processed_filters_during_collection(self, liker, mock_config):
        """Посты, уже обработанные в SQLite, исключаются из результата."""
        posts = [_make_post(1, 1), _make_post(1, 2), _make_post(1, 3)]
        liker._search_service.search = MagicMock(return_value=posts)
        liker._search_service.search_hashtag = MagicMock(return_value=[])
        # Пост (1, 2) уже обработан
        liker._state.is_processed = MagicMock(
            side_effect=lambda owner_id, item_id: (owner_id == 1 and item_id == 2)
        )

        result = liker._collect_posts()

        result_ids = [(p.owner_id, p.item_id) for p in result]
        assert (1, 2) not in result_ids
        assert (1, 1) in result_ids
        assert (1, 3) in result_ids

    def test_resolve_screen_name_none_skips_group(self, liker, mock_config):
        """Если resolve_screen_name возвращает None — группа пропускается."""
        mock_config.search.queries = []
        mock_config.search.hashtags = []
        mock_config.search.groups = ["bad_group"]
        mock_config.search.accounts = []
        mock_config.search.auto_friends = False
        mock_config.search.auto_groups = False

        liker._search_service.resolve_screen_name = MagicMock(return_value=None)
        liker._search_service.get_wall_posts = MagicMock()

        result = liker._collect_posts()

        assert result == []
        liker._search_service.get_wall_posts.assert_not_called()

    def test_vkapierror_on_wall_get_skips_source(self, liker, mock_config):
        """VKApiError на get_wall_posts — источник пропускается, сбор продолжается."""
        from vk_api_client import VKApiError

        mock_config.search.queries = []
        mock_config.search.hashtags = []
        mock_config.search.groups = ["group1", "group2"]
        mock_config.search.accounts = []
        mock_config.search.auto_friends = False
        mock_config.search.auto_groups = False

        liker._search_service.resolve_screen_name = MagicMock(side_effect=[-111, -222])
        # Первая группа — ошибка, вторая — посты
        liker._search_service.get_wall_posts = MagicMock(
            side_effect=[VKApiError(15, "denied"), [_make_post(-222, 1)]]
        )

        result = liker._collect_posts()

        assert len(result) == 1
        assert result[0].owner_id == -222

    def test_deduplication_by_owner_item_id(self, liker, mock_config):
        """Дубликаты (owner_id, item_id) схлопываются."""
        posts1 = [_make_post(1, 1), _make_post(1, 2)]
        posts2 = [_make_post(1, 2), _make_post(1, 3)]
        # search возвращает posts1, search_hashtag возвращает posts2 (с дубликатом)
        liker._search_service.search = MagicMock(return_value=posts1)
        liker._search_service.search_hashtag = MagicMock(return_value=posts2)

        result = liker._collect_posts()

        keys = [(p.owner_id, p.item_id) for p in result]
        assert len(keys) == len(set(keys))
        assert sorted(keys) == [(1, 1), (1, 2), (1, 3)]


class TestRun:
    """Тесты run: лимиты, цикл лайков, обработка ошибок."""

    def test_daily_limit_reached_no_session(self, liker, mock_config):
        """Дневной лимит сессий достигнут — start_session не вызывается."""
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(return_value=(mock_config.limits.sessions_per_day, 0))
        liker._state.start_session = MagicMock()

        liker.run()

        liker._state.start_session.assert_not_called()

    def test_no_limit_skips_daily_limit_check(self, liker, mock_config):
        """no_limit=True — дневной лимит не проверяется, сессия создаётся."""
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(return_value=(mock_config.limits.sessions_per_day, 0))
        liker._state.start_session = MagicMock(return_value=1)
        liker._state.end_session = MagicMock()
        liker._state.get_total_stats = MagicMock(return_value=(1, 0))
        liker._likes_service.is_liked = MagicMock(return_value=False)

        with patch("liker.time.sleep"), patch.object(liker, "_collect_posts", return_value=[]):
            liker.run(no_limit=True)

        # get_daily_stats не вызывается при no_limit=True
        liker._state.get_daily_stats.assert_not_called()
        # start_session вызывается с is_auto=False
        liker._state.start_session.assert_called_once_with(is_auto=False)

    def test_like_success_increments_count(self, liker, mock_config):
        """Успешный лайк → mark_processed, likes_count растёт."""
        posts = [_make_post(1, i) for i in range(3)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._state.start_session = MagicMock(return_value=1)
        liker._state.end_session = MagicMock()
        liker._state.get_total_stats = MagicMock(return_value=(1, 3))
        liker._likes_service.is_liked = MagicMock(return_value=False)
        liker._likes_service.like = MagicMock(return_value=True)
        liker._state.mark_processed = MagicMock()

        with patch("liker.time.sleep"), patch.object(liker, "_collect_posts", return_value=posts):
            liker.run()

        assert liker._state.mark_processed.call_count == 3

    def test_already_liked_skipped_and_marked(self, liker, mock_config):
        """Уже лайкнутый пост → mark_processed, like не вызывается."""
        posts = [_make_post(1, 1)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._state.start_session = MagicMock(return_value=1)
        liker._state.end_session = MagicMock()
        liker._state.get_total_stats = MagicMock(return_value=(1, 0))
        liker._likes_service.is_liked = MagicMock(return_value=True)
        liker._likes_service.like = MagicMock()
        liker._state.mark_processed = MagicMock()

        with patch("liker.time.sleep"), patch.object(liker, "_collect_posts", return_value=posts):
            liker.run()

        liker._likes_service.like.assert_not_called()
        liker._state.mark_processed.assert_called_once_with(1, 1)

    def test_exception_in_cycle_continues(self, liker, mock_config):
        """Exception при обработке поста → mark_processed, цикл продолжается."""
        posts = [_make_post(1, 1), _make_post(1, 2)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._state.start_session = MagicMock(return_value=1)
        liker._state.end_session = MagicMock()
        liker._state.get_total_stats = MagicMock(return_value=(1, 1))
        # Первый пост — exception, второй — успех
        liker._likes_service.is_liked = MagicMock(side_effect=[RuntimeError("boom"), False])
        liker._likes_service.like = MagicMock(return_value=True)
        liker._state.mark_processed = MagicMock()

        with patch("liker.time.sleep"), patch.object(liker, "_collect_posts", return_value=posts):
            liker.run()

        # Оба поста обработаны (mark_processed для обоих)
        assert liker._state.mark_processed.call_count == 2

    def test_likes_per_session_limit_stops_cycle(self, liker, mock_config):
        """Лимит лайков за сессию достигнут → цикл прерывается."""
        mock_config.limits.likes_per_session = 2
        posts = [_make_post(1, i) for i in range(10)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._state.start_session = MagicMock(return_value=1)
        liker._state.end_session = MagicMock()
        liker._state.get_total_stats = MagicMock(return_value=(1, 2))
        liker._likes_service.is_liked = MagicMock(return_value=False)
        liker._likes_service.like = MagicMock(return_value=True)
        liker._state.mark_processed = MagicMock()

        with patch("liker.time.sleep"), patch.object(liker, "_collect_posts", return_value=posts):
            liker.run()

        # Только 2 лайка (лимит), не все 10 постов
        assert liker._likes_service.like.call_count == 2
