"""Тесты main.py: штатное завершение по Ctrl+C, finally закрывает liker."""

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
