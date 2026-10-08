"""Подключение к SQLite: обёртка над sqlite3.Connection.

Database инкапсулирует sqlite3.Connection. Миграции выполняются отдельно
через migrations.run_migrations().
"""

import sqlite3

from settings import Settings


class Database:
    """Подключение к SQLite.

    Использование:
        db = Database(config)
        run_migrations(db.conn)
        db.conn.execute("INSERT ...")
        db.commit()
        db.close()
    """

    def __init__(self, config: Settings):
        """Создаёт подключение к SQLite-базе по пути config.db_path."""
        self._conn: sqlite3.Connection = sqlite3.connect(config.db_path)

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
