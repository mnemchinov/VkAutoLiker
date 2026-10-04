"""Репозиторий закрытых стен: кэш стен с ошибками 15/18/30.

Таблица closed_walls (owner_id, last_checked) — предотвращает повторные
API-вызовы к закрытым/приватным стенам (~38% пустых вызовов).
TTL: closed_wall_ttl_days — через сколько дней стену перепроверить.
"""

import time

from database import Database
from settings import Settings


class ClosedWallsRepository:
    """Репозиторий для таблицы closed_walls."""

    def __init__(self, db: Database, config: Settings):
        """Инициализирует репозиторий с подключением к БД и конфигурацией."""
        self._db = db
        self._ttl_days = config.closed_wall_ttl_days

    def is_wall_closed(self, owner_id: int) -> bool:
        """Проверяет, закрыта ли стена (в пределах TTL).

        Если запись старше closed_wall_ttl_days дней — считаем устаревшей,
        стену нужно перепроверить.
        """
        cursor = self._db.conn.execute(
            "SELECT last_checked FROM closed_walls WHERE owner_id = ?",
            (owner_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        ttl_sec = self._ttl_days * 86400
        return (int(time.time()) - row[0]) < ttl_sec

    def mark_wall_closed(self, owner_id: int) -> None:
        """Отмечает стену как закрытую/приватную (INSERT OR REPLACE)."""
        self._db.conn.execute(
            "INSERT OR REPLACE INTO closed_walls (owner_id, last_checked) VALUES (?, ?)",
            (owner_id, int(time.time())),
        )
        self._db.commit()

    def reset(self) -> None:
        """Очищает таблицу closed_walls."""
        self._db.conn.execute("DELETE FROM closed_walls")
        self._db.commit()
