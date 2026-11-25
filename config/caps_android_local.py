"""安卓本地真机 capabilities（UiAutomator2）。"""
from __future__ import annotations

from appium.options.android import UiAutomator2Options

from config.settings import Settings


def build_android_local_caps(s: Settings) -> UiAutomator2Options:
    opts = UiAutomator2Options()
    opts.platform_name = "Android"
    opts.automation_name = "UiAutomator2"
    # 登录态保留，减少每条用例重复登录；需要干净态时用 app start --clear-data 单独清。
    opts.no_reset = True

    if s.android_udid:
        opts.udid = s.android_udid

    if s.android_apk_path:
        # 传 APK 路径时 Appium 会自动安装并启动
        opts.app = s.android_apk_path
    else:
        opts.app_package = s.android_app_package
        opts.app_activity = s.android_app_activity

    # 采集 App 涉及相机预览，命令超时放宽，避免长链路误判
    opts.new_command_timeout = 120
    return opts
