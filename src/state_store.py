"""SQLite-хранилище: история обработанных постов и сессий."""

import sqlite3
import time
from datetime import date
from typing import Tuple

from config import AppConfig
from logger import AppLogger


class StateStore:
    """Хранит в SQLite обработанные посты и статистику сессий.

    Таблицы:
      processed_posts (owner_id, item_id, liked_at) — дедупликация;
      sessions (id, started_at, ended_at, likes_count, session_date) — лимиты.
    """

    def __init__(self, config: AppConfig, logger: AppLogger):
        self._db_path = config.state.db_path
        self._logger = logger
        self._conn: sqlite3.Connection = sqlite3.connect(self._db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Создаёт таблицы, если их ещё нет."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_posts (
                owner_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                liked_at INTEGER NOT NULL,
                PRIMARY KEY (owner_id, item_id)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at INTEGER NOT NULL,
                ended_at INTEGER,
                likes_count INTEGER DEFAULT 0,
                session_date TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def is_processed(self, owner_id: int, item_id: int) -> bool:
        """Проверяет, был ли пост уже обработан (лайкнут или пропущен)."""
        cursor = self._conn.execute(
            "SELECT 1 FROM processed_posts WHERE owner_id = ? AND item_id = ?",
            (owner_id, item_id),
        )
        return cursor.fetchone() is not None

    def mark_processed(self, owner_id: int, item_id: int) -> None:
        """Отмечает пост как обработанный (INSERT OR IGNORE для дедупликации)."""
        self._conn.execute(
            "INSERT OR IGNORE INTO processed_posts (owner_id, item_id, liked_at) VALUES (?, ?, ?)",
            (owner_id, item_id, int(time.time())),
        )
        self._conn.commit()

    def start_session(self) -> int:
        """Создаёт запись о начале сессии, возвращает session_id."""
        now = int(time.time())
        today = date.today().isoformat()
        cursor = self._conn.execute(
            "INSERT INTO sessions (started_at, session_date) VALUES (?, ?)",
            (now, today),
        )
        self._conn.commit()
        return cursor.lastrowid or 0

    def end_session(self, session_id: int, likes_count: int) -> None:
        """Фиксирует конец сессии и количество лайков."""
        now = int(time.time())
        self._conn.execute(
            "UPDATE sessions SET ended_at = ?, likes_count = ? WHERE id = ?",
            (now, likes_count, session_id),
        )
        self._conn.commit()

    def get_daily_stats(self) -> Tuple[int, int]:
        """Возвращает (сессий сегодня, лайков сегодня) для проверки лимита."""
        today = date.today().isoformat()
        cursor = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(likes_count), 0) FROM sessions WHERE session_date = ?",
            (today,),
        )
        row = cursor.fetchone()
        return (row[0], row[1])

    def get_total_stats(self) -> Tuple[int, int]:
        """Возвращает (всего сессий, всего лайков)."""
        cursor = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(likes_count), 0) FROM sessions"
        )
        row = cursor.fetchone()
        return (row[0], row[1])

    def reset(self) -> None:
        self._conn.execute("DELETE FROM processed_posts")
        self._conn.execute("DELETE FROM sessions")
        self._conn.commit()
        self._logger.info("База данных очищена")

    def close(self) -> None:
        if self._conn:
            self._conn.close()
