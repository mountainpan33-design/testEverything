"""门禁纯函数：下沉到单测，不依赖设备 / 网络。

这些是从《Ego 验收标准》提炼的可判定规则，单独成函数便于单元测试与 CI 门禁。
注意：部分阈值来自验收标准与原型现状的差异点，标注「待确认」的以最终验收口径为准。
"""
from __future__ import annotations


def is_uniform_downsample(src_hz: int, dst_hz: int) -> bool:
    """判断 src_hz 能否均匀抽帧到 dst_hz（即 src 是否为 dst 整数倍）。

    100Hz -> 30Hz 返回 False（非整数倍，均匀抽帧会有相位漂移），这是已知待确认差异点。
    """
    if src_hz <= 0 or dst_hz <= 0:
        raise ValueError("频率必须为正整数")
    return src_hz % dst_hz == 0


def imu_hz_meets_min(imu_hz: int, min_hz: int = 100) -> bool:
    """采集端 IMU 是否达到最低采样率。默认 100Hz（待确认验收口径）。"""
    return imu_hz >= min_hz


def video_meets_spec(
    width: int, height: int, fps: int, spec: tuple[int, int, int] = (1920, 1080, 30)
) -> bool:
    """视频是否达到验收规格。默认 1080p30（v0.6 支持 1080p60/4K30，验收硬性 1080p30，待确认）。"""
    sw, sh, sfps = spec
    return width >= sw and height >= sh and fps >= sfps


def clip_duration_in_range(seconds: float, lo: float = 3.0, hi: float = 30.0) -> bool:
    """单条 clips 时长是否在验收区间内。默认 3~30 秒（原型单条 3~30 分钟，验收 3 分钟，待确认）。"""
    if seconds < 0:
        raise ValueError("时长不能为负")
    return lo <= seconds <= hi
