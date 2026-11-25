"""采集端 API 客户端：供 L2 接口层断言复用。

2026-11 起登录协议已改为「主站 auth-center + DCP 身份解析」两步走（新服务器 package-v1）：

  1. POST {mainSite}/api/auth-center/auth/login
     body { username: Base64(encodeURIComponent(v)), password: 同 }
     响应 envelope {code, data, message}，HTTP 200 不代表成功，必须 code==200；
     data 即裸 token（不是 data.token）。
  2. GET {dcpBase}/auth/me + Bearer token → 身份。

旧服务器（legacy，collector-v1，52.39）仍是 POST /api/v1/auth/platform/login → {token,user}。
两套账号体系互不相通，token 不通用。
"""
from __future__ import annotations

import base64
import urllib.parse

import requests

from utils.logger import log


class AuthError(Exception):
    """登录失败（主站 auth-center 业务错误，或 DCP 身份解析失败）。"""

    def __init__(self, code: int | None, message: str):
        super().__init__(message)
        self.code = code


def encode_auth_field(value: str) -> str:
    """对齐 mainSiteAuth.encodeAuthField：btoa(encodeURIComponent(value))。

    encodeURIComponent 先转义（输出纯 ASCII），再 Base64；顺序不能反，
    否则非 ASCII 密码（如中文）会损坏。
    """
    quoted = urllib.parse.quote(value, safe="-_.!~*'()")
    return base64.b64encode(quoted.encode()).decode()


class CollectorClient:
    def __init__(self, dcp_base: str, main_site_host: str = "", timeout: int = 15):
        self.dcp_base = dcp_base.rstrip("/")
        self.main_site_host = main_site_host.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    # ---------- URL 拼接 ----------
    def _dcp_url(self, path: str) -> str:
        """对齐 collectionConfig.resolveCollectionApiUrl：base 带 /api/v1 时去重，避免 //api/v1/api/v1。"""
        if self.dcp_base.endswith("/api/v1") and path.startswith("/api/v1/"):
            return self.dcp_base + path[len("/api/v1"):]
        return self.dcp_base + path

    # ---------- 鉴权 ----------
    def login(self, username: str, password: str) -> dict:
        """新协议（package-v1）登录。返回 {token, user}。"""
        if not self.main_site_host:
            raise AuthError(None, "未配置主站地址 QA_MAIN_SITE_HOST")

        r = self.session.post(
            f"{self.main_site_host}/api/auth-center/auth/login",
            json={
                "username": encode_auth_field(username),
                "password": encode_auth_field(password),
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        env = r.json()
        if env.get("code") != 200:
            raise AuthError(env.get("code"), env.get("message") or "登录失败")
        token = env.get("data")
        if not isinstance(token, str) or not token:
            raise AuthError(env.get("code"), "登录服务未返回有效凭证")

        self.session.headers.update({"Authorization": f"Bearer {token}"})
        user = self.me()
        return {"token": token, "user": user}

    def me(self) -> dict:
        r = self.session.get(self._dcp_url("/api/v1/auth/me"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def logout(self) -> None:
        # 新协议无 DCP 登出端点；清本地 token 即等效于登出
        self.session.headers.pop("Authorization", None)

    # ---------- 任务 ----------
    def my_assignments(self) -> list:
        r = self.session.get(
            self._dcp_url("/api/v1/collection/my-assignments"), timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()

    def assignment(self, assignment_id: str) -> dict:
        r = self.session.get(
            self._dcp_url(f"/api/v1/collection/assignments/{assignment_id}"),
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    # ---------- 资源包上传（package-v1，后续接入黄金链路）----------
    def create_package(self, assignment_id: str, request_id: str) -> dict:
        r = self.session.post(
            self._dcp_url(f"/api/v1/collection/assignments/{assignment_id}/packages"),
            json={"requestId": request_id},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def assert_logged_in(data: dict) -> bool:
        """登录结果是否有效（token 存在）。"""
        return isinstance(data.get("token"), str) and bool(data["token"])
