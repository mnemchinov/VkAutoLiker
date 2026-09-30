from unittest.mock import MagicMock, patch

from selenium.common.exceptions import WebDriverException

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

    def test_logged_in_network_error_retries_then_success(self, mock_config, mock_logger):
        """WebDriverException на первой попытке — ретрай, успех на второй."""
        browser = VKBrowser(mock_config, mock_logger)
        browser._driver = MagicMock()
        browser._driver.get.side_effect = [
            WebDriverException("No internet"),
            None,
        ]
        browser._driver.get_cookies.return_value = [
            {"name": "remixsid", "value": "session_hash"},
        ]
        with patch("vk_browser.time.sleep"):
            assert browser.is_logged_in() is True

    def test_logged_in_network_error_exhausts_retries(self, mock_config, mock_logger):
        """WebDriverException на всех 3 попытках — возвращает False."""
        browser = VKBrowser(mock_config, mock_logger)
        browser._driver = MagicMock()
        browser._driver.get.side_effect = WebDriverException("No internet")
        with patch("vk_browser.time.sleep"):
            assert browser.is_logged_in() is False
