"""把当前屏幕所有可读标签打印出来 —— 热更新改了文案后用它快速校准定位符。

用法（Appium 已起、真机已连）：
    python tools/dump_labels.py
    python tools/dump_labels.py --screenshot
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from appium.webdriver.common.appiumby import AppiumBy

from config.settings import Settings
from core.driver_factory import create_driver


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screenshot", action="store_true", help="同时保存一张截图")
    args = ap.parse_args()

    s = Settings()
    d = create_driver(s)
    try:
        els = d.find_elements(AppiumBy.XPATH, '//*[@content-desc!="" or @label!=""]')
        seen: list[str] = []
        for e in els:
            for attr in ("content-desc", "label"):
                v = e.get_attribute(attr)
                if v and v not in seen:
                    seen.append(v)
        print(f"共 {len(seen)} 个标签：")
        for v in seen:
            print(" -", v)

        if args.screenshot:
            out = s.evidence_dir / "dump_labels.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            d.get_screenshot_as_file(str(out))
            print("截图:", out)
    finally:
        d.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
