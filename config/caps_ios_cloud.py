"""iOS 云真机 capabilities（XCUITest）。

说明：iOS 真机自动化要求被测 app 为 development 签名（TestFlight 的 distribution 签名无法被
XCUITest 驱动）。本地跑需要 Mac + Xcode + 开发者账号；走云真机则由平台负责重签与安装，本文件按
「云真机」预留参数位，等拿到 development 签名 ipa / 平台下发 UDID 后再填。
"""
from __future__ import annotations

from appium.options.ios import XCUITestOptions

from config.settings import Settings


def build_ios_cloud_caps(s: Settings) -> XCUITestOptions:
    opts = XCUITestOptions()
    opts.platform_name = "iOS"
    opts.automation_name = "XCUITest"
    opts.no_reset = True

    if s.ios_udid:
        opts.udid = s.ios_udid
    if s.ios_bundle_id:
        opts.bundle_id = s.ios_bundle_id
    # 本地跑才必填；云平台重签时留空由平台处理。
    if s.ios_xcode_org_id:
        opts.xcode_org_id = s.ios_xcode_org_id
    if s.ios_xcode_signing_id:
        opts.xcode_signing_id = s.ios_xcode_signing_id
    if s.ios_ipa_path:
        opts.app = s.ios_ipa_path

    opts.new_command_timeout = 120
    return opts
