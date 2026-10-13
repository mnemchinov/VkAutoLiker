"""Юнит-тесты StopFlag: файловый протокол остановки сессии."""

from stop_flag import StopFlag


class TestStopFlag:
    """Тесты touch/clear/exists на временном пути."""

    def test_touch_then_exists(self, tmp_path):
        """touch() ставит флаг — exists() True."""
        flag = StopFlag(tmp_path / ".autoliker.stop")
        assert not flag.exists()
        flag.touch()
        assert flag.exists()

    def test_clear_removes_flag(self, tmp_path):
        """clear() снимает флаг — exists() False."""
        flag = StopFlag(tmp_path / ".autoliker.stop")
        flag.touch()
        assert flag.exists()
        flag.clear()
        assert not flag.exists()

    def test_operations_are_idempotent(self, tmp_path):
        """Повторные вызовы не падают: touch twice, clear без файла."""
        flag = StopFlag(tmp_path / ".autoliker.stop")
        flag.touch()
        flag.touch()  # повторный touch — не ошибка
        assert flag.exists()
        flag.clear()
        flag.clear()  # clear отсутствующего файла — не ошибка (missing_ok)
        assert not flag.exists()
