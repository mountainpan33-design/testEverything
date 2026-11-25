"""用例执行顺序与副作用声明的门禁（R-GATE-05）：pytest -m gate。

为什么需要：2026-11-24 真机跑的时候，AUTH-04（连续 5 次失败锁账号）和几条
要登录的 costly 用例都标了「排最后」，组内按文件顺序排，AUTH-04 排在前面，
跑完把账号锁了 15 分钟，后面 6 条全部登不进去、被误判成产品问题。

所以顺序不能靠「记得把它放后面」，要靠规则 + 门禁。

校验四件事：
  1. policy 里声明的用例必须真的存在，order 取值合法
  2. costly 必须写 why（说明为什么贵）；destructive 必须写 why + affects
  3. depends-on 指向的用例必须存在，且不能自依赖
  4. 按现有声明算出的执行顺序里，destructive 必须排在所有其它用例之后
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.assertions import check

R = "R-GATE-05"

CASES = Path(__file__).resolve().parent.parent / "vision" / "cases" / "cases.yaml"
POLICY = Path(__file__).resolve().parent.parent / "vision" / "cases" / "policy.yaml"

VALID_ORDER = {"normal", "costly", "destructive"}


def _case_ids() -> list[str]:
    text = CASES.read_text(encoding="utf-8")
    return re.findall(r"^- id:\s*(\S+)\s*$", text, re.M)


def _policies() -> dict[str, dict[str, object]]:
    """把 policy.yaml 解析成 {用例: {order, why, affects, depends_on, kind}}。

    只用最简的缩进解析，不引 PyYAML（venv 里没装，见 verification/run_all.py 同样的取舍）。
    """
    out: dict[str, dict[str, object]] = {}
    cur: str | None = None
    pending_key: str | None = None
    for raw in POLICY.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Z0-9]+-\d+):\s*$", raw)
        if m:
            cur = m.group(1)
            out[cur] = {}
            continue
        if cur is None:
            continue
        m = re.match(r"^\s+([a-z-]+):\s*(.*)$", raw)
        if not m:
            # 跨行列表的续行（affects 可能写好几行）——并到上一行去
            if cur and pending_key and raw.strip():
                out[cur][pending_key] = str(out[cur].get(pending_key, "")) + " " + raw.strip()
            continue
        key, val = m.group(1), m.group(2).strip()
        pending_key = key if val.startswith("[") and not val.endswith("]") else None
        if pending_key:
            out[cur][key] = val
            continue
        if key == "affects":
            ids = re.findall(r"[A-Z0-9]+-\d+", val)
            # '*' = 除自己以外全部，单独标记，不能当成「没写」
            out[cur]["affects"] = ["*"] if "*" in val else ids
        elif key == "depends-on":
            out[cur]["depends_on"] = re.findall(r"[A-Z0-9]+-\d+", val)
        elif key in ("order", "kind", "why"):
            out[cur][key] = val.strip("'\"")
    return out


def _rank(policy: dict[str, object]) -> int:
    order = str(policy.get("order") or policy.get("kind") or "normal")
    if order == "destructive":
        return 2
    if order == "costly":
        return 1
    return 0


@pytest.mark.gate
def test_policy_targets_exist():
    cases = set(_case_ids())
    pol = _policies()
    unknown = sorted(set(pol) - cases)
    check(
        R, not unknown,
        expected="policy.yaml 里只出现 cases.yaml 中存在的用例",
        actual=f"不存在的：{unknown}",
        layer="L1-UI",
        message="写错编号会让声明静默失效",
    )


@pytest.mark.gate
def test_order_values_legal():
    pol = _policies()
    bad = [
        f"{cid}: {p.get('order') or p.get('kind')}"
        for cid, p in pol.items()
        if (p.get("order") or p.get("kind")) and str(p.get("order") or p.get("kind")) not in VALID_ORDER
    ]
    check(
        R, not bad,
        expected="order 只能是 normal / costly / destructive",
        actual=f"非法值：{bad}",
        layer="L1-UI",
    )


@pytest.mark.gate
def test_side_effects_are_documented():
    pol = _policies()
    missing_why = [cid for cid, p in pol.items() if _rank(p) > 0 and not p.get("why")]
    missing_affects = [cid for cid, p in pol.items() if _rank(p) == 2 and not p.get("affects")]
    check(
        R, not missing_why,
        expected="costly / destructive 用例必须写 why",
        actual=f"缺 why：{missing_why}",
        layer="L1-UI",
        message="不写清楚副作用，下次没人知道为什么它要排最后",
    )
    check(
        R, not missing_affects,
        expected="destructive 用例必须写 affects（会影响哪些用例）",
        actual=f"缺 affects：{missing_affects}",
        layer="L1-UI",
        message="锁账号/删数据的用例跑完，其余依赖它的用例应当直接标记跳过",
    )


@pytest.mark.gate
def test_depends_on_targets_exist():
    cases = set(_case_ids())
    pol = _policies()
    bad: list[str] = []
    for cid, p in pol.items():
        for dep in p.get("depends_on") or []:
            if dep == cid:
                bad.append(f"{cid} 依赖自己")
            elif dep not in cases:
                bad.append(f"{cid} → {dep}（不存在）")
    check(
        R, not bad,
        expected="depends-on 指向存在的用例且不自依赖",
        actual=f"问题：{bad}",
        layer="L1-UI",
    )


@pytest.mark.gate
def test_destructive_runs_last():
    """按声明算出的顺序里，destructive 必须排在所有其它用例之后。"""
    pol = _policies()
    ordered = sorted(
        enumerate(_case_ids()),
        key=lambda x: (_rank(pol.get(x[1], {})), x[0]),
    )
    ranks = [_rank(pol.get(cid, {})) for _, cid in ordered]
    # 一旦出现过 2，后面不能再出现 <2
    bad = []
    seen_destructive = False
    for (_, cid), r in zip(ordered, ranks):
        if r == 2:
            seen_destructive = True
        elif seen_destructive and r < 2:
            bad.append(cid)
    check(
        R, not bad,
        expected="destructive 用例排在最后",
        actual=f"排在它后面的：{bad}",
        layer="L1-UI",
        message="锁账号/删数据之后还要登录的用例必然失败，顺序必须保证它们在前面跑完",
    )


@pytest.mark.gate
def test_every_case_declares_order():
    """每条用例都必须声明 order——运行时会拦，这里提前在 CI 拦。"""
    declared = set(_policies())
    missing = sorted(set(_case_ids()) - declared)
    check(
        R, not missing,
        expected="cases.yaml 里每条用例都在 policy.yaml 声明了 order",
        actual=f"未声明：{missing}",
        layer="L1-UI",
        message="漏声明的用例会以 normal 身份乱插位置，运行时也会拒绝加载",
    )


# 这些动作会真的产生录制/上传，属于 costly 的典型特征
COSTLY_HINTS = ("开始录制", "结束录制", "加入上传队列", "重新上传")


@pytest.mark.gate
def test_costly_cases_are_declared():
    """步骤里真的会录/传的用例，不能被声明成 normal。

    运行时无法自动判断「这条到底贵不贵」，所以用关键词做启发式兜底：
    漏声明的话，它会插到普通用例中间白白吃掉额度和时间。
    """
    pol = _policies()
    text = CASES.read_text(encoding="utf-8")
    bad: list[str] = []
    for block in re.split(r"^- id:\s*", text, flags=re.M)[1:]:
        cid = block.split("\n", 1)[0].strip()
        taps = re.findall(r"^\s*- tap:\s*(.+)$", block, re.M)
        hit = [h for h in COSTLY_HINTS if any(h in t for t in taps)]
        if hit and _rank(pol.get(cid, {})) == 0:
            bad.append(f"{cid}（{hit[0]}）声明成 normal")
    check(
        R, not bad,
        expected="会录制/上传的用例声明为 costly",
        actual=f"待确认：{bad}",
        layer="L1-UI",
        message="这些用例会真录视频/真上传，排在普通用例里会吃掉额度和时间",
    )
