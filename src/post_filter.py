"""Фильтрация постов по давности, дедупликации и наличию текста."""

import time
from typing import List

from post import Post
from state_store import StateStore
from config import AppConfig
from logger import AppLogger


class PostFilter:
    """Отсеивает посты старше days_back дней, уже обработанные и без текста."""

    def __init__(self, config: AppConfig, state_store: StateStore, logger: AppLogger):
        self._days_back = config.search.days_back
        self._state = state_store
        self._logger = logger

    def filter(self, posts: List[Post]) -> List[Post]:
        """Возвращает только свежие, необработанные посты с непустым текстом."""
        cutoff = int(time.time()) - (self._days_back * 86400)
        result: List[Post] = []

        for post in posts:
            if post.date < cutoff:
                continue

            if self._state.is_processed(post.owner_id, post.item_id):
                continue

            if not post.text.strip():
                continue

            result.append(post)

        removed = len(posts) - len(result)
        self._logger.info(f"Фильтр: {len(posts)} → {len(result)} постов ({removed} отфильтровано)")
        return result
