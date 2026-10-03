"""Пакет Selenium-слоя: управление Chrome и постановка лайков."""

from .browser_likes import BrowserLikesService, LikeResult
from .vk_browser import VKBrowser

__all__ = [
    "BrowserLikesService",
    "LikeResult",
    "VKBrowser",
]
