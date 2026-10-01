"""Unit-тесты стадии дедупликации DedupStage."""

from pipeline import PipelineContext
from post import Post, build_post_url
from stage_dedup import DedupStage


def _make_post(owner_id: int, item_id: int) -> Post:
    """Создаёт тестовый Post."""
    return Post(owner_id=owner_id, item_id=item_id, text="текст", date=0, url=build_post_url(owner_id, item_id))


class TestDedupStage:
    def test_removes_duplicates(self):
        """Дубликаты по (owner_id, item_id) схлопываются."""
        posts = [_make_post(1, 1), _make_post(1, 2), _make_post(1, 1), _make_post(1, 3), _make_post(1, 2)]
        ctx = PipelineContext(posts=posts)

        result = DedupStage().process(ctx)

        keys = [(p.owner_id, p.item_id) for p in result.posts]
        assert len(keys) == len(set(keys))
        assert sorted(keys) == [(1, 1), (1, 2), (1, 3)]

    def test_preserves_order(self):
        """Порядок первого вхождения сохраняется."""
        posts = [_make_post(3, 1), _make_post(2, 1), _make_post(3, 1), _make_post(1, 1)]
        ctx = PipelineContext(posts=posts)

        result = DedupStage().process(ctx)

        keys = [(p.owner_id, p.item_id) for p in result.posts]
        assert keys == [(3, 1), (2, 1), (1, 1)]

    def test_empty_list_passes_through(self):
        """Пустой список проходит без изменений."""
        ctx = PipelineContext(posts=[])

        result = DedupStage().process(ctx)

        assert result.posts == []
