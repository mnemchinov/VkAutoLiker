from state_store import StateStore


class TestStateStore:
    def test_mark_and_check_processed(self, mock_config, mock_logger, tmp_path):
        config = mock_config
        config.state.db_path = str(tmp_path / "test.db")
        state = StateStore(config, mock_logger)

        assert not state.is_processed(1, 100)
        state.mark_processed(1, 100)
        assert state.is_processed(1, 100)
        assert not state.is_processed(1, 101)
        state.close()

    def test_session_lifecycle(self, mock_config, mock_logger, tmp_path):
        config = mock_config
        config.state.db_path = str(tmp_path / "test.db")
        state = StateStore(config, mock_logger)

        session_id = state.start_session()
        assert session_id > 0

        state.end_session(session_id, likes_count=5)

        sessions_today, likes_today = state.get_daily_stats()
        assert sessions_today == 1
        assert likes_today == 5
        state.close()

    def test_manual_session_not_counted_in_daily(self, mock_config, mock_logger, tmp_path):
        """Ручная сессия (is_auto=False) не учитывается в дневном лимите."""
        config = mock_config
        config.state.db_path = str(tmp_path / "test.db")
        state = StateStore(config, mock_logger)

        # Авто-сессия — учитывается
        sid_auto = state.start_session(is_auto=True)
        state.end_session(sid_auto, likes_count=5)

        # Ручная сессия — не учитывается в дневном лимите
        sid_manual = state.start_session(is_auto=False)
        state.end_session(sid_manual, likes_count=10)

        auto_today, auto_likes = state.get_daily_stats()
        assert auto_today == 1
        assert auto_likes == 5

        manual_sessions, manual_likes = state.get_manual_stats()
        assert manual_sessions == 1
        assert manual_likes == 10
        state.close()

    def test_migrate_adds_is_auto_column(self, mock_config, mock_logger, tmp_path):
        """Старая БД без колонки is_auto мигрируется (DEFAULT 1)."""
        import sqlite3

        db_path = str(tmp_path / "test.db")
        # Создаём старую таблицу без is_auto
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

        # StateStore должен добавить колонку
        config = mock_config
        config.state.db_path = db_path
        state = StateStore(config, mock_logger)

        # Старая сессия помечена is_auto=1 (DEFAULT 1)
        auto_today, _ = state.get_daily_stats()
        assert auto_today == 0  # старая сессия в другой дате, сегодня 0
        state.close()

    def test_multiple_sessions_daily(self, mock_config, mock_logger, tmp_path):
        config = mock_config
        config.state.db_path = str(tmp_path / "test.db")
        state = StateStore(config, mock_logger)

        for i in range(3):
            sid = state.start_session()
            state.end_session(sid, likes_count=i + 1)

        sessions_today, likes_today = state.get_daily_stats()
        assert sessions_today == 3
        assert likes_today == 6
        state.close()

    def test_total_stats(self, mock_config, mock_logger, tmp_path):
        config = mock_config
        config.state.db_path = str(tmp_path / "test.db")
        state = StateStore(config, mock_logger)

        sid = state.start_session()
        state.end_session(sid, likes_count=10)

        total_sessions, total_likes = state.get_total_stats()
        assert total_sessions == 1
        assert total_likes == 10
        state.close()

    def test_reset(self, mock_config, mock_logger, tmp_path):
        config = mock_config
        config.state.db_path = str(tmp_path / "test.db")
        state = StateStore(config, mock_logger)

        state.mark_processed(1, 1)
        sid = state.start_session()
        state.end_session(sid, 5)

        state.reset()

        assert not state.is_processed(1, 1)
        total_sessions, total_likes = state.get_total_stats()
        assert total_sessions == 0
        assert total_likes == 0
        state.close()
