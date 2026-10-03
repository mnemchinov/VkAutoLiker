"""SQLite-хранилище: история обработанных постов и сессий."""

import sqlite3
import time
from datetime import date

from logger import AppLogger
from settings import Settings


class StateStore:
    """Хранит в SQLite обработанные посты и статистику сессий.

    Таблицы:
      processed_posts (owner_id, item_id, liked_at) — дедупликация;
      sessions (id, started_at, ended_at, likes_count, session_date, is_auto) — лимиты;
      closed_walls (owner_id, last_checked) — кэш закрытых/приватных стен.
      is_auto=1 — сессия запущена launchd (учитывается в дневном лимите).
      is_auto=0 — ручной запуск через --no-limit (не учитывается в дневном лимите).
    """

    def __init__(self, config: Settings, logger: AppLogger):
        """Инициализирует SQLite-подключение и создаёт таблицы."""
        self._db_path = config.db_path
        self._config = config
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
                session_date TEXT NOT NULL,
                is_auto INTEGER DEFAULT 1
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS closed_walls (
                owner_id INTEGER PRIMARY KEY,
                last_checked INTEGER NOT NULL
            )
        """)
        self._migrate_sessions_is_auto()
        self._conn.commit()

    def _migrate_sessions_is_auto(self) -> None:
        """Добавляет колонку is_auto в существующую таблицу sessions (миграция).

        Старые БД (до --no-limit) не имеют колонки is_auto. PRAGMA table_info
        проверяет наличие; ALTER TABLE добавляет с DEFAULT 1 — все прошлые
        сессии помечаются как авто (корректно: они были запущены launchd).
        """
        cursor = self._conn.execute("PRAGMA table_info(sessions)")
        columns = [row[1] for row in cursor.fetchall()]
        if "is_auto" not in columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN is_auto INTEGER DEFAULT 1")

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

    def start_session(self, is_auto: bool = True) -> int:
        """Создаёт запись о начале сессии, возвращает session_id.

        is_auto=True — учитывается в дневном лимите (запуск launchd).
        is_auto=False — ручной запуск через --no-limit, не учитывается в лимите.
        """
        now = int(time.time())
        today = date.today().isoformat()
        cursor = self._conn.execute(
            "INSERT INTO sessions (started_at, session_date, is_auto) VALUES (?, ?, ?)",
            (now, today, 1 if is_auto else 0),
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

    def get_daily_stats(self) -> tuple[int, int]:
        """Возвращает (авто-сессий сегодня, лайков в авто-сессиях сегодня).

        Учитываются только сессии с is_auto=1 — ручные запуски через --no-limit
        не расходуют дневной лимит.
        """
        today = date.today().isoformat()
        cursor = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(likes_count), 0) "
            "FROM sessions WHERE session_date = ? AND is_auto = 1",
            (today,),
        )
        row = cursor.fetchone()
        return (row[0], row[1])

    def get_total_stats(self) -> tuple[int, int]:
        """Возвращает (всего сессий, всего лайков) — все сессии, включая ручные."""
        cursor = self._conn.execute("SELECT COUNT(*), COALESCE(SUM(likes_count), 0) FROM sessions")
        row = cursor.fetchone()
        return (row[0], row[1])

    def get_manual_stats(self) -> tuple[int, int]:
        """Возвращает (ручных сессий, лайков в ручных сессиях) — is_auto=0."""
        cursor = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(likes_count), 0) FROM sessions WHERE is_auto = 0"
        )
        row = cursor.fetchone()
        return (row[0], row[1])

    def reset(self) -> None:
        """Полностью очищает таблицы processed_posts и sessions."""
        self._conn.execute("DELETE FROM processed_posts")
        self._conn.execute("DELETE FROM sessions")
        self._conn.execute("DELETE FROM closed_walls")
        self._conn.commit()
        self._logger.info("База данных очищена")

    def close(self) -> None:
        """Закрывает SQLite-подключение."""
        if self._conn:
            self._conn.close()

    def is_wall_closed(self, owner_id: int) -> bool:
        """Проверяет, закрыта ли стена (в пределах TTL).

        Если запись старше closed_wall_ttl_days дней — считаем устаревшей,
        стену нужно перепроверить.
        """
        cursor = self._conn.execute(
            "SELECT last_checked FROM closed_walls WHERE owner_id = ?",
            (owner_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        ttl_sec = self._config.closed_wall_ttl_days * 86400
        return (int(time.time()) - row[0]) < ttl_sec

    def mark_wall_closed(self, owner_id: int) -> None:
        """Отмечает стену как закрытую/приватную (INSERT OR REPLACE)."""
        self._conn.execute(
            "INSERT OR REPLACE INTO closed_walls (owner_id, last_checked) VALUES (?, ?)",
            (owner_id, int(time.time())),
        )
        self._conn.commit()
