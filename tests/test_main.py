"""Тесты main.py: Ctrl+C, status через Commands, vkbot/tgbot без токена, finally закрывает liker."""

import sys
from unittest.mock import MagicMock, patch

import pytest

import main


class TestMain:
    def test_run_success_closes_liker(self):
        """Успешный run: main() закрывает liker в finally."""
        mock_liker = MagicMock()
        with (
            patch("main._acquire_lock"),
            patch("main.get_settings"),
            patch("main.AppLogger"),
            patch("main.AutoLiker", return_value=mock_liker),
            patch.object(sys, "argv", ["main.py", "run"]),
        ):
            main.main()

        mock_liker.close.assert_called_once_with()

    def test_keyboard_interrupt_exits_130_and_closes(self):
        """Ctrl+C на любом этапе: exit(130), liker закрывается."""
        mock_liker = MagicMock()
        mock_liker.run.side_effect = KeyboardInterrupt
        with (
            patch("main._acquire_lock"),
            patch("main.get_settings"),
            patch("main.AppLogger"),
            patch("main.AutoLiker", return_value=mock_liker),
            patch.object(sys, "argv", ["main.py", "run"]),
        ):
            with pytest.raises(SystemExit) as exc:
                main.main()

        assert exc.value.code == 130
        mock_liker.close.assert_called_once_with()

    def test_status_prints_commands_status(self, capsys):
        """Команда status — текст берётся из Commands, не из AutoLiker."""
        mock_liker = MagicMock()
        mock_commands = MagicMock(status=MagicMock(return_value="Статус: ОК"))
        with (
            patch("main._acquire_lock"),
            patch("main.get_settings"),
            patch("main.AppLogger"),
            patch("main.AutoLiker", return_value=mock_liker),
            patch("main.Commands", return_value=mock_commands),
            patch.object(sys, "argv", ["main.py", "status"]),
        ):
            main.main()

        mock_commands.status.assert_called_once_with()
        mock_liker.status.assert_not_called()
        assert "Статус: ОК" in capsys.readouterr().out

    def test_bot_without_token_exits_1(self):
        """Команда vkbot без VK_BOT_TOKEN — exit(1), бот и сессия не создаются."""
        mock_config = MagicMock()
        mock_config.bot_token.get_secret_value.return_value = ""
        with (
            patch("main.get_settings", return_value=mock_config),
            patch("main.AppLogger"),
            patch("main.AutoLiker") as mock_liker_cls,
            patch("main.VkBot") as mock_bot_cls,
            patch.object(sys, "argv", ["main.py", "vkbot"]),
        ):
            with pytest.raises(SystemExit) as exc:
                main.main()

        assert exc.value.code == 1
        mock_bot_cls.assert_not_called()
        mock_liker_cls.assert_not_called()

    def test_bot_without_user_id_exits_1(self):
        """Команда vkbot с токеном, но без VK_USER_ID — exit(1), бот не создаётся."""
        mock_config = MagicMock()
        mock_config.bot_token.get_secret_value.return_value = "test-token"
        mock_config.user_id = 0
        with (
            patch("main.get_settings", return_value=mock_config),
            patch("main.AppLogger"),
            patch("main.AutoLiker") as mock_liker_cls,
            patch("main.VkBot") as mock_bot_cls,
            patch.object(sys, "argv", ["main.py", "vkbot"]),
        ):
            with pytest.raises(SystemExit) as exc:
                main.main()

        assert exc.value.code == 1
        mock_bot_cls.assert_not_called()
        mock_liker_cls.assert_not_called()


class TestMainTgBot:
    """Тесты ветки tgbot: неполная конфигурация и запуск демона."""

    def test_tgbot_without_token_exits_1(self):
        """Команда tgbot без VK_TELEGRAM_BOT_TOKEN — exit(1), бот не создаётся."""
        mock_config = MagicMock()
        mock_config.telegram_bot_token.get_secret_value.return_value = ""
        with (
            patch("main.get_settings", return_value=mock_config),
            patch("main.AppLogger"),
            patch("main.AutoLiker") as mock_liker_cls,
            patch("main.TelegramBot") as mock_bot_cls,
            patch.object(sys, "argv", ["main.py", "tgbot"]),
        ):
            with pytest.raises(SystemExit) as exc:
                main.main()

        assert exc.value.code == 1
        mock_bot_cls.assert_not_called()
        mock_liker_cls.assert_not_called()

    def test_tgbot_without_owner_id_exits_1(self):
        """Команда tgbot с токеном, но без VK_TELEGRAM_OWNER_ID — exit(1)."""
        mock_config = MagicMock()
        mock_config.telegram_bot_token.get_secret_value.return_value = "test-tg-token"
        mock_config.telegram_owner_id = 0
        with (
            patch("main.get_settings", return_value=mock_config),
            patch("main.AppLogger"),
            patch("main.AutoLiker") as mock_liker_cls,
            patch("main.TelegramBot") as mock_bot_cls,
            patch.object(sys, "argv", ["main.py", "tgbot"]),
        ):
            with pytest.raises(SystemExit) as exc:
                main.main()

        assert exc.value.code == 1
        mock_bot_cls.assert_not_called()
        mock_liker_cls.assert_not_called()

    def test_tgbot_runs_telegram_bot(self):
        """Команда tgbot с полной конфигурацией запускает TelegramBot.run()."""
        mock_config = MagicMock()
        mock_config.telegram_bot_token.get_secret_value.return_value = "test-tg-token"
        mock_config.telegram_owner_id = 123
        with (
            patch("main.get_settings", return_value=mock_config),
            patch("main.AppLogger") as mock_logger_cls,
            patch("main.TelegramBot") as mock_bot_cls,
            patch.object(sys, "argv", ["main.py", "tgbot"]),
        ):
            main.main()

        args, _ = mock_bot_cls.call_args
        mock_bot_cls.assert_called_once()
        assert args[0] is mock_config
        assert args[1] is mock_logger_cls.return_value
        mock_bot_cls.return_value.run.assert_called_once_with()
