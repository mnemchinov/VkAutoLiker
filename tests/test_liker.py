"""Unit-тесты оркестратора AutoLiker.

Все зависимости заменяются на MagicMock — ни API, ни браузер, ни SQLite
не задействуются. Pipeline мокается как pass-through.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from browser import LikeResult
from post import Post, PostStatus, build_post_url
from stages import PipelineContext


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
    obj._db.close()
    obj._api_client = MagicMock()
    obj._search_service = MagicMock()
    obj._likes_service = MagicMock()
    obj._db = MagicMock()
    obj._posts_repo = MagicMock()
    obj._sessions_repo = MagicMock()
    obj._walls_repo = MagicMock()
    obj._browser = MagicMock()
    obj._pipeline = MagicMock()

    # Pipeline — pass-through: возвращает контекст с постами без изменений
    def _pipeline_run(ctx):
        return ctx

    obj._pipeline.run = MagicMock(side_effect=_pipeline_run)

    # is_processed по умолчанию False (пост не обработан)
    obj._posts_repo.is_processed = MagicMock(return_value=False)

    return obj


class TestRun:
    """Тесты run: лимиты, цикл лайков, обработка ошибок, капча, jitter, burst."""

    def test_daily_limit_reached_no_session(self, liker, mock_config):
        """Дневной лимит сессий достигнут — start_session не вызывается."""
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(
            return_value=(mock_config.sessions_per_day, 0)
        )
        liker._sessions_repo.start_session = MagicMock()

        with patch("liker.time.sleep"), patch("liker.random.uniform", return_value=0):
            liker.run()

        liker._sessions_repo.start_session.assert_not_called()

    def test_no_limit_skips_daily_limit_check(self, liker, mock_config):
        """no_limit=True — дневной лимит не проверяется, сессия создаётся."""
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(
            return_value=(mock_config.sessions_per_day, 0)
        )
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 0))

        # Pipeline возвращает пустой список постов
        liker._pipeline.run = MagicMock(return_value=PipelineContext(config=mock_config, posts=[]))

        with patch("liker.time.sleep"):
            liker.run(no_limit=True)

        # get_daily_stats не вызывается при no_limit=True
        liker._sessions_repo.get_daily_stats.assert_not_called()
        # start_session вызывается с is_auto=False
        liker._sessions_repo.start_session.assert_called_once_with(is_auto=False)

    def test_like_success_increments_count(self, liker, mock_config):
        """Успешный лайк → mark_processed, likes_count растёт."""
        posts = [_make_post(1, i) for i in range(3)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 3))
        liker._likes_service.like = MagicMock(return_value=LikeResult.LIKED)
        liker._posts_repo.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(
            return_value=PipelineContext(config=mock_config, posts=posts)
        )

        with (
            patch("liker.time.sleep"),
            patch("liker.random.uniform", return_value=0),
            patch("liker.random.randint", side_effect=lambda a, b: a),
        ):
            liker.run(no_limit=True)

        assert liker._posts_repo.mark_processed.call_count == 3

    def test_already_liked_skipped_and_marked(self, liker, mock_config):
        """Уже лайкнутый пост → mark_processed, like() вызван, возвращает ALREADY_LIKED."""
        posts = [_make_post(1, 1)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 0))
        liker._likes_service.like = MagicMock(return_value=LikeResult.ALREADY_LIKED)
        liker._posts_repo.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(
            return_value=PipelineContext(config=mock_config, posts=posts)
        )

        with patch("liker.time.sleep"), patch("liker.random.uniform", return_value=0):
            liker.run(no_limit=True)

        liker._likes_service.like.assert_called_once_with(1, 1)
        liker._posts_repo.mark_processed.assert_called_once_with(1, 1, PostStatus.LIKED)

    def test_already_liked_skips_normal_delay(self, liker, mock_config):
        """Уже лайкнутый пост → короткая skip-пауза, обычная пауза НЕ вызывается."""
        posts = [_make_post(1, 1)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 0))
        liker._likes_service.like = MagicMock(return_value=LikeResult.ALREADY_LIKED)
        liker._posts_repo.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(
            return_value=PipelineContext(config=mock_config, posts=posts)
        )

        uniform_calls = []

        def track_uniform(a, b):
            uniform_calls.append((a, b))
            return 0

        with patch("liker.time.sleep"), patch("liker.random.uniform", side_effect=track_uniform):
            liker.run(no_limit=True)

        # skip-пауза random.uniform(2, 5) — должна быть
        assert (2, 5) in uniform_calls
        # обычная пауза random.uniform(min_delay_sec, max_delay_sec) — НЕ должна быть
        assert (mock_config.min_delay_sec, mock_config.max_delay_sec) not in uniform_calls
        # burst-пауза random.uniform(60, 180) — НЕ должна быть
        assert (60, 180) not in uniform_calls

    def test_exception_in_cycle_continues(self, liker, mock_config):
        """Exception при обработке поста → БЕЗ mark_processed (повтор), цикл продолжается."""
        posts = [_make_post(1, 1), _make_post(1, 2)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 1))
        # Первый пост — exception, второй — успех
        liker._likes_service.like = MagicMock(side_effect=[RuntimeError("boom"), LikeResult.LIKED])
        liker._posts_repo.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(
            return_value=PipelineContext(config=mock_config, posts=posts)
        )

        with (
            patch("liker.time.sleep"),
            patch("liker.random.uniform", return_value=0),
            patch("liker.random.randint", side_effect=lambda a, b: a),
        ):
            liker.run(no_limit=True)

        # Только второй пост (LIKED) — mark_processed. Первый (Exception) — без метки.
        assert liker._posts_repo.mark_processed.call_count == 1
        liker._posts_repo.mark_processed.assert_called_once_with(1, 2, PostStatus.LIKED)

    def test_likes_per_session_limit_stops_cycle(self, liker, mock_config):
        """Лимит лайков за сессию достигнут → цикл прерывается."""
        mock_config.likes_per_session_min = 2
        mock_config.likes_per_session_max = 2
        posts = [_make_post(1, i) for i in range(10)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 2))
        liker._likes_service.like = MagicMock(return_value=LikeResult.LIKED)
        liker._posts_repo.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(
            return_value=PipelineContext(config=mock_config, posts=posts)
        )

        with (
            patch("liker.time.sleep"),
            patch("liker.random.uniform", return_value=0),
            patch("liker.random.randint", side_effect=lambda a, b: a),
        ):
            liker.run(no_limit=True)

        # Только 2 лайка (лимит), не все 10 постов
        assert liker._likes_service.like.call_count == 2

    def test_captcha_streak_stops_session(self, liker, mock_config):
        """Серия капч (>= max_captcha_streak) прерывает сессию."""
        mock_config.max_captcha_streak = 3
        posts = [_make_post(1, i) for i in range(10)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 0))
        liker._likes_service.like = MagicMock(return_value=LikeResult.CAPTCHA)
        liker._posts_repo.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(
            return_value=PipelineContext(config=mock_config, posts=posts)
        )

        with patch("liker.time.sleep"), patch("liker.random.uniform", return_value=0):
            liker.run(no_limit=True)

        # Сессия прервана после 3 капч, не все 10 постов обработаны
        assert liker._likes_service.like.call_count == 3

    def test_captcha_not_marked_for_retry(self, liker, mock_config):
        """CAPTCHA → БЕЗ mark_processed (пост повторится в следующей сессии)."""
        posts = [_make_post(1, 1)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 0))
        liker._likes_service.like = MagicMock(return_value=LikeResult.CAPTCHA)
        liker._posts_repo.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(
            return_value=PipelineContext(config=mock_config, posts=posts)
        )

        with patch("liker.time.sleep"), patch("liker.random.uniform", return_value=0):
            liker.run(no_limit=True)

        liker._posts_repo.mark_processed.assert_not_called()

    def test_failed_not_marked_for_retry(self, liker, mock_config):
        """FAILED → БЕЗ mark_processed (пост повторится в следующей сессии)."""
        posts = [_make_post(1, 1)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 0))
        liker._likes_service.like = MagicMock(return_value=LikeResult.FAILED)
        liker._posts_repo.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(
            return_value=PipelineContext(config=mock_config, posts=posts)
        )

        with patch("liker.time.sleep"), patch("liker.random.uniform", return_value=0):
            liker.run(no_limit=True)

        liker._posts_repo.mark_processed.assert_not_called()

    def test_jitter_in_auto_mode(self, liker, mock_config):
        """Авто-запуск (no_limit=False) — jitter после проверки авторизации."""
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(
            return_value=(mock_config.sessions_per_day, 0)
        )
        liker._sessions_repo.start_session = MagicMock()

        with (
            patch("liker.time.sleep") as mock_sleep,
            patch("liker.random.uniform", return_value=42.0),
        ):
            liker.run()

        # Первый sleep — jitter (42 сек)
        assert mock_sleep.call_args_list[0].args[0] == 42.0

    def test_no_jitter_in_manual_mode(self, liker, mock_config):
        """Ручной запуск (no_limit=True) — jitter нет, time.sleep не вызывается до start."""
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 0))

        liker._pipeline.run = MagicMock(return_value=PipelineContext(config=mock_config, posts=[]))

        with patch("liker.time.sleep") as mock_sleep:
            liker.run(no_limit=True)

        # Нет постов → нет пауз. time.sleep не вызывается (нет jitter, нет постов)
        mock_sleep.assert_not_called()

    def test_browser_crash_breaks_not_marks(self, liker, mock_config):
        """WebDriverException — break без mark_processed, остальные посты не трогаются."""
        from selenium.common.exceptions import InvalidSessionIdException

        posts = [_make_post(1, 1), _make_post(1, 2), _make_post(1, 3)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 0))
        liker._likes_service.like = MagicMock(side_effect=InvalidSessionIdException("session dead"))
        liker._posts_repo.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(
            return_value=PipelineContext(config=mock_config, posts=posts)
        )

        with (
            patch("liker.time.sleep"),
            patch("liker.random.uniform", return_value=0),
            patch("liker.random.randint", side_effect=lambda a, b: a),
        ):
            liker.run(no_limit=True)

        # mark_processed НЕ вызывается при крахе браузера
        liker._posts_repo.mark_processed.assert_not_called()
        # like вызван только 1 раз (break после первого)
        assert liker._likes_service.like.call_count == 1

    def test_burst_softening_long_pause(self, liker, mock_config):
        """Каждые 5-10 лайков — длинная пауза (60-180 сек)."""
        mock_config.likes_per_session_min = 10
        mock_config.likes_per_session_max = 10
        posts = [_make_post(1, i) for i in range(10)]
        liker._browser.is_logged_in = MagicMock(return_value=True)
        liker._sessions_repo.get_daily_stats = MagicMock(return_value=(0, 0))
        liker._sessions_repo.start_session = MagicMock(return_value=1)
        liker._sessions_repo.end_session = MagicMock()
        liker._sessions_repo.get_total_stats = MagicMock(return_value=(1, 10))
        liker._likes_service.like = MagicMock(return_value=LikeResult.LIKED)
        liker._posts_repo.mark_processed = MagicMock()

        liker._pipeline.run = MagicMock(
            return_value=PipelineContext(config=mock_config, posts=posts)
        )

        # uniform(60, 180) → burst-пауза (120), прочие uniform → 0
        def _uniform(lo, hi):
            if lo >= 60:
                return 120.0
            return 0.0

        with (
            patch("liker.time.sleep") as mock_sleep,
            patch("liker.random.uniform", side_effect=_uniform),
            patch("liker.random.randint", side_effect=lambda a, b: a),
        ):
            liker.run(no_limit=True)

        # Проверяем, что хотя бы один sleep был >= 60 сек (burst pause)
        long_pauses = [call for call in mock_sleep.call_args_list if call.args[0] >= 60]
        assert len(long_pauses) > 0


class TestPipelineComposition:
    """Композиция pipeline-стадий по filter_mode."""

    def _stages(self, mock_config_data, monkeypatch, **overrides):
        """Собирает AutoLiker и возвращает типы стадий до замены pipeline на мок."""
        from liker import AutoLiker
        from settings import Settings

        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        config = Settings(_env_file=None, **{**mock_config_data, **overrides})
        obj = AutoLiker(config, MagicMock())
        try:
            return [type(st) for st in obj._pipeline._stages]
        finally:
            obj._db.close()

    def test_stop_words_mode_two_stages(self, mock_config_data, monkeypatch):
        """stop_words: CollectStage + DedupStage, без LLMFilterStage."""
        from stages import CollectStage, DedupStage

        stages = self._stages(mock_config_data, monkeypatch)

        assert stages == [CollectStage, DedupStage]

    def test_review_mode_three_stages(self, mock_config_data, monkeypatch):
        """review: CollectStage + DedupStage + LLMFilterStage."""
        from stages import CollectStage, DedupStage, LLMFilterStage

        stages = self._stages(mock_config_data, monkeypatch, filter_mode="review")

        assert stages == [CollectStage, DedupStage, LLMFilterStage]

    def test_llm_mode_three_stages(self, mock_config_data, monkeypatch):
        """llm: CollectStage + DedupStage + LLMFilterStage."""
        from stages import CollectStage, DedupStage, LLMFilterStage

        stages = self._stages(mock_config_data, monkeypatch, filter_mode="llm")

        assert stages == [CollectStage, DedupStage, LLMFilterStage]
