"""Тесты main.py: Ctrl+C, status через Commands, bot без токена, finally закрывает liker."""

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
        """Команда bot без VK_BOT_TOKEN — exit(1), бот и сессия не создаются."""
        mock_config = MagicMock()
        mock_config.bot_token.get_secret_value.return_value = ""
        with (
            patch("main.get_settings", return_value=mock_config),
            patch("main.AppLogger"),
            patch("main.AutoLiker") as mock_liker_cls,
            patch("main.VkBot") as mock_bot_cls,
            patch.object(sys, "argv", ["main.py", "bot"]),
        ):
            with pytest.raises(SystemExit) as exc:
                main.main()

        assert exc.value.code == 1
        mock_bot_cls.assert_not_called()
        mock_liker_cls.assert_not_called()

    def test_bot_without_user_id_exits_1(self):
        """Команда bot с токеном, но без VK_USER_ID — exit(1), бот не создаётся."""
        mock_config = MagicMock()
        mock_config.bot_token.get_secret_value.return_value = "test-token"
        mock_config.user_id = 0
        with (
            patch("main.get_settings", return_value=mock_config),
            patch("main.AppLogger"),
            patch("main.AutoLiker") as mock_liker_cls,
            patch("main.VkBot") as mock_bot_cls,
            patch.object(sys, "argv", ["main.py", "bot"]),
        ):
            with pytest.raises(SystemExit) as exc:
                main.main()

        assert exc.value.code == 1
        mock_bot_cls.assert_not_called()
        mock_liker_cls.assert_not_called()
