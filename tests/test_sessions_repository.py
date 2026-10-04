"""Unit-тесты репозитория сессий SessionsRepository.

Тестирует: start_session, end_session, get_daily_stats, get_total_stats,
get_manual_stats, reset. Использует реальную SQLite-БД.
"""

from database import Database
from migrations import run_migrations
from repositories import SessionsRepository, SessionStats


class TestSessionsRepository:
    def test_session_lifecycle(self, mock_config, tmp_path):
        """Сессия создаётся, завершается, видна в дневной статистике."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = SessionsRepository(db)

        session_id = repo.start_session()
        assert session_id > 0
        repo.end_session(session_id, likes_count=5)

        stats = repo.get_daily_stats()
        assert stats.sessions == 1
        assert stats.likes == 5
        db.close()

    def test_manual_session_not_counted_in_daily(self, mock_config, tmp_path):
        """Ручная сессия (is_auto=False) не учитывается в дневном лимите."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = SessionsRepository(db)

        sid_auto = repo.start_session(is_auto=True)
        repo.end_session(sid_auto, likes_count=5)

        sid_manual = repo.start_session(is_auto=False)
        repo.end_session(sid_manual, likes_count=10)

        auto_stats = repo.get_daily_stats()
        assert auto_stats.sessions == 1
        assert auto_stats.likes == 5

        manual_stats = repo.get_manual_stats()
        assert manual_stats.sessions == 1
        assert manual_stats.likes == 10
        db.close()

    def test_multiple_sessions_daily(self, mock_config, tmp_path):
        """Несколько авто-сессий в один день — все в дневной статистике."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = SessionsRepository(db)

        for i in range(3):
            sid = repo.start_session()
            repo.end_session(sid, likes_count=i + 1)

        stats = repo.get_daily_stats()
        assert stats.sessions == 3
        assert stats.likes == 6
        db.close()

    def test_total_stats_includes_manual(self, mock_config, tmp_path):
        """get_total_stats включает все сессии, включая ручные."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = SessionsRepository(db)

        sid1 = repo.start_session(is_auto=True)
        repo.end_session(sid1, likes_count=10)

        sid2 = repo.start_session(is_auto=False)
        repo.end_session(sid2, likes_count=20)

        stats = repo.get_total_stats()
        assert stats.sessions == 2
        assert stats.likes == 30
        db.close()

    def test_get_daily_stats_returns_named_tuple(self, mock_config, tmp_path):
        """get_daily_stats возвращает SessionStats(NamedTuple)."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = SessionsRepository(db)

        stats = repo.get_daily_stats()
        assert isinstance(stats, SessionStats)
        assert hasattr(stats, "sessions")
        assert hasattr(stats, "likes")
        db.close()

    def test_reset_clears_all(self, mock_config, tmp_path):
        """reset очищает таблицу sessions."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = SessionsRepository(db)

        sid = repo.start_session()
        repo.end_session(sid, likes_count=5)
        repo.reset()

        stats = repo.get_total_stats()
        assert stats.sessions == 0
        assert stats.likes == 0
        db.close()
