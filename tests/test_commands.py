"""Юнит-тесты команд проекта (Commands): status, help, start.

Без сети и без реального процесса: start — на подменённых Popen и Thread,
отчёты о завершении — прямые вызовы _report_completion на мок-процессе.
"""

import re
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock, patch

from commands import Commands
from database import Database
from file_lock import FileLock
from migrations import run_migrations


def _dead_pid() -> int:
    """pid завершившегося процесса — для тестов зомби-сессий."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


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

    def test_status_last_session_with_report(self, mock_config, mock_logger, tmp_path):
        """«Последняя» — время, длительность, лайки, причина + строка отчёта о постах."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        sid = repo.start_session(is_auto=False)
        report = {
            "collected": 214,
            "filtered": 16,
            "duplicates": 12,
            "llm_filtered": 0,
            "llm_timeout": 0,
            "liked": 18,
            "already_liked": 3,
            "failed": 2,
            "reason": "лимит лайков сессии",
        }
        repo.end_session(sid, likes_count=18, report=report)

        text = commands.status()

        assert "Последняя: сегодня " in text
        assert "18 лайков" in text
        assert "стоп: лимит лайков сессии" in text
        assert (
            "Постов: 214, 16 отсеяно фильтром, 12 дубликатов, 3 уже были с лайком, 2 не удалось"
            in text
        )

    def test_status_last_session_without_report_legacy(self, mock_config, mock_logger, tmp_path):
        """Сессия без отчёта (старая схема) — строка «Последняя» без «Постов» и «стоп»."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        sid = repo.start_session(is_auto=False)
        repo.end_session(sid, likes_count=5)

        text = commands.status()

        assert "Последняя: сегодня " in text
        assert "Постов:" not in text
        assert "стоп:" not in text

    def test_status_last_session_old_date_shows_day_month(self, mock_config, mock_logger, tmp_path):
        """Сессия не за сегодня — дата в формате ДД.ММ вместо «сегодня»."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        sid = repo.start_session(is_auto=False)
        repo.end_session(sid, likes_count=5)
        past = int(time.time()) - 86400 * 2
        commands._db.conn.execute(
            "UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?",
            (past, past + 600, sid),
        )
        commands._db.conn.commit()

        text = commands.status()
        last_line = next(line for line in text.splitlines() if line.startswith("Последняя"))

        assert "сегодня" not in last_line
        assert re.search(r"Последняя: \d{2}\.\d{2} ", last_line)
        assert "(10 мин)" in last_line

    def test_status_report_llm_parts_and_hours_duration(self, mock_config, mock_logger, tmp_path):
        """Отчёт с LLM-счётчиками — части в строке; длительность >1 ч — «1 ч 30 мин»."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        sid = repo.start_session(is_auto=False)
        report = {
            "collected": 50,
            "filtered": 0,
            "duplicates": 0,
            "llm_filtered": 2,
            "llm_timeout": 1,
            "liked": 47,
            "already_liked": 0,
            "failed": 0,
            "reason": "посты закончились",
        }
        repo.end_session(sid, likes_count=47, report=report)
        past = int(time.time()) - 86400 * 3
        commands._db.conn.execute(
            "UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?",
            (past, past + 5400, sid),
        )
        commands._db.conn.commit()

        text = commands.status()
        last_line = next(line for line in text.splitlines() if line.startswith("Последняя"))

        assert "(1 ч 30 мин)" in last_line
        assert "Постов: 50, 2 отсеяно LLM, 1 пропущено LLM (таймаут)" in text

    def test_status_report_broken_json_falls_back(self, mock_config, mock_logger, tmp_path):
        """Битый JSON в sessions.report — только строка «Последняя», без падения."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        sid = repo.start_session(is_auto=False)
        repo.end_session(
            sid,
            likes_count=5,
            report={"collected": 10, "reason": "посты закончились"},
        )
        commands._db.conn.execute("UPDATE sessions SET report = 'не json' WHERE id = ?", (sid,))
        commands._db.conn.commit()

        text = commands.status()

        assert "Последняя: " in text
        assert "Постов:" not in text
        assert "стоп:" not in text

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
        """help() — список команд старт/стоп/статус/помощь."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        text = commands.help()
        assert "старт" in text
        assert "стоп" in text
        assert "статус" in text
        assert "помощь" in text

    def test_stop_with_running_session_touches_flag(self, mock_config, mock_logger, tmp_path):
        """stop() при идущей сессии — флаг поставлен, ответ «запрошена остановка»."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        commands._stop_flag = MagicMock()
        repo = commands._sessions_repo
        sid = repo.start_session(is_auto=False)
        try:
            text = commands.stop()
        finally:
            repo.end_session(sid, likes_count=0)
        commands._stop_flag.touch.assert_called_once()
        assert "остановка" in text.lower()

    def test_stop_without_session_still_touches_flag(self, mock_config, mock_logger, tmp_path):
        """stop() без идущей сессии — флаг всё равно ставится, ответ это отмечает."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        commands._stop_flag = MagicMock()
        text = commands.stop()
        commands._stop_flag.touch.assert_called_once()
        assert "нет" in text.lower()

    def test_stop_with_zombie_session_says_no_session(self, mock_config, mock_logger, tmp_path):
        """stop() — зомби-сессия (мёртвый pid) закрывается, «идущей сессии нет»."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        commands._stop_flag = MagicMock()
        repo = commands._sessions_repo
        zombie = repo.start_session(is_auto=False, pid=_dead_pid())

        text = commands.stop()

        assert "нет" in text.lower()
        commands._stop_flag.touch.assert_called_once()
        row = commands._db.conn.execute(
            "SELECT ended_at FROM sessions WHERE id = ?", (zombie,)
        ).fetchone()
        assert row[0] is not None

    def test_status_closes_zombie_session(self, mock_config, mock_logger, tmp_path):
        """status() — зомби-сессия закрывается и видна как «последняя завершённая»."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        zombie = repo.start_session(is_auto=False, pid=_dead_pid())

        text = commands.status()

        assert "Сессия идёт" not in text
        assert "Последняя: " in text
        row = commands._db.conn.execute(
            "SELECT ended_at FROM sessions WHERE id = ?", (zombie,)
        ).fetchone()
        assert row[0] is not None

    def test_start_clears_stale_stop_flag(self, mock_config, mock_logger, tmp_path):
        """start() снимает устаревший флаг — случайный стоп не убьёт новую сессию."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        commands._stop_flag = MagicMock()
        send = MagicMock()
        with (
            patch("commands._SESSION_LOCK", tmp_path / "session.lock"),
            patch("commands.subprocess.Popen") as mock_popen,
            patch("commands.threading.Thread"),
        ):
            mock_popen.return_value = MagicMock()
            commands.start(send)
        commands._stop_flag.clear.assert_called_once()

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
        # Без отчёта (end_session без report) — вторая строка не добавляется
        assert "Постов:" not in text

    def test_report_completion_with_report(self, mock_config, mock_logger, tmp_path):
        """Отчёт сессии — причина остановки и строка постов в том же сообщении."""
        commands = self._make_commands(mock_config, mock_logger, tmp_path)
        repo = commands._sessions_repo
        old_sid = repo.start_session(is_auto=False)
        repo.end_session(old_sid, likes_count=1)
        new_sid = repo.start_session(is_auto=False)
        repo.end_session(
            new_sid,
            likes_count=7,
            report={
                "collected": 12,
                "filtered": 5,
                "duplicates": 1,
                "llm_filtered": 0,
                "llm_timeout": 0,
                "liked": 7,
                "already_liked": 0,
                "failed": 0,
                "reason": "посты закончились",
            },
        )
        send = MagicMock()
        proc = MagicMock()
        proc.wait.return_value = 0

        commands._report_completion(proc, send, old_sid)

        send.assert_called_once()
        text = send.call_args[0][0]
        assert text.startswith("Сессия завершена: 7 лайков (окончание ")
        assert ", стоп: посты закончились" in text
        assert "Постов: 12, 5 отсеяно фильтром, 1 дубликатов" in text

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
