"""四层断言：UI / 接口 / 产物 / 负向。

每次断言都登记到 results（带规则编号），报告据此汇总「对/错」。
规则的语义（对/错是什么）定义在 core/rules.py，断言只负责按规则判真伪。

  L1 UI      —— 元素存在 / 可见 / 状态
  L2 接口    —— 调采集端 API 验证副作用
  L3 产物    —— 录制产物结构与规格
  L4 负向    —— 不应出现
"""
from __future__ import annotations

from core import results


class LayerAssertionError(AssertionError):
    """带层标识与规则编号的断言失败，便于报告归类。"""

    def __init__(self, layer: str, rule: str, message: str):
        prefix = f"[{layer}]" + (f" {rule}" if rule else "")
        super().__init__(f"{prefix} {message}")
        self.layer = layer
        self.rule = rule


def check(
    rule: str,
    cond: bool,
    expected: str = "",
    actual: str = "",
    layer: str = "",
    message: str = "",
) -> None:
    """按规则判定；登记结果，不成立即抛错。"""
    results.record(
        rule=rule,
        status="pass" if cond else "fail",
        layer=layer,
        expected=expected,
        actual=actual or message,
        message=message,
    )
    if not cond:
        raise LayerAssertionError(layer, rule, message or expected or "断言失败")


def skip(rule: str, reason: str, layer: str = "") -> None:
    results.record(rule=rule, status="skip", layer=layer, message=reason)


def assert_ui(cond: bool, message: str = "", rule: str = "",
              expected: str = "", actual: str = "") -> None:
    check(rule, cond, expected=expected, actual=actual, layer="L1-UI", message=message)


def assert_api(cond: bool, message: str = "", rule: str = "",
               expected: str = "", actual: str = "") -> None:
    check(rule, cond, expected=expected, actual=actual, layer="L2-API", message=message)


def assert_artifact(cond: bool, message: str = "", rule: str = "",
                    expected: str = "", actual: str = "") -> None:
    check(rule, cond, expected=expected, actual=actual, layer="L3-产物", message=message)


def assert_negative(cond: bool, message: str = "", rule: str = "",
                    expected: str = "", actual: str = "") -> None:
    check(rule, cond, expected=expected, actual=actual, layer="L4-负向", message=message)
