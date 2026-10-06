"""Unit-тесты FileLock.

Проверяет: захват создаёт файл, повторный захват другим дескриптором
отклоняется, release освобождает блокировку, повторные вызовы идемпотентны.
"""

from file_lock import FileLock


class TestFileLock:
    def test_acquire_creates_file(self, tmp_path):
        """Захват создаёт файл блокировки и возвращает True."""
        lock_path = tmp_path / ".autoliker.lock"
        lock = FileLock(lock_path)

        assert lock.acquire() is True
        assert lock_path.exists()
        lock.release()

    def test_second_acquire_fails(self, tmp_path):
        """Второй FileLock на тот же файл не захватывает блокировку."""
        lock_path = tmp_path / ".autoliker.lock"
        first = FileLock(lock_path)
        second = FileLock(lock_path)

        assert first.acquire() is True
        assert second.acquire() is False
        first.release()

    def test_release_allows_reacquire(self, tmp_path):
        """После release другой FileLock снова может захватить файл."""
        lock_path = tmp_path / ".autoliker.lock"
        first = FileLock(lock_path)
        second = FileLock(lock_path)

        assert first.acquire() is True
        assert second.acquire() is False
        first.release()
        assert second.acquire() is True
        second.release()

    def test_release_idempotent(self, tmp_path):
        """Повторный release и release без acquire не падают."""
        lock_path = tmp_path / ".autoliker.lock"
        lock = FileLock(lock_path)

        lock.release()
        assert lock.acquire() is True
        lock.release()
        lock.release()

    def test_acquire_idempotent(self, tmp_path):
        """Повторный acquire на том же объекте возвращает True."""
        lock_path = tmp_path / ".autoliker.lock"
        lock = FileLock(lock_path)

        assert lock.acquire() is True
        assert lock.acquire() is True
        lock.release()
