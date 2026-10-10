"""Unit-тесты LLMTopicFilter и LLMFilterStage.

litellm.completion мокается через patch — реальных запросов к LLM нет.
"""

import time
from unittest.mock import MagicMock, patch

import litellm

from post import Post, PostStatus, build_post_url
from post_filter import LLMTimeoutError
from stages import PipelineContext


def _make_post(owner_id: int, item_id: int, text: str = "текст поста") -> Post:
    """Создаёт тестовый Post."""
    return Post(
        owner_id=owner_id,
        item_id=item_id,
        text=text,
        date=int(time.time()),
        url=build_post_url(owner_id, item_id),
    )


def _mock_llm_response(answer: str) -> MagicMock:
    """Создаёт мок-ответ litellm.completion с указанным текстом."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = answer
    return resp


class TestLLMTopicFilter:
    """Тесты LLMTopicFilter.should_skip."""

    def test_skip_when_llm_says_skip(self, mock_config, mock_logger):
        """LLM ответил SKIP → should_skip True."""
        from post_filter import LLMTopicFilter

        f = LLMTopicFilter(mock_config, mock_logger)
        post = _make_post(1, 1, "политический пост")

        with patch("litellm.completion", return_value=_mock_llm_response("SKIP")):
            assert f.should_skip(post) is True

    def test_keep_when_llm_says_ok(self, mock_config, mock_logger):
        """LLM ответил OK → should_skip False."""
        from post_filter import LLMTopicFilter

        f = LLMTopicFilter(mock_config, mock_logger)
        post = _make_post(1, 1, "обычный пост")

        with patch("litellm.completion", return_value=_mock_llm_response("OK")):
            assert f.should_skip(post) is False

    def test_keep_on_llm_exception(self, mock_config, mock_logger):
        """Ошибка LLM → should_skip False (безопаснее оставить)."""
        from post_filter import LLMTopicFilter

        f = LLMTopicFilter(mock_config, mock_logger)
        post = _make_post(1, 1, "любой пост")

        with patch("litellm.completion", side_effect=RuntimeError("timeout")):
            assert f.should_skip(post) is False

    def test_timeout_raises_llm_timeout_error(self, mock_config, mock_logger):
        """Таймаут LLM → LLMTimeoutError (пост пропускается без маркировки)."""
        from post_filter import LLMTopicFilter

        f = LLMTopicFilter(mock_config, mock_logger)
        post = _make_post(1, 1, "любой пост")

        with patch(
            "litellm.completion",
            side_effect=litellm.Timeout("timeout", model="test", llm_provider="openai"),
        ):
            try:
                f.should_skip(post)
                assert False, "Должен был подняться LLMTimeoutError"
            except LLMTimeoutError:
                pass

    def test_empty_text_not_sent(self, mock_config, mock_logger):
        """Пустой текст → should_skip False без вызова LLM."""
        from post_filter import LLMTopicFilter

        f = LLMTopicFilter(mock_config, mock_logger)
        post = _make_post(1, 1, "   ")

        with patch("litellm.completion") as mock_completion:
            assert f.should_skip(post) is False
            mock_completion.assert_not_called()

    def test_text_truncated_to_max_length(self, mock_config, mock_logger):
        """Текст обрезается до llm_max_text_length перед отправкой в LLM."""
        from post_filter import LLMTopicFilter

        mock_config.llm_max_text_length = 10
        f = LLMTopicFilter(mock_config, mock_logger)
        long_text = "А" * 1000
        post = _make_post(1, 1, long_text)

        with patch("litellm.completion", return_value=_mock_llm_response("OK")) as mock_c:
            f.should_skip(post)
        sent_text = mock_c.call_args.kwargs["messages"][1]["content"]
        assert sent_text.endswith("А" * 10)
        assert "А" * 11 not in sent_text

    def test_skip_in_answer_detected(self, mock_config, mock_logger):
        """Ответ содержит 'SKIP' (с пробелами/регистром) → отсеивание."""
        from post_filter import LLMTopicFilter

        f = LLMTopicFilter(mock_config, mock_logger)
        post = _make_post(1, 1, "пост")

        with patch("litellm.completion", return_value=_mock_llm_response("  skip  ")):
            assert f.should_skip(post) is True

    def test_system_prompt_is_universal(self, mock_config, mock_logger):
        """Системный промпт — универсальная константа без тем; темы — в user-сообщении."""
        from post_filter import LLMTopicFilter

        mock_config.llm_system_prompt = ""
        mock_config.llm_stop_topics = ["политика", "религия"]
        f = LLMTopicFilter(mock_config, mock_logger)

        assert "политика" not in f._system_prompt
        assert "религия" not in f._system_prompt
        assert "SKIP" in f._system_prompt
        assert "OK" in f._system_prompt

        post = _make_post(1, 1, "тест")
        with patch("litellm.completion", return_value=_mock_llm_response("OK")) as mock_c:
            f.should_skip(post)
            user = mock_c.call_args.kwargs["messages"][1]["content"]
            assert "политика" in user
            assert "религия" in user

    def test_custom_system_prompt_overrides_default(self, mock_config, mock_logger):
        """llm_system_prompt полностью заменяет системный промпт."""
        from post_filter import LLMTopicFilter

        mock_config.llm_system_prompt = "Кастомный промпт"
        mock_config.llm_stop_topics = ["политика"]
        f = LLMTopicFilter(mock_config, mock_logger)

        assert f._system_prompt == "Кастомный промпт"

        post = _make_post(1, 1, "тест")
        with patch("litellm.completion", return_value=_mock_llm_response("OK")) as mock_c:
            f.should_skip(post)
            assert mock_c.call_args.kwargs["messages"][0]["content"] == "Кастомный промпт"

    def test_ssl_verify_false_sets_client_session(self, mock_config, mock_logger):
        """llm_ssl_verify=False → litellm.client_session с verify=False."""
        import httpx
        import litellm

        from post_filter import LLMTopicFilter

        mock_config.llm_ssl_verify = False
        LLMTopicFilter(mock_config, mock_logger)

        assert litellm.client_session is not None
        assert isinstance(litellm.client_session, httpx.Client)

        litellm.client_session = None

    def test_ssl_verify_true_does_not_set_client_session(self, mock_config, mock_logger):
        """llm_ssl_verify=True → litellm.client_session не трогается."""
        import litellm

        from post_filter import LLMTopicFilter

        litellm.client_session = None
        mock_config.llm_ssl_verify = True
        LLMTopicFilter(mock_config, mock_logger)

        assert litellm.client_session is None


class TestLLMFilterStage:
    """Тесты LLMFilterStage.process — фильтрация списка постов."""

    def test_filters_skip_posts(self, mock_config, mock_logger):
        """Стадия отсеивает посты, где LLM ответил SKIP."""
        from stages import LLMFilterStage

        posts_repo = MagicMock()
        stage = LLMFilterStage(mock_config, mock_logger, posts_repo)
        posts = [
            _make_post(1, 1, "политика"),
            _make_post(2, 2, "нейтральный пост"),
            _make_post(3, 3, "религия"),
        ]
        ctx = PipelineContext(config=mock_config, posts=posts)

        responses = [
            _mock_llm_response("SKIP"),
            _mock_llm_response("OK"),
            _mock_llm_response("SKIP"),
        ]
        with patch("litellm.completion", side_effect=responses):
            result = stage.process(ctx)

        assert len(result.posts) == 1
        assert result.posts[0].owner_id == 2

    def test_keeps_all_on_exception(self, mock_config, mock_logger):
        """Ошибка LLM → все посты остаются (should_skip False)."""
        from stages import LLMFilterStage

        stage = LLMFilterStage(mock_config, mock_logger, MagicMock())
        posts = [_make_post(1, 1, "a"), _make_post(2, 2, "b")]
        ctx = PipelineContext(config=mock_config, posts=posts)

        with patch("litellm.completion", side_effect=RuntimeError("network")):
            result = stage.process(ctx)

        assert len(result.posts) == 2

    def test_empty_list_passes_through(self, mock_config, mock_logger):
        """Пустой список → стадия не вызывает LLM."""
        from stages import LLMFilterStage

        stage = LLMFilterStage(mock_config, mock_logger, MagicMock())
        ctx = PipelineContext(config=mock_config, posts=[])

        with patch("litellm.completion") as mock_c:
            result = stage.process(ctx)

        assert len(result.posts) == 0
        mock_c.assert_not_called()

    def test_filtered_posts_marked_in_state(self, mock_config, mock_logger):
        """Отсеянные LLM посты маркируются FILTERED в PostsRepository."""
        from stages import LLMFilterStage

        posts_repo = MagicMock()
        stage = LLMFilterStage(mock_config, mock_logger, posts_repo)
        posts = [
            _make_post(1, 1, "политика"),
            _make_post(2, 2, "нейтральный"),
        ]
        ctx = PipelineContext(config=mock_config, posts=posts)

        responses = [_mock_llm_response("SKIP"), _mock_llm_response("OK")]
        with patch("litellm.completion", side_effect=responses):
            stage.process(ctx)

        posts_repo.mark_processed.assert_called_once_with(1, 1, PostStatus.FILTERED)

    def test_timeout_post_skipped_without_marking(self, mock_config, mock_logger):
        """Таймаут LLM → пост пропускается без маркировки (попадёт в следующую выборку)."""
        from stages import LLMFilterStage

        posts_repo = MagicMock()
        stage = LLMFilterStage(mock_config, mock_logger, posts_repo)
        posts = [
            _make_post(1, 1, "таймаут"),
            _make_post(2, 2, "нейтральный"),
        ]
        ctx = PipelineContext(config=mock_config, posts=posts)

        responses = [
            litellm.Timeout("timeout", model="test", llm_provider="openai"),
            _mock_llm_response("OK"),
        ]
        with patch("litellm.completion", side_effect=responses):
            result = stage.process(ctx)

        assert len(result.posts) == 1
        assert result.posts[0].owner_id == 2
        posts_repo.mark_processed.assert_not_called()

    def test_mark_processed_error_doesnt_crash(self, mock_config, mock_logger):
        """Ошибка mark_processed (БД заблокирована) — стадия не падает, пост отсеян."""
        from stages import LLMFilterStage

        posts_repo = MagicMock()
        posts_repo.mark_processed.side_effect = RuntimeError("database locked")
        stage = LLMFilterStage(mock_config, mock_logger, posts_repo)
        posts = [
            _make_post(1, 1, "политика"),
            _make_post(2, 2, "нейтральный"),
        ]
        ctx = PipelineContext(config=mock_config, posts=posts)

        responses = [_mock_llm_response("SKIP"), _mock_llm_response("OK")]
        with patch("litellm.completion", side_effect=responses):
            result = stage.process(ctx)

        assert len(result.posts) == 1
        assert result.posts[0].owner_id == 2

    def test_summary_log_distinguishes_timeout_skips(self, mock_config, mock_logger, caplog):
        """Сводный лог различает «отсеяно» (FILTERED) и «пропущено» (таймаут)."""
        import logging

        from stages import LLMFilterStage

        stage = LLMFilterStage(mock_config, mock_logger, MagicMock())
        posts = [
            _make_post(1, 1, "политика"),
            _make_post(2, 2, "таймаут"),
            _make_post(3, 3, "нейтральный"),
        ]
        ctx = PipelineContext(config=mock_config, posts=posts)

        responses = [
            _mock_llm_response("SKIP"),
            litellm.Timeout("timeout", model="test", llm_provider="openai"),
            _mock_llm_response("OK"),
        ]
        with (
            patch("litellm.completion", side_effect=responses),
            caplog.at_level(logging.INFO, logger="vk_autoliker"),
        ):
            result = stage.process(ctx)

        assert len(result.posts) == 1
        assert result.posts[0].owner_id == 3
        assert "LLM-фильтр: 3 → 1 постов (1 отсеяно, 1 пропущено: таймаут)" in caplog.text

    def test_review_mode_unmarked_posts_skip_llm(self, mock_config, mock_logger):
        """В review-режиме непомеченные посты проходят без LLM-вызовов."""
        from post import PostReview
        from stages import LLMFilterStage

        mock_config.filter_mode = "review"
        stage = LLMFilterStage(mock_config, mock_logger, MagicMock())

        marked = _make_post(1, 1, "пост про карабин")
        marked.review = PostReview.SOFT
        marked.review_words = ["карабин"]
        clean = _make_post(2, 2, "чистый пост")
        ctx = PipelineContext(config=mock_config, posts=[marked, clean])

        with patch("litellm.completion", return_value=_mock_llm_response("OK")) as mock_c:
            result = stage.process(ctx)

        assert mock_c.call_count == 1
        assert [p.item_id for p in result.posts] == [1, 2]

    def test_review_mode_words_in_user_message(self, mock_config, mock_logger):
        """В review-режиме слова-триггеры попадают в user-сообщение."""
        from post import PostReview
        from stages import LLMFilterStage

        mock_config.filter_mode = "review"
        stage = LLMFilterStage(mock_config, mock_logger, MagicMock())

        marked = _make_post(1, 1, "пост")
        marked.review = PostReview.HARD
        marked.review_words = ["карабин", "виски"]
        ctx = PipelineContext(config=mock_config, posts=[marked])

        with patch("litellm.completion", return_value=_mock_llm_response("OK")) as mock_c:
            stage.process(ctx)

        user = mock_c.call_args.kwargs["messages"][1]["content"]
        assert "карабин" in user
        assert "виски" in user

    def test_review_mode_hard_marked_goes_to_arbitration(self, mock_config, mock_logger):
        """В review-режиме HARD-пометка тоже идёт на арбитраж: SKIP → FILTERED."""
        from post import PostReview
        from stages import LLMFilterStage

        mock_config.filter_mode = "review"
        posts_repo = MagicMock()
        stage = LLMFilterStage(mock_config, mock_logger, posts_repo)

        marked = _make_post(1, 1, "пост")
        marked.review = PostReview.HARD
        marked.review_words = ["наркотики"]
        ctx = PipelineContext(config=mock_config, posts=[marked])

        with patch("litellm.completion", return_value=_mock_llm_response("SKIP")):
            result = stage.process(ctx)

        assert len(result.posts) == 0
        posts_repo.mark_processed.assert_called_once_with(1, 1, PostStatus.FILTERED)

    def test_review_summary_log(self, mock_config, mock_logger, caplog):
        """Сводка review-режима: помечено N → прошло K, отсеяно R."""
        import logging

        from post import PostReview
        from stages import LLMFilterStage

        mock_config.filter_mode = "review"
        stage = LLMFilterStage(mock_config, mock_logger, MagicMock())

        p1 = _make_post(1, 1, "a")
        p1.review = PostReview.HARD
        p1.review_words = ["наркотики"]
        p2 = _make_post(2, 2, "b")
        p2.review = PostReview.SOFT
        p2.review_words = ["карабин"]
        ctx = PipelineContext(config=mock_config, posts=[p1, p2, _make_post(3, 3, "c")])

        responses = [_mock_llm_response("SKIP"), _mock_llm_response("OK")]
        with (
            patch("litellm.completion", side_effect=responses),
            caplog.at_level(logging.INFO, logger="vk_autoliker"),
        ):
            stage.process(ctx)

        assert "LLM-арбитраж: помечено 2 → прошло 1, отсеяно 1" in caplog.text
