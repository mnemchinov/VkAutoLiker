"""Фильтр пустого текста: отсеивает посты без текста."""

from post import Post

from .protocol import PostFilterProtocol


class EmptyTextFilter(PostFilterProtocol):
    """Отсеивает посты с пустым текстом."""

    def should_skip(self, post: Post) -> bool:
        """True, если текст поста пустой или состоит из пробелов."""
        return not post.text.strip()
