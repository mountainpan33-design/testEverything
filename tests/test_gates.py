"""门禁纯函数单测：不依赖设备/网络，跑 `pytest -m gate`。

断言统一走 core.assertions.check，带规则编号进入报告。
"""
from __future__ import annotations

import pytest

from core import gates
from core.assertions import check


@pytest.mark.gate
def test_uniform_downsample_100_to_30_false():
    # 100Hz -> 30Hz 非整数倍，均匀抽帧会有相位漂移（已知待确认差异点）
    got = gates.is_uniform_downsample(100, 30)
    check("R-GATE-01", got is False, expected="100→30 判为非整数倍", actual=str(got))


@pytest.mark.gate
def test_uniform_downsample_120_to_30_true():
    got = gates.is_uniform_downsample(120, 30)
    check("R-GATE-01", got is True, expected="120→30 可整数抽帧", actual=str(got))


@pytest.mark.gate
def test_imu_meets_min():
    ok = gates.imu_hz_meets_min(100)
    check("R-CAP-01", ok is True, expected="IMU 100Hz 达标", actual=str(ok))
    bad = gates.imu_hz_meets_min(50)
    check("R-CAP-01", bad is False, expected="IMU 50Hz 不达标", actual=str(bad))


@pytest.mark.gate
def test_video_meets_spec_1080p30():
    ok = gates.video_meets_spec(1920, 1080, 30)
    check("R-QC-05", ok is True, expected="1920x1080@30 达标", actual=str(ok))
    bad = gates.video_meets_spec(1280, 720, 30)
    check("R-QC-05", bad is False, expected="720p 不达标", actual=str(bad))


@pytest.mark.gate
def test_clip_duration_in_range():
    ok = gates.clip_duration_in_range(10.0)
    check("R-QC-05", ok is True, expected="10s 在区间内", actual=str(ok))
    short = gates.clip_duration_in_range(1.0)
    check("R-QC-05", short is False, expected="1s 过短", actual=str(short))
    long_ = gates.clip_duration_in_range(60.0)
    check("R-QC-05", long_ is False, expected="60s 超上限", actual=str(long_))


@pytest.mark.gate
def test_invalid_freq_raises():
    raised = False
    try:
        gates.is_uniform_downsample(0, 30)
    except ValueError:
        raised = True
    check("R-GATE-01", raised, expected="非法频率抛 ValueError", actual=str(raised))
