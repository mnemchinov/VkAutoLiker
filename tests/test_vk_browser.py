import signal
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


class TestVKBrowserCleanup:
    """Windows-совместимость: размер профиля без du, stale Chrome без pgrep."""

    def test_cleanup_cache_removes_over_limit(self, mock_config, mock_logger, tmp_path):
        """Профиль больше лимита → кэш-каталоги удалены."""
        cache = tmp_path / "profile" / "Default" / "Cache"
        cache.mkdir(parents=True)
        (cache / "data.bin").write_bytes(b"x" * 1024)
        mock_config.profile_max_size_mb = 0

        browser = VKBrowser(mock_config, mock_logger)
        browser._profile_path = str(tmp_path / "profile")
        browser._cleanup_profile_cache()

        assert not cache.exists()

    def test_cleanup_cache_keeps_under_limit(self, mock_config, mock_logger, tmp_path):
        """Профиль меньше лимита → кэш не тронут."""
        cache = tmp_path / "profile" / "Default" / "Cache"
        cache.mkdir(parents=True)
        (cache / "data.bin").write_bytes(b"x" * 1024)
        mock_config.profile_max_size_mb = 1000

        browser = VKBrowser(mock_config, mock_logger)
        browser._profile_path = str(tmp_path / "profile")
        browser._cleanup_profile_cache()

        assert cache.exists()

    def test_cleanup_cache_missing_profile(self, mock_config, mock_logger, tmp_path):
        """Отсутствующий профиль → ранний выход без ошибок."""
        browser = VKBrowser(mock_config, mock_logger)
        browser._profile_path = str(tmp_path / "absent")

        browser._cleanup_profile_cache()

    def test_stale_chrome_pids_windows_uses_powershell(self, mock_config, mock_logger, tmp_path):
        """Windows-ветка ищет процессы через PowerShell и парсит PID."""
        fake_result = MagicMock()
        fake_result.stdout = "111\n222\n"
        browser = VKBrowser(mock_config, mock_logger)
        browser._profile_path = str(tmp_path / "profile")

        with (
            patch("browser.vk_browser.platform.system", return_value="Windows"),
            patch("browser.vk_browser.subprocess.run", return_value=fake_result) as mock_run,
        ):
            pids = browser._stale_chrome_pids()

        assert pids == [111, 222]
        assert mock_run.call_args[0][0][0] == "powershell"

    def test_kill_stale_chrome_kills_pids_and_removes_locks(
        self, mock_config, mock_logger, tmp_path
    ):
        """Найденные процессы завершаются, lock-файлы профиля удаляются."""
        profile = tmp_path / "profile"
        profile.mkdir()
        (profile / "SingletonLock").write_text("")
        browser = VKBrowser(mock_config, mock_logger)
        browser._profile_path = str(profile)

        with (
            patch.object(VKBrowser, "_stale_chrome_pids", return_value=[111]),
            patch("browser.vk_browser.os.kill") as mock_kill,
            patch("browser.vk_browser.time.sleep"),
        ):
            browser._kill_stale_chrome()

        mock_kill.assert_called_once_with(111, signal.SIGTERM)
        assert not (profile / "SingletonLock").exists()

    def test_detect_version_fallback_none(self, mock_config, mock_logger):
        """Реестр и chrome --version недоступны → None (UC без version_main)."""
        with (
            patch.object(VKBrowser, "_detect_chrome_version_windows", return_value=None),
            patch("browser.vk_browser.subprocess.run", side_effect=FileNotFoundError),
        ):
            assert VKBrowser._detect_chrome_version() is None
