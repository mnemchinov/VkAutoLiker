"""Telegram-бот: long polling-демон для запуска сессий и статуса.

Транспорт Telegram: фиксированная мапа команд (старт/стоп/статус/помощь) —
вызовы методов класса Commands; текст входящих сообщений не попадает в shell,
обрабатываются только сообщения владельца (from_user.id == telegram_owner_id)
в личке. Повторяет роль VK-бота (vk_bot.py): та же мапа команд, доступ только
владельцу, запуск сессии отдельным процессом, но на библиотеке pyTelegramBotAPI.

Опрос — синхронный и однопоточный (threaded=False): хендлеры исполняются в
потоке, вызвавшем infinity_polling(). Соединение SQLite в Commands создано в
том же потоке — перенос коннекта между потоками sqlite3 запрещает.
"""

from pathlib import Path
from random import uniform
from time import sleep

import requests
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

from commands import Commands
from file_lock import FileLock
from logger import AppLogger
from settings import Settings

# Собственная блокировка демона: два Telegram-бота не должны делить один
# канал. Файл лежит в src/ — на уровень выше пакета telegram_bot/. VK-бот
# берёт свой файл (.autoliker.bot.lock) и этим ботом не блокируется.
_DAEMON_LOCK = Path(__file__).parent.parent / ".autoliker.tgbot.lock"

_COMMAND_MAP: dict[str, str] = {
    "старт": "start",
    "start": "start",
    "стоп": "stop",
    "stop": "stop",
    "статус": "status",
    "status": "status",
    "помощь": "help",
    "help": "help",
}


class TelegramBot:
    """Telegram-бот: long polling, доступ только владельцу, мапа команд."""

    def __init__(self, config: Settings, logger: AppLogger) -> None:
        """Создаёт клиент Bot API и класс команд (DI через config + logger).

        В сеть при создании не ходит — токен проверяется в run() через
        get_me(). threaded=False, чтобы хендлеры шли в одном потоке с
        созданным здесь соединением Commands (sqlite3-коннект не переносится
        между потоками).
        """
        self._config = config
        self._logger = logger
        self._commands = Commands(config, logger)
        self._bot = telebot.TeleBot(config.telegram_bot_token.get_secret_value(), threaded=False)
        self._owner_id = config.telegram_owner_id

    def run(self) -> None:
        """Основной цикл демона: блокировка, проверка токена, long polling.

        Демон НЕ берёт сессионную блокировку — он резидентный, и взял бы её,
        заблокировал все сессии. Недействительный токен (401) и Ctrl+C —
        чистый выход; сетевые сбои на проверке токена — ретрай с рандомной
        задержкой, внутри polling либа переживает сама (infinity_polling).
        """
        lock = FileLock(_DAEMON_LOCK)
        if not lock.acquire():
            self._logger.error("Telegram-бот уже запущен, выход.")
            return
        try:
            if not self._check_token():
                self._logger.error("Telegram-бот: недействительный токен, выход.")
                return
            self._register_handlers()
            self._logger.info("Telegram-бот: long polling-канал подключён")
            self._listen()
        except KeyboardInterrupt:
            self._logger.info("Telegram-бот: прервано (Ctrl+C)")
        except ApiTelegramException as e:
            self._logger.error(f"Telegram-бот: фатальная ошибка API, выход: {e}")
        finally:
            lock.release()

    def _check_token(self) -> bool:
        """Проверяет токен через get_me(): False при 401 (недействителен).

        Сетевые сбои — ретрай с рандомной задержкой: резидент не должен
        умирать на старте, если API ещё недоступен (как VK-бот в _connect).
        """
        while True:
            try:
                self._bot.get_me()
                return True
            except ApiTelegramException as e:
                if getattr(e, "error_code", None) == 401:
                    return False
                raise
            except requests.RequestException as e:
                delay = uniform(5, 15)
                self._logger.warning(
                    f"Telegram-бот: API недоступен, ретрай через {delay:.0f} сек: {e}"
                )
                sleep(delay)

    def _register_handlers(self) -> None:
        """Подписывает хендлеры: текстовые сообщения и нажатия inline-кнопок."""
        self._bot.message_handler(content_types=["text"])(self._handle_message)
        self._bot.callback_query_handler(func=lambda _: True)(self._handle_callback)

    def _listen(self) -> None:
        """Бесконечный long polling — занимает поток до остановки."""
        self._bot.infinity_polling()

    def _handle_message(self, message: types.Message) -> None:
        """Сообщение от владельца в личке — текстовая команда.

        Сообщения не из лички (группы, беседы) и от посторонних игнорируются.
        Отсечение эха не нужно: Telegram не присылает боту его собственные
        исходящие (в отличие от VK, где нужен трекинг message_id).
        """
        user = message.from_user
        if user is None or user.id != self._owner_id:
            self._logger.info("Telegram-бот: сообщение от постороннего, игнорирую")
            return
        if message.chat.type != "private":
            self._logger.info("Telegram-бот: сообщение не из лички, игнорирую")
            return
        text = (message.text or "").strip().lower()
        self._logger.info(f"Telegram-бот: команда «{text}»")
        self._dispatch(text, message.chat.id)

    def _handle_callback(self, call: types.CallbackQuery) -> None:
        """Нажатие inline-кнопки: ack, проверка владельца, диспетчеризация.

        Telegram не требует ack для дедупликации (в отличие от VK-события 58),
        но answer_callback_query снимает «часики» на кнопке у клиента. Ack
        отправляется первым — до проверки владельца: чужое нажатие тоже
        подтверждается, но не исполняется.
        """
        self._bot.answer_callback_query(call.id)
        user = call.from_user
        if user is None or user.id != self._owner_id:
            self._logger.info("Telegram-бот: кнопка от постороннего, игнорирую")
            return
        command = (call.data or "").strip().lower()
        self._logger.info(f"Telegram-бот: кнопка «{command}»")
        if call.message is not None:
            self._dispatch(command, call.message.chat.id)

    def _dispatch(self, name: str, chat_id: int) -> None:
        """Единый диспетчер: имя команды (текст или callback_data) → Commands.

        /-префикс срезается: /старт, / старт, ///старт → старт. Команды без
        slash продолжают работать. Неизвестное имя — help. Команды
        идемпотентны: повторный вызов безопасен.
        """
        resolved = _COMMAND_MAP.get(name.strip().lstrip("/").strip().lower())
        if resolved == "start":
            self._commands.start(lambda reply: self._send(chat_id, reply))
        elif resolved == "stop":
            self._send(chat_id, self._commands.stop())
        elif resolved == "status":
            self._send(chat_id, self._commands.status())
        else:
            self._send(chat_id, self._commands.help())

    def _keyboard(self) -> types.InlineKeyboardMarkup:
        """Inline-клавиатура: одна строка — Старт / Стоп / Статус."""
        keyboard = types.InlineKeyboardMarkup(row_width=3)
        keyboard.add(
            types.InlineKeyboardButton("▶️ Старт", callback_data="start"),
            types.InlineKeyboardButton("⏹ Стоп", callback_data="stop"),
            types.InlineKeyboardButton("ℹ️ Статус", callback_data="status"),
        )
        return keyboard

    def _send(self, chat_id: int, text: str) -> None:
        """Отправляет ответ с inline-клавиатурой."""
        self._bot.send_message(chat_id, text, reply_markup=self._keyboard())
