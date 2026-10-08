"""Selenium Chrome с персистентным профилем для навигации и кликов по VK."""

import os
import platform
import random
import shutil
import signal
import subprocess
import time
from pathlib import Path

import undetected_chromedriver as uc
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from logger import AppLogger
from settings import Settings


class VKBrowser:
    """Обёртка над Selenium WebDriver с антидетект-настройками.

    Персистентный профиль (--user-data-dir) сохраняет сессию VK между запусками.
    Антидетект: скрытие navigator.webdriver, отключение AutomationControlled.
    Все задержки — random.uniform, фиксированных нет.
    """

    def __init__(self, config: Settings, logger: AppLogger):
        """Инициализирует браузер с путём профиля и режимом headless из конфигурации."""
        self._config = config
        self._profile_path = config.profile_path
        self._headless = config.headless
        self._logger = logger
        self._driver: WebDriver | None = None

    @staticmethod
    def _detect_chrome_version() -> int | None:
        """Определяет мажорную версию установленного Chrome через subprocess.

        UC без version_main скачивает последний ChromeDriver, который может
        не совпадать с установленным Chrome. Авто-детект предотвращает
        SessionNotCreatedException из-за несовпадения версий.
        """
        chrome_paths = {
            "Darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
            "Linux": [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium-browser",
            ],
            "Windows": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ],
        }
        candidates = chrome_paths.get(platform.system(), [])
        for chrome_path in candidates:
            try:
                result = subprocess.run(
                    [chrome_path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                version_str = result.stdout.strip().split()[-1]
                return int(version_str.split(".")[0])
            except (FileNotFoundError, subprocess.SubprocessError, ValueError, IndexError):
                continue
        return None

    def _create_driver(self, headless: bool | None = None) -> WebDriver:
        """Создаёт Chrome driver через undetected-chromedriver с персистентным профилем.

        undetected-chromedriver патчит: UA, navigator.webdriver, navigator.plugins,
        window.chrome, WebGL vendor/renderer, navigator.languages, navigator.permissions.
        Ручные антидетект-патчи не нужны — UC делает всё сам.
        version_main определяется авто-детектом, чтобы UC скачал совместимый ChromeDriver.
        Параметр headless позволяет перекрыть конфиг — login() форсирует False для 2FA.
        """
        effective_headless = headless if headless is not None else self._headless
        profile_dir = Path(self._profile_path).resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)

        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")

        version_main = self._detect_chrome_version()
        if version_main is not None:
            driver = uc.Chrome(
                options=options,
                user_data_dir=str(profile_dir),
                headless=effective_headless,
                version_main=version_main,
            )
        else:
            driver = uc.Chrome(
                options=options,
                user_data_dir=str(profile_dir),
                headless=effective_headless,
            )
        return driver

    @property
    def driver(self) -> WebDriver:
        """Возвращает экземпляр WebDriver (выбрасывает RuntimeError, если не запущен)."""
        if self._driver is None:
            raise RuntimeError("Браузер не запущен. Сначала вызовите start().")
        return self._driver

    def _kill_stale_chrome(self) -> None:
        """Завершает процессы Chrome и удаляет lock-файлы профиля — иначе SessionNotCreatedException."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", self._profile_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            pids = [int(p) for p in result.stdout.split() if p.strip()]
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
            if pids:
                time.sleep(random.uniform(1.5, 2.5))
                self._logger.info(f"Завершены процессы Chrome ({len(pids)}): {pids}")
        except Exception as e:
            self._logger.debug(f"Ошибка cleanup Chrome: {e}")

        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock = Path(self._profile_path) / name
            if lock.exists():
                try:
                    lock.unlink()
                except OSError:
                    pass

    def _cleanup_profile_cache(self) -> None:
        """Проверяет размер профиля Chrome и чистит кэш при превышении лимита.

        При размере профиля > profile_max_size_mb удаляет подкаталоги кэша:
        Cache, Code Cache, GPUCache, Service Worker/CacheStorage.
        Это предотвращает рост профиля до размеров, вызывающих SessionNotCreatedException.
        """
        profile = Path(self._profile_path)
        if not profile.is_dir():
            return

        try:
            result = subprocess.run(
                ["du", "-sk", str(profile)], capture_output=True, text=True, check=True
            )
            total_mb = int(result.stdout.split()[0]) / 1024
        except (subprocess.CalledProcessError, ValueError, IndexError):
            return

        if total_mb > self._config.profile_max_size_mb:
            self._logger.warning(
                f"Размер профиля Chrome: {total_mb:.0f} MB > {self._config.profile_max_size_mb} MB — чистка кэша"
            )
            cache_dirs = ["Cache", "Code Cache", "GPUCache", "Service Worker/CacheStorage"]
            for cache_name in cache_dirs:
                cache_path = profile / "Default" / cache_name
                if cache_path.is_dir():
                    try:
                        shutil.rmtree(cache_path)
                    except OSError as e:
                        self._logger.debug(f"Не удалось удалить {cache_name}: {e}")
            prefs = profile / "Default" / "Preferences"
            if prefs.is_file():
                try:
                    prefs_mb = prefs.stat().st_size / 1024 / 1024
                    if prefs_mb > 50:
                        self._logger.warning(
                            f"Preferences: {prefs_mb:.0f} MB > 50 MB — удаление (Chrome пересоздаст)"
                        )
                        prefs.unlink()
                except OSError as e:
                    self._logger.debug(f"Не удалось удалить Preferences: {e}")
            self._logger.info("Очистка кэша профиля Chrome завершена")

    def start(self, headless: bool | None = None) -> None:
        """Запускает Chrome: завершает stale-процессы, чистит кэш, создаёт driver.

        Параметр headless перекрывает конфиг — login() передаёт False для 2FA.
        """
        if self._driver is not None:
            return
        self._kill_stale_chrome()
        self._cleanup_profile_cache()
        self._driver = self._create_driver(headless=headless)
        self._logger.info("Браузер запущен")

    def login(self) -> None:
        """Открывает vk.ru для ручного логина (включая 2FA) и ждёт подтверждения.

        Форсирует headless=False — для 2FA нужен видимый экран.
        """
        self.start(headless=False)
        self.navigate("https://vk.ru")
        self._logger.info(
            "Открыта страница входа. Войдите вручную (включая 2FA), затем нажмите Enter."
        )
        input()
        self._logger.info("Вход подтверждён пользователем")

    def navigate(self, url: str) -> None:
        """Переход по URL с рандомной задержкой (имитация человека)."""
        self.driver.get(url)
        self._random_sleep(2, 5)

    def wait_for(self, css_selector: str, timeout: int = 10) -> bool:
        """Ожидает появления элемента по CSS-селектору. True, если появился."""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
            )
            return True
        except Exception:
            return False

    def wait_for_clickable(self, css_selector: str, timeout: int = 10) -> bool:
        """Ожидает кликабельности элемента по CSS-селектору."""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector))
            )
            return True
        except Exception:
            return False

    def find_elements(self, css_selector: str):
        """Возвращает список элементов по CSS-селектору."""
        return self.driver.find_elements(By.CSS_SELECTOR, css_selector)

    def find_element(self, css_selector: str):
        """Возвращает первый элемент по CSS-селектору."""
        return self.driver.find_element(By.CSS_SELECTOR, css_selector)

    def click(self, css_selector: str) -> bool:
        """Кликает по элементу по CSS-селектору с прокруткой. True, если успешно."""
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, css_selector)
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            self._random_sleep(0.5, 1.5)
            el.click()
            return True
        except Exception as e:
            self._logger.debug(f"Клик не удался по '{css_selector}': {e}")
            return False

    def click_element(self, element) -> bool:
        """Кликает по переданному элементу через ActionChains с движением мыши.

        ActionChains генерирует mousemove → mouseover → mousedown → mouseup → click
        с реальными координатами, в отличие от синтетического element.click().
        pause между move и click имитирует время реакции человека.
        """
        try:
            actions = ActionChains(self.driver)
            actions.move_to_element(element)
            actions.pause(random.uniform(0.2, 0.8))
            actions.click()
            actions.perform()
            return True
        except Exception as e:
            self._logger.debug(f"Клик не удался по элементу: {e}")
            return False

    def get_attribute(self, css_selector: str, attribute: str) -> str | None:
        """Возвращает значение атрибута элемента по CSS-селектору. None, если не найден."""
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, css_selector)
            return el.get_attribute(attribute)
        except Exception:
            return None

    def get_page_source(self) -> str:
        """Возвращает HTML-исходник текущей страницы."""
        return self.driver.page_source

    def current_url(self) -> str:
        """Возвращает URL текущей страницы."""
        return self.driver.current_url

    def scroll_down(self, pixels: int = 800) -> None:
        """Прокручивает страницу вниз на заданное число пикселей."""
        self.driver.execute_script(f"window.scrollBy(0, {pixels});")
        self._random_sleep(1, 3)

    def is_logged_in(self) -> bool:
        """Проверяет наличие remixsid cookie (признак активной сессии VK).

        Навигирует на vk.ru, чтобы cookie были доступны через get_cookies()
        (Selenium возвращает cookie только для текущего домена).

        При сетевой ошибке (Mac после сна — WiFi ещё не подключён) —
        ретрай до 3 раз с паузой 60 сек. Все неудачные — return False,
        чтобы run() штатно вышел, а не упал с WebDriverException.
        """
        if self._driver is None:
            return False

        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._driver.get("https://vk.ru")
                self._random_sleep(2, 4)
                cookies = self._driver.get_cookies()
                for cookie in cookies:
                    if cookie.get("name") == "remixsid" and cookie.get("value"):
                        return True
                return False
            except WebDriverException as e:
                if attempt < max_retries - 1:
                    self._logger.warning(
                        f"Сетевая ошибка при проверке авторизации (попытка {attempt + 1}/{max_retries}): {e}"
                    )
                    time.sleep(random.uniform(55, 65))
                else:
                    self._logger.error(
                        f"Не удалось проверить авторизацию после {max_retries} попыток: {e}"
                    )
        return False

    def close(self) -> None:
        """Закрывает браузер и освобождает драйвер, затем чистит кэш профиля.

        Очистка вызывается после quit(), чтобы Chrome освободил файлы кэша,
        и зеркалит поведение start() — профиль не растёт между запусками.
        """
        if self._driver is not None:
            self._driver.quit()
            self._driver = None
            self._logger.info("Браузер закрыт")
            self._cleanup_profile_cache()

    @staticmethod
    def _random_sleep(min_sec: float, max_sec: float) -> None:
        """Пауза на случайную величину в диапазоне [min_sec, max_sec]."""
        time.sleep(random.uniform(min_sec, max_sec))
