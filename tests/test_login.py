"""登录链路冒烟：UI 驱动 + 接口断言（L1 + L2）。"""
from __future__ import annotations

import pytest

from apis.collector_client import CollectorClient
from core.assertions import assert_api, assert_ui
from pages.login_page import LoginPage


@pytest.mark.smoke
def test_login_ok(driver, settings, evidence):
    login_page = LoginPage(driver)
    login_page.ensure_new_server()  # 默认 legacy，主站账号必须先切新服务器
    login_page.login(settings.username, settings.password)

    # L1 UI：登录成功后离开登录页（落地 /consent、/permissions 或 /home，随账号 onboarding 状态）
    assert_ui(login_page.is_logged_in(), "登录成功后应离开登录页")

    # L2 接口：同一账号走新协议登录，验证 token 有效（副作用校验）
    client = CollectorClient(settings.api_base, settings.main_site_host)
    data = client.login(settings.username, settings.password)
    assert_api(CollectorClient.assert_logged_in(data), "登录接口应返回有效 token")
