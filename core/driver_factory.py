"""driver 工厂：按「平台（android/ios）× 来源（local/cloud）」创建 Appium driver。

当前支持组合：
  - android + local  → 本地真机 UiAutomator2
  - ios + cloud      → 云真机 XCUITest（云平台负责签名/安装）

暂不支持：
  - ios + local      → 需要 Mac + Xcode + 开发者账号 + dev 签名 ipa，拿到再补
  - android + cloud  → 云平台 Appium 端点接入方式各异，按实际平台再补
"""
from __future__ import annotations

import subprocess

import pytest
from appium import webdriver
from appium.webdriver.webdriver import WebDriver

from config.caps_android_local import build_android_local_caps
from config.caps_ios_cloud import build_ios_cloud_caps
from config.settings import Settings
from utils.logger import log


def _adb_devices() -> dict[str, str]:
    """返回 {udid: state}；adb 不可用返回空 dict。"""
    try:
        cp = subprocess.run(["adb", "devices"], capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001
        return {}
    out = cp.stdout.decode(errors="replace").splitlines()[1:]
    result = {}
    for line in out:
        parts = line.split()
        if len(parts) >= 2:
            result[parts[0]] = parts[1]
    return result


def precheck_android_device(s: Settings) -> None:
    """开跑前检查真机是否可用；不可用时给出可执行的中文提示并 skip。"""
    devices = _adb_devices()
    if not devices:
        pytest.skip(
            "adb 没看到任何设备：请插好 USB 线、在手机上确认「允许 USB 调试」。\n"
            "排查：adb devices（应显示 <udid>  device）"
        )
    udid = s.android_udid
    if not udid:
        pytest.skip("未配置 ANDROID_UDID，当前可用设备：" + ", ".join(devices))
    state = devices.get(udid)
    if state is None:
        pytest.skip(
            f"设备 {udid} 不在 adb 列表里（当前：{devices}）。"
            "常见原因：线松了、手机锁屏断连、USB 调试授权被撤销。\n"
            "排查：adb devices → 重新插拔 / 手机上允许调试"
        )
    if state != "device":
        pytest.skip(
            f"设备 {udid} 状态为 {state}，不是 device。"
            + (" 请在手机上点「允许 USB 调试」" if state == "unauthorized"
               else " 可尝试：adb kill-server && adb start-server")
        )
    log.info("设备就绪: %s", udid)


def create_driver(s: Settings) -> WebDriver:
    platform = s.platform.lower()
    source = s.device_source.lower()

    if platform == "android" and source == "local":
        precheck_android_device(s)
        options = build_android_local_caps(s)
    elif platform == "ios" and source == "cloud":
        options = build_ios_cloud_caps(s)
    else:
        raise NotImplementedError(
            f"暂不支持组合 platform={s.platform} source={s.device_source}；"
            "当前支持 android+local、ios+cloud。"
        )

    return webdriver.Remote(s.appium_server_url, options=options)
