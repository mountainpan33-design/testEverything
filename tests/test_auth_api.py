"""接口层用例：登录与任务列表（只读，不产生业务数据）。

对应 testcases.md：
  AUTH-01 主站账号登录成功进入 onboarding（L2 部分）
  AUTH-03 错误密码登录失败
  TASK-01 首页 my-assignments 列表加载
  TASK-02 不可用任务标记（只读校验）
"""
from __future__ import annotations

import pytest

from apis.collector_client import AuthError, CollectorClient
from config.settings import Settings
from core.assertions import assert_api, skip

pytestmark = pytest.mark.api


@pytest.fixture(scope="module")
def settings() -> Settings:
    s = Settings()
    missing = s.missing_credentials()
    if missing:
        pytest.skip(f"缺少配置 {missing}，无法跑接口用例")
    return s


@pytest.fixture(scope="module")
def client(settings) -> CollectorClient:
    c = CollectorClient(settings.api_base, settings.main_site_host)
    c.login(settings.username, settings.password)
    return c


# ---------------------------------------------------------------- AUTH-01
def test_auth_01_login_returns_token_and_identity(settings):
    """登录成功：拿到 token，身份含 username/displayName。"""
    c = CollectorClient(settings.api_base, settings.main_site_host)
    data = c.login(settings.username, settings.password)

    assert_api(
        CollectorClient.assert_logged_in(data),
        "登录应返回非空 token", rule="R-AUTH-01",
        expected="code=200 且 data 为非空 token", actual=f"token 存在={bool(data.get('token'))}",
    )
    user = data["user"]
    assert_api(bool(user.get("username")), "身份应含 username", rule="R-AUTH-01",
               expected="/auth/me 返回 username", actual=str(user.get("username")))
    assert_api(bool(user.get("displayName")), "身份应含 displayName", rule="R-AUTH-01",
               expected="/auth/me 返回 displayName", actual=str(user.get("displayName")))
    assert_api(bool(user.get("id")), "身份应含 id", rule="R-AUTH-01",
               expected="/auth/me 返回 id", actual=str(user.get("id")))


# ---------------------------------------------------------------- AUTH-03
def test_auth_03_wrong_password_rejected(settings):
    """错误密码：必须登录失败，且错误信息非空。

    只尝试一次，避免触发服务端可能的失败次数限制。
    """
    c = CollectorClient(settings.api_base, settings.main_site_host)
    rejected = False
    code = None
    message = ""
    try:
        c.login(settings.username, settings.password + "_wrong")
    except AuthError as e:
        rejected = True
        code = e.code
        message = str(e)
    assert_api(rejected, "错误密码必须被拒绝", rule="R-AUTH-02",
               expected="code!=200 且无 token", actual=f"是否拒绝={rejected}")
    assert_api(code != 200, "业务码不应为 200", rule="R-AUTH-02",
               expected="code != 200", actual=str(code))
    assert_api(bool(message), "失败应带可读信息", rule="R-AUTH-02",
               expected="非空 message", actual=message[:60])


# ---------------------------------------------------------------- TASK-01
def test_task_01_my_assignments_shape(client):
    """任务列表：返回数组，元素含 id/taskId，且与详情接口一致。"""
    assignments = client.my_assignments()
    assert_api(isinstance(assignments, list), "my-assignments 应返回数组",
               rule="R-TASK-01", expected="数组", actual=type(assignments).__name__)

    if not assignments:
        skip("R-TASK-01", "当前账号没有 assignment，无法校验字段", layer="L2-API")
        pytest.skip("当前账号没有 assignment，无法校验字段")

    first = assignments[0]
    assert_api(bool(first.get("id")), "任务应含 id", rule="R-TASK-01",
               expected="id 非空", actual=str(first.get("id")))
    assert_api(bool(first.get("taskId")), "任务应含 taskId", rule="R-TASK-01",
               expected="taskId 非空", actual=str(first.get("taskId")))

    # 一致性：列表里的 id 能查到详情
    detail = client.assignment(first["id"])
    assert_api(detail.get("id") == first["id"], "详情 id 应与列表一致", rule="R-TASK-01",
               expected=first["id"], actual=str(detail.get("id")))
    assert_api(detail.get("taskId") == first["taskId"], "详情 taskId 应与列表一致",
               rule="R-TASK-01", expected=str(first["taskId"]),
               actual=str(detail.get("taskId")))


# ---------------------------------------------------------------- TASK-02
def test_task_02_unavailable_flags_are_readable(client):
    """不可用任务：unavailableReason 空/非空语义可读（只读校验，不改变状态）。"""
    assignments = client.my_assignments()
    if not assignments:
        skip("R-TASK-02", "当前账号没有 assignment", layer="L2-API")
        pytest.skip("当前账号没有 assignment")

    bad = [
        a.get("id") for a in assignments
        if not (a.get("unavailableReason") is None or isinstance(a.get("unavailableReason"), str))
    ]
    assert_api(not bad, "unavailableReason 类型必须是字符串或缺失", rule="R-TASK-02",
               expected="全部为 str/None", actual=f"异常项: {bad}")
