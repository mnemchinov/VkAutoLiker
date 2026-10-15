"""Фильтр неизвестного содержания: отсеивает посты, содержание которых не известно.

Содержание — это post.text: текст поста или извлечённое из метаданных
вложений при парсинге (см. VkApiSearchService._extract_attachment_text).
Пусто — пост неизвестен, лайкать его нельзя (канон, инвариант #26).
"""

from post import Post

from .protocol import PostFilterProtocol


class EmptyTextFilter(PostFilterProtocol):
    """Отсеивает посты с неизвестным содержанием (пустой текст после обогащения)."""

    def should_skip(self, post: Post) -> bool:
        """True, если содержание поста пусто или состоит из пробелов."""
        return not post.text.strip()
