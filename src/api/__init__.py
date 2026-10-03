"""Пакет VK API-слоя: HTTP-клиент и сервис поиска постов."""

from .api_search import ApiSearchService
from .vk_api_client import CaptchaError, VKApiClient, VKApiError

__all__ = [
    "ApiSearchService",
    "CaptchaError",
    "VKApiClient",
    "VKApiError",
]
