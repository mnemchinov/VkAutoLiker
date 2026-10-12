"""VK-бот: long polling-демон для запуска сессий и статуса.

Транспорт VK: фиксированная мапа команд (старт/статус/помощь) — вызовы
методов класса Commands; текст входящих сообщений не попадает в shell,
обрабатываются только сообщения владельца (from_id == user_id).

Бот не ходит через VKApiClient: это отдельный Bot API с собственным
токеном доступа — long polling это цикл запросов, а не rate-limit'ные
вызовы основного API.
"""

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
_CHAT_PEER_START = 2_000_000_000
_LP_MODE = 234
_LP_VERSION = 3


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
        peer_id в обычном диалоге пользователя и есть автор. Прочие типы
        (например, 61 — «пользователь печатает») боту не нужны.
        """
        return [e for e in (self._decode_message_new(raw) for raw in updates) if e]

    def _decode_message_new(self, raw: Any) -> dict | None:
        """Один компактный event: MESSAGE_NEW → словарь, остальное — None.

        Эхо собственного ответа отсечено по ID: _send генерирует random_id,
        а message_id получает из ответа API — входящее событие с одним из
        этих ID наше. Поля flags VK для этого не годятся: входящие
        сообщения владельца приходят с разными значениями (наблюдались 1
        и 3), как и эхо.
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
        return {
            "type": "message_new",
            "message": {"from_id": peer_id, "peer_id": peer_id, "text": raw[5]},
        }

    def _handle_event(self, event: dict) -> None:
        """Обрабатывает событие: только message_new от владельца, фиксированная мапа."""
        if event.get("type") != "message_new":
            return
        message = event["message"]
        if int(message["from_id"]) != self._config.user_id:
            self._logger.info("VK-бот: сообщение от постороннего, игнорирую")
            return
        peer_id = int(message["peer_id"])
        text = message.get("text", "").strip().lower()
        self._logger.info(f"VK-бот: команда «{text}»")
        if text in ("старт", "start"):
            self._commands.start(lambda reply: self._send(peer_id, reply))
        elif text in ("статус", "status"):
            self._send(peer_id, self._commands.status())
        else:
            self._send(peer_id, self._commands.help())

    def _send(self, peer_id: int, text: str) -> None:
        """Отправляет ответ через messages.send и запоминает его ID.

        Запоминаем random_id (сгенерированный нами) и message_id (из
        ответа) — эхо этого сообщения вернётся событием MESSAGE_NEW, и
        декодер отсечёт его по одному из этих ID.
        """
        random_id = random.randint(1, 2_000_000_000)
        self._sent_ids.append(random_id)
        # messages.send возвращает в response сразу message_id (int)
        message_id = self._api(
            "messages.send",
            peer_id=peer_id,
            message=text,
            random_id=random_id,
        )
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
