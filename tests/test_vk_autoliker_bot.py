"""Юнит-тесты команды бота (VkAutoLikerBot): long polling, авторизация, мапа команд.

Без сети: requests.get — патчи, Commands — мок.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from file_lock import FileLock
from vk_autoliker_bot import VkAutoLikerBot


class TestVkAutoLikerBot:
    """Тесты транспорта VK-бота."""

    def _make_bot(self, mock_config, mock_logger, tmp_path):
        """Создаёт бота с временной БД и подменёнными командами."""
        mock_config.db_path = str(tmp_path / "test_bot.db")
        bot = VkAutoLikerBot(mock_config, mock_logger)
        bot._commands = MagicMock()
        bot._server = "http://test-server"
        bot._ts = "1"
        bot._key = "test-key"
        return bot

    def _message_event(self, text, from_id, peer_id):
        """Событие message_new с заданным текстом и отправителем."""
        return {
            "type": "message_new",
            "message": {"from_id": from_id, "peer_id": peer_id, "text": text},
        }

    def test_foreign_from_id_is_silence(self, mock_config, mock_logger, tmp_path):
        """Сообщение не от владельца: не отвечаем и не выполняем команды."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(self._message_event("статус", 999999, 999999))
        mock_send.assert_not_called()
        bot._commands.start.assert_not_called()
        bot._commands.status.assert_not_called()

    def test_status_command_sends_status_text(self, mock_config, mock_logger, tmp_path):
        """«статус» от владельца — ответ текстом status() (регистр не важен)."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.status.return_value = "Статус: ОК"
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(
                self._message_event("Статус", mock_config.user_id, mock_config.user_id)
            )
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[0] == mock_config.user_id
        assert args[1] == "Статус: ОК"
        assert "keyboard" in mock_send.call_args[1]

    def test_start_command_calls_commands_start(self, mock_config, mock_logger, tmp_path):
        """«старт» от владельца — вызов Commands.start с callback'ом; ответы несут клавиатуру."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(
                self._message_event("старт", mock_config.user_id, mock_config.user_id)
            )
            assert bot._commands.start.call_count == 1
            send_callback = bot._commands.start.call_args[0][0]
            assert callable(send_callback)
            send_callback("тест-ответ")
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert args[0] == mock_config.user_id
            assert args[1] == "тест-ответ"
            assert "keyboard" in mock_send.call_args[1]

    def test_slash_prefixed_command_dispatches(self, mock_config, mock_logger, tmp_path):
        """/-префикс срезается: «/ старт» (со slash и пробелом) → Commands.start.

        VK-подсказки команд возвращают «/старт»; регистрация в настройках
        сообщества — за пользователем, парсер обязан принять любой вариант.
        """
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send"):
            for text in ("/старт", "/ старт", "///старт", "/start"):
                bot._commands.start.reset_mock()
                bot._handle_event(
                    self._message_event(text, mock_config.user_id, mock_config.user_id)
                )
                assert bot._commands.start.call_count == 1, text

    def test_command_without_slash_still_works(self, mock_config, mock_logger, tmp_path):
        """Команда без slash продолжает работать (назад-совместимо)."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.status.return_value = "Статус: ОК"
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(
                self._message_event("статус", mock_config.user_id, mock_config.user_id)
            )
        assert mock_send.call_args[0][1] == "Статус: ОК"

    def test_capture_server_raises_on_vk_error(self, mock_config, mock_logger, tmp_path):
        """Error-ответ VK на getLongPollServer (нет server/key) — RequestException.

        Резидентный демон должен ретраить с задержкой, а не падать с
        KeyError (не пойман ни в run(), ни в main.py).
        """
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_api", return_value={}):
            with pytest.raises(requests.RequestException):
                bot._capture_server()

    def test_unknown_command_sends_help(self, mock_config, mock_logger, tmp_path):
        """Неизвестный текст — список команд (help)."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.help.return_value = "Команды: старт, статус, помощь"
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(
                self._message_event("привет", mock_config.user_id, mock_config.user_id)
            )
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[0] == mock_config.user_id
        assert args[1] == "Команды: старт, статус, помощь"
        assert "keyboard" in mock_send.call_args[1]

    def test_non_message_event_ignored(self, mock_config, mock_logger, tmp_path):
        """События, не являющиеся message_new — без обработки."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event({"type": "message_reply", "message": {"text": "старт"}})
        mock_send.assert_not_called()

    def _compact_message_new(self, text, peer_id, flags=1, extra=None):
        """Компактное событие MESSAGE_NEW: позиционный массив VK.

        extra — словарь metadata (raw[6]): у нажатия inline-кнопки там
        payload JSON-строкой (live-форма 12.10).
        """
        return [4, 13, flags, peer_id, 1791743626, text, extra or {}, [], 1]

    def test_button_payload_in_message_new_dispatches_command(
        self, mock_config, mock_logger, tmp_path
    ):
        """Live-форма 12.10: нажатие кнопки — MESSAGE_NEW с payload в extra.

        Текст такого сообщения — метка кнопки («ℹ️ Статус»), не команда;
        исполняться должна команда из payload.
        """
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        raw = [
            4,
            182,
            1,
            mock_config.user_id,
            1791811397,
            "ℹ️ Статус",
            {"emoji": "1", "payload": '{"command":"status"}', "title": " ... "},
            {},
            -810034547,
        ]
        with (
            patch("vk_autoliker_bot.requests.get") as mock_get,
            patch.object(bot, "_send"),
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = {"ts": "9", "pts": "1", "updates": [raw]}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            bot._poll_once()
        bot._commands.status.assert_called_once()
        bot._commands.help.assert_not_called()

    def test_button_payload_takes_priority_over_label_text(
        self, mock_config, mock_logger, tmp_path
    ):
        """Payload приоритетнее текста: label «Старт» + payload stop → stop."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.stop.return_value = "Запрошена остановка сессии"
        event = {
            "type": "message_new",
            "message": {
                "from_id": mock_config.user_id,
                "peer_id": mock_config.user_id,
                "text": "▶️ Старт",
                "payload": '{"command":"stop"}',
            },
        }
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(event)
        bot._commands.stop.assert_called_once()
        bot._commands.start.assert_not_called()
        assert mock_send.call_args[0][1] == "Запрошена остановка сессии"

    def test_invalid_payload_falls_through_to_text(self, mock_config, mock_logger, tmp_path):
        """Битый payload — не падаем, исполняем текст сообщения как команду."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.status.return_value = "Статус: ОК"
        event = {
            "type": "message_new",
            "message": {
                "from_id": mock_config.user_id,
                "peer_id": mock_config.user_id,
                "text": "статус",
                "payload": "{битый json",
            },
        }
        with patch.object(bot, "_send"):
            bot._handle_event(event)
        bot._commands.status.assert_called_once()

    def test_payload_without_command_falls_through_to_text(
        self, mock_config, mock_logger, tmp_path
    ):
        """Payload без поля command (чужой клиент) — текстовая ветка."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.status.return_value = "Статус: ОК"
        event = {
            "type": "message_new",
            "message": {
                "from_id": mock_config.user_id,
                "peer_id": mock_config.user_id,
                "text": "статус",
                "payload": '{"other":1}',
            },
        }
        with patch.object(bot, "_send"):
            bot._handle_event(event)
        bot._commands.status.assert_called_once()

    def test_message_send_carries_inline_keyboard(self, mock_config, mock_logger, tmp_path):
        """Каждый messages.send несёт keyboard: валидный JSON, 3 кнопки, цвета, payload."""
        import json

        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_api", return_value=55) as mock_api:
            bot._send(mock_config.user_id, "text", keyboard=bot._keyboard())
        params = mock_api.call_args[1]
        assert params["peer_id"] == mock_config.user_id
        keyboard = json.loads(params["keyboard"])
        assert keyboard["inline"] is True
        buttons = keyboard["buttons"][0]
        assert len(buttons) == 3
        colors = [b["color"] for b in buttons]
        payloads = [json.loads(b["action"]["payload"])["command"] for b in buttons]
        assert colors == ["positive", "negative", "primary"]
        assert payloads == ["start", "stop", "status"]
        labels = [b["action"]["label"] for b in buttons]
        assert labels[0].endswith("Старт") and labels[1].endswith("Стоп")

    def test_decode_message_event_code_58(self, mock_config, mock_logger, tmp_path):
        """Compact-код 58 (callback-кнопка) → событие message_event с payload.

        Layout: [58, event_id, user_id, peer_id, ts, action, label, payload].
        Ветка сохранена на случай кнопок callback-типа (для них VK шлёт 58 и
        требует sendMessageEventAnswer); payload — JSON-строка команды.
        """
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        raw = [
            58,
            "ev-1",
            mock_config.user_id,
            mock_config.user_id,
            1791811397,
            "action",
            "ℹ️ Статус",
            '{"command":"status"}',
        ]
        events = bot._decode_events([raw])
        assert len(events) == 1
        event = events[0]
        assert event["type"] == "message_event"
        assert event["event_id"] == "ev-1"
        assert event["peer_id"] == mock_config.user_id
        assert event["payload"] == '{"command":"status"}'

    def test_message_event_dispatches_payload_command(self, mock_config, mock_logger, tmp_path):
        """_handle_message_event: ack, затем payload {"command":"stop"} → Commands.stop."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.stop.return_value = "Запрошена остановка сессии"
        event = {
            "type": "message_event",
            "event_id": "ev-2",
            "user_id": mock_config.user_id,
            "peer_id": mock_config.user_id,
            "payload": '{"command":"stop"}',
        }
        with (
            patch.object(bot, "_send") as mock_send,
            patch.object(bot, "_api", return_value=1) as mock_api,
        ):
            bot._handle_event(event)
        bot._commands.stop.assert_called_once()
        # Ack — до обработки: event_id + user_id + peer_id (обязательные параметры VK)
        mock_api.assert_called_once()
        assert mock_api.call_args[0][0] == "messages.sendMessageEventAnswer"
        ack = mock_api.call_args[1]
        assert ack["event_id"] == "ev-2"
        assert ack["user_id"] == mock_config.user_id
        assert ack["peer_id"] == mock_config.user_id
        args = mock_send.call_args[0]
        assert args[0] == mock_config.user_id
        assert args[1] == "Запрошена остановка сессии"
        assert "keyboard" in mock_send.call_args[1]

    def test_message_event_from_non_owner_is_ignored(self, mock_config, mock_logger, tmp_path):
        """58 от постороннего — команды не исполняются, но ack отправлен.

        Без ack VK бесконечно ределиверит event; игнор без ответа превратил
        бы чужое нажатие в вечный поток событий.
        """
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with (
            patch.object(bot, "_send") as mock_send,
            patch.object(bot, "_api", return_value=1) as mock_api,
        ):
            bot._handle_event(
                {
                    "type": "message_event",
                    "event_id": "ev-4",
                    "user_id": 999999,
                    "peer_id": 999999,
                    "payload": '{"command":"stop"}',
                }
            )
        mock_send.assert_not_called()
        bot._commands.stop.assert_not_called()
        mock_api.assert_called_once()
        assert mock_api.call_args[0][0] == "messages.sendMessageEventAnswer"
        assert mock_api.call_args[1]["event_id"] == "ev-4"

    def test_message_event_empty_payload_is_noop(self, mock_config, mock_logger, tmp_path):
        """message_event без payload (None) — ack отправлен, команды не выполняются."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with (
            patch.object(bot, "_send") as mock_send,
            patch.object(bot, "_api", return_value=1) as mock_api,
        ):
            bot._handle_event(
                {
                    "type": "message_event",
                    "event_id": "ev-5",
                    "user_id": mock_config.user_id,
                    "peer_id": mock_config.user_id,
                    "payload": None,
                }
            )
        mock_send.assert_not_called()
        mock_api.assert_called_once()
        bot._commands.stop.assert_not_called()
        bot._commands.status.assert_not_called()

    def test_message_event_invalid_payload_is_noop(self, mock_config, mock_logger, tmp_path):
        """message_event с битым payload — ack отправлен, no-op без падения."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with (
            patch.object(bot, "_send") as mock_send,
            patch.object(bot, "_api", return_value=1) as mock_api,
        ):
            bot._handle_event(
                {
                    "type": "message_event",
                    "event_id": "ev-6",
                    "user_id": mock_config.user_id,
                    "peer_id": mock_config.user_id,
                    "payload": "{битый",
                }
            )
        mock_send.assert_not_called()
        mock_api.assert_called_once()

    def test_decode_events_skips_malformed_raw(self, mock_config, mock_logger, tmp_path):
        """Не-список и короткие массивы декодеры игнорируют (ветки None)."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        assert bot._decode_message_new(None) is None
        assert bot._decode_message_new([4, 1, 1]) is None
        assert bot._decode_message_event(None) is None
        assert bot._decode_message_event([58, "ev", 1]) is None
        assert bot._decode_events([[61, mock_config.user_id, 1]]) == []

    def test_decode_message_new_drops_echo_by_random_id(self, mock_config, mock_logger, tmp_path):
        """Эхо отсечено по random_id (raw[8]), когда message_id не совпал.

        Наш ответ возвращается событием с нашим random_id на позиции 8 —
        декодер обязан выбросить его, даже если message_id (raw[1]) иной.
        """
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._sent_ids.append(4242)
        raw = [4, 999, 1, mock_config.user_id, 1791811397, "Статус: ОК", {}, [], 4242]
        assert bot._decode_message_new(raw) is None

    def test_poll_once_dispatches_updates(self, mock_config, mock_logger, tmp_path):
        """a_update — ts обновляется и каждое событие уходит в обработчик."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        payload = {
            "ts": "2",
            "pts": "1",
            "updates": [
                self._compact_message_new("статус", mock_config.user_id),
                self._compact_message_new("старт", mock_config.user_id),
            ],
        }
        with (
            patch("vk_autoliker_bot.requests.get") as mock_get,
            patch.object(bot, "_handle_event") as mock_handle,
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = payload
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            bot._poll_once()
        assert bot._ts == "2"
        assert mock_handle.call_count == 2
        first = mock_handle.call_args_list[0][0][0]
        assert first["type"] == "message_new"
        assert first["message"]["text"] == "статус"
        assert first["message"]["from_id"] == mock_config.user_id

    def test_poll_once_ignores_non_message_events(self, mock_config, mock_logger, tmp_path):
        """События не MESSAGE_NEW (например, 61 — «печатает») — без обработки."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        payload = {
            "ts": "3",
            "pts": "1",
            "updates": [[61, mock_config.user_id, 1]],
        }
        with (
            patch("vk_autoliker_bot.requests.get") as mock_get,
            patch.object(bot, "_handle_event") as mock_handle,
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = payload
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            bot._poll_once()
        mock_handle.assert_not_called()

    def test_poll_once_ignores_own_outgoing_echo(self, mock_config, mock_logger, tmp_path):
        """Собственный ответ возвращается событием — отсечён по отправленным ID.

        Эхо несёт тот же message_id, что вернул messages.send, и тот же
        random_id, что сгенерировал _send (flags у эха — те же, что у
        входящих, и не служат дискриминатором).
        """
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_api", return_value=77):
            bot._send(mock_config.user_id, "Статус: ОК")
        sent_random_id = bot._sent_ids[0]
        assert bot._sent_ids[1] == 77
        payload = {
            "ts": "5",
            "pts": "1",
            "updates": [
                [4, 77, 3, mock_config.user_id, 1791743626, "Статус: ОК", {}, [], sent_random_id]
            ],
        }
        with (
            patch("vk_autoliker_bot.requests.get") as mock_get,
            patch.object(bot, "_handle_event") as mock_handle,
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = payload
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            bot._poll_once()
        mock_handle.assert_not_called()

    def test_poll_once_accepts_owner_message_with_any_flags(
        self, mock_config, mock_logger, tmp_path
    ):
        """Инцидент 12.10: сообщение владельца пришло с flags=3 — обрабатывается.

        Старый фильтр flags==1 (против эха) молча выбрасывал его. Входящее
        чужое событие отличать от эха можно только по отправленным ID.
        """
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        payload = {
            "ts": "6",
            "pts": "1",
            "updates": [[4, 153, 3, mock_config.user_id, 1791795461, "статус", {}, [], -794099438]],
        }
        with (
            patch("vk_autoliker_bot.requests.get") as mock_get,
            patch.object(bot, "_handle_event") as mock_handle,
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = payload
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            bot._poll_once()
        mock_handle.assert_called_once()
        assert mock_handle.call_args[0][0]["message"]["text"] == "статус"

    def test_poll_once_ignores_chat_peer(self, mock_config, mock_logger, tmp_path):
        """peer_id беседы (>= 2*10^9) — автор не определён, событие пропускается."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        payload = {
            "ts": "4",
            "pts": "1",
            "updates": [self._compact_message_new("статус", 2_000_000_001)],
        }
        with (
            patch("vk_autoliker_bot.requests.get") as mock_get,
            patch.object(bot, "_handle_event") as mock_handle,
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = payload
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            bot._poll_once()
        mock_handle.assert_not_called()

    def test_poll_once_failed_updates_ts_or_recaptures(self, mock_config, mock_logger, tmp_path):
        """failed=1 — новый ts; failed=3 — повторный захват сервера."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with (
            patch("vk_autoliker_bot.requests.get") as mock_get,
            patch.object(bot, "_capture_server") as mock_capture,
        ):
            ts_response = MagicMock()
            ts_response.json.return_value = {"failed": 1, "ts": "7"}
            ts_response.raise_for_status.return_value = None
            failed3_response = MagicMock()
            failed3_response.json.return_value = {"failed": 3, "ts": "8"}
            failed3_response.raise_for_status.return_value = None
            mock_get.side_effect = [ts_response, failed3_response]
            bot._poll_once()
            bot._poll_once()
        assert bot._ts == "7"
        mock_capture.assert_called_once()

    def test_poll_once_a_config_recaptures_server(self, mock_config, mock_logger, tmp_path):
        """a_config — адрес сервера переполучается."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch("vk_autoliker_bot.requests.get") as mock_get:
            config_response = MagicMock()
            config_response.json.return_value = {"action": "a_config"}
            capture_response = MagicMock()
            capture_response.json.return_value = {
                "response": {
                    "server": "api.example.ru/gim123",
                    "key": "new-key",  # pragma: allowlist secret
                    "ts": "5",
                }
            }
            mock_get.side_effect = [config_response, capture_response]
            bot._poll_once()
        assert bot._server == "https://api.example.ru/gim123"
        assert bot._key == "new-key"

    def test_run_daemon_lock_busy_exits(self, mock_config, mock_logger, tmp_path):
        """Демон при занятой блокировке — выход без long polling."""
        mock_config.db_path = str(tmp_path / "test_bot.db")
        bot = VkAutoLikerBot(mock_config, mock_logger)
        with (
            patch("vk_autoliker_bot._DAEMON_LOCK", tmp_path / "bot.lock"),
            patch("vk_autoliker_bot.requests.get") as mock_get,
        ):
            lock = FileLock(tmp_path / "bot.lock")
            lock.acquire()
            try:
                bot.run()
            finally:
                lock.release()
        mock_get.assert_not_called()

    def test_run_keyboard_interrupt_clean_exit(self, mock_config, mock_logger, tmp_path):
        """Ctrl+C в цикле — чистый выход, блокировка освобождается."""
        mock_config.db_path = str(tmp_path / "test_bot.db")
        bot = VkAutoLikerBot(mock_config, mock_logger)
        with (
            patch("vk_autoliker_bot._DAEMON_LOCK", tmp_path / "bot.lock"),
            patch("vk_autoliker_bot.requests.get") as mock_get,
        ):
            capture_response = MagicMock()
            capture_response.json.return_value = {
                "response": {
                    "server": "http://test-server",
                    "key": "k",
                    "ts": "1",
                }
            }
            mock_get.side_effect = [capture_response, KeyboardInterrupt]
            bot.run()
        # Блокировка освобождена: повторный захват удаётся
        lock = FileLock(tmp_path / "bot.lock")
        assert lock.acquire()
        lock.release()
