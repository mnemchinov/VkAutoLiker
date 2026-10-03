"""Интерфейс фильтра постов.

Все фильтры реализуют PostFilterProtocol.should_skip(post) -> bool:
True — отсеять пост, False — оставить.
"""

from typing import Protocol, runtime_checkable

from post import Post


@runtime_checkable
class PostFilterProtocol(Protocol):
    """Интерфейс фильтра постов: True — отсеять, False — оставить."""

    def should_skip(self, post: Post) -> bool: ...
