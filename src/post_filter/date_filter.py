"""Фильтр по давности: отсеивает посты старше days_back дней."""

import time

from post import Post

from .protocol import PostFilterProtocol


class DateFilter(PostFilterProtocol):
    """Отсеивает посты старше days_back дней."""

    def __init__(self, days_back: int):
        """Инициализирует фильтр по давности."""
        self._days_back = days_back

    def should_skip(self, post: Post) -> bool:
        """True, если пост старше days_back дней."""
        cutoff = int(time.time()) - (self._days_back * 86400)
        return post.date < cutoff
