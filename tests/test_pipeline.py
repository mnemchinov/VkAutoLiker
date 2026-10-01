"""Unit-тесты конвейера Pipeline.

Pipeline прогоняет PipelineContext через стадии по порядку.
Стадии — MagicMock для изоляции.
"""

from unittest.mock import MagicMock

from pipeline import Pipeline, PipelineContext
from post import Post, build_post_url


def _make_post(owner_id: int = 1, item_id: int = 1) -> Post:
    """Создаёт тестовый Post."""
    return Post(owner_id=owner_id, item_id=item_id, text="текст", date=0, url=build_post_url(owner_id, item_id))


class TestPipeline:
    def test_stages_called_in_order(self):
        """Стадии вызываются в порядке передачи в конструктор."""
        calls = []

        def make_stage(name):
            stage = MagicMock()
            stage.process.side_effect = lambda ctx: (calls.append(name), ctx)[1]
            return stage

        pipeline = Pipeline([make_stage("A"), make_stage("B"), make_stage("C")])
        ctx = PipelineContext(config=MagicMock())
        pipeline.run(ctx)

        assert calls == ["A", "B", "C"]

    def test_chaining_returns_final_context(self):
        """Pipeline возвращает контекст после последней стадии."""
        stage = MagicMock()
        final_ctx = PipelineContext(config=MagicMock(), posts=[_make_post(1, 1)])
        stage.process.return_value = final_ctx

        pipeline = Pipeline([stage])
        input_ctx = PipelineContext(config=MagicMock())
        result = pipeline.run(input_ctx)

        assert result is final_ctx
        assert len(result.posts) == 1

    def test_empty_stages_returns_input(self):
        """Pipeline без стадий возвращает входной контекст без изменений."""
        pipeline = Pipeline([])
        ctx = PipelineContext(config=MagicMock(), posts=[_make_post(1, 1)])
        result = pipeline.run(ctx)

        assert result is ctx
        assert len(result.posts) == 1
