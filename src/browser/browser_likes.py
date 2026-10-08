"""Лайки постов через DOM-клики в Selenium (VK не поддерживает likes.add через API)."""

import random
import time
from enum import Enum
from typing import ClassVar

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.remote.webelement import WebElement

from logger import AppLogger
from post import build_post_url
from settings import Settings

from .vk_browser import VKBrowser


class LikeResult(Enum):
    """Результат попытки постановки лайка.

    LIKED — лайк подтверждён (aria-label сменился на «Убрать»);
    ALREADY_LIKED — пост уже лайкнут, клик не выполнялся;
    FAILED — кнопка не найдена, клик не удался, или проверка не прошла;
    CAPTCHA — VK показал капчу, стоп-сигнал для прерывания сессии.
    """

    LIKED = "liked"
    ALREADY_LIKED = "already_liked"
    FAILED = "failed"
    CAPTCHA = "captcha"


class BrowserLikesService:
    """Постановка лайков через клик по кнопке в браузере.

    VK — React SPA: на странице wall{owner_id}_{item_id} отображается не только
    целевой пост, но и лента с соседними постами, у каждого — своя кнопка лайка.
    Поэтому селектор ограничивается контейнером поста через data-post-id.

    aria-label кнопки меняется после клика:
      «Отправить реакцию «Лайк»» → «Убрать реакцию «Лайк»»
    После клика элемент нужно искать заново (React перерисовывает DOM).

    Антидетект: случайный скролл, движения мыши и паузы имитируют живое чтение,
    а не бот-паттерн «navigate → click → navigate». ActionChains генерирует
    реальные mousemove → mousedown → mouseup → click с координатами.
    """

    _CAPTCHA_SELECTORS: ClassVar[list[str]] = [
        '[class*="captcha"]',
        'input[name="captcha_sid"]',
        'img[src*="captcha"]',
    ]

    def __init__(self, browser: VKBrowser, config: Settings, logger: AppLogger):
        """Инициализирует сервис лайков с браузером и конфигурацией."""
        self._browser = browser
        self._config = config
        self._logger = logger

    def is_liked(self, owner_id: int, item_id: int) -> bool:
        """Проверяет, стоит ли лайк на посте, по aria-label кнопки внутри контейнера поста.

        Навигация на пост + проверка без клика. Основной цикл run() использует
        like(), который проверяет лайк внутри себя и не требует двойной навигации.
        """
        post_url = build_post_url(owner_id, item_id)
        self._browser.navigate(post_url)

        element = self._find_like_button(owner_id, item_id)
        if element is None:
            self._logger.warning(f"Кнопка лайка не найдена: {owner_id}_{item_id}")
            return False

        return self._check_liked(element)

    def like(self, owner_id: int, item_id: int) -> LikeResult:
        """Ставит лайк: навигация → «чтение» → клик → проверка.

        Возвращает LikeResult:
          LIKED — лайк подтверждён (aria-label сменился на «Убрать»);
          ALREADY_LIKED — пост уже лайкнут, клик не выполнялся;
          FAILED — кнопка не найдена, клик не удался, или проверка не прошла;
          CAPTCHA — VK показал капчу, нужен стоп-сигнал для прерывания сессии.

        Антидетект: между навигацией и кликом — случайный скролл и движения
        мыши (имитация живого чтения), не бот-паттерн «зашёл → кликнул → ушёл».
        """
        post_url = build_post_url(owner_id, item_id)
        self._logger.info(f"Переход на {post_url}")
        self._browser.navigate(post_url)

        if self._detect_captcha():
            self._logger.warning(f"Обнаружена капча: {owner_id}_{item_id}")
            return LikeResult.CAPTCHA

        delay = random.uniform(
            self._config.view_delay_min_sec,
            self._config.view_delay_max_sec,
        )

        self._simulate_human_behavior()

        self._logger.debug(f"«Чтение» поста {delay:.1f} сек перед лайком")
        time.sleep(delay)

        element = self._find_like_button(owner_id, item_id)
        if element is None:
            self._logger.warning(f"Кнопка лайка не найдена: {owner_id}_{item_id}")
            return LikeResult.FAILED

        if self._check_liked(element):
            self._logger.info(f"Уже лайкнут: {owner_id}_{item_id}")
            return LikeResult.ALREADY_LIKED

        clicked = self._browser.click_element(element)
        if not clicked:
            self._logger.warning(f"Клик не удался: {owner_id}_{item_id}")
            return LikeResult.FAILED

        time.sleep(random.uniform(1, 3))

        if random.random() < 0.15:
            self._browser.scroll_down(random.randint(200, 600))

        new_element = self._find_like_button(owner_id, item_id)
        if new_element is None:
            self._logger.warning(f"Кнопка лайка исчезла после клика: {owner_id}_{item_id}")
            return LikeResult.FAILED

        if self._check_liked(new_element):
            self._logger.info(f"Лайк поставлен: {owner_id}_{item_id}")
            return LikeResult.LIKED
        else:
            self._logger.warning(f"Проверка лайка не удалась: {owner_id}_{item_id}")
            return LikeResult.FAILED

    def _simulate_human_behavior(self) -> None:
        """Случайные действия, имитирующие живое чтение страницы.

        20% — лёгкий скролл вниз (осмотр поста);
        30% — случайное движение мыши (реакция на контент);
        10% — длинная пауза «вдумчивого чтения» (view_delay × 2).
        Каждое действие независимо — человек может и скроллить, и двигать мышью.
        """
        if random.random() < 0.20:
            self._browser.scroll_down(random.randint(100, 400))

        if random.random() < 0.30:
            try:
                driver = self._browser.driver
                ActionChains(driver).move_by_offset(
                    random.randint(-50, 50), random.randint(-30, 30)
                ).perform()
            except Exception as e:
                self._logger.debug(f"Имитация движения мыши не удалась: {e}")

        if random.random() < 0.10:
            extra = random.uniform(
                self._config.view_delay_min_sec,
                self._config.view_delay_max_sec,
            )
            time.sleep(extra)

    def _detect_captcha(self) -> bool:
        """Проверяет наличие капчи на странице после навигации.

        VK может показать капчу при подозрительной активности.
        Проверка по нескольким селекторам — классы, input, img.
        """
        for selector in self._CAPTCHA_SELECTORS:
            elements = self._browser.find_elements(selector)
            if elements:
                return True
        return False

    def _find_like_button(self, owner_id: int, item_id: int) -> WebElement | None:
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

    def _check_liked(self, element: WebElement) -> bool:
        """True, если aria-label содержит «Убрать» (пост уже лайкнут)."""
        aria = element.get_attribute("aria-label")
        if aria and "Убрать" in aria:
            return True

        class_attr = element.get_attribute("class") or ""
        if "active" in class_attr.lower() or "liked" in class_attr.lower():
            return True

        return False
