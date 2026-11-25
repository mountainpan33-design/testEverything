"""点击安全区的纯函数单测（不依赖设备）：pytest -m gate。

背景：`_click_safely` 原本硬性拒绝底部 22% 的点击，用来躲开 QC 页的
「放弃并重录」。但权限页的主 CTA「进入首页」本身就在屏高 95% 处
（bounds y=2209~2356 / 屏高 2400），于是被静默挡掉，黄金链路跑满
60 秒超时才报「未能进入首页」，看不出是脚本自己的问题。

这组用例锁住三件事：
  1. 默认仍然拒绝底部——安全区的初衷不能丢；
  2. allow_bottom=True 时底部按钮可点；
  3. 顶部状态栏内的元素始终不可点，与 allow_bottom 无关。
"""
from __future__ import annotations

import pytest

from core.assertions import check
from pages.capture_flow import FOOTER_TOP, STATUS_BAR_BOTTOM, is_click_safe

R = "R-GATE-02"
H = 2400  # Xiaomi 13 实测屏高


@pytest.mark.gate
def test_default_rejects_footer():
    """默认行为不变：底部 footer 里的元素不点（防误触「放弃并重录」）。"""
    check(R, is_click_safe(H * 0.95, H) is False,
          expected="底部默认拒绝", actual=f"y=95% -> {is_click_safe(H * 0.95, H)}")
    check(R, is_click_safe(H * 0.90, H) is False,
          expected="90% 也拒绝", actual=f"y=90% -> {is_click_safe(H * 0.90, H)}")


@pytest.mark.gate
def test_allow_bottom_permits_footer():
    """页面主 CTA 长在底部时必须能点——权限页「进入首页」回归用例。"""
    # 实测 bounds [55,2209][1025,2356]，中心 y = 2282.5
    cta_center = (2209 + 2356) / 2
    check(R, is_click_safe(cta_center, H) is False,
          expected="不传 allow_bottom 时被拒（复现原 bug）",
          actual=f"y={cta_center:.0f} ({cta_center / H * 100:.0f}%)")
    check(R, is_click_safe(cta_center, H, allow_bottom=True) is True,
          expected="传 allow_bottom=True 时可点", actual="True")


@pytest.mark.gate
def test_status_bar_always_rejected():
    """顶部状态栏内的元素永远不可点，allow_bottom 不应放开这里。"""
    check(R, is_click_safe(H * 0.02, H) is False, expected="顶部拒绝", actual="True")
    check(R, is_click_safe(H * 0.02, H, allow_bottom=True) is False,
          expected="顶部允许底部也仍拒绝", actual="True")


@pytest.mark.gate
def test_body_is_clickable():
    """页面中部正常可点，别把安全区做成过度防御。"""
    check(R, is_click_safe(H * 0.5, H) is True, expected="中部可点", actual="True")
    check(R, is_click_safe(H * 0.10, H) is True, expected="上部可点", actual="True")


@pytest.mark.gate
def test_thresholds_are_stable():
    """阈值本身锁住：改这两个数字会改变所有页面的可点区域。"""
    check(R, FOOTER_TOP == 0.78, expected="FOOTER_TOP=0.78", actual=str(FOOTER_TOP))
    check(R, STATUS_BAR_BOTTOM == 0.06, expected="STATUS_BAR_BOTTOM=0.06",
          actual=str(STATUS_BAR_BOTTOM))
