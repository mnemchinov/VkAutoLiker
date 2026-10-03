"""Пакет фильтрации постов: протокол, фильтры и композит FilterChain.

Каждый фильтр реализует PostFilterProtocol.should_skip(post) -> bool:
True — отсеять пост, False — оставить.

FilterChain объединяет фильтры и применяется в CollectStage._accept().
Быстрые фильтры (date, empty, stop_words) работают inline при сборе,
сохраняя ранний выход (enough = target_likes * 2).

LLMTopicFilter реализует протокол, но НЕ входит в FilterChain —
вызывается через LLMFilterStage после DedupStage (стоимость вызова).
"""

from .date_filter import DateFilter
from .empty_text_filter import EmptyTextFilter
from .filter_chain import FilterChain
from .llm_topic_filter import LLMTopicFilter
from .protocol import PostFilterProtocol
from .stop_words_filter import StopWordsFilter

__all__ = [
    "DateFilter",
    "EmptyTextFilter",
    "FilterChain",
    "LLMTopicFilter",
    "PostFilterProtocol",
    "StopWordsFilter",
]
