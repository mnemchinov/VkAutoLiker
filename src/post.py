"""Dataclass-модель поста VK и шаблон URL."""

from dataclasses import dataclass

POST_URL_TEMPLATE = "https://vk.ru/wall{owner_id}_{item_id}"


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
