"""Dataclass-модель поста VK."""

from dataclasses import dataclass


@dataclass
class Post:
    """Пост VK: идентификаторы, текст, дата (unix timestamp) и URL."""

    owner_id: int
    item_id: int
    text: str
    date: int
    url: str = ""
