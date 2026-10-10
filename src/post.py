"""Dataclass-модель поста VK, статус обработки и шаблон URL."""

from dataclasses import dataclass, field
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


class PostReview(IntEnum):
    """Серьёзность метки стоп-слов для LLM-арбитража.

    NONE — стоп-слова не сработали (или словарь не участвует).
    SOFT — сработало мягкое слово (без '!'): в режиме review пост идёт
           на арбитраж, безобидный контекст не наказуем.
    HARD — сработало жёсткое слово (с '!'): в режиме stop_words пост
           отсекается сразу, в режиме review тоже идёт на арбитраж.
    """

    NONE = 0
    SOFT = 1
    HARD = 2


def build_post_url(owner_id: int, item_id: int) -> str:
    """Строит URL поста по owner_id и item_id."""
    return POST_URL_TEMPLATE.format(owner_id=owner_id, item_id=item_id)


@dataclass
class Post:
    """Пост VK: идентификаторы, текст, дата (unix timestamp) и URL.

    review / review_words — метка стоп-слов для LLM-арбитража (режим review):
    устанавливается CollectStage, в БД не сохраняется.
    """

    owner_id: int
    item_id: int
    text: str
    date: int
    url: str = ""
    from_id: int = 0
    review: PostReview = PostReview.NONE
    review_words: list[str] = field(default_factory=list)
