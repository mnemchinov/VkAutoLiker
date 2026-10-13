"""Юнит-тесты Telegram-бота (TelegramBot): мапа команд, авторизация владельца, демон.

Без сети: клиент telebot.TeleBot подменяется моком, сообщения и callback-запросы
собираются моками — как их собирает библиотека.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests
from telebot.apihelper import ApiTelegramException

from file_lock import FileLock
from telegram_bot import TelegramBot


def _unauthorized_error() -> ApiTelegramException:
    """ApiTelegramException с кодом 401 (недействительный токен)."""
    return ApiTelegramException("getMe", None, {"error_code": 401, "description": "Unauthorized"})


class TestTelegramBot:
    """Тесты транспорта Telegram-бота."""

    def _make_bot(self, mock_config, mock_logger, tmp_path):
        """Создаёт бота: клиент TeleBot подменён моком, Commands — мок."""
        mock_config.db_path = str(tmp_path / "test_tgbot.db")
        with patch("telegram_bot.telegram_bot.telebot.TeleBot"):
            bot = TelegramBot(mock_config, mock_logger)
        bot._commands = MagicMock()
        return bot

    def _bare_bot(self, mock_config, mock_logger, tmp_path):
        """Бот без мока Commands (для тестов run(), где команды не вызываются)."""
        mock_config.db_path = str(tmp_path / "test_tgbot.db")
        with patch("telegram_bot.telegram_bot.telebot.TeleBot"):
            return TelegramBot(mock_config, mock_logger)

    def _message(self, text: str, user_id: int, chat_type: str = "private"):
        """Входящее сообщение: from_user.id, chat.type, chat.id, text."""
        message = MagicMock()
        message.from_user = MagicMock(id=user_id)
        message.chat = MagicMock(type=chat_type, id=user_id)
        message.text = text
        return message

    def _callback(self, user_id: int, data: str, with_message: bool = True):
        """Нажатие inline-кнопки: id, from_user.id, data, message.chat.id."""
        call = MagicMock()
        call.id = "cb-1"
        call.from_user = MagicMock(id=user_id)
        call.data = data
        call.message = MagicMock(chat=MagicMock(id=user_id)) if with_message else None
        return call

    def test_foreign_from_id_is_silence(self, mock_config, mock_logger, tmp_path):
        """Сообщение не от владельца: не отвечаем и не выполняем команды."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_message(self._message("статус", user_id=999999))
        mock_send.assert_not_called()
        bot._commands.start.assert_not_called()
        bot._commands.status.assert_not_called()

    def test_non_private_chat_ignored(self, mock_config, mock_logger, tmp_path):
        """Сообщение владельца из группы — игнорируется: бот — личный ассистент."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_message(
                self._message("статус", user_id=mock_config.telegram_owner_id, chat_type="group")
            )
        mock_send.assert_not_called()
        bot._commands.status.assert_not_called()

    def test_status_command_sends_status_text(self, mock_config, mock_logger, tmp_path):
        """«статус» от владельца — ответ текстом status() (регистр не важен)."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.status.return_value = "Статус: ОК"
        with patch.object(bot, "_send") as mock_send:
            bot._handle_message(self._message("Статус", user_id=mock_config.telegram_owner_id))
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[0] == mock_config.telegram_owner_id
        assert args[1] == "Статус: ОК"

    def test_start_command_calls_commands_start(self, mock_config, mock_logger, tmp_path):
        """«старт» от владельца — вызов Commands.start с колбэком; ответы несут клавиатуру."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_message(self._message("старт", user_id=mock_config.telegram_owner_id))
            assert bot._commands.start.call_count == 1
            send_callback = bot._commands.start.call_args[0][0]
            assert callable(send_callback)
            send_callback("тест-ответ")
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert args[0] == mock_config.telegram_owner_id
            assert args[1] == "тест-ответ"

    def test_slash_prefixed_command_dispatches(self, mock_config, mock_logger, tmp_path):
        """/-префикс срезается: /старт, / старт, ///старт, /start → Commands.start."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        with patch.object(bot, "_send"):
            for text in ("/старт", "/ старт", "///старт", "/start"):
                bot._commands.start.reset_mock()
                bot._handle_message(self._message(text, user_id=mock_config.telegram_owner_id))
                assert bot._commands.start.call_count == 1, text

    def test_command_without_slash_still_works(self, mock_config, mock_logger, tmp_path):
        """Команда без slash продолжает работать."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.status.return_value = "Статус: ОК"
        with patch.object(bot, "_send") as mock_send:
            bot._handle_message(self._message("статус", user_id=mock_config.telegram_owner_id))
        assert mock_send.call_args[0][1] == "Статус: ОК"

    def test_unknown_command_sends_help(self, mock_config, mock_logger, tmp_path):
        """Неизвестный текст — список команд (help)."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.help.return_value = "Команды: старт, стоп, статус, помощь"
        with patch.object(bot, "_send") as mock_send:
            bot._handle_message(self._message("привет", user_id=mock_config.telegram_owner_id))
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[0] == mock_config.telegram_owner_id
        assert args[1] == "Команды: старт, стоп, статус, помощь"

    def test_callback_dispatches_command(self, mock_config, mock_logger, tmp_path):
        """Нажатие inline-кнопки — callback_data (команда), не метка кнопки."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.stop.return_value = "Запрошена остановка сессии"
        call = self._callback(mock_config.telegram_owner_id, "stop")
        with patch.object(bot, "_send") as mock_send:
            bot._handle_callback(call)
        bot._commands.stop.assert_called_once()
        assert mock_send.call_args[0][1] == "Запрошена остановка сессии"

    def test_callback_ack_sent_with_call_id(self, mock_config, mock_logger, tmp_path):
        """answer_callback_query — с id запроса, «часики» на кнопке снимаются."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._commands.status.return_value = "Статус: ОК"
        call = self._callback(mock_config.telegram_owner_id, "status")
        with patch.object(bot, "_send"):
            bot._handle_callback(call)
        bot._bot.answer_callback_query.assert_called_once_with("cb-1")
        bot._commands.status.assert_called_once()

    def test_callback_from_non_owner_acked_but_not_executed(
        self, mock_config, mock_logger, tmp_path
    ):
        """Кнопка от постороннего — ack отправлен, команда не исполняется."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        call = self._callback(999999, "stop")
        with patch.object(bot, "_send") as mock_send:
            bot._handle_callback(call)
        bot._bot.answer_callback_query.assert_called_once_with("cb-1")
        mock_send.assert_not_called()
        bot._commands.stop.assert_not_called()

    def test_callback_without_message_is_noop(self, mock_config, mock_logger, tmp_path):
        """Callback без message (сообщение удалено) — ack отправлен, команды нет."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        call = self._callback(mock_config.telegram_owner_id, "status", with_message=False)
        with patch.object(bot, "_send") as mock_send:
            bot._handle_callback(call)
        bot._bot.answer_callback_query.assert_called_once_with("cb-1")
        mock_send.assert_not_called()
        bot._commands.status.assert_not_called()

    def test_send_carries_inline_keyboard(self, mock_config, mock_logger, tmp_path):
        """Каждый ответ несёт reply_markup: 3 кнопки, callback_data = команды."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._send(mock_config.telegram_owner_id, "текст")
        bot._bot.send_message.assert_called_once()
        args, kwargs = bot._bot.send_message.call_args
        assert args[0] == mock_config.telegram_owner_id
        assert args[1] == "текст"
        buttons = kwargs["reply_markup"].inline_keyboard[0]
        assert [b.callback_data for b in buttons] == ["start", "stop", "status"]
        labels = [b.text for b in buttons]
        assert labels[0].endswith("Старт") and labels[1].endswith("Стоп")

    def test_keyboard_payloads_resolve_in_command_map(self, mock_config, mock_logger, tmp_path):
        """Каждый callback_data кнопки — известная команда (единый источник: _COMMAND_MAP)."""
        from telegram_bot.telegram_bot import _COMMAND_MAP

        keyboard = self._make_bot(mock_config, mock_logger, tmp_path)._keyboard()
        for button in keyboard.inline_keyboard[0]:
            assert _COMMAND_MAP[button.callback_data] == button.callback_data

    def test_check_token_true_on_success(self, mock_config, mock_logger, tmp_path):
        """get_me прошёл — токен валиден."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        assert bot._check_token() is True

    def test_check_token_false_on_401(self, mock_config, mock_logger, tmp_path):
        """401 (недействительный токен) — False, без падения."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._bot.get_me.side_effect = _unauthorized_error()
        assert bot._check_token() is False

    def test_check_token_reraises_other_codes(self, mock_config, mock_logger, tmp_path):
        """Ошибки, не 401 (сеть/сервер) — пробрасываются: не «невалидный токен»."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        error = ApiTelegramException("getMe", None, {"error_code": 500, "description": "boom"})
        bot._bot.get_me.side_effect = error
        with pytest.raises(ApiTelegramException):
            bot._check_token()

    def test_check_token_retries_on_network_error(self, mock_config, mock_logger, tmp_path):
        """Сетевой сбой в get_me — рандомная задержка и повтор, резидент не умирает."""
        bot = self._make_bot(mock_config, mock_logger, tmp_path)
        bot._bot.get_me.side_effect = [requests.RequestException("boom"), None]
        with patch("telegram_bot.telegram_bot.sleep") as mock_sleep:
            assert bot._check_token() is True
        mock_sleep.assert_called_once()

    def test_run_exits_on_fatal_api_error(self, mock_config, mock_logger, tmp_path):
        """API-ошибка, не 401 — чистый выход, блокировка освобождена."""
        bot = self._bare_bot(mock_config, mock_logger, tmp_path)
        error = ApiTelegramException("getMe", None, {"error_code": 500, "description": "boom"})
        bot._bot.get_me.side_effect = error
        with patch("telegram_bot.telegram_bot._DAEMON_LOCK", tmp_path / "tgbot.lock"):
            bot.run()
        bot._bot.infinity_polling.assert_not_called()
        lock = FileLock(tmp_path / "tgbot.lock")
        assert lock.acquire()
        lock.release()

    def test_run_daemon_lock_busy_exits(self, mock_config, mock_logger, tmp_path):
        """Демон при занятой блокировке — выход без get_me и polling."""
        bot = self._bare_bot(mock_config, mock_logger, tmp_path)
        with patch("telegram_bot.telegram_bot._DAEMON_LOCK", tmp_path / "tgbot.lock"):
            lock = FileLock(tmp_path / "tgbot.lock")
            lock.acquire()
            try:
                bot.run()
            finally:
                lock.release()
        bot._bot.get_me.assert_not_called()
        bot._bot.infinity_polling.assert_not_called()

    def test_run_keyboard_interrupt_clean_exit(self, mock_config, mock_logger, tmp_path):
        """Ctrl+C в polling — чистый выход, блокировка освобождается."""
        bot = self._bare_bot(mock_config, mock_logger, tmp_path)
        bot._bot.infinity_polling.side_effect = KeyboardInterrupt
        with patch("telegram_bot.telegram_bot._DAEMON_LOCK", tmp_path / "tgbot.lock"):
            bot.run()
        lock = FileLock(tmp_path / "tgbot.lock")
        assert lock.acquire()
        lock.release()

    def test_run_exits_on_invalid_token(self, mock_config, mock_logger, tmp_path):
        """Недействительный токен (401) — чистый выход, polling не начинается."""
        bot = self._bare_bot(mock_config, mock_logger, tmp_path)
        bot._bot.get_me.side_effect = _unauthorized_error()
        with patch("telegram_bot.telegram_bot._DAEMON_LOCK", tmp_path / "tgbot.lock"):
            bot.run()
        bot._bot.infinity_polling.assert_not_called()
        lock = FileLock(tmp_path / "tgbot.lock")
        assert lock.acquire()
        lock.release()
