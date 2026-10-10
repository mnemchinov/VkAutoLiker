#!/usr/bin/env python3
"""Точка входа CLI: login | run | test | status | reset."""

import argparse
import fcntl
import sys
from pathlib import Path
from typing import TextIO

sys.path.insert(0, str(Path(__file__).parent))

from liker import AutoLiker
from logger import AppLogger
from settings import get_settings

# Файл-блокировка: предотвращает двойной запуск (launchd может стартовать 2 процесса)
_LOCK_FILE = Path(__file__).parent / ".autoliker.lock"


def _acquire_lock() -> TextIO:
    """Захватывает эксклюзивную блокировку. При неудаче — выход.

    launchd иногда стартует процесс дважды в один слот. Без блокировки
    второй процесс убивает Chrome первого через _kill_stale_chrome(),
    после чего первый работает с мёртвой сессией (invalid session id).
    """
    lock_file = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except OSError:
        print("Другой экземпляр уже запущен, выход.", file=sys.stderr)
        sys.exit(0)


def main() -> None:
    """Точка входа CLI: парсит аргументы, создаёт AutoLiker, выполняет команду.

    Ctrl+C завершает процесс с кодом 130; finally закрывает браузер, базу и lock.
    """
    parser = argparse.ArgumentParser(description="VkAutoLiker — автолайкер ВКонтакте")
    subparsers = parser.add_subparsers(dest="command", help="Доступные команды")

    subparsers.add_parser("login", help="Открыть браузер для ручного входа в VK (включая 2FA)")
    run_parser = subparsers.add_parser("run", help="Запустить сессию автолайкинга")
    run_parser.add_argument(
        "--no-limit",
        action="store_true",
        help="Не учитывать дневной лимит сессий (ручной запуск)",
    )
    subparsers.add_parser("test", help="Тест поиска и лайка на одном посте")
    subparsers.add_parser("status", help="Показать статистику сессий и лайков")
    subparsers.add_parser("reset", help="Очистить базу состояния")

    args = parser.parse_args()

    command = args.command or "run"

    lock = _acquire_lock()

    liker: AutoLiker | None = None
    try:
        config = get_settings()
        logger = AppLogger(config)
        liker = AutoLiker(config, logger)

        if command == "login":
            liker.login()
        elif command == "run":
            liker.run(no_limit=args.no_limit)
        elif command == "test":
            liker.test()
        elif command == "status":
            liker.status()
        elif command == "reset":
            liker.reset()
        else:
            parser.print_help()
            sys.exit(1)
    except FileNotFoundError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        # Ctrl+C — штатное прерывание на любом этапе (старт браузера, проверка
        # авторизации, jitter): трейсбэк не нужен, очистку делает finally
        print("Прервано (Ctrl+C)", file=sys.stderr)
        sys.exit(130)
    finally:
        if liker is not None:
            liker.close()
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    main()
