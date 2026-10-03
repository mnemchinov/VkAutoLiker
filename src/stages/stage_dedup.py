"""Стадия дедупликации: убирает повторы постов по (owner_id, item_id).

Посты из разных источников могут пересекаться (один и тот же пост на стене
группы и в ленте новостей). Дедупликация сохраняет первое вхождение.
"""

from .pipeline import PipelineContext


class DedupStage:
    """Дедуплицирует посты по паре (owner_id, item_id)."""

    def process(self, ctx: PipelineContext) -> PipelineContext:
        """Убирает дубликаты, сохраняя порядок первого вхождения."""
        unique: dict = {}
        for p in ctx.posts:
            key = (p.owner_id, p.item_id)
            if key not in unique:
                unique[key] = p
        ctx.posts = list(unique.values())
        return ctx
