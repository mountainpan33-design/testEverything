"""真机权限预授予（Android）。

precheck 要求相机/麦克风/定位/运动等权限就绪。UI 点系统弹窗容易受厂商 ROM 影响，
直接用 adb pm grant 授予更稳定；失败的不阻塞，由 precheck 自己再兜底。
"""
from __future__ import annotations

import subprocess

from utils.logger import log

# 采集链路需要的运行时权限
ANDROID_PERMISSIONS = [
    "android.permission.CAMERA",
    "android.permission.RECORD_AUDIO",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.ACTIVITY_RECOGNITION",  # 运动与健身（Android 10+）
    "android.permission.BODY_SENSORS",
]


def grant_android_permissions(udid: str, package: str) -> dict[str, bool]:
    """逐条授予权限，返回 {权限: 是否成功}。不抛异常。"""
    result: dict[str, bool] = {}
    for perm in ANDROID_PERMISSIONS:
        try:
            cp = subprocess.run(
                ["adb", "-s", udid, "shell", "pm", "grant", package, perm],
                capture_output=True,
                timeout=20,
            )
            ok = cp.returncode == 0 and b"Exception" not in cp.stdout + cp.stderr
            result[perm] = ok
        except Exception:  # noqa: BLE001
            result[perm] = False
    failed = [p for p, ok in result.items() if not ok]
    if failed:
        log.warning("以下权限未授予成功（可能不支持或需手动）：%s", failed)
    else:
        log.info("权限已全部授予: %s", package)
    return result
