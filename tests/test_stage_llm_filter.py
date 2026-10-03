"""Unit-тесты LLMTopicFilter и LLMFilterStage.

litellm.completion мокается через patch — реальных запросов к LLM нет.
"""

import time
from unittest.mock import MagicMock, patch

from post import Post, build_post_url
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
            assert len(sent_text) <= 10

    def test_skip_in_answer_detected(self, mock_config, mock_logger):
        """Ответ содержит 'SKIP' (с пробелами/регистром) → отсеивание."""
        from post_filter import LLMTopicFilter

        f = LLMTopicFilter(mock_config, mock_logger)
        post = _make_post(1, 1, "пост")

        with patch("litellm.completion", return_value=_mock_llm_response("  skip  ")):
            assert f.should_skip(post) is True

    def test_system_prompt_built_from_stop_topics(self, mock_config, mock_logger):
        """Промпт собирается из llm_stop_topics, если llm_system_prompt пуст."""
        from post_filter import LLMTopicFilter

        mock_config.llm_system_prompt = ""
        mock_config.llm_stop_topics = ["политика", "религия"]
        f = LLMTopicFilter(mock_config, mock_logger)

        assert "политика" in f._system_prompt
        assert "религия" in f._system_prompt
        assert "SKIP" in f._system_prompt

    def test_custom_system_prompt_overrides_stop_topics(self, mock_config, mock_logger):
        """llm_system_prompt переопределяет сборку из llm_stop_topics."""
        from post_filter import LLMTopicFilter

        mock_config.llm_system_prompt = "Кастомный промпт"
        mock_config.llm_stop_topics = ["политика"]
        f = LLMTopicFilter(mock_config, mock_logger)

        assert f._system_prompt == "Кастомный промпт"

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

        stage = LLMFilterStage(mock_config, mock_logger)
        posts = [
            _make_post(1, 1, "политика"),
            _make_post(2, 2, "нейтральный пост"),
            _make_post(3, 3, "религия"),
        ]
        ctx = PipelineContext(config=mock_config, posts=posts)

        responses = [_mock_llm_response("SKIP"), _mock_llm_response("OK"), _mock_llm_response("SKIP")]
        with patch("litellm.completion", side_effect=responses):
            result = stage.process(ctx)

        assert len(result.posts) == 1
        assert result.posts[0].owner_id == 2

    def test_keeps_all_on_exception(self, mock_config, mock_logger):
        """Ошибка LLM → все посты остаются (should_skip False)."""
        from stages import LLMFilterStage

        stage = LLMFilterStage(mock_config, mock_logger)
        posts = [_make_post(1, 1, "a"), _make_post(2, 2, "b")]
        ctx = PipelineContext(config=mock_config, posts=posts)

        with patch("litellm.completion", side_effect=RuntimeError("network")):
            result = stage.process(ctx)

        assert len(result.posts) == 2

    def test_empty_list_passes_through(self, mock_config, mock_logger):
        """Пустой список → стадия не вызывает LLM."""
        from stages import LLMFilterStage

        stage = LLMFilterStage(mock_config, mock_logger)
        ctx = PipelineContext(config=mock_config, posts=[])

        with patch("litellm.completion") as mock_c:
            result = stage.process(ctx)

        assert len(result.posts) == 0
        mock_c.assert_not_called()
