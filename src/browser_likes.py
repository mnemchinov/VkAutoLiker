"""Лайки постов через DOM-клики в Selenium (VK не поддерживает likes.add через API)."""

import random
import time
from typing import Optional

from config import AppConfig
from logger import AppLogger
from vk_browser import VKBrowser


class BrowserLikesService:
    """Постановка лайков через клик по кнопке в браузере.

    VK — React SPA: на странице wall{owner_id}_{item_id} отображается не только
    целевой пост, но и лента с соседними постами, у каждого — своя кнопка лайка.
    Поэтому селектор ограничивается контейнером поста через data-post-id.

    aria-label кнопки меняется после клика:
      «Отправить реакцию «Лайк»» → «Убрать реакцию «Лайк»»
    После клика элемент нужно искать заново (React перерисовывает DOM).
    """

    def __init__(self, browser: VKBrowser, config: AppConfig, logger: AppLogger):
        self._browser = browser
        self._config = config
        self._logger = logger

    def is_liked(self, owner_id: int, item_id: int) -> bool:
        """Проверяет, стоит ли лайк на посте, по aria-label кнопки внутри контейнера поста."""
        post_url = f"https://vk.ru/wall{owner_id}_{item_id}"
        self._browser.navigate(post_url)

        element = self._find_like_button(owner_id, item_id)
        if element is None:
            self._logger.warning(f"Кнопка лайка не найдена: {owner_id}_{item_id}")
            return False

        return self._check_liked(element)

    def like(self, owner_id: int, item_id: int) -> bool:
        """Ставит лайк: навигация → пауза «чтения» → клик → проверка.

        Возвращает True, если лайк подтвердился (aria-label сменился на «Убрать»).
        """
        post_url = f"https://vk.ru/wall{owner_id}_{item_id}"
        self._logger.info(f"Переход на {post_url}")
        self._browser.navigate(post_url)

        delay = random.uniform(
            self._config.limits.view_delay_min_sec,
            self._config.limits.view_delay_max_sec,
        )
        self._logger.debug(f"«Чтение» поста {delay:.1f} сек перед лайком")
        time.sleep(delay)

        element = self._find_like_button(owner_id, item_id)
        if element is None:
            self._logger.warning(f"Кнопка лайка не найдена: {owner_id}_{item_id}")
            return False

        if self._check_liked(element):
            self._logger.info(f"Уже лайкнут: {owner_id}_{item_id}")
            return True

        clicked = self._browser.click_element(element)
        if not clicked:
            self._logger.warning(f"Клик не удался: {owner_id}_{item_id}")
            return False

        time.sleep(random.uniform(1, 3))

        # После клика React перерисовывает кнопку — ищем заново в том же контейнере
        new_element = self._find_like_button(owner_id, item_id)
        if new_element is None:
            self._logger.warning(f"Кнопка лайка исчезла после клика: {owner_id}_{item_id}")
            return False

        if self._check_liked(new_element):
            self._logger.info(f"Лайк поставлен: {owner_id}_{item_id}")
            return True
        else:
            self._logger.warning(f"Проверка лайка не удалась: {owner_id}_{item_id}")
            return False

    def _find_like_button(self, owner_id: int, item_id: int):
        """Находит кнопку лайка внутри контейнера конкретного поста.

        VK рендерит каждый пост в контейнер с data-post-id="{owner_id}_{item_id}".
        Селектор ограничен этим контейнером, чтобы не матчить кнопки соседних постов.
        CSS-селектор [aria-label*="Лайк"] уже фильтрует по содержимому aria-label.
        """
        selector = f'[data-post-id="{owner_id}_{item_id}"] [aria-label*="Лайк"]'
        if not self._browser.wait_for(selector, timeout=5):
            return None
        elements = self._browser.find_elements(selector)
        if elements:
            return elements[0]
        return None

    def _check_liked(self, element) -> bool:
        """True, если aria-label содержит «Убрать» (пост уже лайкнут)."""
        aria = element.get_attribute("aria-label")
        if aria and "Убрать" in aria:
            return True

        # Fallback: проверка по class (на случай изменения aria-label в будущем)
        class_attr = element.get_attribute("class") or ""
        if "active" in class_attr.lower() or "liked" in class_attr.lower():
            return True

        return False
