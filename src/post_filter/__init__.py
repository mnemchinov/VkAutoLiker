"""Пакет фильтрации постов: протокол, фильтры и композит FilterChain.

Каждый фильтр реализует PostFilterProtocol.should_skip(post) -> bool:
True — отсеять пост, False — оставить.

FilterChain объединяет structural-фильтры (date, empty) и применяется
в CollectStage._accept(). StopWordsFilter передаётся в CollectStage
отдельно: жёсткое слово ('!') отсекает пост, мягкое — помечает для
LLM-арбитража (matched() → StopMatch).

LLMTopicFilter реализует протокол, но НЕ входит в FilterChain —
вызывается через LLMFilterStage после DedupStage (стоимость вызова).
"""

from .date_filter import DateFilter
from .empty_text_filter import EmptyTextFilter
from .filter_chain import FilterChain
from .llm_topic_filter import LLMTimeoutError, LLMTopicFilter
from .protocol import PostFilterProtocol
from .stop_words_filter import StopMatch, StopWordsFilter

__all__ = [
    "DateFilter",
    "EmptyTextFilter",
    "FilterChain",
    "LLMTimeoutError",
    "LLMTopicFilter",
    "PostFilterProtocol",
    "StopMatch",
    "StopWordsFilter",
]
