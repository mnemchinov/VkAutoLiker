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
        mock_send.assert_called_once_with(mock_config.user_id, "Статус: ОК")

    def test_start_command_calls_commands_start(self, mock_config, mock_logger, tmp_path):
        """«старт» от владельца — вызов Commands.start с callback'ом."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event(
                self._message_event("старт", mock_config.user_id, mock_config.user_id)
            )
            assert bot._commands.start.call_count == 1
            send_callback = bot._commands.start.call_args[0][0]
            assert callable(send_callback)
            send_callback("тест-ответ")
            mock_send.assert_called_once_with(mock_config.user_id, "тест-ответ")

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
        mock_send.assert_called_once_with(mock_config.user_id, "Команды: старт, статус, помощь")

    def test_non_message_event_ignored(self, mock_config, mock_logger, tmp_path):
        """События, не являющиеся message_new — без обработки."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_event({"type": "message_reply", "message": {"text": "старт"}})
        mock_send.assert_not_called()

    def _compact_message_new(self, text, peer_id, flags=1):
        """Компактное событие MESSAGE_NEW: позиционный массив VK."""
        return [4, 13, flags, peer_id, 1791743626, text, {}, [], 1]

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
