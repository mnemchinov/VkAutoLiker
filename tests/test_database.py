"""Unit-тесты подключения Database.

Database — тонкая обёртка над sqlite3.Connection.
Миграции тестируются отдельно в test_migrations.py.
"""

import sqlite3

from database import Database


class TestDatabase:
    def test_conn_returns_sqlite_connection(self, mock_config, tmp_path):
        """conn возвращает sqlite3.Connection."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        assert isinstance(db.conn, sqlite3.Connection)
        db.close()

    def test_close_closes_connection(self, mock_config, tmp_path):
        """close закрывает подключение."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        db.close()
        # Повторный close не падает
        db.close()

    def test_commit_persists_changes(self, mock_config, tmp_path):
        """commit фиксирует изменения в БД."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        db.conn.execute("CREATE TABLE t (x INTEGER)")
        db.conn.execute("INSERT INTO t (x) VALUES (42)")
        db.commit()
        # Новое подключение видит данные
        conn2 = sqlite3.connect(mock_config.db_path)
        row = conn2.execute("SELECT x FROM t").fetchone()
        conn2.close()
        db.close()
        assert row is not None
        assert row[0] == 42
