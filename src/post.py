"""Dataclass-модель поста VK, статус обработки и шаблон URL."""

from dataclasses import dataclass
from enum import IntEnum

POST_URL_TEMPLATE = "https://vk.ru/wall{owner_id}_{item_id}"


class PostStatus(IntEnum):
    """Статус обработки поста в БД.

    UNKNOWN — миграция существующих записей (до добавления status).
    LIKED — успешный лайк (или уже был лайкнут).
    FILTERED — отсеян стоп-словами или LLM.
    """

    UNKNOWN = 0
    LIKED = 1
    FILTERED = 2


def build_post_url(owner_id: int, item_id: int) -> str:
    """Строит URL поста по owner_id и item_id."""
    return POST_URL_TEMPLATE.format(owner_id=owner_id, item_id=item_id)


@dataclass
class Post:
    """Пост VK: идентификаторы, текст, дата (unix timestamp) и URL."""

    owner_id: int
    item_id: int
    text: str
    date: int
    url: str = ""
    from_id: int = 0
