"""Selenium Chrome с персистентным профилем для навигации и кликов по VK."""

import os
import random
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from config import AppConfig
from logger import AppLogger


class VKBrowser:
    """Обёртка над Selenium WebDriver с антидетект-настройками.

    Персистентный профиль (--user-data-dir) сохраняет сессию VK между запусками.
    Антидетект: скрытие navigator.webdriver, отключение AutomationControlled.
    Все задержки — random.uniform, фиксированных нет.
    """

    def __init__(self, config: AppConfig, logger: AppLogger):
        self._profile_path = config.browser.profile_path
        self._headless = config.browser.headless
        self._logger = logger
        self._driver: Optional[WebDriver] = None

    def _create_driver(self) -> WebDriver:
        """Создаёт Chrome driver с персистентным профилем и антидетект-настройками."""
        options = Options()

        profile_dir = Path(self._profile_path).resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir}")

        if self._headless:
            options.add_argument("--headless=new")

        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("detach", True)

        driver = webdriver.Chrome(options=options)
        # Скрываем navigator.webdriver — типичный признак Selenium-автоматизации
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            },
        )
        return driver

    @property
    def driver(self) -> WebDriver:
        if self._driver is None:
            raise RuntimeError("Браузер не запущен. Сначала вызовите start().")
        return self._driver

    def _kill_stale_chrome(self) -> None:
        """Завершает процессы Chrome, использующие этот профиль — иначе SessionNotCreatedException."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", self._profile_path],
                capture_output=True, text=True, timeout=5,
            )
            pids = [int(p) for p in result.stdout.split() if p.strip()]
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
            if pids:
                time.sleep(2)
                self._logger.info(f"Завершены процессы Chrome ({len(pids)}): {pids}")
        except Exception:
            pass

    def start(self) -> None:
        if self._driver is not None:
            return
        self._kill_stale_chrome()
        self._driver = self._create_driver()
        self._logger.info("Браузер запущен")

    def login(self) -> None:
        """Открывает vk.ru для ручного логина (включая 2FA) и ждёт подтверждения."""
        self.start()
        self.navigate("https://vk.ru")
        self._logger.info("Открыта страница входа. Войдите вручную (включая 2FA), затем нажмите Enter.")
        input()
        self._logger.info("Вход подтверждён пользователем")

    def navigate(self, url: str) -> None:
        """Переход по URL с рандомной задержкой (имитация человека)."""
        self.driver.get(url)
        self._random_sleep(2, 5)

    def wait_for(self, css_selector: str, timeout: int = 10) -> bool:
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
            )
            return True
        except Exception:
            return False

    def wait_for_clickable(self, css_selector: str, timeout: int = 10) -> bool:
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector))
            )
            return True
        except Exception:
            return False

    def find_elements(self, css_selector: str):
        return self.driver.find_elements(By.CSS_SELECTOR, css_selector)

    def find_element(self, css_selector: str):
        return self.driver.find_element(By.CSS_SELECTOR, css_selector)

    def click(self, css_selector: str) -> bool:
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
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            self._random_sleep(0.5, 1.5)
            element.click()
            return True
        except Exception as e:
            self._logger.debug(f"Клик не удался по элементу: {e}")
            return False

    def get_attribute(self, css_selector: str, attribute: str) -> Optional[str]:
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, css_selector)
            return el.get_attribute(attribute)
        except Exception:
            return None

    def get_page_source(self) -> str:
        return self.driver.page_source

    def current_url(self) -> str:
        return self.driver.current_url

    def scroll_down(self, pixels: int = 800) -> None:
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
                    time.sleep(60)
                else:
                    self._logger.error(f"Не удалось проверить авторизацию после {max_retries} попыток: {e}")
                    return False
        return False

    def close(self) -> None:
        if self._driver is not None:
            self._driver.quit()
            self._driver = None
            self._logger.info("Браузер закрыт")

    @staticmethod
    def _random_sleep(min_sec: float, max_sec: float) -> None:
        time.sleep(random.uniform(min_sec, max_sec))
