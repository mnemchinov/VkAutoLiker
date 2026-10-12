"""VK-бот: long polling-демон для запуска сессий и статуса.

Транспорт VK: фиксированная мапа команд (старт/стоп/статус/помощь) — вызовы
методов класса Commands; текст входящих сообщений не попадает в shell,
обрабатываются только сообщения владельца (from_id == user_id).

Бот не ходит через VKApiClient: это отдельный Bot API с собственным
токеном доступа — long polling это цикл запросов, а не rate-limit'ные
вызовы основного API.
"""

import json
import random
import time
from collections import deque
from pathlib import Path
from typing import Any

import requests

from commands import Commands
from file_lock import FileLock
from logger import AppLogger
from settings import Settings

# Собственная блокировка демона: два демона не должны делить один канал
_DAEMON_LOCK = Path(__file__).parent / ".autoliker.bot.lock"

_LONG_POLL_WAIT_SEC = 25
_REQUEST_TIMEOUT_SEC = 30

# Компактный формат long polling: события — позиционные массивы,
# параметры mode/version запрашивают полный набор полей (референс — vk_api)
_EVENT_MESSAGE_NEW = 4
_EVENT_MESSAGE_EVENT = 58
_CHAT_PEER_START = 2_000_000_000
_LP_MODE = 234
_LP_VERSION = 3

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


class VkAutoLikerBot:
    """VK-бот: long polling, авторизация владельца, фиксированная мапа команд."""

    def __init__(self, config: Settings, logger: AppLogger) -> None:
        """Создаёт класс команд для выполнения (DI через config + logger)."""
        self._config = config
        self._logger = logger
        self._commands = Commands(config, logger)
        self._server: str = ""
        self._ts: str = "0"
        self._key: str = ""
        # ID собственных исходящих (random_id + message_id) — для отсечения
        # эха: ответ бота сам возвращается событием MESSAGE_NEW
        self._sent_ids: deque[int] = deque(maxlen=200)

    def run(self) -> None:
        """Основной цикл демона: a_check/a_config, обработка сообщений.

        Демон НЕ берёт сессионную блокировку — он резидентный, и взял бы
        её, заблокировал все сессии. Сетевые ошибки — ретрай через
        рандомную задержку и повтор (включая error-ответы VK); Ctrl+C — чистый
        выход.
        """
        lock = FileLock(_DAEMON_LOCK)
        if not lock.acquire():
            self._logger.error("VK-бот уже запущен, выход.")
            return
        try:
            while True:
                try:
                    self._capture_server()
                    break
                except requests.RequestException as e:
                    delay = random.uniform(5, 15)
                    self._logger.warning(
                        f"VK-бот: канал недоступен, ретрай через {delay:.0f} сек: {e}"
                    )
                    time.sleep(delay)
            while True:
                try:
                    self._poll_once()
                except requests.RequestException as e:
                    delay = random.uniform(5, 15)
                    self._logger.warning(
                        f"VK-бот: сетевая ошибка, ретрай через {delay:.0f} сек: {e}"
                    )
                    time.sleep(delay)
        except KeyboardInterrupt:
            self._logger.info("VK-бот: прервано (Ctrl+C)")
        finally:
            lock.release()

    def _capture_server(self) -> None:
        """Получает адрес long polling-сервера (при старте и на a_config).

        Bot API отдаёт ключ в поле `key` (не `auth_key`), а адрес сервера —
        без схемы (`api.vk.ru/gim...`); схему подставляем, отдельного пути
        /longpoll нет — a_check идёт по корню сервера. lp_version/need_pts —
        параметры протокола v3, без них events приходят в урезанной форме.
        """
        data = self._api("messages.getLongPollServer", lp_version=_LP_VERSION, need_pts=1)
        server, key = data.get("server"), data.get("key")
        if not server or not key:
            # VK вернул error-ответ (ротация канала, недействительный токен,
            # ошибка 6): повторяем как сетевую ошибку, а не падаем с KeyError
            raise requests.RequestException(f"getLongPollServer без server/key: {data!r}")
        if not server.startswith("http"):
            server = f"https://{server}"
        self._server = server
        self._ts = str(data.get("ts", "0"))
        self._key = key
        self._logger.info("VK-бот: long polling-канал подключён")

    def _keyboard(self) -> str:
        """Возвращает JSON inline-клавиатуры (одна строка: Старт/Стоп/Статус)."""
        return _KEYBOARD_JSON

    def _poll_once(self) -> None:
        """Один запрос a_check; события диспатчит по одному.

        Реальный ответ a_check не несёт поля action — форма {ts, pts, updates};
        обновления берём по наличию ключа updates, a_config — по ключу
        auth_key/key или action (документированная форма). failed=1 — новый ts,
        failed=2/3 — повторный захват сервера (как в референсе vk_api).
        """
        response = requests.get(
            self._server,
            params={
                "act": "a_check",
                "ts": self._ts,
                "key": self._key,
                "wait": _LONG_POLL_WAIT_SEC,
                "mode": _LP_MODE,
                "version": _LP_VERSION,
            },
            timeout=_REQUEST_TIMEOUT_SEC,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("action") == "a_config" or "auth_key" in data or "key" in data:
            self._capture_server()
            return
        if data.get("failed") in (2, 3):
            self._capture_server()
            return
        self._ts = str(data.get("ts", self._ts))
        updates = data.get("updates", [])
        if updates:
            self._logger.info(f"VK-бот: сырые updates: {updates!r}")
            for event in self._decode_events(updates):
                self._handle_event(event)

    def _decode_events(self, updates: Any) -> list[dict]:
        """Расшифровывает компактные события VK в словари.

        VK шлёт события позиционными массивами, а не словарями: первый
        элемент — код типа, далее поля в фиксированном порядке. MESSAGE_NEW
        (код 4) — [message_id, flags, peer_id, timestamp, text, ...];
        peer_id в обычном диалоге пользователя и есть автор.
        message_event (код 58) — [58, event_id, user_id, peer_id, ts, ...].
        Прочие типы (например, 61 — «пользователь печатает») боту не нужны.
        """
        events: list[dict] = []
        for raw in updates:
            decoded = self._decode_message_new(raw)
            if decoded:
                events.append(decoded)
                continue
            decoded = self._decode_message_event(raw)
            if decoded:
                events.append(decoded)
        return events

    def _decode_message_new(self, raw: Any) -> dict | None:
        """Один компактный event: MESSAGE_NEW → словарь, остальное — None.

        Эхо собственного ответа отсечено по ID: _send генерирует random_id,
        а message_id получает из ответа API — входящее событие с одним из
        этих ID наше. Поля flags VK для этого не годятся: входящие
        сообщения владельца приходят с разными значениями (наблюдались 1
        и 3), как и эхо.

        Live-форма 12.10: нажатие inline-кнопки приходит СЮДА ЖЕ (код 4),
        а не кодом 58: text (raw[5]) — метка кнопки («ℹ️ Статус»), а payload
        лежит в extra-словаре (raw[6]): {'emoji': '1', 'payload':
        '{"command":"status"}', ...}. Payload кладём в событие — обработчик
        отдаёт ему приоритет над текстом.
        """
        if not isinstance(raw, list) or len(raw) < 6 or raw[0] != _EVENT_MESSAGE_NEW:
            return None
        peer_id = raw[3]
        if not isinstance(peer_id, int) or peer_id >= _CHAT_PEER_START:
            # беседа: автор не равен peer_id — такому бот отвечает не обязан
            return None
        if raw[1] in self._sent_ids:
            return None
        if len(raw) >= 9 and raw[8] in self._sent_ids:
            return None
        extra = raw[6] if len(raw) >= 7 and isinstance(raw[6], dict) else {}
        return {
            "type": "message_new",
            "message": {
                "from_id": peer_id,
                "peer_id": peer_id,
                "text": raw[5],
                "payload": extra.get("payload"),
            },
        }

    def _decode_message_event(self, raw: Any) -> dict | None:
        """Один компактный event: message_event (код 58) → словарь, остальное — None.

        Compact-формат VK (предварительный, подтвердится live-проверкой):
        [58, event_id, user_id, peer_id, ts, action, label, payload, ...]
        payload — JSON-строка {"command": "start"|"stop"|"status"}.
        """
        if not isinstance(raw, list) or len(raw) < 8 or raw[0] != _EVENT_MESSAGE_EVENT:
            return None
        return {
            "type": "message_event",
            "event_id": raw[1],
            "user_id": raw[2],
            "peer_id": raw[3],
            "ts": raw[4],
            "payload": raw[7],
        }

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

    def _handle_event(self, event: dict) -> None:
        """Обрабатывает событие: message_new от владельца или callback-кнопки."""
        etype = event.get("type")
        if etype == "message_new":
            self._handle_message_new(event)
        elif etype == "message_event":
            self._handle_message_event(event)

    def _handle_message_new(self, event: dict) -> None:
        """Сообщение от владельца — текстовые команды и нажатия кнопок.

        Нажатие inline-кнопки (action type=text) приходит как MESSAGE_NEW с
        payload в extra; text при этом — метка кнопки («ℹ️ Статус»), не
        команда. Payload имеет приоритет: его команда исполняется вместо
        текста; невалидный payload — fallthrough на текст.
        """
        message = event["message"]
        if int(message["from_id"]) != self._config.user_id:
            self._logger.info("VK-бот: сообщение от постороннего, игнорирую")
            return
        peer_id = int(message["peer_id"])
        command = self._payload_command(message.get("payload"))
        if command is not None:
            self._logger.info(f"VK-бот: кнопка «{command}»")
            self._dispatch(command, peer_id)
            return
        text = (message.get("text") or "").strip().lower()
        self._logger.info(f"VK-бот: команда «{text}»")
        self._dispatch(text, peer_id)

    def _payload_command(self, payload_str: Any) -> str | None:
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

    def _handle_message_event(self, event: dict) -> None:
        """Callback-кнопка (код 58): ack, проверка владельца, payload-команда.

        Live-наблюдение 12.10 показало: inline-кнопки type=text приходят
        как MESSAGE_NEW с payload в extra, а не этим событием. Ветку
        сохраняем на случай кнопок callback-типа. VK требует на каждое
        событие 58 ответ messages.sendMessageEventAnswer (без него —
        бесконечные ределиверы), поэтому ack отправляется первым, до
        проверки владельца и payload: чужое или битое событие тоже
        отвечает.
        """
        peer_id = int(event.get("peer_id", 0))
        user_id = int(event.get("user_id", 0))
        self._api(
            "messages.sendMessageEventAnswer",
            event_id=event.get("event_id"),
            user_id=user_id,
            peer_id=peer_id,
        )
        if user_id != self._config.user_id:
            self._logger.info("VK-бот: кнопка от постороннего, игнорирую")
            return
        command = self._payload_command(event.get("payload"))
        if command is None:
            return
        self._logger.info(f"VK-бот: payload кнопка «{command}»")
        self._dispatch(command, peer_id)

    def _send(self, peer_id: int, text: str, keyboard: str | None = None) -> None:
        """Отправляет ответ через messages.send и запоминает его ID.

        Запоминаем random_id (сгенерированный нами) и message_id (из
        ответа) — эхо этого сообщения вернётся событием MESSAGE_NEW, и
        декодер отсечёт его по одному из этих ID.
        """
        random_id = random.randint(1, 2_000_000_000)
        self._sent_ids.append(random_id)
        params: dict[str, Any] = {
            "peer_id": peer_id,
            "message": text,
            "random_id": random_id,
        }
        if keyboard is not None:
            params["keyboard"] = keyboard
        message_id = self._api("messages.send", **params)
        if isinstance(message_id, int):
            self._sent_ids.append(message_id)

    def _api(self, method: str, **params) -> dict:
        """Вызывает метод Bot API с токеном бота, возвращает тело ответа.

        Паттерн тот же, что у VKApiClient: GET на {base_url}/{method} с
        параметрами в query — POST на голый /method VK отвечает 404.
        """
        response = requests.get(
            f"{self._config.base_url}/{method}",
            params={
                "access_token": self._config.bot_token.get_secret_value(),
                "v": self._config.api_version,
                **params,
            },
            timeout=_REQUEST_TIMEOUT_SEC,
        )
        response.raise_for_status()
        return response.json().get("response", {})
