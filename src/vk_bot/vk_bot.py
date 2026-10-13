"""VK-бот: long polling-демон для запуска сессий и статуса.

Транспорт VK: фиксированная мапа команд (старт/стоп/статус/помощь) — вызовы
методов класса Commands; текст входящих сообщений не попадает в shell,
обрабатываются только сообщения владельца (from_id == user_id).

Бот не ходит через VKApiClient: это отдельный Bot API с собственным
токеном доступа. Опрос, декодирование событий и вызовы Bot API идут через
библиотеку `vk_api` (VkLongPoll/Event/VkApi): messages.getLongPollServer,
mode 234, version 3.
"""

import json
import random
import time
from collections import deque
from pathlib import Path

import requests
from vk_api import VkApi, VkApiError
from vk_api.longpoll import Event, VkEventType, VkLongPoll

from commands import Commands
from file_lock import FileLock
from logger import AppLogger
from settings import Settings

# Собственная блокировка демона: два демона не должны делить один канал.
# Файл лежит в src/ — на уровень выше пакета vk_bot/
_DAEMON_LOCK = Path(__file__).parent.parent / ".autoliker.bot.lock"

# message_event (код 58) либой `Event` не замэпчен — компактный массив
# читаем вручную из `event.raw`
_EVENT_MESSAGE_EVENT = 58

# JSON-строка inline-клавиатуры: одна строка, три кнопки
_KEYBOARD_JSON = (
    '{"inline":true,"one_time":false,"buttons":['
    '[{"action":{"type":"text","label":"\\u25b6\\ufe0f \\u0421\\u0442\\u0430\\u0440\\u0442",'
    '"payload":"{\\"command\\":\\"start\\"}"},"color":"positive"},'
    '{"action":{"type":"text","label":"\\u23f9\\ufe0f \\u0421\\u0442\\u043e\\u043f",'
    '"payload":"{\\"command\\":\\"stop\\"}"},"color":"negative"},'
    '{"action":{"type":"text","label":"\\u2139\\ufe0f \\u0421\\u0442\\u0430\\u0442\\u0443\\u0441",'
    '"payload":"{\\"command\\":\\"status\\"}"},"color":"primary"}]'
    "]}"
)

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


class VkBot:
    """VK-бот: long polling, авторизация владельца, фиксированная мапа команд."""

    def __init__(self, config: Settings, logger: AppLogger) -> None:
        """Создаёт класс команд для выполнения (DI через config + logger)."""
        self._config = config
        self._logger = logger
        self._commands = Commands(config, logger)
        # Клиент Bot API (либа): хранит токен бота, в сеть при создании
        # не ходит — канал захватывается в run()
        self._vk = VkApi(
            token=config.bot_token.get_secret_value(),
            api_version=config.api_version,
        )
        # Канал long polling (VkLongPoll) — создаётся в run(), под блокировкой
        self._lp: VkLongPoll | None = None
        # ID собственных исходящих (random_id + message_id) — для отсечения
        # эха: ответ бота сам возвращается событием MESSAGE_NEW
        self._sent_ids: deque[int] = deque(maxlen=200)

    def run(self) -> None:
        """Основной цикл демона: захват канала, обработка событий.

        Демон НЕ берёт сессионную блокировку — он резидентный, и взял бы
        её, заблокировал все сессии. Сетевые ошибки и ротация канала
        (a_config) — переподключение без выхода; ошибка одного события
        не роняет цикл; недействительный токен и Ctrl+C — чистый выход.
        """
        lock = FileLock(_DAEMON_LOCK)
        if not lock.acquire():
            self._logger.error("VK-бот уже запущен, выход.")
            return
        try:
            self._connect()
            while True:
                try:
                    events = self._lp.check()
                except requests.RequestException as e:
                    self._logger.warning(f"VK-бот: сетевая ошибка, переподключение: {e}")
                    self._connect()
                    continue
                except KeyError:
                    # Зазор либы: a_config (ротация канала) check() не
                    # обрабатывает и падает KeyError — перезахватываем
                    # сервер и идём дальше
                    self._logger.info("VK-бот: a_config (ротация канала) — переподключение")
                    self._connect()
                    continue
                for event in events:
                    try:
                        self._handle_event(event)
                    except (requests.RequestException, VkApiError) as e:
                        # Канал жив (check() прошёл) — ошибка одного вызова
                        # Bot API: логируем и продолжаем, демон не падает
                        self._logger.warning(f"VK-бот: ошибка обработки события: {e}")
        except KeyboardInterrupt:
            self._logger.info("VK-бот: прервано (Ctrl+C)")
        except VkApiError as e:
            self._logger.error(f"VK-бот: фатальная ошибка, выход: {e}")
        finally:
            lock.release()

    def _connect(self) -> None:
        """Захват long polling-канала с ретраями до успеха.

        Конструктор либы (VkLongPoll) сразу ходит в
        messages.getLongPollServer, поэтому сетевая или API-ошибка
        проявляется здесь. Сетевые сбои и временные API-ошибки — ретрай
        с рандомной задержкой; недействительный токен (error 5) фатален
        и поднимается наверх.
        """
        while True:
            try:
                self._lp = VkLongPoll(self._vk)
                self._logger.info("VK-бот: long polling-канал подключён")
                return
            except (requests.RequestException, VkApiError) as e:
                if isinstance(e, VkApiError) and getattr(e, "code", None) == 5:
                    raise
                delay = random.uniform(5, 15)
                self._logger.warning(f"VK-бот: канал недоступен, ретрай через {delay:.0f} сек: {e}")
                time.sleep(delay)

    def _keyboard(self) -> str:
        """Возвращает JSON inline-клавиатуры (одна строка: Старт/Стоп/Статус)."""
        return _KEYBOARD_JSON

    def _handle_event(self, event: Event) -> None:
        """Обрабатывает событие: message_new от владельца или callback-кнопка."""
        if event.type == VkEventType.MESSAGE_NEW:
            self._handle_message_new(event)
        elif event.type == _EVENT_MESSAGE_EVENT:
            self._handle_message_event(event)

    def _handle_message_new(self, event: Event) -> None:
        """Сообщение от владельца — текстовые команды и нажатия кнопок.

        Нажатие inline-кнопки (action type=text) приходит как MESSAGE_NEW с
        payload в extra; text при этом — метка кнопки («ℹ️ Статус»), не
        команда. Payload имеет приоритет: его команда исполняется вместо
        текста; невалидный payload — fallthrough на текст. Эхо собственного
        ответа отсечено по ID (random_id + message_id) — поле flags VK не
        надёжный дискриминатор (входящие владельца и эхо приходят с flags=1
        и flags=3).
        """
        if not event.from_user:
            # беседа или группа: автор не равен peer_id — бот ответить
            # не обязан
            return
        if event.message_id in self._sent_ids or (event.random_id or 0) in self._sent_ids:
            return
        if int(event.user_id) != self._config.user_id:
            self._logger.info("VK-бот: сообщение от постороннего, игнорирую")
            return
        peer_id = int(event.peer_id)
        extra = event.extra_values if isinstance(event.extra_values, dict) else {}
        command = self._payload_command(extra.get("payload"))
        if command is not None:
            self._logger.info(f"VK-бот: кнопка «{command}»")
            self._dispatch(command, peer_id)
            return
        text = (event.text or "").strip().lower()
        self._logger.info(f"VK-бот: команда «{text}»")
        self._dispatch(text, peer_id)

    def _handle_message_event(self, event: Event) -> None:
        """Callback-кнопка (код 58): ack, проверка владельца, payload-команда.

        Inline-кнопки type=text приходят как MESSAGE_NEW с payload в extra,
        а не этим событием. Ветка — на случай кнопок callback-типа.
        VK требует на каждое событие 58 ответ
        messages.sendMessageEventAnswer (без него — бесконечные
        ределиверы), поэтому ack отправляется первым, до проверки владельца
        и payload: чужое или битое событие тоже отвечает. Либа `Event` не
        мапит поля 58 — компактный массив читаем из `event.raw`.
        """
        raw = getattr(event, "raw", None)
        if not isinstance(raw, list) or len(raw) < 8 or raw[0] != _EVENT_MESSAGE_EVENT:
            return
        peer_id = int(raw[3])
        user_id = int(raw[2])
        self._vk.method(
            "messages.sendMessageEventAnswer",
            {"event_id": raw[1], "user_id": user_id, "peer_id": peer_id},
        )
        if user_id != self._config.user_id:
            self._logger.info("VK-бот: кнопка от постороннего, игнорирую")
            return
        command = self._payload_command(raw[7])
        if command is None:
            return
        self._logger.info(f"VK-бот: payload кнопка «{command}»")
        self._dispatch(command, peer_id)

    def _payload_command(self, payload_str: object) -> str | None:
        """Команда из payload кнопки: JSON-строка {"command": ...} → имя команды.

        Возвращает None, если payload отсутствует или не содержит строковой
        команды — вызывающий уходит на текстовую ветку (не падать на
        чужих клиентах, шлющих битый payload).
        """
        if not isinstance(payload_str, str) or not payload_str:
            return None
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            self._logger.warning(f"VK-бот: невалидный payload кнопки: {payload_str!r}")
            return None
        command = payload.get("command") if isinstance(payload, dict) else None
        return command if isinstance(command, str) else None

    def _dispatch(self, name: str, peer_id: int) -> None:
        """Единый диспетчер: имя команды (текст или payload) → Commands.

        /-префикс срезается: /старт, / старт, ///старт → старт. Команды
        без slash продолжают работать (назад-совместимо). Неизвестное
        имя — help. Команды идемпотентны: повторный вызов (ределивер
        события) безопасен.
        """
        resolved = _COMMAND_MAP.get(name.strip().lstrip("/").strip().lower())
        if resolved == "start":
            self._commands.start(
                lambda reply: self._send(peer_id, reply, keyboard=self._keyboard())
            )
        elif resolved == "stop":
            self._send(peer_id, self._commands.stop(), keyboard=self._keyboard())
        elif resolved == "status":
            self._send(peer_id, self._commands.status(), keyboard=self._keyboard())
        else:
            self._send(peer_id, self._commands.help(), keyboard=self._keyboard())

    def _send(self, peer_id: int, text: str, keyboard: str) -> None:
        """Отправляет ответ через messages.send и запоминает его ID.

        Запоминаем random_id (сгенерированный нами) и message_id (из
        ответа) — эхо этого сообщения вернётся событием MESSAGE_NEW и
        будет отсечено по одному из этих ID. Ответ всегда несёт клавиатуру.
        """
        random_id = random.randint(1, 2_000_000_000)
        self._sent_ids.append(random_id)
        params: dict[str, object] = {
            "peer_id": peer_id,
            "message": text,
            "random_id": random_id,
            "keyboard": keyboard,
        }
        message_id = self._vk.method("messages.send", params)
        if isinstance(message_id, int):
            self._sent_ids.append(message_id)
