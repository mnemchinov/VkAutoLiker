"""Unit-тесты миграций SQLite.

Тестирует: создание таблиц с нуля, миграция старых БД (is_auto, status),
PRAGMA user_version после миграций.
"""

import sqlite3

from migrations import LATEST_VERSION, run_migrations


class TestMigrations:
    def test_fresh_db_creates_all_tables(self, mock_config, tmp_path):
        """Свежая БД → все три таблицы созданы."""
        db_path = str(tmp_path / "test.db")
        mock_config.db_path = db_path
        conn = sqlite3.connect(db_path)
        run_migrations(conn)

        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        assert "processed_posts" in tables
        assert "sessions" in tables
        assert "closed_walls" in tables
        conn.close()

    def test_user_version_after_migrations(self, mock_config, tmp_path):
        """После миграций PRAGMA user_version == LATEST_VERSION."""
        db_path = str(tmp_path / "test.db")
        mock_config.db_path = db_path
        conn = sqlite3.connect(db_path)
        run_migrations(conn)

        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == LATEST_VERSION
        conn.close()

    def test_migrate_adds_is_auto_column(self, mock_config, tmp_path):
        """Старая БД без is_auto → миграция добавляет колонку (DEFAULT 1)."""
        db_path = str(tmp_path / "test.db")
        # Создаём старую таблицу sessions без is_auto
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at INTEGER NOT NULL,
                ended_at INTEGER,
                likes_count INTEGER DEFAULT 0,
                session_date TEXT NOT NULL
            )
        """)
        conn.execute("INSERT INTO sessions (started_at, session_date) VALUES (1, '2026-01-01')")
        conn.commit()
        conn.close()

        # run_migrations должна пропустить m001 (таблицы есть) и применить m002
        # Но m001 создаст таблицы только если их нет...
        # На самом деле m001 создаст таблицы заново, поэтому нужно симулировать
        # старую БД с user_version=0 и существующими таблицами.
        # m001 использует CREATE TABLE IF NOT EXISTS, так что существующие таблицы не пересоздаются.
        conn = sqlite3.connect(db_path)
        run_migrations(conn)

        # Проверяем, что is_auto добавлена
        cols = [row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()]
        assert "is_auto" in cols

        # Старая сессия помечена is_auto=1 (DEFAULT 1)
        row = conn.execute("SELECT is_auto FROM sessions WHERE id = 1").fetchone()
        assert row[0] == 1
        conn.close()

    def test_migrate_adds_status_column(self, mock_config, tmp_path):
        """Старая БД с liked_at, без status → миграция заменяет liked_at на status."""
        from post import PostStatus

        db_path = str(tmp_path / "test.db")
        # Создаём старую таблицу с liked_at, без status
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE processed_posts (
                owner_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                liked_at INTEGER NOT NULL,
                PRIMARY KEY (owner_id, item_id)
            )
        """)
        conn.execute(
            "INSERT INTO processed_posts (owner_id, item_id, liked_at) VALUES (1, 100, 12345)"
        )
        conn.commit()
        conn.close()

        # run_migrations применит m001 (IF NOT EXISTS — пропуск) и m003 (liked_at → status)
        conn = sqlite3.connect(db_path)
        run_migrations(conn)

        # Проверяем, что status есть, liked_at нет
        cols = [row[1] for row in conn.execute("PRAGMA table_info(processed_posts)").fetchall()]
        assert "status" in cols
        assert "liked_at" not in cols

        # Старая запись сохранилась, status=0 (UNKNOWN)
        row = conn.execute(
            "SELECT status FROM processed_posts WHERE owner_id=1 AND item_id=100"
        ).fetchone()
        assert row is not None
        assert row[0] == PostStatus.UNKNOWN
        conn.close()

    def test_idempotent_run(self, mock_config, tmp_path):
        """Повторный запуск run_migrations на свежей БД — не падает."""
        db_path = str(tmp_path / "test.db")
        mock_config.db_path = db_path
        conn = sqlite3.connect(db_path)
        run_migrations(conn)
        run_migrations(conn)

        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == LATEST_VERSION
        conn.close()
