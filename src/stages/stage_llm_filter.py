"""Pipeline-стадия LLMFilterStage.

LLMTopicFilter (сам класс фильтра) живёт в post_filter/llm_topic_filter.py вместе
с остальными фильтрами (DateFilter, EmptyTextFilter, StopWordsFilter) — все реализуют
PostFilterProtocol. Здесь — только stage-обёртка для конвейера.

LLMFilterStage размещается ПОСЛЕ DedupStage, чтобы:
  1. Не отправлять дубликаты в LLM (экономия вызовов и денег).
  2. Работать с уже отфильтрованным списком (~target * 2 постов), а не с сырыми.

Ban-risk: нулевой — запросы идут к провайдеру LLM, не к VK.
"""

from logger import AppLogger
from post_filter import LLMTopicFilter
from settings import Settings

from .pipeline import PipelineContext


class LLMFilterStage:
    """Pipeline-стадия: отсеивает посты через LLMTopicFilter.

    Размещается после DedupStage, чтобы LLM работал с дедуплицированным списком.
    """

    def __init__(self, config: Settings, logger: AppLogger):
        """Инициализирует стадию с LLMTopicFilter."""
        self._filter = LLMTopicFilter(config, logger)
        self._logger = logger

    def process(self, ctx: PipelineContext) -> PipelineContext:
        """Фильтрует ctx.posts через LLM, обновляет список."""
        before = len(ctx.posts)
        ctx.posts = [p for p in ctx.posts if not self._filter.should_skip(p)]
        removed = before - len(ctx.posts)
        self._logger.info(f"LLM-фильтр: {before} → {len(ctx.posts)} постов ({removed} отсеяно)")
        return ctx
