"""输入框判定纯函数（不下沉，可单测）：占位符识别 / 是否可填。

为什么需要这一层——真机事实（2026-11-19 QC 页 UiAutomator2 XML）：

    <EditText text="例如：电子厂、厨房、超市"
              hint="例如：电子厂、厨房、超市"
              showing-hint="true" multiline="false" enabled="true" />

空输入框的 `text` 属性**不是空串**，而是占位示例文案。用「text 非空 = 已填」判断，
会把页面上所有空输入框都当成已填而跳过 —— 表现就是 QC 页只选 chip 不写字、
提交按钮一直灰着（R-QC-06 必填项缺失）。

判定口径：
  1. `showing-hint="true"` → 显示的是占位符，框里没有真实内容；
  2. `text == hint` → 同上（部分平台不暴露 showing-hint）；
  3. `text` 以示例/提示前缀开头（例如 / 请输入 / e.g …）→ 兜底按占位符处理。
"""
from __future__ import annotations

# 占位符常见前缀：中文引导语 + 英文引导语
PLACEHOLDER_PREFIXES: tuple[str, ...] = (
    "例如",
    "例：",
    "请输入",
    "请填写",
    "请选择",
    "请说明",
    "e.g.",
    "e.g",
    "Enter ",
    "Type ",
)


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def is_placeholder(text, hint="", showing_hint="false") -> bool:
    """text 是不是占位示例文案（而非用户真实输入）。"""
    t = _s(text)
    if not t:
        return False
    if _s(showing_hint).lower() == "true":
        return True
    h = _s(hint)
    if h and t == h:
        return True
    return t.startswith(PLACEHOLDER_PREFIXES)


def is_empty_value(text, hint="", showing_hint="false") -> bool:
    """框里没有真实内容：空串或占位符。"""
    return not _s(text) or is_placeholder(text, hint, showing_hint)


def is_fillable_input(
    *,
    text="",
    hint="",
    showing_hint="false",
    multiline="false",
    enabled="true",
) -> bool:
    """需要且可以填写：可用、单行、当前没有真实内容。

    多行框（备注）默认不碰——需求口径里它不是必填（R-QC-06），
    误填会污染交付数据；需要时由调用方传 allow_multiline=True。
    """
    return _is_fillable(
        text=text, hint=hint, showing_hint=showing_hint,
        multiline=multiline, enabled=enabled, allow_multiline=False,
    )


def _is_fillable(*, text, hint, showing_hint, multiline, enabled, allow_multiline: bool) -> bool:
    if _s(enabled).lower() == "false":
        return False
    if not allow_multiline and _s(multiline).lower() == "true":
        return False
    return is_empty_value(text, hint, showing_hint)


def is_fillable_any(*, text="", hint="", showing_hint="false", multiline="false", enabled="true") -> bool:
    """含多行框在内、任意空输入框都可填（最后兜底用）。"""
    return _is_fillable(
        text=text, hint=hint, showing_hint=showing_hint,
        multiline=multiline, enabled=enabled, allow_multiline=True,
    )
