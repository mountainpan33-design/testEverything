"""输入框判定的纯函数单测（不依赖设备）：pytest -m gate。

用例数据全部来自真机 XML（evidence/golden_20261119200259_aff7216f/page_source.xml），
复现的是「QC 页空输入框被当成已填」这个真实缺陷。
"""
from __future__ import annotations

import pytest

from core.assertions import check
from core.inputs import is_empty_value, is_fillable_any, is_fillable_input, is_placeholder

R = "R-QC-06"


@pytest.mark.gate
def test_hint_text_is_placeholder():
    """空框的 text 就是占位示例文案 —— 不能算已填。"""
    text = "例如：电子厂、厨房、超市"
    check(R, is_placeholder(text, hint=text, showing_hint="true"),
          expected="showing-hint=true 视为占位符", actual=text)
    check(R, is_empty_value(text, hint=text, showing_hint="true"),
          expected="占位符视为空", actual=text)


@pytest.mark.gate
def test_real_value_is_not_placeholder():
    t = "上海某电子厂"
    check(R, not is_placeholder(t, hint="例如：电子厂、厨房、超市", showing_hint="false"),
          expected="真实输入不是占位符", actual=t)
    check(R, not is_empty_value(t, hint="例如：电子厂、厨房、超市", showing_hint="false"),
          expected="真实输入视为已填", actual=t)


@pytest.mark.gate
def test_empty_string_is_empty():
    check(R, is_empty_value(""), expected="空串视为空", actual="''")
    check(R, not is_placeholder(""), expected="空串不是占位符", actual="''")


@pytest.mark.gate
def test_placeholder_fallback_when_showing_hint_missing():
    """没有 showing-hint / hint 属性时，用「例如…」前缀兜底。"""
    t = "例如：清洗了 8 个盘子、2 个碗"
    check(R, is_placeholder(t), expected="示例前缀兜底判占位符", actual=t)
    check(R, is_placeholder("请输入具体操作"), expected="「请输入…」前缀同样判占位符", actual="请输入具体操作")
    check(R, not is_placeholder("清洗了 8 个盘子"), expected="正常文本非占位符", actual="清洗了 8 个盘子")


@pytest.mark.gate
def test_fillable_skips_multiline_by_default():
    """QC 页三个框：L2/L3 单行、L4 多行备注；默认只填前两个。"""
    l2 = dict(text="例如：电子厂、厨房、超市", hint="例如：电子厂、厨房、超市",
              showing_hint="true", multiline="false", enabled="true")
    l3 = dict(text="例如：零件组装、切菜、货架摆放", hint="例如：零件组装、切菜、货架摆放",
              showing_hint="true", multiline="false", enabled="true")
    l4 = dict(text="例如：清洗了 8 个盘子、2 个碗", hint="例如：清洗了 8 个盘子、2 个碗",
              showing_hint="true", multiline="true", enabled="true")
    check(R, is_fillable_input(**l2), expected="L2 单行空框可填", actual=str(l2))
    check(R, is_fillable_input(**l3), expected="L3 单行空框可填", actual=str(l3))
    check(R, not is_fillable_input(**l4), expected="L4 多行备注默认跳过", actual=str(l4))
    check(R, is_fillable_any(**l4), expected="兜底模式下多行可填", actual=str(l4))


@pytest.mark.gate
def test_filled_single_line_is_not_refilled():
    """已填过的框不重复覆盖（重试轮次不能把用户/上一轮的内容改掉）。"""
    v = dict(text="上海某电子厂", hint="例如：电子厂、厨房、超市",
             showing_hint="false", multiline="false", enabled="true")
    check(R, not is_fillable_input(**v), expected="有真实内容不再填", actual=str(v))


@pytest.mark.gate
def test_disabled_input_is_not_fillable():
    v = dict(text="", hint="", showing_hint="false", multiline="false", enabled="false")
    check(R, not is_fillable_input(**v), expected="禁用输入框不可填", actual=str(v))
