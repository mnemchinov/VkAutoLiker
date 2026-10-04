"""Пакет VK API-слоя: HTTP-клиент и сервис поиска постов."""

from .vk_api_client import CaptchaError, VKApiClient, VKApiError
from .vk_api_search_service import VkApiSearchService

__all__ = [
    "CaptchaError",
    "VKApiClient",
    "VKApiError",
    "VkApiSearchService",
]
