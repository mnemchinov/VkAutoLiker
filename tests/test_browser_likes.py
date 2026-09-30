from unittest.mock import MagicMock

from browser_likes import BrowserLikesService

LIKED_LABEL = "Убрать реакцию «Лайк»"
NOT_LIKED_LABEL = "Отправить реакцию «Лайк»"


class TestBrowserLikesMock:
    def test_is_liked_true_by_aria_label(self, mock_config, mock_logger, mock_driver):
        browser = MagicMock()
        browser.navigate = MagicMock()
        browser.wait_for = MagicMock(return_value=True)

        el = MagicMock()
        el.get_attribute = MagicMock(return_value=LIKED_LABEL)
        browser.find_elements = MagicMock(return_value=[el])

        svc = BrowserLikesService(browser, mock_config, mock_logger)
        assert svc.is_liked(-123, 456) is True

    def test_is_liked_false_by_aria_label(self, mock_config, mock_logger, mock_driver):
        browser = MagicMock()
        browser.navigate = MagicMock()
        browser.wait_for = MagicMock(return_value=True)

        el = MagicMock()
        el.get_attribute = MagicMock(return_value=NOT_LIKED_LABEL)
        browser.find_elements = MagicMock(return_value=[el])

        svc = BrowserLikesService(browser, mock_config, mock_logger)
        assert svc.is_liked(-123, 456) is False

    def test_is_liked_by_class_fallback(self, mock_config, mock_logger, mock_driver):
        browser = MagicMock()
        browser.navigate = MagicMock()
        browser.wait_for = MagicMock(return_value=True)

        el = MagicMock()
        # aria-label возвращает None → fallback на class
        el.get_attribute = MagicMock(side_effect=lambda attr: "active liked" if attr == "class" else None)
        browser.find_elements = MagicMock(return_value=[el])

        svc = BrowserLikesService(browser, mock_config, mock_logger)
        assert svc.is_liked(-123, 456) is True

    def test_is_liked_button_not_found(self, mock_config, mock_logger, mock_driver):
        browser = MagicMock()
        browser.navigate = MagicMock()
        browser.wait_for = MagicMock(return_value=False)

        svc = BrowserLikesService(browser, mock_config, mock_logger)
        assert svc.is_liked(-123, 456) is False

    def test_like_clicks_and_verifies(self, mock_config, mock_logger, mock_driver):
        browser = MagicMock()
        browser.navigate = MagicMock()
        browser.wait_for = MagicMock(return_value=True)
        browser.click_element = MagicMock(return_value=True)

        call_count = [0]
        def make_element():
            call_count[0] += 1
            el = MagicMock()
            aria = NOT_LIKED_LABEL if call_count[0] == 1 else LIKED_LABEL
            el.get_attribute = MagicMock(side_effect=lambda attr: aria if attr == "aria-label" else None)
            return el

        browser.find_elements = MagicMock(side_effect=lambda sel: [make_element()])

        svc = BrowserLikesService(browser, mock_config, mock_logger)
        result = svc.like(-123, 456)
        assert result is True
        assert browser.click_element.called

    def test_like_already_liked(self, mock_config, mock_logger, mock_driver):
        browser = MagicMock()
        browser.navigate = MagicMock()
        browser.wait_for = MagicMock(return_value=True)

        el = MagicMock()
        el.get_attribute = MagicMock(return_value=LIKED_LABEL)
        browser.find_elements = MagicMock(return_value=[el])

        svc = BrowserLikesService(browser, mock_config, mock_logger)
        result = svc.like(-123, 456)
        assert result is True
        assert not browser.click_element.called

    def test_like_click_fails(self, mock_config, mock_logger, mock_driver):
        browser = MagicMock()
        browser.navigate = MagicMock()
        browser.wait_for = MagicMock(return_value=True)
        browser.click_element = MagicMock(return_value=False)

        el = MagicMock()
        el.get_attribute = MagicMock(return_value=NOT_LIKED_LABEL)
        browser.find_elements = MagicMock(return_value=[el])

        svc = BrowserLikesService(browser, mock_config, mock_logger)
        result = svc.like(-123, 456)
        assert result is False

    def test_like_button_not_found(self, mock_config, mock_logger, mock_driver):
        browser = MagicMock()
        browser.navigate = MagicMock()
        browser.wait_for = MagicMock(return_value=False)

        svc = BrowserLikesService(browser, mock_config, mock_logger)
        result = svc.like(-123, 456)
        assert result is False
