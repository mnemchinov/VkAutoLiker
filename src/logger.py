"""Логирование в консоль и файл с единым форматом."""

import logging

from settings import Settings


class AppLogger:
    """Обёртка над logging.Logger с консольным и файловым хендлерами."""

    def __init__(self, config: Settings, name: str = "vk_autoliker"):
        """Инициализирует логгер с консольным и файловым хендлерами."""
        self._logger = logging.getLogger(name)
        self._logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))
        self._logger.propagate = False

        if self._logger.handlers:
            return

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        file_handler = logging.FileHandler(config.log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)

    def debug(self, msg: str) -> None:
        """Логирует на уровне DEBUG."""
        self._logger.debug(msg)

    def info(self, msg: str) -> None:
        """Логирует на уровне INFO."""
        self._logger.info(msg)

    def warning(self, msg: str) -> None:
        """Логирует на уровне WARNING."""
        self._logger.warning(msg)

    def error(self, msg: str) -> None:
        """Логирует на уровне ERROR."""
        self._logger.error(msg)

    def critical(self, msg: str) -> None:
        """Логирует на уровне CRITICAL."""
        self._logger.critical(msg)

    @property
    def logger(self) -> logging.Logger:
        """Возвращает обёрнутый logging.Logger."""
        return self._logger
