"""Unit-тесты оркестратора AutoLiker.

Все зависимости заменяются на MagicMock — ни API, ни браузер, ни SQLite
не задействуются. Pipeline мокается как pass-through.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from browser_likes import LikeResult
from pipeline import PipelineContext
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
    """AutoLiker с мок-зависимостями: search, likes, state, filter, browser, pipeline."""
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
    obj._pipeline = MagicMock()

    # Pipeline — pass-through: возвращает контекст с постами без изменений
    def _pipeline_run(ctx):
        return ctx

    obj._pipeline.run = MagicMock(side_effect=_pipeline_run)

    # is_processed по умолчанию False (пост не обработан)
    obj._state.is_processed = MagicMock(return_value=False)

    return obj


class TestRun:
    """Тесты run: лимиты, цикл лайков, обработка ошибок, капча, jitter, burst."""

    def test_daily_limit_reached_no_session(self, liker, mock_config):
        """Дневной лимит сессий достигнут — start_session не вызывается."""
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(
            return_value=(mock_config.limits.sessions_per_day, 0)
        )
        liker._state.start_session = MagicMock()

        with patch("liker.time.sleep"), patch("liker.random.uniform", return_value=0):
            liker.run()

        liker._state.start_session.assert_not_called()

    def test_no_limit_skips_daily_limit_check(self, liker, mock_config):
        """no_limit=True — дневной лимит не проверяется, сессия создаётся."""
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(
            return_value=(mock_config.limits.sessions_per_day, 0)
        )
        liker._state.start_session = MagicMock(return_value=1)
        liker._state.end_session = MagicMock()
        liker._state.get_total_stats = MagicMock(return_value=(1, 0))

        # Pipeline возвращает пустой список постов
        liker._pipeline.run = MagicMock(return_value=PipelineContext(posts=[]))

        with patch("liker.time.sleep"):
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
        liker._likes_service.like = MagicMock(return_value=LikeResult.LIKED)
        liker._state.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(return_value=PipelineContext(posts=posts))

        with patch("liker.time.sleep"), patch("liker.random.uniform", return_value=0), \
             patch("liker.random.randint", side_effect=lambda a, b: a):
            liker.run(no_limit=True)

        assert liker._state.mark_processed.call_count == 3

    def test_already_liked_skipped_and_marked(self, liker, mock_config):
        """Уже лайкнутый пост → mark_processed, like() вызван, возвращает ALREADY_LIKED."""
        posts = [_make_post(1, 1)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._state.start_session = MagicMock(return_value=1)
        liker._state.end_session = MagicMock()
        liker._state.get_total_stats = MagicMock(return_value=(1, 0))
        liker._likes_service.like = MagicMock(return_value=LikeResult.ALREADY_LIKED)
        liker._state.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(return_value=PipelineContext(posts=posts))

        with patch("liker.time.sleep"), patch("liker.random.uniform", return_value=0):
            liker.run(no_limit=True)

        liker._likes_service.like.assert_called_once_with(1, 1)
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
        liker._likes_service.like = MagicMock(
            side_effect=[RuntimeError("boom"), LikeResult.LIKED]
        )
        liker._state.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(return_value=PipelineContext(posts=posts))

        with patch("liker.time.sleep"), patch("liker.random.uniform", return_value=0), \
             patch("liker.random.randint", side_effect=lambda a, b: a):
            liker.run(no_limit=True)

        # Оба поста обработаны (mark_processed для обоих)
        assert liker._state.mark_processed.call_count == 2

    def test_likes_per_session_limit_stops_cycle(self, liker, mock_config):
        """Лимит лайков за сессию достигнут → цикл прерывается."""
        mock_config.limits.likes_per_session_min = 2
        mock_config.limits.likes_per_session_max = 2
        posts = [_make_post(1, i) for i in range(10)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._state.start_session = MagicMock(return_value=1)
        liker._state.end_session = MagicMock()
        liker._state.get_total_stats = MagicMock(return_value=(1, 2))
        liker._likes_service.like = MagicMock(return_value=LikeResult.LIKED)
        liker._state.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(return_value=PipelineContext(posts=posts))

        with patch("liker.time.sleep"), patch("liker.random.uniform", return_value=0), \
             patch("liker.random.randint", side_effect=lambda a, b: a):
            liker.run(no_limit=True)

        # Только 2 лайка (лимит), не все 10 постов
        assert liker._likes_service.like.call_count == 2

    def test_captcha_streak_stops_session(self, liker, mock_config):
        """Серия капч (>= max_captcha_streak) прерывает сессию."""
        mock_config.limits.max_captcha_streak = 3
        posts = [_make_post(1, i) for i in range(10)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._state.start_session = MagicMock(return_value=1)
        liker._state.end_session = MagicMock()
        liker._state.get_total_stats = MagicMock(return_value=(1, 0))
        liker._likes_service.like = MagicMock(return_value=LikeResult.CAPTCHA)
        liker._state.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(return_value=PipelineContext(posts=posts))

        with patch("liker.time.sleep"), patch("liker.random.uniform", return_value=0):
            liker.run(no_limit=True)

        # Сессия прервана после 3 капч, не все 10 постов обработаны
        assert liker._likes_service.like.call_count == 3

    def test_jitter_in_auto_mode(self, liker, mock_config):
        """Авто-запуск (no_limit=False) — jitter перед стартом браузера."""
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(
            return_value=(mock_config.limits.sessions_per_day, 0)
        )
        liker._state.start_session = MagicMock()

        with patch("liker.time.sleep") as mock_sleep, \
             patch("liker.random.uniform", return_value=42.0):
            liker.run()

        # Первый sleep — jitter (42 сек)
        assert mock_sleep.call_args_list[0].args[0] == 42.0

    def test_no_jitter_in_manual_mode(self, liker, mock_config):
        """Ручной запуск (no_limit=True) — jitter нет, time.sleep не вызывается до start."""
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._state.start_session = MagicMock(return_value=1)
        liker._state.end_session = MagicMock()
        liker._state.get_total_stats = MagicMock(return_value=(1, 0))

        liker._pipeline.run = MagicMock(return_value=PipelineContext(posts=[]))

        with patch("liker.time.sleep") as mock_sleep:
            liker.run(no_limit=True)

        # Нет постов → нет пауз. time.sleep не вызывается (нет jitter, нет постов)
        mock_sleep.assert_not_called()

    def test_burst_softening_long_pause(self, liker, mock_config):
        """Каждые 5-10 лайков — длинная пауза (60-180 сек)."""
        mock_config.limits.likes_per_session_min = 10
        mock_config.limits.likes_per_session_max = 10
        posts = [_make_post(1, i) for i in range(10)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._state.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._state.start_session = MagicMock(return_value=1)
        liker._state.end_session = MagicMock()
        liker._state.get_total_stats = MagicMock(return_value=(1, 10))
        liker._likes_service.like = MagicMock(return_value=LikeResult.LIKED)
        liker._state.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(return_value=PipelineContext(posts=posts))

        # uniform(60, 180) → burst-пауза (120), прочие uniform → 0
        def _uniform(lo, hi):
            if lo >= 60:
                return 120.0
            return 0.0

        with patch("liker.time.sleep") as mock_sleep, \
             patch("liker.random.uniform", side_effect=_uniform), \
             patch("liker.random.randint", side_effect=lambda a, b: a):
            liker.run(no_limit=True)

        # Проверяем, что хотя бы один sleep был >= 60 сек (burst pause)
        long_pauses = [call for call in mock_sleep.call_args_list if call.args[0] >= 60]
        assert len(long_pauses) > 0
