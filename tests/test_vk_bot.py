"""Юнит-тесты VK-бота (VkBot): long polling, авторизация владельца, мапа команд.

Без сети: библиотека vk_api (VkLongPoll/VkApi) подменяется моками, события
`Event` собираются из компактных массивов — как их отдаёт VK.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from vk_api import VkApiError
from vk_api.longpoll import Event

from file_lock import FileLock
from vk_bot import VkBot


class TestVkBot:
    """Тесты транспорта VK-бота."""

    def _make_bot(self, mock_config, mock_logger, tmp_path):
        """Создаёт бота: клиент VkApi подменён моком, Commands — мок."""
        mock_config.db_path = str(tmp_path / "test_bot.db")
        with patch("vk_bot.vk_bot.VkApi"):
            bot = VkBot(mock_config, mock_logger)
        bot._commands = MagicMock()
        return bot

    def _message_new(self, text, user_id, message_id=13, random_id=1, extra=None, flags=1):
        """Компактное событие MESSAGE_NEW: id, flags, peer_id, ts, text, extra, attach, random_id."""
        return Event([4, message_id, flags, user_id, 0, text, extra or {}, [], random_id])

    def _message_event(self, user_id, peer_id, payload, event_id="ev-1"):
        """Компактное событие message_event (58): id, user_id, peer_id, ts, action, label, payload."""
        return Event([58, event_id, user_id, peer_id, 0, None, None, payload])

    def test_foreign_from_id_is_silence(self, mock_config, mock_logger, tmp_path):
        """Сообщение не от владельца: не отвечаем и не выполняем команды."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(self._message_new("статус", user_id=999999))
        mock_send.assert_not_called()
        bot._commands.start.assert_not_called()
        bot._commands.status.assert_not_called()

    def test_status_command_sends_status_text(self, mock_config, mock_logger, tmp_path):
        """«статус» от владельца — ответ текстом status() (регистр не важен)."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.status.return_value = "Статус: ОК"
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(self._message_new("Статус", user_id=mock_config.user_id))
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[0] == mock_config.user_id
        assert args[1] == "Статус: ОК"
        assert "keyboard" in mock_send.call_args[1]

    def test_start_command_calls_commands_start(self, mock_config, mock_logger, tmp_path):
        """«старт» от владельца — вызов Commands.start с колбэком; ответы несут клавиатуру."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(self._message_new("старт", user_id=mock_config.user_id))
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
        """/-префикс срезается: /старт, / старт, ///старт, /start → Commands.start."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send"):
            for text in ("/старт", "/ старт", "///старт", "/start"):
                bot._commands.start.reset_mock()
                bot._handle_event(self._message_new(text, user_id=mock_config.user_id))
                assert bot._commands.start.call_count == 1, text

    def test_command_without_slash_still_works(self, mock_config, mock_logger, tmp_path):
        """Команда без slash продолжает работать."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.status.return_value = "Статус: ОК"
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(self._message_new("статус", user_id=mock_config.user_id))
        assert mock_send.call_args[0][1] == "Статус: ОК"

    def test_unknown_command_sends_help(self, mock_config, mock_logger, tmp_path):
        """Неизвестный текст — список команд (help)."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.help.return_value = "Команды: старт, стоп, статус, помощь"
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(self._message_new("привет", user_id=mock_config.user_id))
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[0] == mock_config.user_id
        assert args[1] == "Команды: старт, стоп, статус, помощь"
        assert "keyboard" in mock_send.call_args[1]

    def test_non_message_event_ignored(self, mock_config, mock_logger, tmp_path):
        """Событие не MESSAGE_NEW (61 — «печатает») — без обработки."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(Event([61, mock_config.user_id, 1]))
        mock_send.assert_not_called()

    def test_button_payload_in_message_new_dispatches_command(
        self, mock_config, mock_logger, tmp_path
    ):
        """Нажатие inline-кнопки — MESSAGE_NEW с payload в extra; текст — метка кнопки."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        event = self._message_new(
            "ℹ️ Статус",
            user_id=mock_config.user_id,
            extra={"emoji": "1", "payload": '{"command":"status"}'},
        )
        with patch.object(bot, "_send"):
            bot._handle_event(event)
        bot._commands.status.assert_called_once()
        bot._commands.help.assert_not_called()

    def test_button_payload_takes_priority_over_label_text(
        self, mock_config, mock_logger, tmp_path
    ):
        """Payload приоритетнее текста: метка «Старт» + payload stop → stop."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.stop.return_value = "Запрошена остановка сессии"
        event = self._message_new(
            "▶️ Старт",
            user_id=mock_config.user_id,
            extra={"payload": '{"command":"stop"}'},
        )
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(event)
        bot._commands.stop.assert_called_once()
        bot._commands.start.assert_not_called()
        assert mock_send.call_args[0][1] == "Запрошена остановка сессии"

    def test_invalid_payload_falls_through_to_text(self, mock_config, mock_logger, tmp_path):
        """Битый payload — не падаем, исполняем текст сообщения как команду."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.status.return_value = "Статус: ОК"
        event = self._message_new(
            "статус", user_id=mock_config.user_id, extra={"payload": "{битый json"}
        )
        with patch.object(bot, "_send"):
            bot._handle_event(event)
        bot._commands.status.assert_called_once()

    def test_payload_without_command_falls_through_to_text(
        self, mock_config, mock_logger, tmp_path
    ):
        """Payload без поля command (чужой клиент) — текстовая ветка."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.status.return_value = "Статус: ОК"
        event = self._message_new(
            "статус", user_id=mock_config.user_id, extra={"payload": '{"other":1}'}
        )
        with patch.object(bot, "_send"):
            bot._handle_event(event)
        bot._commands.status.assert_called_once()

    def test_echo_cutoff_by_message_id(self, mock_config, mock_logger, tmp_path):
        """Эхо собственного ответа отсечено по message_id."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._sent_ids.append(777)
        event = self._message_new("статус", user_id=mock_config.user_id, message_id=777)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(event)
        mock_send.assert_not_called()
        bot._commands.status.assert_not_called()

    def test_echo_cutoff_by_random_id(self, mock_config, mock_logger, tmp_path):
        """Эхо собственного ответа отсечено по random_id."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._sent_ids.append(555)
        event = self._message_new("статус", user_id=mock_config.user_id, random_id=555)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(event)
        mock_send.assert_not_called()
        bot._commands.status.assert_not_called()

    def test_chat_peer_ignored(self, mock_config, mock_logger, tmp_path):
        """peer_id беседы (>= 2*10^9) — автор не владелец диалога, событие пропускается."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(self._message_new("статус", user_id=2_000_000_001))
        mock_send.assert_not_called()
        bot._commands.status.assert_not_called()

    def test_message_send_carries_inline_keyboard(self, mock_config, mock_logger, tmp_path):
        """Каждый messages.send несёт keyboard: валидный JSON, 3 кнопки, цвета, payload."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._vk.method.return_value = 55
        bot._send(mock_config.user_id, "text", keyboard=bot._keyboard())
        method, params = bot._vk.method.call_args[0]
        assert method == "messages.send"
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

    def test_send_records_message_and_random_id(self, mock_config, mock_logger, tmp_path):
        """_send запоминает random_id и message_id — для отсечения эха."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._vk.method.return_value = 77
        bot._send(mock_config.user_id, "текст", keyboard=bot._keyboard())
        params = bot._vk.method.call_args[0][1]
        assert params["random_id"] in bot._sent_ids
        assert 77 in bot._sent_ids

    def test_keyboard_payloads_resolve_in_command_map(self):
        """Каждый payload кнопки — известная команда (единый источник: _COMMAND_MAP)."""
        from vk_bot.vk_bot import _COMMAND_MAP, _KEYBOARD_JSON

        for button in json.loads(_KEYBOARD_JSON)["buttons"][0]:
            command = json.loads(button["action"]["payload"])["command"]
            assert _COMMAND_MAP[command] == command

    def test_payload_command_edge_cases(self, mock_config, mock_logger, tmp_path):
        """_payload_command: не-строка / пустая / не-dict JSON — None, без падения."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        assert bot._payload_command(None) is None
        assert bot._payload_command(123) is None
        assert bot._payload_command("") is None
        assert bot._payload_command("{битый") is None
        assert bot._payload_command("[1,2]") is None
        assert bot._payload_command('{"command":"stop"}') == "stop"

    def test_message_event_dispatches_payload_command(self, mock_config, mock_logger, tmp_path):
        """_handle_message_event: ack, затем payload {"command":"stop"} → Commands.stop."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.stop.return_value = "Запрошена остановка сессии"
        event = self._message_event(
            user_id=mock_config.user_id,
            peer_id=mock_config.user_id,
            payload='{"command":"stop"}',
            event_id="ev-2",
        )
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(event)
        bot._commands.stop.assert_called_once()
        # Ack — до обработки: event_id + user_id + peer_id (обязательные параметры VK)
        bot._vk.method.assert_called_once()
        assert bot._vk.method.call_args[0][0] == "messages.sendMessageEventAnswer"
        ack = bot._vk.method.call_args[0][1]
        assert ack["event_id"] == "ev-2"
        assert ack["user_id"] == mock_config.user_id
        assert ack["peer_id"] == mock_config.user_id
        args = mock_send.call_args[0]
        assert args[0] == mock_config.user_id
        assert args[1] == "Запрошена остановка сессии"
        assert "keyboard" in mock_send.call_args[1]

    def test_message_event_from_non_owner_is_ignored(self, mock_config, mock_logger, tmp_path):
        """58 от постороннего — команды не исполняются, но ack отправлен.

        Без ack VK бесконечно ределиверит событие: игнор без ответа превратил
        бы чужое нажатие в вечный поток.
        """
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        event = self._message_event(
            user_id=999999, peer_id=999999, payload='{"command":"stop"}', event_id="ev-4"
        )
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(event)
        mock_send.assert_not_called()
        bot._commands.stop.assert_not_called()
        bot._vk.method.assert_called_once()
        assert bot._vk.method.call_args[0][0] == "messages.sendMessageEventAnswer"
        assert bot._vk.method.call_args[0][1]["event_id"] == "ev-4"

    def test_message_event_empty_payload_is_noop(self, mock_config, mock_logger, tmp_path):
        """message_event без payload (None) — ack отправлен, команды не выполняются."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        event = self._message_event(
            user_id=mock_config.user_id,
            peer_id=mock_config.user_id,
            payload=None,
            event_id="ev-5",
        )
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(event)
        mock_send.assert_not_called()
        bot._vk.method.assert_called_once()
        bot._commands.stop.assert_not_called()
        bot._commands.status.assert_not_called()

    def test_message_event_invalid_payload_is_noop(self, mock_config, mock_logger, tmp_path):
        """message_event с битым payload — ack отправлен, no-op без падения."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        event = self._message_event(
            user_id=mock_config.user_id,
            peer_id=mock_config.user_id,
            payload="{битый",
            event_id="ev-6",
        )
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(event)
        mock_send.assert_not_called()
        bot._vk.method.assert_called_once()

    def test_message_event_malformed_raw_is_noop(self, mock_config, mock_logger, tmp_path):
        """58 с коротким raw (<8 полей) — ack собрать нечем, no-op без падения."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(Event([58, "ev-7", mock_config.user_id]))
        mock_send.assert_not_called()
        bot._vk.method.assert_not_called()

    def _bare_bot(self, mock_config, mock_logger, tmp_path):
        """Бот без мока Commands (для тестов run(), где команды не вызываются)."""
        mock_config.db_path = str(tmp_path / "test_bot.db")
        with patch("vk_bot.vk_bot.VkApi"):
            return VkBot(mock_config, mock_logger)

    def test_run_daemon_lock_busy_exits(self, mock_config, mock_logger, tmp_path):
        """Демон при занятой блокировке — выход без long polling."""
        bot = self._bare_bot(mock_config, mock_logger, tmp_path)
        with (
            patch("vk_bot.vk_bot._DAEMON_LOCK", tmp_path / "bot.lock"),
            patch("vk_bot.vk_bot.VkLongPoll") as mock_lp,
        ):
            lock = FileLock(tmp_path / "bot.lock")
            lock.acquire()
            try:
                bot.run()
            finally:
                lock.release()
        mock_lp.assert_not_called()

    def test_run_keyboard_interrupt_clean_exit(self, mock_config, mock_logger, tmp_path):
        """Ctrl+C в цикле — чистый выход, блокировка освобождается."""
        bot = self._bare_bot(mock_config, mock_logger, tmp_path)
        lp = MagicMock()
        lp.check.side_effect = KeyboardInterrupt
        with (
            patch("vk_bot.vk_bot._DAEMON_LOCK", tmp_path / "bot.lock"),
            patch("vk_bot.vk_bot.VkLongPoll", return_value=lp),
        ):
            bot.run()
        # Блокировка освобождена: повторный захват удаётся
        lock = FileLock(tmp_path / "bot.lock")
        assert lock.acquire()
        lock.release()

    def test_run_dispatches_events(self, mock_config, mock_logger, tmp_path):
        """События, полученные из check(), уходят в обработчик."""
        bot = self._bare_bot(mock_config, mock_logger, tmp_path)
        event = self._message_new("статус", user_id=mock_config.user_id)
        lp = MagicMock()
        lp.check.side_effect = [[event], KeyboardInterrupt]
        with (
            patch("vk_bot.vk_bot._DAEMON_LOCK", tmp_path / "bot.lock"),
            patch("vk_bot.vk_bot.VkLongPoll", return_value=lp),
            patch.object(bot, "_handle_event") as mock_handle,
        ):
            bot.run()
        mock_handle.assert_called_once_with(event)

    def test_run_recaptures_on_a_config(self, mock_config, mock_logger, tmp_path):
        """a_config (KeyError из check) — переподключение, не выход."""
        bot = self._bare_bot(mock_config, mock_logger, tmp_path)
        lp = MagicMock()
        lp.check.side_effect = [KeyError("updates"), KeyboardInterrupt]
        with (
            patch("vk_bot.vk_bot._DAEMON_LOCK", tmp_path / "bot.lock"),
            patch("vk_bot.vk_bot.VkLongPoll", return_value=lp) as mock_lp_cls,
        ):
            bot.run()
        assert mock_lp_cls.call_count == 2

    def test_run_recaptures_on_network_error(self, mock_config, mock_logger, tmp_path):
        """Сетевая ошибка в цикле — переподключение, не выход."""
        bot = self._bare_bot(mock_config, mock_logger, tmp_path)
        lp = MagicMock()
        lp.check.side_effect = [requests.RequestException("boom"), KeyboardInterrupt]
        with (
            patch("vk_bot.vk_bot._DAEMON_LOCK", tmp_path / "bot.lock"),
            patch("vk_bot.vk_bot.VkLongPoll", return_value=lp) as mock_lp_cls,
        ):
            bot.run()
        assert mock_lp_cls.call_count == 2

    def test_connect_retries_on_error(self, mock_config, mock_logger, tmp_path):
        """_connect: ошибка захвата канала — сон и повтор, резидент не умирает."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with (
            patch(
                "vk_bot.vk_bot.VkLongPoll",
                side_effect=[requests.RequestException("x"), MagicMock()],
            ),
            patch("vk_bot.vk_bot.time.sleep") as mock_sleep,
        ):
            bot._connect()
        mock_sleep.assert_called_once()
        assert bot._lp is not None

    def test_connect_exits_fatal_on_invalid_token(self, mock_config, mock_logger, tmp_path):
        """Недействительный токен (error 5) — фатально, без бесконечных ретраев."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        error = VkApiError("invalid token")
        error.code = 5
        with (
            patch("vk_bot.vk_bot.VkLongPoll", side_effect=error),
            patch("vk_bot.vk_bot.time.sleep") as mock_sleep,
        ):
            with pytest.raises(VkApiError):
                bot._connect()
        mock_sleep.assert_not_called()

    def test_run_exits_on_fatal_error(self, mock_config, mock_logger, tmp_path):
        """Фатальная ошибка захвата канала — чистый выход, блокировка освобождена."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        error = VkApiError("invalid token")
        error.code = 5
        with (
            patch("vk_bot.vk_bot._DAEMON_LOCK", tmp_path / "bot.lock"),
            patch("vk_bot.vk_bot.VkLongPoll", side_effect=error),
        ):
            bot.run()
        lock = FileLock(tmp_path / "bot.lock")
        assert lock.acquire()
        lock.release()

    def test_run_survives_event_error(self, mock_config, mock_logger, tmp_path):
        """Ошибка одного события (VkApiError) логируется, демон не падает."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        event = self._message_new("статус", user_id=mock_config.user_id)
        lp = MagicMock()
        lp.check.side_effect = [[event], KeyboardInterrupt]
        with (
            patch("vk_bot.vk_bot._DAEMON_LOCK", tmp_path / "bot.lock"),
            patch("vk_bot.vk_bot.VkLongPoll", return_value=lp),
            patch.object(
                bot, "_handle_event", side_effect=VkApiError("send failed")
            ) as mock_handle,
        ):
            bot.run()
        mock_handle.assert_called_once_with(event)
