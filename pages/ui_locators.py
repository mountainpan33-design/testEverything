"""Appium 定位符清单（自动生成，请勿手改）。

来源：src/ 下各组件的 accessibilityLabel。
重新生成：cd app-automation/vision && npx tsx src/cli.ts --gen-pages --write
检查是否过期：npx tsx src/cli.ts --gen-pages   （有差异时退出码 1）

为什么自动生成：label 改了，手抄的常量就断。定位符由源码唯一决定，交给机器抄。
"""

from appium.webdriver.common.appiumby import AppiumBy

# 来源：src/TrimTimeline.tsx
TRIMTIMELINE = {
    "起点手柄": (AppiumBy.ACCESSIBILITY_ID, "起点手柄"),
    "终点手柄": (AppiumBy.ACCESSIBILITY_ID, "终点手柄"),
}

# 来源：src/app/(tabs)/me.tsx
APP_TABS_ME = {
    "中文": (AppiumBy.ACCESSIBILITY_ID, "中文"),
    "English": (AppiumBy.ACCESSIBILITY_ID, "English"),
}

# 来源：src/app/calib.tsx
APP_CALIB = {
    "返回": (AppiumBy.ACCESSIBILITY_ID, "返回"),
}

# 来源：src/app/consent.tsx
APP_CONSENT = {
    "同意并继续": (AppiumBy.ACCESSIBILITY_ID, "同意并继续"),
}

# 来源：src/app/legal-doc.tsx
APP_LEGAL_DOC = {
    "返回": (AppiumBy.ACCESSIBILITY_ID, "返回"),
}

# 来源：src/app/location-test.tsx
APP_LOCATION_TEST = {
    "重新探测定位": (AppiumBy.ACCESSIBILITY_ID, "重新探测定位"),
}

# 来源：src/app/login.tsx
APP_LOGIN = {
    "ApexCollect": (AppiumBy.ACCESSIBILITY_ID, "ApexCollect"),
    "用户名": (AppiumBy.ACCESSIBILITY_ID, "用户名"),
    "密码": (AppiumBy.ACCESSIBILITY_ID, "密码"),
    "登录": (AppiumBy.ACCESSIBILITY_ID, "登录"),
    "记住密码": (AppiumBy.ACCESSIBILITY_ID, "记住密码"),
    "忘记密码": (AppiumBy.ACCESSIBILITY_ID, "忘记密码"),
    "DEV 用 .env token 进入": (AppiumBy.ACCESSIBILITY_ID, "DEV 用 .env token 进入"),
}

# 来源：src/app/messages.tsx
APP_MESSAGES = {
    "1": (AppiumBy.ACCESSIBILITY_ID, "1"),
}

# 来源：src/app/permissions.tsx
APP_PERMISSIONS = {
    "返回": (AppiumBy.ACCESSIBILITY_ID, "返回"),
    "长按重置登录": (AppiumBy.ACCESSIBILITY_ID, "长按重置登录"),
}

# 来源：src/app/precheck.tsx
APP_PRECHECK = {
    "返回": (AppiumBy.ACCESSIBILITY_ID, "返回"),
    "确认画面里没有未授权的人": (AppiumBy.ACCESSIBILITY_ID, "确认画面里没有未授权的人"),
}

# 来源：src/app/record.tsx
APP_RECORD = {
    "重试开始录制": (AppiumBy.ACCESSIBILITY_ID, "重试开始录制"),
    "退出黑屏省电": (AppiumBy.ACCESSIBILITY_ID, "退出黑屏省电"),
}

# 来源：src/app/trim-demo.tsx
APP_TRIM_DEMO = {
    "起点手柄": (AppiumBy.ACCESSIBILITY_ID, "起点手柄"),
    "终点手柄": (AppiumBy.ACCESSIBILITY_ID, "终点手柄"),
}

# 来源：src/app/trim.tsx
APP_TRIM = {
    "不剪，直接下一步": (AppiumBy.ACCESSIBILITY_ID, "不剪，直接下一步"),
    "完成剪辑": (AppiumBy.ACCESSIBILITY_ID, "完成剪辑"),
}

# 以下页面没有埋 accessibilityLabel：Appium 只能靠 XPath/文案定位，容易随改版失效。
#   - src/Hud.tsx
#   - src/app/camera-diagnostics.tsx
#   - src/app/capture-options.tsx
#   - src/app/capture-smoke.tsx


def locator(page: dict, label: str):
    """按 label 取定位符；取不到时直接抛出，别让用例静默跑错元素。"""
    try:
        return page[label]
    except KeyError:
        hint = "如果界面确实有这个元素，先给它补 accessibilityLabel。"
        raise KeyError(f"定位符 {label!r} 不在此页。可用：{sorted(page)}。{hint}") from None
