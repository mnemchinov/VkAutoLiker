"""Юнит-тесты команд проекта (Commands): status, help, start.

Без сети и без реального процесса: start — на подменённых Popen и Thread,
отчёты о завершении — прямые вызовы _report_completion на мок-процессе.
"""

import sys
import threading
from unittest.mock import MagicMock, patch

from commands import Commands
from database import Database
from file_lock import FileLock
from migrations import run_migrations


class TestCommands:
    """Тесты класса Commands (транспортно-независимые команды)."""

    def _make_commands(self, mock_config, mock_logger, tmp_path):
        """Создаёт Commands с реальной временной БД."""
        mock_config.db_path = str(tmp_path / "test_commands.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        return Commands(mock_config, mock_logger)

    def test_status_returns_stats_text(self, mock_config, mock_logger, tmp_path):
        """status() — три строки: всего / сегодня / последняя завершённая."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        auto_sid = repo.start_session(is_auto=True)
        repo.end_session(auto_sid, likes_count=5)
        manual_sid = repo.start_session(is_auto=False)
        repo.end_session(manual_sid, likes_count=10)

        text = commands.status()

        assert "Всего: 2 запуска, 15 лайков" in text
        assert "Сегодня: 2 запуска, 15 лайков" in text
        assert "Последняя: " in text
        assert "Сессия идёт" not in text

    def test_status_shows_running_session(self, mock_config, mock_logger, tmp_path):
        """status() с идущей сессией — промежуточная строка вместо «Последняя»."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        sid = repo.start_session(is_auto=False)
        repo.update_session_likes(sid, likes_count=4)

        text = commands.status()

        assert "Сессия идёт с " in text
        assert "4 лайка" in text
        assert "Последняя" not in text

    def test_help_returns_command_list(self, mock_config, mock_logger, tmp_path):
        """help() — список команд старт/статус/помощь."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        text = commands.help()
        assert "старт" in text
        assert "статус" in text
        assert "помощь" in text

    def test_start_when_lock_busy_reports_and_does_not_spawn(
        self, mock_config, mock_logger, tmp_path
    ):
        """start при занятой сессионной блокировке — «уже идёт», процесса нет."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        send = MagicMock()
        with (
            patch("commands._SESSION_LOCK", tmp_path / "session.lock"),
            patch("commands.subprocess.Popen") as mock_popen,
        ):
            lock = FileLock(tmp_path / "session.lock")
            lock.acquire()
            try:
                commands.start(send)
            finally:
                lock.release()
        send.assert_called_once_with("Сессия уже идёт")
        mock_popen.assert_not_called()

    def test_start_when_lock_free_spawns_and_reports(self, mock_config, mock_logger, tmp_path):
        """start со свободной блокировкой — Popen и «запущена», отчёт — в потоке."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        send = MagicMock()
        with (
            patch("commands._SESSION_LOCK", tmp_path / "session.lock"),
            patch("commands.subprocess.Popen") as mock_popen,
            patch("commands.threading.Thread") as mock_thread,
        ):
            mock_proc = MagicMock()
            mock_proc.wait.return_value = 0
            mock_popen.return_value = mock_proc
            commands.start(send)

        send.assert_called_once_with("Сессия запущена")
        mock_popen.assert_called_once()
        argv = mock_popen.call_args[0][0]
        assert argv[0] == sys.executable
        assert argv[-2:] == ["run", "--no-limit"]
        assert mock_popen.call_args[1]["cwd"] is not None
        mock_thread.assert_called_once()

    def test_report_completion_success(self, mock_config, mock_logger, tmp_path):
        """rc=0 и новая запись в БД — отчёт «Сессия завершена: N лайков»."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        old_sid = repo.start_session(is_auto=False)
        repo.end_session(old_sid, likes_count=1)
        new_sid = repo.start_session(is_auto=False)
        repo.end_session(new_sid, likes_count=7)
        send = MagicMock()
        proc = MagicMock()
        proc.wait.return_value = 0

        commands._report_completion(proc, send, old_sid)

        send.assert_called_once()
        text = send.call_args[0][0]
        assert text.startswith("Сессия завершена: 7 лайков (окончание ")

    def test_report_completion_error_code(self, mock_config, mock_logger, tmp_path):
        """rc != 0 — отчёт об ошибке с кодом."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        send = MagicMock()
        proc = MagicMock()
        proc.wait.return_value = 1

        commands._report_completion(proc, send, 0)

        send.assert_called_once_with("Сессия завершилась с ошибкой (код 1)")

    def test_report_completion_without_new_session(self, mock_config, mock_logger, tmp_path):
        """rc=0, но новая сессия в БД не появилась — не выдумываем отчёт."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        sid = repo.start_session(is_auto=False)
        repo.end_session(sid, likes_count=3)
        send = MagicMock()
        proc = MagicMock()
        proc.wait.return_value = 0

        commands._report_completion(proc, send, sid)

        send.assert_called_once_with("Сессия не началась: в базе нет записи о новой сессии")

    def test_report_completion_from_thread_uses_own_connection(
        self, mock_config, mock_logger, tmp_path
    ):
        """Отчёт из отдельного треда — своё SQLite-подключение (регрессия
        ProgrammingError: коннект главного треда не переносится в тред отчёта)."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        sid = repo.start_session(is_auto=False)
        repo.end_session(sid, likes_count=4)
        send = MagicMock()
        proc = MagicMock()
        proc.wait.return_value = 0

        thread = threading.Thread(target=commands._report_completion, args=(proc, send, 0))
        thread.start()
        thread.join(timeout=5)

        assert not thread.is_alive()
        send.assert_called_once()
        assert send.call_args[0][0].startswith("Сессия завершена: 4 лайка (окончание ")
