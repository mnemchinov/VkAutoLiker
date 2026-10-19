"""Конвейер обработки постов: сбор → дедупликация → (опц.) LLM-фильтр.

Каждая стадия — отдельный класс с методом process(ctx) → ctx.
Pipeline прогоняет контекст через стадии по порядку.
Новые стадии добавляются в список без правки существующих.
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from post import Post
from settings import Settings


@dataclass
class SessionFunnel:
    """Отчёт о сессии: счётчики постов по этапам и причина остановки.

    Конвейерные стадии инкрементят свои счётчики (collected/filtered/
    stop_words_filtered/duplicates/llm_*), цикл лайков в liker.run() —
    liked/already_liked/
    failed и reason. Сериализуется в JSON и хранится в sessions.report —
    «статус» в боте показывает его второй строкой.
    """

    collected: int = 0
    filtered: int = 0
    stop_words_filtered: int = 0
    duplicates: int = 0
    llm_filtered: int = 0
    llm_timeout: int = 0
    liked: int = 0
    already_liked: int = 0
    failed: int = 0
    reason: str = ""


@dataclass
class PipelineContext:
    """Контекст конвейера: переносит посты, конфиг и target_likes между стадиями.

    posts — список постов, накапливаемый по мере прохождения стадий.
    config — конфигурация приложения, доступна всем стадиям.
    target_likes — целевое число лайков в текущей сессии (random от min до max),
    используется CollectStage для раннего выхода (enough = target_likes * 2).
    funnel — отчёт сессии: стадии пишут свои счётчики, liker.run() дописывает
    лайки и причину остановки.
    """

    config: Settings
    target_likes: int = 0
    posts: list[Post] = field(default_factory=list)
    funnel: SessionFunnel = field(default_factory=SessionFunnel)


@runtime_checkable
class Stage(Protocol):
    """Интерфейс стадии: принимает контекст, возвращает изменённый контекст."""

    def process(self, ctx: PipelineContext) -> PipelineContext: ...


class Pipeline:
    """Прогоняет контекст через список стадий по порядку.

    Каждая стадия получает контекст и возвращает его (возможно изменённый).
    Порядок стадий = порядок в списке конструктора.
    """

    def __init__(self, stages: list[Stage]):
        """Инициализирует конвейер со списком стадий."""
        self._stages = stages

    def run(self, ctx: PipelineContext) -> PipelineContext:
        """Прогоняет контекст через все стадии, возвращает результат."""
        for stage in self._stages:
            ctx = stage.process(ctx)
        return ctx
