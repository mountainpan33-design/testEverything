"""重试与超时预算。

原则：任何「找不到 / 点不中」的循环都必须有上限，到点就失败并留证，
不允许无限滑动 —— 真机上空转几分钟和卡死没有区别。
"""
from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


# 单个元素最多滑动几次去找它（上下来回算一次）
MAX_SWIPES = _int("QA_MAX_SWIPES", 6)
# 自适应补答 / 补填的最大轮数
MAX_ROUNDS = _int("QA_MAX_ROUNDS", 2)
# 同一目标最多尝试几个候选文案（如 自然光/室内灯光/混合光）
MAX_CANDIDATES = _int("QA_MAX_CANDIDATES", 2)
# 单个步骤（进入某页、完成某页操作）的总时长上限，秒
STEP_TIMEOUT = _int("QA_STEP_TIMEOUT", 60)
# QC 填答整体预算，秒
QC_TIMEOUT = _int("QA_QC_TIMEOUT", 150)
