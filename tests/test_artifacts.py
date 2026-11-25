"""资源包产物校验（L3）：pytest -m artifact。

视觉层只看得见界面，看不见「这个包对不对」。这个测试把最近一次上传的包整个拉下来，
按 core/rules.py 的编号校验结构、字段、视频参数和哈希——不需要浏览器凭据，
用测试账号自己登录即可。

覆盖的规则：R-UP-01、R-QC-01/02/03/04/05、R-CAP-01。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from core.assertions import check

R = "R-QC-01"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.artifact


def _prereqs() -> list[str]:
    missing = []
    if not os.environ.get("QA_API_BASE"):
        missing.append("QA_API_BASE")
    if not os.environ.get("QA_USERNAME") or not os.environ.get("QA_PASSWORD"):
        missing.append("QA_USERNAME / QA_PASSWORD")
    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")
    return missing


@pytest.mark.artifact
def test_latest_upload_is_valid():
    """最近一次上传的资源包必须结构完整、字段齐全、视频参数与声明一致。"""
    missing = _prereqs()
    if missing:
        pytest.skip("缺少前置：" + "、".join(missing))

    from apis.collector_client import CollectorClient
    from verification.artifacts import fetch_file_index, verify_upload

    client = CollectorClient(
        os.environ["QA_API_BASE"], os.environ.get("QA_MAIN_SITE_HOST", "")
    )
    client.login(os.environ["QA_USERNAME"], os.environ["QA_PASSWORD"])

    assignments = client.my_assignments()
    if not assignments:
        pytest.skip("测试账号没有派工")

    uploads = fetch_file_index(client, assignments[0]["id"])
    completed = [u for u in uploads if u.get("status") == "COMPLETED"]
    if not completed:
        pytest.skip("这个派工还没有 COMPLETED 的上传")

    checks = verify_upload(client, completed[0], with_video=True)
    failed = [c for c in checks if not c.ok]
    detail = "; ".join(f"{c.rule} {c.name}: {c.detail}" for c in failed) or "全部通过"
    check(
        R,
        not failed,
        expected="最近一次上传的资源包通过全部产物校验",
        actual=f"{len(checks) - len(failed)}/{len(checks)} 通过；{detail}",
        layer="L3-ARTIFACT",
        message="产物问题看 verification/artifacts.py 的输出，逐条对到规则编号",
    )
