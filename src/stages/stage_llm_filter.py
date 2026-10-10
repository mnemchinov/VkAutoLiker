"""Pipeline-стадия LLMFilterStage.

LLMTopicFilter (сам класс фильтра) живёт в post_filter/llm_topic_filter.py вместе
с остальными фильтрами (DateFilter, EmptyTextFilter, StopWordsFilter) — все реализуют
PostFilterProtocol. Здесь — только stage-обёртка для конвейера.

LLMFilterStage размещается ПОСЛЕ DedupStage, чтобы:
  1. Не отправлять дубликаты в LLM (экономия вызовов и денег).
  2. Работать с уже отфильтрованным списком (~target * 2 постов), а не с сырыми.

Режимы (config.filter_mode):
  review — LLM арбитраж ТОЛЬКО помеченных стоп-словами постов (post.review != NONE),
           в промпт передаются слова-триггеры (post.review_words);
  llm — LLM проверяет ВСЕ посты по темам (llm_stop_topics).

Ban-risk: нулевой — запросы идут к провайдеру LLM, не к VK.
"""

from logger import AppLogger
from post import Post, PostReview, PostStatus
from post_filter import LLMTimeoutError, LLMTopicFilter
from repositories import PostsRepository
from settings import Settings

from .pipeline import PipelineContext


class LLMFilterStage:
    """Pipeline-стадия: LLM-проверка постов (арбитраж меток или все посты).

    Размещается после DedupStage, чтобы LLM работал с дедуплицированным списком.
    Отсеянные посты маркируются FILTERED — не повторяются в следующих сессиях.
    """

    def __init__(self, config: Settings, logger: AppLogger, posts_repo: PostsRepository):
        """Инициализирует стадию с LLMTopicFilter и PostsRepository для маркировки."""
        self._config = config
        self._filter = LLMTopicFilter(config, logger)
        self._logger = logger
        self._posts_repo = posts_repo

    def process(self, ctx: PipelineContext) -> PipelineContext:
        """Фильтрует ctx.posts через LLM, маркирует отсеянные как FILTERED.

        review-режим: на арбитраж идут только помеченные посты, непомеченные
        проходят без LLM-вызова. llm-режим: проверяются все посты.
        При таймауте LLM (LLMTimeoutError) пост пропускается без маркировки —
        попадёт в следующую выборку для повторной проверки.
        Сводный лог различает «отсеяно» (FILTERED) и «пропущено» (таймаут):
        пропущенные посты не маркировались и будут перепроверены.
        """
        before = len(ctx.posts)
        kept: list[Post] = []
        marked = 0
        skipped = 0
        review_mode = self._config.filter_mode == "review"
        for p in ctx.posts:
            if review_mode and p.review == PostReview.NONE:
                kept.append(p)
                continue
            if review_mode:
                marked += 1
            try:
                skip = self._filter.should_skip(p, found_words=p.review_words or None)
            except LLMTimeoutError:
                skipped += 1
                continue
            if skip:
                try:
                    self._posts_repo.mark_processed(p.owner_id, p.item_id, PostStatus.FILTERED)
                except Exception as e:
                    self._logger.warning(
                        f"Не удалось маркировать пост {p.owner_id}_{p.item_id} как FILTERED: {e}"
                    )
            else:
                kept.append(p)
        ctx.posts = kept
        removed = before - len(kept) - skipped
        if review_mode:
            passed = marked - removed - skipped
            timeout_part = f", {skipped} пропущено: таймаут" if skipped else ""
            self._logger.info(
                f"LLM-арбитраж: помечено {marked} → прошло {passed}, "
                f"отсеяно {removed}{timeout_part}"
            )
        elif skipped:
            self._logger.info(
                f"LLM-фильтр: {before} → {len(kept)} постов "
                f"({removed} отсеяно, {skipped} пропущено: таймаут)"
            )
        else:
            self._logger.info(f"LLM-фильтр: {before} → {len(kept)} постов ({removed} отсеяно)")
        return ctx
