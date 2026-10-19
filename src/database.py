"""Подключение к SQLite: обёртка над sqlite3.Connection.

Database инкапсулирует sqlite3.Connection. Миграции выполняются в __init__ —
любое подключение сразу получает актуальную схему (идемпотентно через
PRAGMA user_version), включая демоны ботов, которые не создают AutoLiker.
"""

import sqlite3

from migrations import run_migrations
from settings import Settings


class Database:
    """Подключение к SQLite.

    Использование:
        db = Database(config)
        db.conn.execute("INSERT ...")
        db.commit()
        db.close()
    """

    def __init__(self, config: Settings):
        """Создаёт подключение к SQLite-базе по пути config.db_path и применяет миграции."""
        self._conn: sqlite3.Connection = sqlite3.connect(config.db_path)
        run_migrations(self._conn)

    @property
    def conn(self) -> sqlite3.Connection:
        """Возвращает текущее подключение."""
        return self._conn

    def commit(self) -> None:
        """Фиксирует транзакцию."""
        self._conn.commit()

    def close(self) -> None:
        """Закрывает подключение."""
        if self._conn:
            self._conn.close()
