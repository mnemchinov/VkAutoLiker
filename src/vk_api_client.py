"""HTTP-клиент к VK API с rate-лимитом и обработкой ошибок."""

import time

import requests

from config import AppConfig
from logger import AppLogger


class VKApiError(Exception):
    """Ошибка VK API с кодом и сообщением."""

    def __init__(self, code: int, message: str):
        """Создаёт ошибку с кодом VK API и сообщением."""
        self.code = code
        self.message = message
        super().__init__(f"VK API error {code}: {message}")


class CaptchaError(VKApiError):
    """VK API требует капчу (error_code 14). Останавливает сессию."""

    def __init__(self, message: str):
        """Создаёт CaptchaError с code=14."""
        super().__init__(14, message)


class VKApiClient:
    """Клиент VK API с service-токеном.

    Rate-лимит ~3 req/sec (0.34s между вызовами).
    При error 6 (too many requests) — ретрай в цикле (max 3), задержка 1с.
    При error 14 (captcha) — выбрасывает CaptchaError.
    При сетевой ошибке (ConnectionError/Timeout) — ретрай max 3, задержка 5с.
    """

    _MAX_ERROR6_RETRIES = 3
    _MAX_NETWORK_RETRIES = 3
    _NETWORK_RETRY_DELAY = 5.0

    def __init__(self, config: AppConfig, logger: AppLogger):
        """Инициализирует клиент с service-токеном и параметрами rate-лимита."""
        self._token = config.api.service_token.get_secret_value()
        self._api_version = config.api.api_version
        self._base_url = config.api.base_url
        self._logger = logger
        self._last_call_time: float = 0.0
        self._min_interval: float = 0.34  # ~3 req/sec

    def call(self, method: str, params: dict | None = None) -> dict:
        """Вызывает VK API метод и возвращает поле 'response' из ответа.

        При error 6 — ретрай в цикле (не рекурсия), max 3 попытки.
        При сетевой ошибке — ретрай max 3 с задержкой 5с.
        """
        if params is None:
            params = {}

        request_params = dict(params)
        request_params["access_token"] = self._token
        request_params["v"] = self._api_version

        url = f"{self._base_url}/{method}"

        error6_retries = 0
        network_retries = 0

        while True:
            self._rate_limit()

            try:
                response = requests.get(url, params=request_params, timeout=30)
            except requests.exceptions.RequestException as e:
                network_retries += 1
                if network_retries < self._MAX_NETWORK_RETRIES:
                    self._logger.warning(
                        f"Сетевая ошибка (попытка {network_retries}/{self._MAX_NETWORK_RETRIES}): {e}"
                    )
                    time.sleep(self._NETWORK_RETRY_DELAY)
                    continue
                raise VKApiError(0, f"Сетевая ошибка после {self._MAX_NETWORK_RETRIES} попыток: {e}")

            try:
                data = response.json()
            except (ValueError, requests.exceptions.JSONDecodeError) as e:
                network_retries += 1
                if network_retries < self._MAX_NETWORK_RETRIES:
                    self._logger.warning(
                        f"Не-JSON ответ (попытка {network_retries}/{self._MAX_NETWORK_RETRIES}): {e}"
                    )
                    time.sleep(self._NETWORK_RETRY_DELAY)
                    continue
                raise VKApiError(0, f"Не-JSON ответ после {self._MAX_NETWORK_RETRIES} попыток: {e}")

            if "error" in data:
                error = data["error"]
                code = error.get("error_code", 0)
                msg = error.get("error_msg", "Unknown error")

                if code == 6:
                    error6_retries += 1
                    if error6_retries < self._MAX_ERROR6_RETRIES:
                        self._logger.warning(
                            f"Превышен лимит запросов, повтор через 1 сек "
                            f"(попытка {error6_retries}/{self._MAX_ERROR6_RETRIES}): {msg}"
                        )
                        time.sleep(1)
                        continue
                    raise VKApiError(code, f"Превышен лимит запросов после {self._MAX_ERROR6_RETRIES} попыток: {msg}")
                elif code == 14:
                    raise CaptchaError(f"Требуется капча: {msg}")
                else:
                    raise VKApiError(code, msg)

            return data.get("response", {})

    def _rate_limit(self) -> None:
        """Гарантирует минимальный интервал между вызовами API."""
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()
