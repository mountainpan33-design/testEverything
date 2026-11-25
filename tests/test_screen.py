"""界面识别与选项分组的纯函数单测（不依赖设备）：pytest -m gate。"""
from __future__ import annotations

import pytest

from core.assertions import check
from core.screen import group_chips

R = "R-GATE-01"


def _chip(label: str, y: int, h: int = 40) -> dict:
    return {"label": label, "rect": {"x": 0, "y": y, "width": 120, "height": h}}


@pytest.mark.gate
def test_group_chips_two_rows():
    chips = [
        _chip("自然光", 100), _chip("室内灯光", 104), _chip("混合光", 98),
        _chip("扫码枪", 200), _chip("无", 203),
    ]
    groups = group_chips(chips)
    check(R, len(groups) == 2, expected="两行分两组", actual=f"{len(groups)} 组")
    labels = [[c["label"] for c in g] for g in groups]
    check(R, labels[0] == ["混合光", "自然光", "室内灯光"], expected="第一行三选", actual=str(labels[0]))
    check(R, {c["label"] for c in groups[1]} == {"扫码枪", "无"}, expected="第二行两项", actual=str(labels[1]))


@pytest.mark.gate
def test_group_chips_vertical_gap_makes_new_row():
    groups = group_chips([_chip("A", 100), _chip("B", 200)])
    check(R, len(groups) == 2, expected="纵向间隔分开", actual=f"{len(groups)} 组")


@pytest.mark.gate
def test_group_chips_tolerates_small_offset():
    groups = group_chips([_chip("A", 100), _chip("B", 130)])
    check(R, len(groups) == 1, expected="小幅偏移仍同行", actual=f"{len(groups)} 组")


@pytest.mark.gate
def test_group_chips_empty():
    groups = group_chips([])
    check(R, groups == [], expected="空输入返回空", actual=str(groups))
