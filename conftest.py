"""pytest fixtures 与失败留证 hook。

fixture 层次：
  settings (session) —— 读 .env 一次
  driver   (session) —— 按 platform × source 创建 Appium driver，session 结束 quit
  run_id   (function)—— 每条用例唯一 run_id
  evidence (function)—— 失败留证 / 成功清理
"""
from __future__ import annotations

import pytest

from config.settings import Settings
from core import results
from core.driver_factory import create_driver
from core.evidence import EvidenceCollector
from core.run_id import new_run_id
from reporting import report as report_mod
from utils.logger import log


def pytest_sessionstart(session):
    results.reset()


def pytest_runtest_setup(item):
    results.set_case(item.nodeid)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """把每个 phase 的 report 挂到 item 上，供 fixture teardown 判断失败。"""
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{call.when}", report)
    if report.skipped and call.when in ("setup", "call"):
        reason = ""
        if isinstance(getattr(report, "longrepr", None), tuple):
            reason = str(report.longrepr[2])
        results.record(rule="", status="skip", message=reason)


def pytest_sessionfinish(session, exitstatus):
    """收尾时生成报告（失败不影响测试结果）。"""
    try:
        path = report_mod.write(Settings())
        session.config._app_auto_report = str(path)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        log.warning("生成测试报告失败: %s", e)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    path = getattr(config, "_app_auto_report", None)
    if path:
        terminalreporter.write_sep("=", "测试报告")
        terminalreporter.write_line(f"HTML: {path}")
        terminalreporter.write_line(f"JSON: {path.replace('.html', '.json')}")


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def driver(settings):
    missing = settings.missing_credentials()
    if missing:
        pytest.skip(f"缺少必填配置 {missing}，请在 .env 补齐后重试")
    d = create_driver(settings)
    yield d
    d.quit()


@pytest.fixture(scope="function")
def run_id(request) -> str:
    return new_run_id(request.node.nodeid)


@pytest.fixture(scope="function")
def evidence(driver, run_id, settings, request):
    ec = EvidenceCollector(driver, run_id, settings.evidence_dir)
    yield ec
    # teardown：失败留证 / 成功清理
    call = getattr(request.node, "rep_call", None)
    setup = getattr(request.node, "rep_setup", None)
    if (call is not None and call.failed) or (setup is not None and setup.failed):
        ec.collect_on_failure(udid=settings.android_udid or None)
    else:
        ec.cleanup_on_success()
