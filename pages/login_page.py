"""登录页（src/app/login.tsx）。

定位符来自登录页已埋好的 accessibilityLabel（无需新增埋点）：
  - 用户名输入框  accessibilityLabel="用户名"
  - 密码输入框    accessibilityLabel="密码"
  - 登录按钮      accessibilityLabel="登录"（accessibilityRole=button）
  - 记住密码      accessibilityLabel="记住密码"
  - 服务器切换    chip label（serverProfileCopy.ts）：新服务器="新服务器（118.196）"
                 选中时追加「（当前）」

两个真实约束（来自源码）：
  1. 登录页顶部有服务器切换（ServerSwitch），默认 legacy（旧服务器），而主站账号
     （如 pss2）只能登新服务器；登录前必须先切到「新服务器」，否则必失败。
  2. 登录有防暴力锁定：连续 5 次失败锁 15 分钟（MAX_ATTEMPTS=5）。
"""
from __future__ import annotations

import time

from appium.webdriver.common.appiumby import AppiumBy

from pages.base_page import BasePage


class LoginPage(BasePage):
    USERNAME = (AppiumBy.ACCESSIBILITY_ID, "用户名")
    PASSWORD = (AppiumBy.ACCESSIBILITY_ID, "密码")
    SUBMIT = (AppiumBy.ACCESSIBILITY_ID, "登录")
    REMEMBER = (AppiumBy.ACCESSIBILITY_ID, "记住密码")
    # 新服务器 chip：label 含「新服务器」，选中时追加「（当前）」，故用 contains 匹配；
    # Android 暴露为 content-desc，iOS 暴露为 label，两者都写上跨端通用。
    SERVER_NEW = (
        AppiumBy.XPATH,
        '//*[contains(@content-desc, "新服务器") or contains(@label, "新服务器")]',
    )

    def ensure_new_server(self) -> bool:
        """登录前切到「新服务器（118.196）」。

        只在登录页上有意义：不在登录页（已登录/已跳转）时直接返回 False，
        不等待、不抛异常 —— 调用方常在没有前置判断的情况下顺手调用。
        ServerSwitch 默认 legacy；当前已是新服务器时点击会被内部 no-op。
        """
        if not self.is_visible(self.USERNAME, timeout=2):
            return False
        try:
            self.find(self.SERVER_NEW, timeout=10).click()
        except Exception:  # noqa: BLE001 - 找不到服务器选项不阻塞登录
            return False
        time.sleep(1)
        return True

    def login(self, username: str, password: str) -> None:
        self.input(self.USERNAME, username)
        self.input(self.PASSWORD, password)
        self.tap(self.SUBMIT)

    def is_logged_in(self, timeout: int = 10) -> bool:
        """登录按钮消失 = 已离开登录页。

        落地页可能是 /consent、/permissions 或 /home（取决于账号 onboarding 状态），
        所以用「离开登录页」作为唯一稳定的登录成功信号，而不是断言某个具体页面。
        """
        return self.wait_invisible(self.SUBMIT, timeout)
