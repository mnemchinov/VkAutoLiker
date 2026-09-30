from unittest.mock import MagicMock, patch

from vk_browser import VKBrowser


class TestVKBrowserIsLoggedIn:
    def test_logged_in_true_with_remixsid(self, mock_config, mock_logger):
        browser = VKBrowser(mock_config, mock_logger)
        browser._driver = MagicMock()
        browser._driver.get_cookies.return_value = [
            {"name": "other", "value": "abc"},
            {"name": "remixsid", "value": "some_session_hash"},
        ]
        assert browser.is_logged_in() is True

    def test_logged_in_false_without_remixsid(self, mock_config, mock_logger):
        browser = VKBrowser(mock_config, mock_logger)
        browser._driver = MagicMock()
        browser._driver.get_cookies.return_value = [
            {"name": "other", "value": "abc"},
            {"name": "remixlang", "value": "0"},
        ]
        assert browser.is_logged_in() is False

    def test_logged_in_false_empty_cookies(self, mock_config, mock_logger):
        browser = VKBrowser(mock_config, mock_logger)
        browser._driver = MagicMock()
        browser._driver.get_cookies.return_value = []
        assert browser.is_logged_in() is False

    def test_logged_in_false_remixsid_empty_value(self, mock_config, mock_logger):
        browser = VKBrowser(mock_config, mock_logger)
        browser._driver = MagicMock()
        browser._driver.get_cookies.return_value = [
            {"name": "remixsid", "value": ""},
        ]
        assert browser.is_logged_in() is False

    def test_logged_in_false_no_driver(self, mock_config, mock_logger):
        browser = VKBrowser(mock_config, mock_logger)
        browser._driver = None
        assert browser.is_logged_in() is False
