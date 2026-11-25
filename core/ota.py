"""OTA 热更新清单查询：用于记录「本次跑的是哪个 bundle」。

App 的 JS 走 expo-updates，UI 文案可能与仓库代码不一致（开发热更新过）。
每轮 UI 结果都应记录当时发布的 updateId，否则出了问题无法归因到具体 bundle。
"""
from __future__ import annotations

import requests

MANIFEST_URL = "https://ota.deeptranslate.app/mono-capture/{platform}/{runtime}/manifest.json"


def latest_update(platform: str = "android", runtime_version: str = "4", timeout: int = 15) -> dict | None:
    """返回 {id, createdAt, nativeBuild, releaseNotes}；取不到返回 None。"""
    url = MANIFEST_URL.format(platform=platform, runtime=runtime_version)
    try:
        r = requests.get(
            url,
            headers={
                "Expo-Platform": platform,
                "Expo-Runtime-Version": runtime_version,
                "expo-protocol-version": "1",
            },
            timeout=timeout,
        )
        r.raise_for_status()
        m = r.json()
    except Exception:
        return None
    extra = m.get("extra") or {}
    return {
        "id": m.get("id"),
        "createdAt": m.get("createdAt"),
        "nativeBuild": extra.get("nativeBuild"),
        "releaseNotes": extra.get("releaseNotes"),
    }
