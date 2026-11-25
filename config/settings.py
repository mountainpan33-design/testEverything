"""配置层：从 .env 读取运行参数，作为单一数据源。

所有敏感信息（账号密码、UDID、签名）只进本地 .env，禁止提交。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 优先读项目根 .env；不存在也不报错（允许纯环境变量注入）。
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


@dataclass(frozen=True)
class Settings:
    """运行配置。实例化时读取环境变量，便于 fixture 里复用同一份。"""

    platform: str = field(default_factory=lambda: _get("QA_PLATFORM", "android"))
    device_source: str = field(default_factory=lambda: _get("QA_DEVICE_SOURCE", "local"))

    api_base: str = field(default_factory=lambda: _get("QA_API_BASE", ""))
    main_site_host: str = field(default_factory=lambda: _get("QA_MAIN_SITE_HOST", ""))
    server_id: str = field(default_factory=lambda: _get("QA_SERVER_ID", "new"))
    username: str = field(default_factory=lambda: _get("QA_USERNAME", ""))
    password: str = field(default_factory=lambda: _get("QA_PASSWORD", ""))

    # 安卓本地真机
    android_udid: str = field(default_factory=lambda: _get("ANDROID_UDID", ""))
    android_app_package: str = field(default_factory=lambda: _get("ANDROID_APP_PACKAGE", ""))
    android_app_activity: str = field(default_factory=lambda: _get("ANDROID_APP_ACTIVITY", ""))
    android_apk_path: str = field(default_factory=lambda: _get("ANDROID_APK_PATH", ""))

    # iOS 云真机（预留）
    ios_bundle_id: str = field(default_factory=lambda: _get("IOS_BUNDLE_ID", ""))
    ios_udid: str = field(default_factory=lambda: _get("IOS_UDID", ""))
    ios_xcode_org_id: str = field(default_factory=lambda: _get("IOS_XCODE_ORG_ID", ""))
    ios_xcode_signing_id: str = field(
        default_factory=lambda: _get("IOS_XCODE_SIGNING_ID", "iPhone Developer")
    )
    ios_ipa_path: str = field(default_factory=lambda: _get("IOS_IPA_PATH", ""))

    # 黄金链路：录制时长（QC 要求 ≥30 秒）与验收视频规格
    golden_record_seconds: int = field(
        default_factory=lambda: int(_get("QA_GOLDEN_RECORD_SECONDS", "35") or 35)
    )
    video_spec_width: int = field(
        default_factory=lambda: int(_get("QA_VIDEO_WIDTH", "1920") or 1920)
    )
    video_spec_height: int = field(
        default_factory=lambda: int(_get("QA_VIDEO_HEIGHT", "1080") or 1080)
    )
    video_spec_fps: int = field(
        default_factory=lambda: int(_get("QA_VIDEO_FPS", "30") or 30)
    )
    # QC 必填项（源码 qc.tsx requiredLeft 共 6 项：光线、工具、L2、L3 无条件必填）
    qc_lighting: str = field(default_factory=lambda: _get("QA_QC_LIGHTING", "自然光"))
    qc_tools: str = field(default_factory=lambda: _get("QA_QC_TOOLS", "无"))
    qc_l2: str = field(default_factory=lambda: _get("QA_QC_L2", "办公室"))
    qc_l3: str = field(default_factory=lambda: _get("QA_QC_L3", "整理货架"))

    # 视觉回归（截图对比）
    vision_enabled: bool = field(
        default_factory=lambda: _get("QA_VISION", "1") not in ("0", "false", "False", "no")
    )
    vision_tolerance: float = field(
        default_factory=lambda: float(_get("QA_VISION_TOLERANCE", "0.02") or 0.02)
    )
    vision_update: bool = field(
        default_factory=lambda: _get("QA_VISION_UPDATE", "0") in ("1", "true", "True", "yes")
    )

    @property
    def vision_dir(self) -> Path:
        return Path(_get("QA_VISION_DIR", str(PROJECT_ROOT / "screenshots")))

    @property
    def vision_baseline_dir(self) -> Path:
        return self.vision_dir / "baseline" / self.platform.lower()

    evidence_dir: Path = field(
        default_factory=lambda: Path(_get("EVIDENCE_DIR", "./evidence")).resolve()
    )

    @property
    def appium_server_url(self) -> str:
        return os.environ.get("APPIUM_SERVER_URL", "http://127.0.0.1:4723")

    def missing_credentials(self) -> list[str]:
        """返回缺失的必填项，便于启动前快速拦截，避免连上真机才发现没账号。"""
        missing = []
        if not self.username:
            missing.append("QA_USERNAME")
        if not self.password:
            missing.append("QA_PASSWORD")
        if not self.api_base:
            missing.append("QA_API_BASE")
        return missing
