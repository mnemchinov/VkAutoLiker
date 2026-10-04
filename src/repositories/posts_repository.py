"""Репозиторий постов: маркировка статусов обработки.

Таблица processed_posts (owner_id, item_id, status) — первичный ключ (owner_id, item_id).
status: 0=UNKNOWN (миграция), 1=LIKED, 2=FILTERED.
"""

from database import Database
from post import PostStatus


class PostsRepository:
    """Репозиторий для таблицы processed_posts.

    is_processed — простая проверка существования записи (любой статус).
    mark_processed — INSERT OR REPLACE с указанным статусом.
    """

    def __init__(self, db: Database):
        """Инициализирует репозиторий с подключением к БД."""
        self._db = db

    def is_processed(self, owner_id: int, item_id: int) -> bool:
        """Проверяет, был ли пост уже обработан (лайкнут или отсеян)."""
        cursor = self._db.conn.execute(
            "SELECT 1 FROM processed_posts WHERE owner_id = ? AND item_id = ?",
            (owner_id, item_id),
        )
        return cursor.fetchone() is not None

    def mark_processed(
        self, owner_id: int, item_id: int, status: PostStatus = PostStatus.LIKED
    ) -> None:
        """Записывает пост в БД с указанным статусом (INSERT OR REPLACE).

        status=LIKED — успешный лайк (или уже был лайкнут).
        status=FILTERED — отсеян стоп-словами или LLM.
        INSERT OR REPLACE позволяет перезаписать FILTERED→LIKED при будущем
        перетестировании ценза (если стоп-слова изменились и пост прошёл).
        """
        self._db.conn.execute(
            "INSERT OR REPLACE INTO processed_posts (owner_id, item_id, status) VALUES (?, ?, ?)",
            (owner_id, item_id, int(status)),
        )
        self._db.commit()

    def reset(self) -> None:
        """Очищает таблицу processed_posts."""
        self._db.conn.execute("DELETE FROM processed_posts")
        self._db.commit()
