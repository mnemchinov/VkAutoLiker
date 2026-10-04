"""Подключение к SQLite: context manager для управления соединением.

Database инкапсулирует sqlite3.Connection и предоставляет контекстный менеджер
для транзакций. Миграции выполняются отдельно через migrations.run_migrations().
"""

import sqlite3

from settings import Settings


class Database:
    """Подключение к SQLite с поддержкой контекстного менеджера.

    Использование:
        db = Database(config)
        run_migrations(db.conn)
        with db:
            db.conn.execute("INSERT ...")
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

    def __enter__(self) -> "Database":
        """Вход в контекст: ничего не делает (autocommit отключён по умолчанию)."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Выход из контекста: commit при успехе, rollback при ошибке."""
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
