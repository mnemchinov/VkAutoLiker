"""Фильтрация постов: протокол, отдельные фильтры и композит FilterChain.

Каждый фильтр реализует PostFilterProtocol.should_skip(post) -> bool:
True — отсеять пост, False — оставить.

FilterChain объединяет фильтры и применяется в CollectStage._accept().
Быстрые фильтры (date, empty, stop_words) работают inline при сборе,
сохраняя ранний выход (enough = target_likes * 2).

Стоп-слова загружаются из двух источников:
  1. stop_words_file — внешний текстовый файл (одно слово на строку, '#' — комментарий)
  2. stop_words — inline-список из Settings
Списки объединяются. Если файл не найден — предупреждение в лог, используется только inline.

LLMTopicFilter также живёт здесь (реализует PostFilterProtocol), но НЕ входит
в FilterChain — вызывается через LLMFilterStage после DedupStage (стоимость вызова).
"""

import time
from pathlib import Path
from typing import Protocol, runtime_checkable

import litellm

from logger import AppLogger
from post import Post
from settings import Settings


@runtime_checkable
class PostFilterProtocol(Protocol):
    """Интерфейс фильтра постов: True — отсеять, False — оставить."""

    def should_skip(self, post: Post) -> bool: ...


class DateFilter:
    """Отсеивает посты старше days_back дней."""

    def __init__(self, days_back: int):
        """Инициализирует фильтр по давности."""
        self._days_back = days_back

    def should_skip(self, post: Post) -> bool:
        """True, если пост старше days_back дней."""
        cutoff = int(time.time()) - (self._days_back * 86400)
        return post.date < cutoff


class EmptyTextFilter:
    """Отсеивает посты с пустым текстом."""

    def should_skip(self, post: Post) -> bool:
        """True, если текст поста пустой или состоит из пробелов."""
        return not post.text.strip()


class StopWordsFilter:
    """Отсеивает посты, содержащие стоп-слова (регистронезависимо).

    Стоп-слова загружаются из файла (stop_words_file) и inline-списка (stop_words).
    Объединяются в один set. Если файл не найден — warning, используется только inline.
    """

    def __init__(self, config: Settings, logger: AppLogger):
        """Инициализирует фильтр стоп-слов из файла и inline-списка Settings."""
        self._logger = logger

        file_words = self._load_stop_words_file(config.stop_words_file)
        inline_words = [w.lower() for w in config.stop_words]
        self._stop_words = list(set(file_words + inline_words))

    def _load_stop_words_file(self, path: str) -> list[str]:
        """Загружает стоп-слова из текстового файла.

        Формат: одно слово на строку, строки с '#' и пустые — пропускаются.
        Возвращает пустой список, если путь пуст или файл не найден.
        """
        if not path:
            return []

        p = Path(path)
        if not p.is_file():
            self._logger.warning(f"Файл стоп-слов не найден: {path}")
            return []

        words: list[str] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            words.append(stripped.lower())

        self._logger.info(f"Загружено {len(words)} стоп-слов из {path}")
        return words

    def should_skip(self, post: Post) -> bool:
        """True, если текст поста содержит любое стоп-слово."""
        if not self._stop_words:
            return False
        return any(w in post.text.lower() for w in self._stop_words)


class FilterChain:
    """Композит: прогоняет пост через список фильтров.

    Пост отсеивается, если хотя бы один фильтр вернул should_skip == True.
    Порядок фильтров важен для производительности: быстрые проверки (date,
    empty) идут раньше тяжёлых (stop_words, LLM).
    """

    def __init__(self, filters: list[PostFilterProtocol]):
        """Инициализирует цепочку фильтров."""
        self._filters = filters

    def filter(self, posts: list[Post]) -> list[Post]:
        """Возвращает посты, прошедшие все фильтры."""
        return [p for p in posts if not any(f.should_skip(p) for f in self._filters)]


DEFAULT_SYSTEM_PROMPT = """Ты — модератор постов ВКонтакте. \
Определи, подходит ли пост для автоматического лайка корпоративным аккаунтом.

Отклоняй (ответ SKIP) посты на темы: политика, выборы, секс, порно, религия, \
алкоголь, курение, наркотики, азартные игры, оружие, экстремизм, криптовалюта.

Разрешай (ответ OK) нейтральные посты: новости компании, продукция, акции, \
повседневный контент, рецепты, лайфхаки, кухня, быт, спорт без политики.

Ответь только одним словом: SKIP или OK."""


class LLMTopicFilter:
    """Фильтр тематики постов через LLM (litellm.completion).

    Реализует PostFilterProtocol, но НЕ включается в FilterChain —
    вызывается только через LLMFilterStage после DedupStage,
    чтобы LLM работал с дедуплицированным списком (~40 постов, не 100+).

    should_skip возвращает True, если LLM ответил SKIP.
    При любой ошибке — False (не отсеивать, безопаснее оставить).
    """

    def __init__(self, config: Settings, logger: AppLogger):
        """Инициализирует LLM-фильтр с параметрами из конфигурации."""
        self._config = config
        self._logger = logger
        self._system_prompt = config.llm_system_prompt or DEFAULT_SYSTEM_PROMPT

    def should_skip(self, post: Post) -> bool:
        """True, если LLM определил пост как нежелательный (SKIP).

        При ошибке LLM — False (не отсеивать). Текст обрезается до max_text_length.
        """
        text = post.text.strip()[: self._config.llm_max_text_length]
        if not text:
            return False

        try:
            response = litellm.completion(
                model=self._config.llm_model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": text},
                ],
                api_base=self._config.llm_api_base or None,
                api_key=self._config.llm_api_key.get_secret_value() or None,
                timeout=self._config.llm_timeout,
                temperature=0,
                max_tokens=1,
            )
            answer = response.choices[0].message.content.strip().upper()
            skip = "SKIP" in answer
            if skip:
                self._logger.debug(f"LLM отсеял пост {post.owner_id}_{post.item_id}: {text[:50]}")
            return skip
        except Exception as e:
            self._logger.warning(f"Ошибка LLM для поста {post.owner_id}_{post.item_id}: {e}")
            return False
