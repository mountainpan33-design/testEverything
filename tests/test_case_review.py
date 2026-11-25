"""用例审核状态的门禁：pytest -m gate。

为什么需要：用例可以由代码生成，但「什么算对」代码不知道。
没人看过的断言绿了，只能说明「和实现一致」，不能说明产品对——
AUTH-05 就是这么绿的：它验了用户名预填，没验密码，因为写它的人是照着实现写的。

所以每条跑视觉层的用例都必须有 review 声明，取值必须是三选一。
本门禁**不拦未审核**（用户明确要求「都跑，但报告里标未审核」），
拦的是「声明写错」和「派生用例缺审核块」。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.assertions import check

R = "R-GATE-05"

CASES_DIR = Path(__file__).resolve().parent.parent / "vision" / "cases"
CASE_FILES = [CASES_DIR / "cases.yaml", CASES_DIR / "derived.yaml"]

VALID_STATUS = {"draft", "approved", "rejected"}
VALID_SOURCE = {"doc", "code", "guess", "human"}


def _blocks(path: Path) -> list[dict]:
    """把文件按 `- id:` 切成块，返回 {id, text}。不引 PyYAML。"""
    if not path.is_file():
        return []
    out: list[dict] = []
    cur: dict | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^- id:\s*(\S+)", line)
        if m:
            cur = {"id": m.group(1), "lines": []}
            out.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
    return out


def _review(block: dict) -> dict[str, str]:
    """取 review 块下的字段（4 空格缩进）。"""
    got: dict[str, str] = {}
    inside = False
    for line in block["lines"]:
        if re.match(r"^ {2}review:\s*$", line):
            inside = True
            continue
        if inside:
            if line.strip() and not line.startswith("    "):
                break
            m = re.match(r"^ {4}(\w+):\s*(.+)$", line)
            if m:
                got[m.group(1)] = m.group(2).strip().strip("'\"")
    return got


@pytest.mark.gate
def test_declared_review_values_are_valid():
    """写了 review 的，取值必须合法；没写就等于未审核（这是安全默认）。

    为什么容忍「没写」：人写的用例默认就是没人审过，
    逼着每条都写一遍 `status: draft` 只是噪音，不会让任何一条更可信。
    真正要防的是「写了个不认识的值」，那会让报告把未审核显示成已审核。
    """
    problems = []
    total = 0
    declared = 0
    for f in CASE_FILES:
        for b in _blocks(f):
            total += 1
            rv = _review(b)
            if not rv:
                continue                      # 没写 = draft
            declared += 1
            if rv.get("status") not in VALID_STATUS:
                problems.append(f"{b['id']} 的 review.status「{rv.get('status')}」不合法")
    check(
        R,
        not problems and total > 0,
        expected="写了 review 的用例，status ∈ {draft, approved, rejected}；没写视为未审核",
        actual=(
            "; ".join(problems)
            if problems
            else f"{total} 条中 {declared} 条显式声明，其余视为未审核"
        ),
    )


@pytest.mark.gate
def test_derived_cases_declare_review():
    """派生用例必须显式声明 review，且 source 不能是 human。

    派生的东西是机器写的，来源必须留在文件里——否则过两周没人分得清
    哪条是人精心写的、哪条是「页面能打开」的兜底冒烟。
    """
    problems = []
    path = CASES_DIR / "derived.yaml"
    for b in _blocks(path):
        rv = _review(b)
        if not rv:
            problems.append(f"{b['id']} 没有 review 块")
            continue
        status = rv.get("status", "draft")
        source = rv.get("source", "")
        if source == "human":
            problems.append(f"{b['id']} 的 source 是 human（派生用例不该被当成人写的）")
        if status not in VALID_STATUS:
            problems.append(f"{b['id']} 的状态「{status}」不合法")
    check(
        R,
        not problems,
        expected="derived.yaml 里每条都有 review 块，source 是 code/doc/guess",
        actual="; ".join(problems) if problems else "全部正确",
    )


@pytest.mark.gate
def test_review_source_values_are_valid():
    """source 只能是 doc / code / guess / human，写错会让审核页的提示失真。"""
    problems = []
    for f in CASE_FILES:
        for b in _blocks(f):
            rv = _review(b)
            src = rv.get("source")
            if src is not None and src not in VALID_SOURCE:
                problems.append(f"{b['id']} 的 source「{src}」不合法")
    check(
        R,
        not problems,
        expected=f"review.source ∈ {sorted(VALID_SOURCE)}",
        actual="; ".join(problems) if problems else "全部合法",
    )
