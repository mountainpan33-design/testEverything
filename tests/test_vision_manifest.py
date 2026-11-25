"""视觉层用例清单的同步检查（不依赖设备/网络）：pytest -m gate。

为什么需要：pytest 侧要知道「哪些 Midscene 用例是能跑的」，才能逐条报结果；
用例定义在 vision/cases/*.yaml。两边各写一份清单必然会漂，漂了就会静默漏跑——
报告显示全绿，其实有两条根本没执行。这条用例专门盯着这件事。

清单来源：
  cases.yaml   —— 真能跑的用例
  planned.yaml —— 已登记但还没实现的（必须有，否则缺口在报告里看不见）
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.assertions import check

R = "R-GATE-03"

CASES_DIR = Path(__file__).resolve().parent.parent / "vision" / "cases"
CASES_YAML = CASES_DIR / "cases.yaml"
PLANNED_YAML = CASES_DIR / "planned.yaml"

# 与 cases.yaml 一一对应；改了用例清单必须同步这里
EXPECTED_IMPLEMENTED = [
    "ONB-01", "ONB-02", "ONB-04", "ONB-05",
    "AUTH-01", "AUTH-02", "AUTH-03", "AUTH-04", "AUTH-05", "AUTH-06",
    "TASK-01", "TASK-02", "TASK-03",
    "CAP-01", "CAP-02", "CAP-05",
    "QC-09", "UP-04", "I18N-01",
    "FLOW-01", "LP-01", "LP-04", "LP-05",
]

# YAML 顶层条目形如「- id: AUTH-01」，缩进固定两个空格
ID_RE = re.compile(r"^- id:\s*([A-Z][A-Z0-9]*-\d+)\s*$", re.M)


def _ids(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return sorted(set(ID_RE.findall(path.read_text(encoding="utf-8"))))


@pytest.mark.gate
def test_vision_manifest_in_sync():
    """cases.yaml 里真正能跑的用例，必须和 pytest 侧清单一致。"""
    assert CASES_YAML.is_file(), f"找不到 {CASES_YAML}"
    yaml_ids = _ids(CASES_YAML)
    check(
        R,
        sorted(EXPECTED_IMPLEMENTED) == yaml_ids,
        expected=f"两侧一致：{sorted(EXPECTED_IMPLEMENTED)}",
        actual=f"cases.yaml：{yaml_ids}",
        layer="L1-UI",
        message="改了 vision/cases/cases.yaml，记得同步 tests/test_vision_manifest.py",
    )


@pytest.mark.gate
def test_vision_planned_is_disjoint():
    """planned.yaml 不能和已实现的用例重号，否则会出现「既能跑又未实现」。"""
    done = set(_ids(CASES_YAML))
    planned = set(_ids(PLANNED_YAML))
    check(
        R,
        not (done & planned),
        expected="planned 与已实现无交集",
        actual=f"重号：{sorted(done & planned)}",
        layer="L1-UI",
    )


@pytest.mark.gate
def test_vision_planned_covers_table():
    """testcases.md 里标为 Midscene 主驱动的 18 条，必须落在「已实现」或「计划中」之一。"""
    midscene_ids = {
        "AUTH-01", "AUTH-02", "AUTH-03", "AUTH-04", "AUTH-05", "AUTH-06",
        "ONB-01", "ONB-02", "ONB-03", "ONB-05",
        "TASK-01", "TASK-02", "TASK-05",
        "CAP-02", "QC-09", "UP-04", "I18N-01", "I18N-02",
    }
    known = set(_ids(CASES_YAML)) | set(_ids(PLANNED_YAML))
    missing = sorted(midscene_ids - known)
    check(
        R,
        not missing,
        expected="testcases.md 里 18 条 Midscene 用例都有归属",
        actual=f"无归属：{missing}",
        layer="L1-UI",
        message="这些用例既没实现也没登记，会在报告里凭空消失",
    )
