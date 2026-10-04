"""Композит: прогоняет пост через список structural-фильтров.

Пост отсеивается, если хотя бы один фильтр вернул should_skip == True.
Включает только быстрые проверки (date, empty). StopWordsFilter и
LLMTopicFilter передаются в CollectStage и LLMFilterStage отдельно.
"""

from post import Post

from .protocol import PostFilterProtocol


class FilterChain:
    """Композит: прогоняет пост через список фильтров."""

    def __init__(self, filters: list[PostFilterProtocol]):
        """Инициализирует цепочку фильтров."""
        self._filters = filters

    def filter(self, posts: list[Post]) -> list[Post]:
        """Возвращает посты, прошедшие все фильтры."""
        return [p for p in posts if not self.should_skip(p)]

    def should_skip(self, post: Post) -> bool:
        """Проверяет один пост: True, если хотя бы один фильтр отсёк."""
        return any(f.should_skip(post) for f in self._filters)

    def log_summaries(self) -> None:
        """Вызывает log_summary() у всех фильтров, у которых он есть."""
        for f in self._filters:
            if hasattr(f, "log_summary"):
                f.log_summary()
