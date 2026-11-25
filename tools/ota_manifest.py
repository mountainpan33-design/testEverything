"""打印当前 OTA 热更新清单，确认被测 bundle 是哪一版。

用法：
    python tools/ota_manifest.py                # android, runtime 4
    python tools/ota_manifest.py --platform ios
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ota import latest_update


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="android", choices=["android", "ios"])
    ap.add_argument("--runtime", default="4")
    args = ap.parse_args()

    info = latest_update(args.platform, args.runtime)
    if info is None:
        print("取不到 OTA 清单（网络或地址问题）")
        return 1
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
