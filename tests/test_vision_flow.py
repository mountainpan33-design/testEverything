"""视觉驱动层（Midscene.js）的 pytest 桥。

它不直接操作 UI —— UI 由 `vision/` 那个 Node 工程驱动，这里只做三件事：
  1. 检查前置（node / 依赖 / 设备 / 模型 Key / 账号），缺什么就 skip 并说清楚；
  2. 用 adb 预授予采集权限（绕开厂商 ROM 的系统弹窗）；
  3. 调一次 Node CLI，把它吐出来的 JSON 翻译成 core.results 里的断言，
     这样视觉层的结论和 Appium / 接口层进同一份报告、同一套规则编号。

为什么不让 pytest 逐条调 Node：每起一个进程都要重连 adb、重建 Agent，
慢且容易抢设备。一次进程跑完全部用例，结果一次性拿回来。

运行：pytest -m vision
前置：vision/.env 里填好模型配置与账号，见 vision/.env.example
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from config.settings import PROJECT_ROOT, Settings
from core import results
from core.permissions import grant_android_permissions
from utils.logger import log

pytestmark = pytest.mark.vision

VISION_DIR = PROJECT_ROOT / "vision"
CLI = VISION_DIR / "src" / "cli.ts"


def _esbuild_platform_pkg() -> str:
    """本机应装的 esbuild 二进制包名，例如 @esbuild/darwin-arm64。"""
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(
        platform.machine().lower(), platform.machine().lower()
    )
    os_name = {"darwin": "darwin", "linux": "linux"}.get(sys.platform, sys.platform)
    return f"@esbuild/{os_name}-{arch}"


def _missing_prereqs(settings: Settings) -> list[str]:
    missing: list[str] = []
    if shutil.which("node") is None:
        missing.append("node（需要 Node ≥20.19 / 22.12 / 24）")
    if not (VISION_DIR / "node_modules").is_dir():
        missing.append("vision/node_modules（先在 vision/ 目录跑 npm install）")
    elif not (VISION_DIR / "node_modules" / "@esbuild" / _esbuild_platform_pkg().split("/")[1]).is_dir():
        # 常见于把别的机器/容器里装好的 node_modules 拷过来：esbuild 是原生二进制，跨平台必炸
        missing.append(
            f"node_modules 是别的平台装的（缺 {_esbuild_platform_pkg()}）。"
            "在 vision/ 里删掉 node_modules 和 package-lock.json 后重新 npm install"
        )
    if not CLI.is_file():
        missing.append(f"{CLI}")
    if not os.environ.get("MIDSCENE_MODEL_API_KEY"):
        missing.append("MIDSCENE_MODEL_API_KEY（写在 vision/.env）")
    if not settings.android_udid:
        missing.append("ANDROID_UDID")
    if not settings.android_app_package:
        missing.append("ANDROID_APP_PACKAGE")
    if not settings.username or not settings.password:
        missing.append("QA_USERNAME / QA_PASSWORD")
    return missing


def _run_cli(settings: Settings, out_path: Path) -> dict:
    env = os.environ.copy()
    # vision 侧的变量名和 app-automation 的 .env 不一样，这里做一次映射
    env.setdefault("EGO_APP_PACKAGE", settings.android_app_package)
    env.setdefault("EGO_USERNAME", settings.username)
    env.setdefault("EGO_PASSWORD", settings.password)
    env.setdefault("MIDSCENE_ANDROID_DEVICE_ID", settings.android_udid)

    cmd = [
        "npx", "tsx", "src/cli.ts",
        "--all",
        "--out", str(out_path),
        "--device", settings.android_udid,
        # pytest 侧只要一轮结果；自愈是独立的、有 3 轮上限的动作，由人单独跑
        "--no-heal",
    ]
    log.info("[vision] 执行：%s", " ".join(cmd))
    cp = subprocess.run(
        cmd, cwd=VISION_DIR, env=env, capture_output=True, text=True, timeout=60 * 30
    )
    if cp.stdout.strip():
        log.info("[vision] stdout:\n%s", cp.stdout[-4000:])
    if cp.stderr.strip():
        log.warning("[vision] stderr:\n%s", cp.stderr[-4000:])
    if not out_path.is_file():
        raise AssertionError(
            f"视觉层没有产出结果文件（退出码 {cp.returncode}）。\n"
            f"标准错误：{(cp.stderr or '')[-1500:]}\n"
            "先单独跑一次排查：cd vision && npx tsx src/cli.ts --list"
        )
    return json.loads(out_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def vision_run(settings: Settings) -> dict:
    missing = _missing_prereqs(settings)
    if missing:
        pytest.skip("视觉层前置不全：" + "；".join(missing))

    # 系统权限弹窗受 ROM 影响大，先用 adb 直接授予
    grant_android_permissions(settings.android_udid, settings.android_app_package)

    with tempfile.TemporaryDirectory(prefix="ego-vision-") as tmp:
        out = Path(tmp) / "vision.json"
        data = _run_cli(settings, out)
    return data


def test_vision_cases(vision_run: dict):
    """把所有视觉层用例的断言登记进报告，最后统一判定。"""
    failures: list[str] = []
    executed = 0

    for case in vision_run.get("cases", []):
        case_id = case.get("caseId", "?")
        executed += 1

        for a in case.get("assertions", []):
            results.record(
                rule=a.get("rule", ""),
                status="pass" if a.get("ok") else "fail",
                layer="L1-UI",
                expected=a.get("expected", ""),
                actual=a.get("actual", ""),
                message=f"{case_id} {a.get('message', '')}".strip(),
            )
            if not a.get("ok"):
                failures.append(
                    f"{case_id} {a.get('rule')}: {a.get('expected')} → {a.get('actual')}"
                )

        if case.get("status") == "skipped":
            results.record(
                rule="", status="skip",
                message=f"{case_id} {case.get('skipReason', '')}",
            )
        elif case.get("error"):
            results.record(
                rule="", status="fail", layer="L1-UI",
                expected=f"{case_id} 完整走通",
                actual=case["error"],
                message=f"{case_id} 执行中断",
            )
            failures.append(f"{case_id} {case['error'].splitlines()[0]}")

    assert executed > 0, "视觉层一条用例都没执行，检查 CLI 输出"
    assert not failures, "视觉层有断言失败：\n" + "\n".join(failures)
