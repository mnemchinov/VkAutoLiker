"""Unit-тесты репозитория закрытых стен ClosedWallsRepository.

Тестирует: is_wall_closed, mark_wall_closed, TTL, reset.
Использует реальную SQLite-БД.
"""

import time

from database import Database
from migrations import run_migrations
from repositories import ClosedWallsRepository


class TestClosedWallsRepository:
    def test_mark_and_check_closed(self, mock_config, tmp_path):
        """Стена помечена закрытой → is_wall_closed True."""
        mock_config.db_path = str(tmp_path / "test.db")
        mock_config.closed_wall_ttl_days = 7
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = ClosedWallsRepository(db, mock_config)

        assert not repo.is_wall_closed(-111)
        repo.mark_wall_closed(-111)
        assert repo.is_wall_closed(-111)
        db.close()

    def test_wall_closed_expired_ttl(self, mock_config, tmp_path):
        """Запись старше TTL → is_wall_closed False (нужно перепроверить)."""
        mock_config.db_path = str(tmp_path / "test.db")
        mock_config.closed_wall_ttl_days = 7
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = ClosedWallsRepository(db, mock_config)

        # Вставляем старую запись (30 дней назад)
        old_ts = int(time.time()) - 30 * 86400
        db.conn.execute(
            "INSERT INTO closed_walls (owner_id, last_checked) VALUES (?, ?)",
            (-222, old_ts),
        )
        db.commit()

        assert not repo.is_wall_closed(-222)
        db.close()

    def test_wall_closed_within_ttl(self, mock_config, tmp_path):
        """Запись свежая (в пределах TTL) → is_wall_closed True."""
        mock_config.db_path = str(tmp_path / "test.db")
        mock_config.closed_wall_ttl_days = 7
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = ClosedWallsRepository(db, mock_config)

        # Запись 1 день назад — в пределах TTL (7 дней)
        recent_ts = int(time.time()) - 1 * 86400
        db.conn.execute(
            "INSERT INTO closed_walls (owner_id, last_checked) VALUES (?, ?)",
            (-333, recent_ts),
        )
        db.commit()

        assert repo.is_wall_closed(-333)
        db.close()

    def test_reset_clears_all(self, mock_config, tmp_path):
        """reset очищает таблицу closed_walls."""
        mock_config.db_path = str(tmp_path / "test.db")
        mock_config.closed_wall_ttl_days = 7
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = ClosedWallsRepository(db, mock_config)

        repo.mark_wall_closed(-111)
        repo.mark_wall_closed(-222)
        repo.reset()
        assert not repo.is_wall_closed(-111)
        assert not repo.is_wall_closed(-222)
        db.close()
