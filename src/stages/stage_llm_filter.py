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
from post import PostStatus
from post_filter import LLMTimeoutError, LLMTopicFilter
from repositories import PostsRepository
from settings import Settings

from .pipeline import PipelineContext


class LLMFilterStage:
    """Pipeline-стадия: отсеивает посты через LLMTopicFilter.

    Размещается после DedupStage, чтобы LLM работал с дедуплицированным списком.
    Отсеянные посты маркируются FILTERED — не повторяются в следующих сессиях.
    """

    def __init__(self, config: Settings, logger: AppLogger, posts_repo: PostsRepository):
        """Инициализирует стадию с LLMTopicFilter и PostsRepository для маркировки."""
        self._filter = LLMTopicFilter(config, logger)
        self._logger = logger
        self._posts_repo = posts_repo

    def process(self, ctx: PipelineContext) -> PipelineContext:
        """Фильтрует ctx.posts через LLM, маркирует отсеянные как FILTERED.

        При таймауте LLM (LLMTimeoutError) пост пропускается без маркировки —
        попадёт в следующую выборку для повторной проверки.
        """
        before = len(ctx.posts)
        kept: list = []
        for p in ctx.posts:
            try:
                if self._filter.should_skip(p):
                    self._posts_repo.mark_processed(p.owner_id, p.item_id, PostStatus.FILTERED)
                else:
                    kept.append(p)
            except LLMTimeoutError:
                continue
        ctx.posts = kept
        removed = before - len(ctx.posts)
        self._logger.info(f"LLM-фильтр: {before} → {len(ctx.posts)} постов ({removed} отсеяно)")
        return ctx
