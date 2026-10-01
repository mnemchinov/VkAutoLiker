from unittest.mock import MagicMock

import pytest


@pytest.mark.browser
class TestBrowserLikesFixture:
    def test_find_like_button_in_post_container(self, http_fixture_server, mock_config, mock_logger):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By

        from browser_likes import BrowserLikesService

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")

        driver = webdriver.Chrome(options=options)
        try:
            browser = MagicMock()
            browser.driver = driver
            browser.navigate = MagicMock(side_effect=lambda url: driver.get(url))
            browser.wait_for = MagicMock(return_value=True)

            def find_elements(selector):
                return driver.find_elements(By.CSS_SELECTOR, selector)
            browser.find_elements = find_elements

            def click_element(el):
                try:
                    el.click()
                    return True
                except Exception:
                    return False
            browser.click_element = click_element

            svc = BrowserLikesService(browser, mock_config, mock_logger)

            driver.get(f"{http_fixture_server}/vk_post.html")
            import time
            time.sleep(0.5)

            element = svc._find_like_button(-123, 456)
            assert element is not None, "Like button not found in post container"

            aria = element.get_attribute("aria-label") or ""
            assert "Лайк" in aria, f"Unexpected aria-label: {aria}"

        finally:
            driver.quit()
