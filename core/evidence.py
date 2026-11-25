"""失败留证 / 成功清理。

策略（对齐计划「失败留证、成功清理」）：
  - 失败：截图 + page_source 写入 evidence/<run_id>/，供报告归档；
  - 成功：只清理本次会话登记的临时文件，不误删采集产物（产物校验完再删）。
"""
from __future__ import annotations

from pathlib import Path

from appium.webdriver.webdriver import WebDriver

from utils.logger import log


class EvidenceCollector:
    def __init__(self, driver: WebDriver, run_id: str, evidence_dir: Path):
        self.driver = driver
        self.run_id = run_id
        self.root = evidence_dir / run_id
        self._tmp_files: list[Path] = []

    def register_tmp(self, path: Path) -> None:
        """登记会话产生的临时文件，成功时统一清理。"""
        self._tmp_files.append(path)

    def collect_on_failure(self, udid: str | None = None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.driver.get_screenshot_as_file(str(self.root / "screenshot.png"))
        except Exception as e:  # noqa: BLE001 - 留证失败不能反过来打断用例
            log.warning("截图失败: %s", e)
        try:
            (self.root / "page_source.xml").write_text(
                self.driver.page_source, encoding="utf-8"
            )
        except Exception as e:  # noqa: BLE001
            log.warning("page_source 保存失败: %s", e)
        # Android：把 logcat 也留下来，401/崩溃/RN 报错都在里面
        if udid:
            try:
                from core.device_files import dump_logcat, grep_logcat

                path = dump_logcat(udid, self.root / "logcat.txt")
                if path is not None:
                    hits = grep_logcat(
                        path, ["401", "unauthorized", "expire", "请先登录", "登录已失效"]
                    )
                    if hits:
                        (self.root / "logcat_hits.txt").write_text(
                            "\n".join(hits), encoding="utf-8"
                        )
                        log.warning("logcat 关键行已存: %s", self.root / "logcat_hits.txt")
            except Exception as e:  # noqa: BLE001
                log.warning("logcat 留证失败: %s", e)
        log.info("失败留证已写入 %s", self.root)

    def cleanup_on_success(self) -> None:
        for p in self._tmp_files:
            try:
                p.unlink(missing_ok=True)
            except OSError as e:  # noqa: BLE001
                log.warning("清理临时文件失败 %s: %s", p, e)
