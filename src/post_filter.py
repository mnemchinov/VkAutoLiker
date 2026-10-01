"""Фильтрация постов по давности, наличию текста и стоп-словам.

Фильтр проверяет только свойства поста (дата, текст) — без обращения к StateStore.
Проверка is_processed выполняется в CollectStage, где она нужна для раннего выхода.

Стоп-слова загружаются из двух источников:
  1. stop_words_file — внешний текстовый файл (одно слово на строку, '#' — комментарий)
  2. stop_words — inline-список из config.yaml
Списки объединяются. Если файл не найден — предупреждение в лог, используется только inline.
"""

import time
from pathlib import Path

from config import AppConfig
from logger import AppLogger
from post import Post


class PostFilter:
    """Отсеивает посты старше days_back дней, без текста или со стоп-словами."""

    def __init__(self, config: AppConfig, logger: AppLogger):
        """Инициализирует фильтр: days_back + стоп-слова из файла и config.yaml."""
        self._days_back = config.search.days_back
        self._logger = logger

        file_words = self._load_stop_words_file(config.search.stop_words_file)
        inline_words = [w.lower() for w in config.search.stop_words]
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

    def filter(self, posts: list[Post]) -> list[Post]:
        """Возвращает только свежие посты с непустым текстом."""
        cutoff = int(time.time()) - (self._days_back * 86400)
        result: list[Post] = []

        for post in posts:
            if post.date < cutoff:
                continue

            if not post.text.strip():
                continue

            if self._stop_words and any(
                w in post.text.lower() for w in self._stop_words
            ):
                continue

            result.append(post)

        removed = len(posts) - len(result)
        self._logger.info(f"Фильтр: {len(posts)} → {len(result)} постов ({removed} отфильтровано)")
        return result
