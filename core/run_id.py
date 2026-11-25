"""每条用例唯一 run_id，用于留证文件关联与失败追踪。"""
from __future__ import annotations

import re
import time
import uuid


def new_run_id(nodeid: str) -> str:
    """由 pytest nodeid 生成稳定可读的 run_id。

    例：tests/test_login.py::test_login_ok[android] -> test_login_ok_android_20261119_ab12cd34
    """
    tail = nodeid.split("::")[-1]
    tail = re.sub(r"[^0-9a-zA-Z_]+", "_", tail).strip("_") or "case"
    ts = time.strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"{tail}_{ts}_{short}"
