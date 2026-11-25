"""Page Object 基类。"""
from __future__ import annotations

from appium.webdriver.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

Locator = tuple[str, str]


class BasePage:
    def __init__(self, driver: WebDriver):
        self.driver = driver

    def find(self, locator: Locator, timeout: int = 10):
        """显式等待并返回单个元素。locator 形如 (AppiumBy.ACCESSIBILITY_ID, 'btn_login')。"""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located(locator)
        )

    def is_visible(self, locator: Locator, timeout: int = 5) -> bool:
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.visibility_of_element_located(locator)
            )
            return True
        except Exception:
            return False

    def wait_invisible(self, locator: Locator, timeout: int = 10) -> bool:
        """等待元素消失（用于判断离开某页面）。"""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.invisibility_of_element_located(locator)
            )
            return True
        except Exception:
            return False

    def tap(self, locator: Locator, timeout: int = 10) -> None:
        self.find(locator, timeout).click()

    def input(self, locator: Locator, text: str, timeout: int = 10) -> None:
        el = self.find(locator, timeout)
        el.clear()
        el.send_keys(text)
