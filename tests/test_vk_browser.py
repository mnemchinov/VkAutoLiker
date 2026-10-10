from unittest.mock import MagicMock, patch

from selenium.common.exceptions import WebDriverException

from browser import VKBrowser


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
        with patch("browser.vk_browser.time.sleep"):
            assert browser.is_logged_in() is True

    def test_logged_in_network_error_exhausts_retries(self, mock_config, mock_logger):
        """WebDriverException на всех 3 попытках — возвращает False."""
        browser = VKBrowser(mock_config, mock_logger)
        browser._driver = MagicMock()
        browser._driver.get.side_effect = WebDriverException("No internet")
        with patch("browser.vk_browser.time.sleep"):
            assert browser.is_logged_in() is False

    def test_logged_in_logs_check_start(self, mock_config, mock_logger, caplog):
        """Старт проверки логируется: навигация на vk.ru может идти долго."""
        import logging

        browser = VKBrowser(mock_config, mock_logger)
        browser._driver = MagicMock()
        browser._driver.get_cookies.return_value = []
        with (
            patch("browser.vk_browser.time.sleep"),
            caplog.at_level(logging.INFO, logger="vk_autoliker"),
        ):
            assert browser.is_logged_in() is False
        assert "Проверка авторизации..." in caplog.text


class TestVKBrowserClose:
    def test_close_quits_driver_and_cleans_cache(self, mock_config, mock_logger):
        """close() завершает драйвер и чистит кэш профиля — как при старте."""
        browser = VKBrowser(mock_config, mock_logger)
        driver = MagicMock()
        browser._driver = driver

        with patch.object(browser, "_cleanup_profile_cache") as cleanup:
            browser.close()

        driver.quit.assert_called_once()
        cleanup.assert_called_once()
        assert browser._driver is None

    def test_close_without_driver_skips_cache_cleanup(self, mock_config, mock_logger):
        """close() без активного драйвера не чистит кэш и не падает."""
        browser = VKBrowser(mock_config, mock_logger)
        browser._driver = None

        with patch.object(browser, "_cleanup_profile_cache") as cleanup:
            browser.close()

        cleanup.assert_not_called()
