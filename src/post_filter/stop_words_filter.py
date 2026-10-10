"""Стоп-слова: словарь с маркером жёсткости, лемматизация pymorphy3.

Роль слова задаётся суффиксом '!' в самом словаре (файл и inline-список):
  'наркотики!' — жёсткое: в режиме stop_words пост отсекается;
  'карабин'    — мягкое: не отсекается, в режиме review пост помечается
                 на LLM-арбитраж (matched() → StopMatch).
Смешанное совпадение (жёсткое + мягкое) — hard.

Стоп-слова загружаются из двух источников:
  1. stop_words_file — внешний текстовый файл (одно слово на строку, '#' — комментарий)
  2. stop_words — inline-список из Settings
Списки объединяются, '!' из любого источника превалирует. Если файл не найден —
предупреждение в лог, используется только inline.

Группы:
  1. _stop_lemmas — леммы русских слов (pymorphy3: «церковью» → «церковь»).
  2. _stop_substrings — нерусские слова и аббревиатуры (18+, xxx, СВО, mlm) — substring.
  3. _stop_phrases — многословные фразы («игровые автоматы») — substring.

MorphAnalyzer — class-level singleton: словарь (~5MB) грузится один раз.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from pymorphy3 import MorphAnalyzer

from logger import AppLogger
from post import Post
from settings import Settings

from .protocol import PostFilterProtocol


@dataclass
class StopMatch:
    """Совпадение стоп-слов в тексте поста.

    words — леммы/слова-триггеры (передаются в LLM-промпт арбитража).
    hard — True, если сработало хотя бы одно жёсткое слово (с '!').
    """

    words: list[str]
    hard: bool


class StopWordsFilter(PostFilterProtocol):
    """Стоп-слова в тексте поста: matched() — совпадение (слова + жёсткость), should_skip() — только hard."""

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
        self._config = config
        self._checked: int = 0
        self._matched: int = 0
        self._skipped: int = 0

        file_words = self._load_stop_words_file(config.stop_words_file)
        all_raw = file_words + list(config.stop_words)

        # Слово → жёсткость: '!' из любого источника превалирует
        entries: dict[str, bool] = {}
        for raw in all_raw:
            word, hard = self._parse_word(raw)
            if word:
                entries[word] = entries.get(word, False) or hard

        self._stop_lemmas: dict[str, bool] = {}
        self._stop_substrings: dict[str, bool] = {}
        self._stop_phrases: dict[str, bool] = {}

        morph = self._get_morph()
        for word, hard in entries.items():
            if " " in word:
                self._stop_phrases[word] = hard
            elif re.fullmatch(r"[а-яё]+", word):
                lemma = morph.parse(word)[0].normal_form
                self._stop_lemmas[lemma] = self._stop_lemmas.get(lemma, False) or hard
            else:
                self._stop_substrings[word] = self._stop_substrings.get(word, False) or hard

    @staticmethod
    def _parse_word(raw: str) -> tuple[str, bool]:
        """Разбирает слово с маркером жёсткости: 'слово!' → ('слово', True), 'слово' → ('слово', False)."""
        w = raw.strip().lower()
        if w.endswith("!"):
            return w[:-1].strip(), True
        return w, False

    def _load_stop_words_file(self, path: str) -> list[str]:
        """Загружает стоп-слова из текстового файла (маркер '!' сохраняется в строке).

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
            words.append(stripped)

        self._logger.info(f"Загружено {len(words)} стоп-слов из {path}")
        return words

    def matched(self, post: Post) -> StopMatch | None:
        """Находит стоп-слова в тексте поста, возвращает StopMatch или None.

        words — все сработавшие слова/леммы (для LLM-промпта), hard — если
        сработало хотя бы одно жёсткое слово. Совпадения логируются на INFO,
        OK — на DEBUG.
        """
        self._checked += 1
        post_id = f"{post.owner_id}_{post.item_id}"

        if not self._stop_lemmas and not self._stop_substrings and not self._stop_phrases:
            self._logger.debug(f"Стоп-слова: пост {post_id} → OK (словарь пуст)")
            return None

        text_lower = post.text.lower()
        words: list[str] = []
        hard = False

        for s, h in self._stop_substrings.items():
            if s in text_lower:
                words.append(s)
                hard = hard or h
        for p, h in self._stop_phrases.items():
            if p in text_lower:
                words.append(p)
                hard = hard or h

        if self._stop_lemmas:
            morph = self._get_morph()
            for token in re.findall(r"[а-яё]{3,}", text_lower):
                lemma = morph.parse(token)[0].normal_form
                if lemma in self._stop_lemmas:
                    if lemma not in words:
                        words.append(lemma)
                    hard = hard or self._stop_lemmas[lemma]

        if not words:
            self._logger.debug(f"Стоп-слова: пост {post_id} → OK")
            return None

        self._matched += 1
        if hard:
            self._skipped += 1
        role = "hard" if hard else "soft"
        self._logger.info(f"Стоп-слова: пост {post_id} → совпадение {words} ({role})")
        return StopMatch(words=words, hard=hard)

    def should_skip(self, post: Post) -> bool:
        """True, если сработало хотя бы одно жёсткое стоп-слово (с '!')."""
        m = self.matched(post)
        return m is not None and m.hard

    def log_summary(self) -> None:
        """Логирует сводку: в режиме review — помечено для LLM, иначе — отсеяно."""
        if self._config.filter_mode == "review":
            self._logger.info(
                f"Стоп-слова: проверено {self._checked}, помечено {self._matched} для LLM"
            )
            return
        pct = round(self._skipped / self._checked * 100, 1) if self._checked else 0.0
        self._logger.info(
            f"Стоп-слова: проверено {self._checked}, отсеяно {self._skipped} ({pct}%)"
        )
