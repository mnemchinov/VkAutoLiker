"""Фильтрация постов по давности и наличию текста.

Фильтр проверяет только свойства поста (дата, текст) — без обращения к StateStore.
Проверка is_processed выполняется в CollectStage, где она нужна для раннего выхода.
"""

import time
from typing import List

from config import AppConfig
from logger import AppLogger
from post import Post


class PostFilter:
    """Отсеивает посты старше days_back дней и без текста."""

    def __init__(self, config: AppConfig, logger: AppLogger):
        """Инициализирует фильтр с параметром days_back."""
        self._days_back = config.search.days_back
        self._logger = logger

    def filter(self, posts: List[Post]) -> List[Post]:
        """Возвращает только свежие посты с непустым текстом."""
        cutoff = int(time.time()) - (self._days_back * 86400)
        result: List[Post] = []

        for post in posts:
            if post.date < cutoff:
                continue

            if not post.text.strip():
                continue

            result.append(post)

        removed = len(posts) - len(result)
        self._logger.info(f"Фильтр: {len(posts)} → {len(result)} постов ({removed} отфильтровано)")
        return result
