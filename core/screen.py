"""界面识别：判断当前停在哪个页面。

用例不再假设「上一步成功就一定在下一页」，而是每步先识别页面再决定动作，
这样权限弹窗、热更新改文案、偶发跳转都能被发现并纠正。
"""
from __future__ import annotations

import time

from appium.webdriver.common.appiumby import AppiumBy

# 顺序即优先级：同一时刻只应命中一个
SIGNATURES: dict[str, tuple[str, str]] = {
    "login": (AppiumBy.ACCESSIBILITY_ID, "用户名"),
    "consent": (AppiumBy.XPATH, '//*[contains(@content-desc,"同意并继续")]'),
    "permissions": (
        AppiumBy.XPATH,
        '//*[contains(@content-desc,"开启权限") or contains(@content-desc,"进入首页")]',
    ),
    "precheck": (
        AppiumBy.XPATH,
        '//*[contains(@text,"开始校准") or contains(@content-desc,"开始校准")]',
    ),
    "calib": (AppiumBy.XPATH, '//*[contains(@content-desc,"开始录制")]'),
    "record": (AppiumBy.XPATH, '//*[contains(@content-desc,"结束录制")]'),
    "trim": (AppiumBy.XPATH, '//*[contains(@content-desc,"不剪")]'),
    "qc": (
        AppiumBy.XPATH,
        '//*[contains(@text,"上传前检查") or contains(@content-desc,"加入上传队列")'
        ' or contains(@content-desc,"仍然上传")]',
    ),
    "done": (AppiumBy.XPATH, '//*[contains(@content-desc,"本地交付包")]'),
    "home": (AppiumBy.XPATH, '//*[contains(@content-desc,"刷新")]'),
}


def detect(driver) -> str | None:
    """返回当前页面名；识别不出返回 None。"""
    for name, loc in SIGNATURES.items():
        try:
            if driver.find_elements(*loc):
                return name
        except Exception:  # noqa: BLE001 - 识别失败不应打断流程
            continue
    return None


def wait_for(driver, names, timeout: float = 30.0, poll: float = 0.5) -> str | None:
    """等到出现 names 里的任一页面，返回页面名；超时返回 None。"""
    if isinstance(names, str):
        names = [names]
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = detect(driver)
        if s in names:
            return s
        time.sleep(poll)
    return None


def group_chips(chips: list[dict]) -> list[list[dict]]:
    """按纵坐标把选项 chip 分行聚类：同一行视为同一道题。

    纯函数（输入 [{label, rect:{x,y,width,height}}...]），便于单测。
    容差取行高的 0.9 倍，允许同一行内因字号/内边距造成的小幅偏移。
    """
    ordered = sorted(
        chips, key=lambda c: c["rect"]["y"] + c["rect"]["height"] / 2
    )
    groups: list[list[dict]] = []
    for c in ordered:
        cy = c["rect"]["y"] + c["rect"]["height"] / 2
        placed = False
        for g in groups:
            gcy = sum(i["rect"]["y"] + i["rect"]["height"] / 2 for i in g) / len(g)
            tol = max(c["rect"]["height"], g[0]["rect"]["height"]) * 0.9
            if abs(cy - gcy) <= tol:
                g.append(c)
                placed = True
                break
        if not placed:
            groups.append([c])
    return groups
