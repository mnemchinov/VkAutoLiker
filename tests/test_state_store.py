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
