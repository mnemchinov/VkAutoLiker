"""Команды проекта, вызываемые из любой точки входа (CLI, VK-бот, Telegram-бот).

Класс не знает про транспорт: status() и help() возвращают текст,
start() запускает сессию в отдельном процессе и сообщает о результате
через callback send. Текст входящих сообщений в класс не попадает —
точки входа вызывают методы напрямую.
"""

import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from database import Database
from file_lock import FileLock
from logger import AppLogger
from repositories import SessionsRepository
from settings import Settings
from stop_flag import StopFlag

# Сессионная блокировка: та же, что в main.py. Пробуем её, чтобы не
# запустить вторую сессию поверх уже идущей
_SESSION_LOCK = Path(__file__).parent / ".autoliker.lock"
_PROJECT_ROOT = Path(__file__).parent.parent
_MAIN_SCRIPT = Path(__file__).parent / "main.py"


def _plural(n: int, one: str, few: str, many: str) -> str:
    """Склонение русского слова по числу: 1 запуск, 2 запуска, 5 запусков."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


class Commands:
    """Команды проекта: статус, помощь, запуск сессии.

    Транспортонезависим: status()/help() возвращают текст, start()
    сообщает о результате через callback send.
    """

    def __init__(self, config: Settings, logger: AppLogger) -> None:
        """Создаёт базу и репозиторий сессий (DI через config + logger)."""
        self._config = config
        self._logger = logger
        self._db = Database(config)
        self._sessions_repo = SessionsRepository(self._db)
        self._stop_flag = StopFlag()

    def stop(self) -> str:
        """Просит идущую сессию остановиться: ставит файловый флаг.

        Сессия — отдельный процесс (subprocess.Popen в start()); сигнал
        послать нечем, PID обратно не передаётся — работает только
        файловый флаг. Проверка идемпотентна: повторный стоп не ошибка.
        Если сессии нет, флаг всё равно ставится и будет снят clear()
        при следующем старте.
        """
        running = self._sessions_repo.get_running_session()
        self._stop_flag.touch()
        if running is None:
            return "Идущей сессии нет (флаг остановки снятится при следующем старте)"
        return "Запрошена остановка сессии"

    def status(self) -> str:
        """Возвращает статус: всего, за сегодня и третья строка —
        либо идущая сессия с текущим числом лайков, либо последняя завершённая."""
        total_sessions, total_likes = self._sessions_repo.get_total_stats()
        today = self._sessions_repo.get_today_stats()
        lines = [
            f"Всего: {total_sessions} {_plural(total_sessions, 'запуск', 'запуска', 'запусков')}, "
            f"{total_likes} {_plural(total_likes, 'лайк', 'лайка', 'лайков')}",
            f"Сегодня: {today.sessions} {_plural(today.sessions, 'запуск', 'запуска', 'запусков')}, "
            f"{today.likes} {_plural(today.likes, 'лайк', 'лайка', 'лайков')}",
        ]
        running = self._sessions_repo.get_running_session()
        if running is not None:
            since = datetime.fromtimestamp(running.started_at).strftime("%H:%M")
            lines.append(
                f"Сессия идёт с {since}, "
                f"{running.likes} {_plural(running.likes, 'лайк', 'лайка', 'лайков')}"
            )
        else:
            last = self._sessions_repo.get_last_session()
            if last is not None:
                ended = datetime.fromtimestamp(last.ended_at).strftime("%H:%M")
                lines.append(
                    f"Последняя: {ended}, "
                    f"{last.likes} {_plural(last.likes, 'лайк', 'лайка', 'лайков')}"
                )
        return "\n".join(lines)

    def help(self) -> str:
        """Возвращает список доступных команд."""
        return (
            "Команды: старт — запустить сессию; стоп — остановить текущую; "
            "статус — статистика; помощь — список команд"
        )

    def start(self, send: Callable[[str], None]) -> None:
        """Запускает сессию лайкинга в отдельном процессе, результат — через send.

        Сессия — отдельный процесс (main.py run --no-limit): сессия в процессе
        вызывающего невозможна — файловая блокировка процессная, и второй
        поток того же процесса либо заблокировался бы, либо заблокировал бы
        вызывающего. Отчёт о завершении приходит из демон-потока.
        """
        lock = FileLock(_SESSION_LOCK)
        if not lock.acquire():
            send("Сессия уже идёт")
            return
        lock.release()

        # Снимаем устаревший флаг остановки: случайный «стоп» между сессиями
        # не должен убить следующую (файл вне жизненного цикла процесса сессии)
        self._stop_flag.clear()

        before = self._sessions_repo.get_last_session()
        started_before_id = before.id if before is not None else 0
        proc = subprocess.Popen(
            [sys.executable, str(_MAIN_SCRIPT), "run", "--no-limit"],
            cwd=str(_PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._logger.info(f"Сессия запущена через команды (pid {proc.pid})")
        send("Сессия запущена")
        thread = threading.Thread(
            target=self._report_completion,
            args=(proc, send, started_before_id),
            daemon=True,
        )
        thread.start()

    def _report_completion(
        self, proc: subprocess.Popen, send: Callable[[str], None], started_before_id: int
    ) -> None:
        """Ждёт выхода процесса сессии и шлёт финальный отчёт.

        Отчёт по записи в БД: если процесс вышел с кодом 0, но новой записи
        о сессии нет (например, блокировку в зазоре занял другой процесс) —
        числа не выдумываем.
        """
        rc = proc.wait()
        if rc != 0:
            send(f"Сессия завершилась с ошибкой (код {rc})")
            return
        # Своё подключение: коннект, созданный в главном треде, не переносится
        # в тред отчёта (sqlite3 по умолчанию запрещает перенос между тредами)
        db = Database(self._config)
        try:
            last = SessionsRepository(db).get_last_session()
        finally:
            db.close()
        if last is None or last.id <= started_before_id:
            send("Сессия не началась: в базе нет записи о новой сессии")
            return
        ended = datetime.fromtimestamp(last.ended_at).strftime("%H:%M")
        send(
            f"Сессия завершена: "
            f"{last.likes} {_plural(last.likes, 'лайк', 'лайка', 'лайков')} (окончание {ended})"
        )
