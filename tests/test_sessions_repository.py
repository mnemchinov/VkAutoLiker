"""Unit-тесты репозитория сессий SessionsRepository.

Тестирует: start_session, end_session, get_daily_stats, get_total_stats,
get_today_stats, get_running_session, get_last_session, update_session_likes,
reset. Использует реальную SQLite-БД.
"""

from database import Database
from migrations import run_migrations
from repositories import LastSession, SessionsRepository, SessionStats


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

    def test_get_last_session(self, mock_config, tmp_path):
        """get_last_session — последняя за сегодня (по id) или None."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = SessionsRepository(db)

        assert repo.get_last_session() is None

        sid1 = repo.start_session(is_auto=False)
        repo.end_session(sid1, likes_count=7)
        sid2 = repo.start_session(is_auto=False)
        repo.end_session(sid2, likes_count=3)

        last = repo.get_last_session()
        assert isinstance(last, LastSession)
        assert last.id == sid2
        assert last.likes == 3
        assert last.ended_at > 0
        assert last.started_at > 0

        # идущая сессия (ended_at IS NULL) — не «последняя завершённая»
        repo.start_session(is_auto=False)
        assert repo.get_last_session().id == sid2
        db.close()

    def test_get_today_stats_counts_all_sessions(self, mock_config, tmp_path):
        """get_today_stats — все запуски за сегодня, без разделения авто/ручные."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = SessionsRepository(db)

        assert repo.get_today_stats().sessions == 0

        sid_auto = repo.start_session(is_auto=True)
        repo.end_session(sid_auto, likes_count=5)
        sid_manual = repo.start_session(is_auto=False)
        repo.end_session(sid_manual, likes_count=10)

        stats = repo.get_today_stats()
        assert stats.sessions == 2
        assert stats.likes == 15
        db.close()

    def test_get_running_session_and_update_likes(self, mock_config, tmp_path):
        """get_running_session — идущая сессия; update_session_likes — лайки в полёте."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = SessionsRepository(db)

        assert repo.get_running_session() is None

        sid = repo.start_session(is_auto=False)
        repo.update_session_likes(sid, likes_count=3)
        running = repo.get_running_session()
        assert isinstance(running, LastSession)
        assert running.id == sid
        assert running.likes == 3
        assert running.ended_at == 0
        assert running.started_at > 0

        repo.end_session(sid, likes_count=5)
        assert repo.get_running_session() is None
        db.close()
