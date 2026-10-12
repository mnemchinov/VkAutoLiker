"""Репозиторий сессий: учёт запусков и дневных лимитов.

Таблица sessions (id, started_at, ended_at, likes_count, session_date, is_auto).
is_auto=1 — запуск `run` (учитывается в дневном лимите).
is_auto=0 — запуск `run --no-limit` (не учитывается в дневном лимите).
ended_at NULL — сессия ещё идёт.
"""

import time
from datetime import date
from typing import NamedTuple

from database import Database


class SessionStats(NamedTuple):
    """Статистика сессий: количество сессий и суммарное количество лайков."""

    sessions: int
    likes: int


class LastSession(NamedTuple):
    """Сессия за сегодня: ID, лайки, время начала и окончания (unix).

    Для идущей сессии (ended_at IS NULL) поле ended_at = 0.
    """

    id: int
    likes: int
    ended_at: int
    started_at: int


class SessionsRepository:
    """Репозиторий для таблицы sessions."""

    def __init__(self, db: Database):
        """Инициализирует репозиторий с подключением к БД."""
        self._db = db

    def start_session(self, is_auto: bool = True) -> int:
        """Создаёт запись о начале сессии, возвращает session_id.

        is_auto=True — запуск `run`, учитывается в дневном лимите.
        is_auto=False — запуск `run --no-limit`, не учитывается в лимите.
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

    def get_today_stats(self) -> SessionStats:
        """Возвращает статистику всех запусков за сегодня (без разделения авто/ручные)."""
        today = date.today().isoformat()
        cursor = self._db.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(likes_count), 0) FROM sessions WHERE session_date = ?",
            (today,),
        )
        row = cursor.fetchone()
        return SessionStats(sessions=row[0], likes=row[1])

    def get_running_session(self) -> LastSession | None:
        """Возвращает идущую сессию за сегодня (ended_at IS NULL) или None.

        Для промежуточного статуса: время старта и текущее число лайков
        (обновляется в update_session_likes после каждого лайка).
        """
        today = date.today().isoformat()
        cursor = self._db.conn.execute(
            "SELECT id, COALESCE(likes_count, 0), 0, started_at "
            "FROM sessions WHERE session_date = ? AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (today,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return LastSession(id=row[0], likes=row[1], ended_at=0, started_at=row[3])

    def get_last_session(self) -> LastSession | None:
        """Возвращает последнюю завершённую сессию за сегодня или None.

        Идущие сессии (ended_at IS NULL) не считаются — для них есть
        get_running_session. Используется в отчёте бота после завершения.
        """
        today = date.today().isoformat()
        cursor = self._db.conn.execute(
            "SELECT id, COALESCE(likes_count, 0), ended_at, started_at "
            "FROM sessions WHERE session_date = ? AND ended_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (today,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return LastSession(id=row[0], likes=row[1], ended_at=row[2], started_at=row[3])

    def update_session_likes(self, session_id: int, likes_count: int) -> None:
        """Обновляет текущее число лайков идущей сессии (промежуточный статус)."""
        self._db.conn.execute(
            "UPDATE sessions SET likes_count = ? WHERE id = ?",
            (likes_count, session_id),
        )
        self._db.commit()

    def reset(self) -> None:
        """Очищает таблицу sessions."""
        self._db.conn.execute("DELETE FROM sessions")
        self._db.commit()
