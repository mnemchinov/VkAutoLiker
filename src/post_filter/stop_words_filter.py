"""Фильтр стоп-слов: отсеивает посты по словарю через лемматизацию pymorphy3.

Стоп-слова загружаются из двух источников:
  1. stop_words_file — внешний текстовый файл (одно слово на строку, '#' — комментарий)
  2. stop_words — inline-список из Settings
Списки объединяются. Если файл не найден — предупреждение в лог, используется только inline.

Разделяются на три группы:
  1. _stop_lemmas — леммы русских слов (pymorphy3: «церковью» → «церковь»).
  2. _stop_substrings — нерусские слова и аббревиатуры (18+, xxx, СВО, mlm) — substring.
  3. _stop_phrases — многословные фразы («игровые автоматы») — substring.

MorphAnalyzer — class-level singleton: словарь (~5MB) грузится один раз.
"""

import re
from pathlib import Path

from pymorphy3 import MorphAnalyzer

from logger import AppLogger
from post import Post
from settings import Settings

from .protocol import PostFilterProtocol


class StopWordsFilter(PostFilterProtocol):
    """Отсеивает посты, содержащие стоп-слова (регистронезависимо)."""

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
        """Логирует сводку: достигло фильтра N, отсеяно M (X%)."""
        pct = round(self._skipped / self._checked * 100, 1) if self._checked else 0.0
        self._logger.info(
            f"Стоп-слова: достигло фильтра {self._checked}, отсеяно {self._skipped} ({pct}%)"
        )
