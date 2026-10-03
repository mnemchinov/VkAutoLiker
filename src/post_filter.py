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

import re
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx
import litellm
from pymorphy3 import MorphAnalyzer

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
    Объединяются и разделяются на три группы:

      1. _stop_lemmas — леммы русских слов (pymorphy3: «церковью» → «церковь»).
         Текст поста лемматизируется, леммы сравниваются с этим множеством.
      2. _stop_substrings — нерусские слова и аббревиатуры (18+, xxx, СВО, mlm) —
         substring-поиск, лемматизация неприменима.
      3. _stop_phrases — многословные фразы («игровые автоматы») — substring-поиск.

    MorphAnalyzer — class-level singleton: словарь (~5MB) грузится один раз.
    """

    _morph: MorphAnalyzer | None = None

    @classmethod
    def _get_morph(cls) -> MorphAnalyzer:
        """Возвращает class-level singleton MorphAnalyzer (словарь грузится один раз)."""
        if cls._morph is None:
            cls._morph = MorphAnalyzer()
        return cls._morph

    def __init__(self, config: Settings, logger: AppLogger):
        """Инициализирует фильтр стоп-слов из файла и inline-списка Settings."""
        self._logger = logger
        self._checked: int = 0
        self._skipped: int = 0

        file_words = self._load_stop_words_file(config.stop_words_file)
        inline_words = [w.lower() for w in config.stop_words]
        all_words = set(file_words + inline_words)

        self._stop_lemmas: set[str] = set()
        self._stop_substrings: set[str] = set()
        self._stop_phrases: set[str] = set()

        morph = self._get_morph()
        for word in all_words:
            if " " in word:
                self._stop_phrases.add(word)
            elif re.fullmatch(r"[а-яё]+", word):
                parse = morph.parse(word)[0]
                self._stop_lemmas.add(parse.normal_form)
            else:
                self._stop_substrings.add(word)

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
        """True, если текст поста содержит любое стоп-слово.

        Сначала проверяются substring-группы (быстро), затем лемматизация.
        Совпадения логируются на INFO, OK — на DEBUG.
        """
        self._checked += 1
        post_id = f"{post.owner_id}_{post.item_id}"

        if not self._stop_lemmas and not self._stop_substrings and not self._stop_phrases:
            self._logger.debug(f"Стоп-слова: пост {post_id} → OK (словарь пуст)")
            return False

        text_lower = post.text.lower()

        for s in self._stop_substrings:
            if s in text_lower:
                self._skipped += 1
                self._logger.info(f"Стоп-слова: пост {post_id} → совпадение '{s}' (substring)")
                return True
        for p in self._stop_phrases:
            if p in text_lower:
                self._skipped += 1
                self._logger.info(f"Стоп-слова: пост {post_id} → совпадение '{p}' (фраза)")
                return True

        if not self._stop_lemmas:
            self._logger.debug(f"Стоп-слова: пост {post_id} → OK")
            return False

        morph = self._get_morph()
        for token in re.findall(r"[а-яё]{3,}", text_lower):
            lemma = morph.parse(token)[0].normal_form
            if lemma in self._stop_lemmas:
                self._skipped += 1
                self._logger.info(
                    f"Стоп-слова: пост {post_id} → совпадение '{token}' → лемма '{lemma}'"
                )
                return True

        self._logger.debug(f"Стоп-слова: пост {post_id} → OK")
        return False

    def log_summary(self) -> None:
        """Логирует сводку: проверено N, отсеяно M (X%)."""
        pct = round(self._skipped / self._checked * 100, 1) if self._checked else 0.0
        self._logger.info(
            f"Стоп-слова: проверено {self._checked}, отсеяно {self._skipped} ({pct}%)"
        )


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

    def log_summaries(self) -> None:
        """Вызывает log_summary() у всех фильтров, у которых он есть."""
        for f in self._filters:
            if hasattr(f, "log_summary"):
                f.log_summary()


DEFAULT_SYSTEM_PROMPT_TEMPLATE = """Ты — модератор постов ВКонтакте. \
Определи, подходит ли пост для автоматического лайка.

Отклоняй (ответ SKIP) посты на темы:
{topics}

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
        """Инициализирует LLM-фильтр с параметрами из конфигурации.

        Промпт собирается из config.llm_stop_topics (список стоп-тем),
        если config.llm_system_prompt не задан явно.

        При llm_ssl_verify=False устанавливает litellm.client_session с
        отключённой проверкой SSL — для корпоративных endpoint'ов с
        самоподписанным CA-сертификатом, отсутствующим в certifi.
        """
        self._config = config
        self._logger = logger
        if config.llm_system_prompt:
            self._system_prompt = config.llm_system_prompt
        else:
            topics = "\n".join(f"— {t};" for t in config.llm_stop_topics)
            self._system_prompt = DEFAULT_SYSTEM_PROMPT_TEMPLATE.format(topics=topics)

        if not config.llm_ssl_verify:
            litellm.client_session = httpx.Client(verify=False, follow_redirects=True)

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
                max_tokens=self._config.llm_max_tokens,
            )
            answer = response.choices[0].message.content.strip().upper()
            skip = "SKIP" in answer
            self._logger.info(
                f"LLM: пост {post.owner_id}_{post.item_id} → ответ={answer!r} skip={skip}"
            )
            return skip
        except Exception as e:
            self._logger.warning(f"Ошибка LLM для поста {post.owner_id}_{post.item_id}: {e}")
            return False
