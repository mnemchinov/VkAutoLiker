"""Репозиторий сессий: учёт запусков и дневных лимитов.

Таблица sessions (id, started_at, ended_at, likes_count, session_date, is_auto).
is_auto=1 — сессия запущена launchd (учитывается в дневном лимите).
is_auto=0 — ручной запуск через --no-limit (не учитывается в дневном лимите).
"""

import time
from datetime import date
from typing import NamedTuple

from database import Database


class SessionStats(NamedTuple):
    """Статистика сессий: количество сессий и суммарное количество лайков."""

    sessions: int
    likes: int


class SessionsRepository:
    """Репозиторий для таблицы sessions."""

    def __init__(self, db: Database):
        """Инициализирует репозиторий с подключением к БД."""
        self._db = db

    def start_session(self, is_auto: bool = True) -> int:
        """Создаёт запись о начале сессии, возвращает session_id.

        is_auto=True — учитывается в дневном лимите (запуск launchd).
        is_auto=False — ручной запуск через --no-limit, не учитывается в лимите.
        """
        now = int(time.time())
        today = date.today().isoformat()
        cursor = self._db.conn.execute(
            "INSERT INTO sessions (started_at, session_date, is_auto) VALUES (?, ?, ?)",
            (now, today, 1 if is_auto else 0),
        )
        self._db.commit()
        return cursor.lastrowid or 0

    def end_session(self, session_id: int, likes_count: int) -> None:
        """Фиксирует конец сессии и количество лайков."""
        now = int(time.time())
        self._db.conn.execute(
            "UPDATE sessions SET ended_at = ?, likes_count = ? WHERE id = ?",
            (now, likes_count, session_id),
        )
        self._db.commit()

    def get_daily_stats(self) -> SessionStats:
        """Возвращает статистику авто-сессий за сегодня (is_auto=1).

        Ручные запуски через --no-limit не расходуют дневной лимит.
        """
        today = date.today().isoformat()
        cursor = self._db.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(likes_count), 0) "
            "FROM sessions WHERE session_date = ? AND is_auto = 1",
            (today,),
        )
        row = cursor.fetchone()
        return SessionStats(sessions=row[0], likes=row[1])

    def get_total_stats(self) -> SessionStats:
        """Возвращает статистику всех сессий, включая ручные."""
        cursor = self._db.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(likes_count), 0) FROM sessions"
        )
        row = cursor.fetchone()
        return SessionStats(sessions=row[0], likes=row[1])

    def get_manual_stats(self) -> SessionStats:
        """Возвращает статистику ручных сессий (is_auto=0)."""
        cursor = self._db.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(likes_count), 0) FROM sessions WHERE is_auto = 0"
        )
        row = cursor.fetchone()
        return SessionStats(sessions=row[0], likes=row[1])

    def reset(self) -> None:
        """Очищает таблицу sessions."""
        self._db.conn.execute("DELETE FROM sessions")
        self._db.commit()
