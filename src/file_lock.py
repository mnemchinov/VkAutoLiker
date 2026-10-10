"""Кроссплатформенная эксклюзивная блокировка файла.

POSIX: fcntl.flock, Windows: msvcrt.locking. Нужна для защиты от двойного
запуска: launchd иногда стартует два процесса в один слот, и второй убил бы
Chrome первого через _kill_stale_chrome(), после чего первый работал бы с
мёртвой сессией (invalid session id).
"""

import sys
from pathlib import Path
from typing import BinaryIO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class FileLock:
    """Эксклюзивная неблокирующая блокировка файла.

    Открывает файл в режиме r+b (создаёт при отсутствии) и захватывает
    один байт: fcntl.flock на POSIX, msvcrt.locking на Windows.
    Повторный захват из другого процесса/дескриптора возвращает False.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: BinaryIO | None = None

    def acquire(self) -> bool:
        """Пробует захватить блокировку. False — файл уже заблокирован."""
        if self._handle is not None:
            return True

        self._path.touch(exist_ok=True)
        handle = open(self._path, "r+b")
        try:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False

        self._handle = handle
        return True

    def release(self) -> None:
        """Снимает блокировку и закрывает файл. Идемпотентно."""
        if self._handle is None:
            return
        try:
            if sys.platform == "win32":
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None
