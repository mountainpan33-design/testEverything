"""采集链路页面流 —— 状态机 + 自适应填答。

设计原则（针对「实际情况变数多」）：
  1. 每步先识别当前页面（core.screen.detect），再决定动作，不假设上一步必然成功；
  2. 页面跑偏时给出明确原因（登录页=会话失效、precheck=误触放弃、未知=列出标签）；
  3. QC 不再写死选项：按行分组找「每组至少一个未选」自动补选，补空文本，直到提交可用；
  4. 点击前校验落点，避开底部固定按钮区，防止误触「放弃并重录」；
  5. 所有等待都是条件等待，不用固定 sleep。
"""
from __future__ import annotations

import time

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import StaleElementReferenceException

from core import inputs as input_probe
from core import limits
from core import screen as screen_detect
from core.assertions import check
from pages.base_page import BasePage
from pages.login_page import LoginPage
from utils.logger import log

# 非选项节点：导航/系统类文案，自动填答时跳过
NAV_STOPWORDS = {
    "返回", "取消", "退出", "退出登录", "登录", "记住密码", "忘记密码",
    "刷新", "刷新任务", "刷新列表", "重试", "删除", "保存",
}

SYSTEM_ALLOW_TEXTS = [
    "允许", "仅在使用中允许", "使用应用时允许", "始终允许",
    "While using the app", "Allow", "OK",
]

# 底部固定 footer 的起点（占屏高比例）。QC 页底部是「放弃并重录」，误触作废整段采集。
FOOTER_TOP = 0.78
# 顶部状态栏的终点。低于它的元素点不到。
STATUS_BAR_BOTTOM = 0.06


def is_click_safe(center_y: float, screen_height: float, allow_bottom: bool = False) -> bool:
    """元素中心点是否可点。

    默认避开底部 footer；页面主 CTA 本身就长在底部时，调用方显式允许。
    抽成纯函数是为了能单测——这条规则曾经把权限页「进入首页」（中心在 95%）
    静默挡掉，跑满 60 秒超时才暴露。
    """
    ratio = center_y / screen_height
    if ratio < STATUS_BAR_BOTTOM:
        return False
    if not allow_bottom and ratio > FOOTER_TOP:
        return False
    return True


class CaptureFlow(BasePage):
    # ------------------------------------------------------------------ 定位符
    HOME_RECORD = (
        AppiumBy.XPATH,
        '//*[(contains(@content-desc,"录制") and contains(@content-desc,"视频"))'
        ' or (contains(@label,"录制") and contains(@label,"视频"))]',
    )
    CONSENT_AGREE = (
        AppiumBy.XPATH, '//*[contains(@content-desc,"同意并继续")]'
    )
    CONSENT_ITEM = (
        AppiumBy.XPATH, '//*[contains(@content-desc,"勾选")]'
    )
    PERM_ENABLE = (
        AppiumBy.XPATH, '//*[contains(@content-desc,"开启权限")]'
    )
    PERM_ENTER_HOME = (
        AppiumBy.XPATH, '//*[contains(@content-desc,"进入首页")]'
    )
    PRECHECK_CHECK = (AppiumBy.ACCESSIBILITY_ID, "确认画面里没有未授权的人")
    PRECHECK_CTA = (
        AppiumBy.XPATH,
        '//*[contains(@text,"开始校准") or contains(@content-desc,"开始校准")]',
    )
    CALIB_START = (
        AppiumBy.XPATH, '//*[contains(@content-desc,"开始录制")]'
    )
    RECORD_STOP = (
        AppiumBy.XPATH, '//*[contains(@content-desc,"结束录制")]'
    )
    TRIM_SKIP = (
        AppiumBy.XPATH, '//*[contains(@content-desc,"不剪")]'
    )
    QC_SUBMIT = (
        AppiumBy.XPATH,
        '//*[contains(@content-desc,"加入上传队列") or contains(@content-desc,"仍然上传")]',
    )
    DONE_MARK = (
        AppiumBy.XPATH, '//*[contains(@content-desc,"本地交付包")]'
    )
    DEMO_NAME = (AppiumBy.XPATH, '//*[@text="林晓雨"]')
    ME_TAB = (
        AppiumBy.XPATH, '//*[contains(@content-desc,"我的")]'
    )
    SIGN_OUT = (
        AppiumBy.XPATH, '//*[contains(@content-desc,"退出登录")]'
    )
    ALERT_SIGN_OUT = (AppiumBy.XPATH, '//*[@text="退出"]')

    # ------------------------------------------------------------------ 基础工具
    def _exists(self, locator, timeout: float = 1.0) -> bool:
        deadline = time.time() + timeout
        while True:
            try:
                if self.driver.find_elements(*locator):
                    return True
            except Exception:  # noqa: BLE001
                pass
            if time.time() >= deadline:
                return False
            time.sleep(0.2)

    def _tap_if_present(self, locator, allow_bottom: bool = False) -> bool:
        try:
            els = [e for e in self.driver.find_elements(*locator) if e.is_displayed()]
        except Exception:  # noqa: BLE001
            return False
        if not els:
            return False
        return self._click_safely(els[0], allow_bottom=allow_bottom)

    def _click_safely(self, el, allow_bottom: bool = False) -> bool:
        """点击元素，默认避开底部固定 footer（QC 页底部是「放弃并重录」，误触作废整段采集）。

        但页面的主 CTA 本身就长在底部（权限页「进入首页」bounds y=2209~2356 / 屏高 2400，
        中心在 95%），对这些已知安全的按钮必须显式传 allow_bottom=True。
        曾因为没传，权限页空转 60 秒一次都没点中，报「未能进入首页」。
        """
        try:
            rect = el.rect
            h = self.driver.get_window_size()["height"]
            cy = rect["y"] + rect["height"] / 2
            if not is_click_safe(cy, h, allow_bottom):
                return False
            el.click()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _swipe(self, from_y: float, to_y: float) -> None:
        size = self.driver.get_window_size()
        w, h = size["width"], size["height"]
        try:
            self.driver.swipe(w * 0.5, h * from_y, w * 0.5, h * to_y, 400)
        except Exception:  # noqa: BLE001
            pass
        self._swipe_count = getattr(self, "_swipe_count", 0) + 1
        if self._swipe_count % 5 == 0:
            log.info("[flow] 已累计滑动 %s 次", self._swipe_count)
        time.sleep(0.45)

    def _swipe_up(self) -> None:
        self._swipe(0.72, 0.32)

    def _swipe_down(self) -> None:
        self._swipe(0.32, 0.72)

    def _keyboard_shown(self) -> bool:
        try:
            return bool(self.driver.is_keyboard_shown())
        except Exception:  # noqa: BLE001
            return False

    def _dismiss_keyboard(self) -> None:
        """收起键盘，绝不按 BACK（Android 上 hide_keyboard 就是 BACK，会退出页面）。"""
        if not self._keyboard_shown():
            return
        for label in ("上传前检查", "具体场所（L2）"):
            try:
                els = self.driver.find_elements(AppiumBy.XPATH, f'//*[@text="{label}"]')
                if els and self._click_safely(els[0]):
                    time.sleep(0.4)
                    break
            except Exception:  # noqa: BLE001
                pass
        if not self._keyboard_shown():
            return
        try:
            self.driver.hide_keyboard()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)

    def screen_labels(self, limit: int = 40) -> str:
        labels: list[str] = []
        for xpath in ('//*[@content-desc!=""]', '//*[@text!=""]'):
            try:
                els = self.driver.find_elements(AppiumBy.XPATH, xpath)
            except Exception:  # noqa: BLE001
                continue
            for e in els:
                if len(labels) >= limit:
                    break
                try:
                    v = (e.get_attribute("content-desc") or e.get_attribute("text") or "").strip()
                except Exception:  # noqa: BLE001
                    continue
                if v and v not in ("null", "None") and v not in labels:
                    labels.append(v)
            if len(labels) >= limit:
                break
        return "; ".join(labels)[:1500] or "<界面上没有可读标签>"

    def _guard(self, where: str, expect: str | None = None) -> str:
        """确认当前页面；跑偏就给明确原因。返回实际页面名。"""
        actual = screen_detect.detect(self.driver)
        if expect is None or actual == expect:
            return actual or "unknown"
        if actual == "login":
            raise AssertionError(
                f"{where}：页面停在登录页，会话已失效（多为接口 401 触发自动登出），"
                "本轮无法继续。evidence 下的 logcat_hits.txt 有具体原因。"
            )
        if actual == "precheck" and expect != "precheck":
            raise AssertionError(
                f"{where}：页面退回了「录前自检」，本轮采集已失效（多因误触放弃/返回）。"
            )
        raise AssertionError(
            f"{where}：期望在「{expect}」页，实际在「{actual}」。界面标签：{self.screen_labels()}"
        )

    # ------------------------------------------------------------------ 登录 + onboarding
    def is_demo_session(self) -> bool:
        """是否为内置演示身份（linxy/林晓雨）：说明没有真实会话。"""
        return self._exists(self.DEMO_NAME, timeout=1)

    def sign_out_demo(self) -> None:
        log.warning("检测到演示身份「林晓雨」，先退出登录再切真实账号")
        # 「我的」是底部 tab（(tabs)/_layout.tsx tabBar），必然落在安全区外
        self._tap_if_present(self.ME_TAB, allow_bottom=True)
        time.sleep(1)
        if not self._tap_if_present(self.SIGN_OUT, allow_bottom=True):
            raise AssertionError("未找到「退出登录」按钮，无法切回真实账号")
        time.sleep(1)
        self._tap_if_present(self.ALERT_SIGN_OUT, allow_bottom=True)
        screen_detect.wait_for(self.driver, "login", timeout=15)

    def ensure_ready(self, username: str, password: str, timeout: int = 60) -> None:
        """状态机：把 App 推到「已登录且在首页」。"""
        login_page = LoginPage(self.driver)
        deadline = time.time() + timeout
        last_screen = None
        # 页面没变化且没有任何动作成功，就是在空转。等满 timeout 才报错太贵，
        # 而且报出来只有一句「未能进入首页」，看不出是按钮点不动。
        stall = 0
        while time.time() < deadline:
            s = screen_detect.detect(self.driver)
            if s != last_screen:
                log.info("[screen] %s", s or "unknown")
                last_screen = s
                stall = 0

            if s == "login":
                login_page.ensure_new_server()
                login_page.login(username, password)
                assert login_page.is_logged_in(25), "登录失败：未离开登录页"
                continue
            if s == "consent":
                acted = False
                for el in self.driver.find_elements(*self.CONSENT_ITEM):
                    try:
                        acted = self._click_safely(el) or acted
                    except Exception:  # noqa: BLE001
                        pass
                acted = self._tap_if_present(self.CONSENT_AGREE, allow_bottom=True) or acted
                time.sleep(1)
                stall = 0 if acted else stall + 1
                if stall >= 8:
                    raise AssertionError(
                        f"停在协议页：勾选或「同意并继续」点了 {stall} 次都没生效。"
                        f"界面标签：{self.screen_labels()}{self._stuck_hint()}"
                    )
                continue
            if s == "permissions":
                if self._tap_if_present(self.PERM_ENABLE, allow_bottom=True):
                    time.sleep(1.5)
                    for text in SYSTEM_ALLOW_TEXTS:
                        if self._tap_if_present((AppiumBy.XPATH, f'//*[@text="{text}"]')):
                            break
                    time.sleep(1)
                    continue
                if self._tap_if_present(self.PERM_ENTER_HOME, allow_bottom=True):
                    time.sleep(1)
                    continue
                stall += 1
                if stall >= 8:
                    raise AssertionError(
                        f"停在权限页：「进入首页 / 开启权限」点了 {stall} 次都没生效。"
                        f"界面标签：{self.screen_labels()}{self._stuck_hint()}"
                    )
            if s == "home":
                if self.is_demo_session():
                    self.sign_out_demo()
                    continue
                return
            time.sleep(0.5)

        raise AssertionError(
            f"{timeout}s 内未能进入首页，当前页面：{screen_detect.detect(self.driver)}。"
            f"界面标签：{self.screen_labels()}{self._stuck_hint()}"
        )

    def _stuck_hint(self) -> str:
        """卡住时给出「按钮在但点不动」的原因，别只报一句超时。"""
        for name, loc in (
            ("进入首页/开启权限", (AppiumBy.XPATH, '//*[contains(@content-desc,"进入首页")'
                                                 ' or contains(@content-desc,"开启权限")]')),
            ("结束录制", self.RECORD_STOP),
            ("开始录制", self.CALIB_START),
        ):
            try:
                els = [e for e in self.driver.find_elements(*loc) if e.is_displayed()]
            except Exception:  # noqa: BLE001
                continue
            for e in els:
                try:
                    rect = e.rect
                    h = self.driver.get_window_size()["height"]
                    cy = rect["y"] + rect["height"] / 2
                    if not is_click_safe(cy, h, allow_bottom=False):
                        pct = cy / h * 100
                        return (
                            f"\n诊断：找到「{name}」按钮，但中心在屏高 {pct:.0f}%，"
                            "被 _click_safely 的底部安全区规则挡掉了——该调用点需要 "
                            "allow_bottom=True。"
                        )
                except Exception:  # noqa: BLE001
                    continue
        return ""

    # ------------------------------------------------------------------ 采集各步
    def start_first_available_assignment(self, timeout: int = 60) -> None:
        self._guard("开始任务", expect="home")
        deadline = time.time() + timeout
        while time.time() < deadline:
            for b in self.driver.find_elements(*self.HOME_RECORD):
                # 首页没有「放弃并重录」这类危险 footer，卡片里的录制按钮即便落在
                # 屏幕下半区也要能点（任务卡少时按钮位置会很低）。
                if b.is_displayed() and b.is_enabled() and self._click_safely(
                    b, allow_bottom=True
                ):
                    screen_detect.wait_for(self.driver, "precheck", timeout=20)
                    return
            time.sleep(0.5)
            self._swipe_up()
        raise AssertionError(
            "首页没有可用的「录制…视频」按钮（兼容考核/作业等叫法）："
            f"任务为空、不可用或仍在审核中。界面标签：{self.screen_labels()}"
        )

    PRIVACY_LABEL = "确认画面里没有未授权的人"

    def _checkbox_checked(self, label: str) -> bool:
        try:
            els = self.driver.find_elements(
                AppiumBy.XPATH, f'//*[@content-desc="{label}"]'
            )
        except Exception:  # noqa: BLE001
            return False
        for e in els:
            try:
                if str(e.get_attribute("checked")).lower() == "true":
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def confirm_precheck(self) -> None:
        self._guard("录前自检", expect="precheck")

        # 隐私勾选框在底部 footer（canProceed = checksPass && privacyConfirmed），
        # 必须 allow_bottom=True，否则被安全区规则挡掉、永远处于禁用状态。
        if not self._checkbox_checked(self.PRIVACY_LABEL):
            self._tap_if_present(self.PRECHECK_CHECK, allow_bottom=True)
        if not self._checkbox_checked(self.PRIVACY_LABEL):
            for el in self.driver.find_elements(
                AppiumBy.XPATH, '//*[contains(@text,"没有未授权的人")]'
            ):
                if self._click_safely(el, allow_bottom=True):
                    break
            time.sleep(0.3)

        cta = self.find(self.PRECHECK_CTA, timeout=10)
        if not cta.is_enabled():
            raise AssertionError(
                "precheck 按钮不可用：隐私勾选="
                f"{self._checkbox_checked(self.PRIVACY_LABEL)}；"
                "定位/运动/相机/麦克风检查可能未通过。"
                f"界面标签：{self.screen_labels()}"
            )
        self._click_safely(cta, allow_bottom=True) or cta.click()
        if screen_detect.wait_for(self.driver, "calib", timeout=30) is None:
            self._guard("进入校准页", expect="calib")

    def start_from_calib(self) -> None:
        self._guard("校准页", expect="calib")
        # 「开始录制」在右侧侧栏底部（calib.tsx sidebar + actionBlock，space-between 贴底）
        self._tap_if_present(self.CALIB_START, allow_bottom=True) or self.find(
            self.CALIB_START, 10
        ).click()
        if screen_detect.wait_for(self.driver, "record", timeout=45) is None:
            self._guard("进入录制页", expect="record")

    def record_for(self, seconds: int) -> None:
        time.sleep(seconds)

    def stop_recording(self) -> None:
        self._guard("录制页", expect="record")
        # 「结束录制」在右侧侧栏底部（Hud.tsx controlsBlock，space-between 贴底）
        self._tap_if_present(self.RECORD_STOP, allow_bottom=True)
        if screen_detect.wait_for(self.driver, "trim", timeout=90) is None:
            self._guard("结束录制后进入剪辑页", expect="trim")

    def skip_trim(self) -> None:
        self._guard("剪辑页", expect="trim")
        # 「不剪」和「完成剪辑」并排躺在 footer（trim.tsx styles.footer），必须放行底部
        self._tap_if_present(self.TRIM_SKIP, allow_bottom=True)
        if screen_detect.wait_for(self.driver, "qc", timeout=60) is None:
            self._guard("跳过剪辑后进入 QC", expect="qc")

    def wait_done(self, timeout: int = 240) -> None:
        if screen_detect.wait_for(self.driver, "done", timeout=timeout) is None:
            self._guard("提交后进入完成页", expect="done")

    # ------------------------------------------------------------------ QC 自适应填答
    def _chip_nodes(self) -> list[dict]:
        out: list[dict] = []
        try:
            els = self.driver.find_elements(AppiumBy.XPATH, '//*[@content-desc!=""]')
        except Exception:  # noqa: BLE001
            return out
        for e in els:
            try:
                label = (e.get_attribute("content-desc") or "").strip()
                if not label or label in NAV_STOPWORDS:
                    continue
                sel = e.get_attribute("selected")
                if sel is None:
                    continue
                out.append(
                    {
                        "label": label,
                        "el": e,
                        "selected": str(sel).lower() == "true",
                        "rect": e.rect,
                    }
                )
            except Exception:  # noqa: BLE001
                continue
        return out

    def _chip_groups(self) -> list[list[dict]]:
        """按行聚类：同一行的 chip 属于同一道题（单选/多选）。"""
        return screen_detect.group_chips(self._chip_nodes())

    def _is_chip_selected(self, label: str) -> bool:
        try:
            els = self.driver.find_elements(
                AppiumBy.XPATH, f'//*[@content-desc="{label}"]'
            )
        except Exception:  # noqa: BLE001
            return False
        for e in els:
            try:
                if str(e.get_attribute("selected")).lower() == "true":
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _tap_chip(self, label: str, max_swipes: int = limits.MAX_SWIPES) -> bool:
        """点选项并校验选中；每次重新查找，绝不跨操作持有句柄。

        兼容两种情况：选项在折叠区下方（双向滚动找），或选项在底部 footer 带里
        （先滚到可点区间再点，避免被安全区静默拒绝）。
        """
        h = self.driver.get_window_size()["height"]
        for attempt in range(max_swipes + 1):
            if self._is_chip_selected(label):
                return True
            try:
                els = [
                    e
                    for e in self.driver.find_elements(
                        AppiumBy.XPATH, f'//*[@content-desc="{label}"]'
                    )
                    if e.is_displayed()
                ]
            except Exception:  # noqa: BLE001
                els = []
            if not els:
                # 前一半尝试向上找（内容在下方），后一半向下找（滚过头了）
                if attempt < max_swipes // 2:
                    self._swipe_up()
                else:
                    self._swipe_down()
                continue
            el = els[0]
            try:
                r = el.rect
                cy = r["y"] + r["height"] / 2
                if cy > h * self._BAND_BOTTOM:
                    self._swipe_up()
                    continue
                if cy < h * 0.06:
                    self._swipe_down()
                    continue
            except Exception:  # noqa: BLE001
                pass
            clicked = self._click_safely(el)
            time.sleep(0.35)
            if screen_detect.detect(self.driver) == "precheck":
                raise AssertionError(
                    f"点击「{label}」时误触了底部按钮，页面退回录前自检，本轮采集已作废"
                )
            if self._is_chip_selected(label):
                return True
            if not clicked:
                self._swipe_up()
        return False

    def _autofill_chips(self, rounds: int = limits.MAX_ROUNDS) -> bool:
        """每组（同一行）若全未选，就点一个；直到所有组都有选中项。"""
        for _ in range(rounds):
            groups = self._chip_groups()
            missing = [g for g in groups if not any(i["selected"] for i in g)]
            if not missing:
                return True
            progressed = False
            for g in missing:
                label = g[0]["label"]
                if self._tap_chip(label):
                    progressed = True
            if not progressed:
                return False
        return True

    # 可交互带：滚动时把目标带到这个纵向区间再点，避开顶部状态栏与底部 footer/键盘
    _BAND_TOP = 0.08
    _BAND_BOTTOM = 0.68

    def _edit_texts(self) -> list:
        for cls in ("android.widget.EditText", "XCUIElementTypeTextField"):
            try:
                els = self.driver.find_elements(AppiumBy.CLASS_NAME, cls)
            except Exception:  # noqa: BLE001
                els = []
            if els:
                return els
        return []

    def _attr(self, e, name: str) -> str:
        try:
            v = e.get_attribute(name)
        except Exception:  # noqa: BLE001
            return ""
        return "" if v is None else str(v)

    def _meta(self, e) -> dict:
        """读一个输入框的判定所需属性（键名与 core.inputs 的参数对齐）。"""
        return {
            "text": self._attr(e, "text"),
            "hint": self._attr(e, "hint"),
            "showing_hint": self._attr(e, "showing-hint"),
            "multiline": self._attr(e, "multiline"),
            "enabled": self._attr(e, "enabled"),
        }

    def _is_fillable(self, e, allow_multiline: bool = False) -> bool:
        """可用、单行（默认）、且没有真实内容 —— 才需要填。

        注意：空输入框的 text 属性是占位示例文案（如「例如：电子厂、厨房、超市」），
        不是空串。判空必须走 core.inputs（showing-hint / hint 比对），
        否则会把整页空框当成已填、直接跳过（QC 提交按钮因此一直灰着）。
        """
        try:
            meta = self._meta(e)
        except Exception:  # noqa: BLE001
            return False
        fn = input_probe.is_fillable_any if allow_multiline else input_probe.is_fillable_input
        return fn(**meta)

    def _log_inputs(self, tag: str) -> None:
        """把当前页所有输入框打成一行日志，排查「填不进去」时看这条就够。"""
        for i, e in enumerate(self._edit_texts()):
            try:
                r = e.rect
                where = f"[{r['y']},{r['y'] + r['height']}]"
            except Exception:  # noqa: BLE001
                where = "?"
            m = self._meta(e)
            log.info(
                "[QC] %s 输入框#%s text=%r hint=%r multiline=%s enabled=%s y=%s",
                tag, i, m["text"], m["hint"], m["multiline"], m["enabled"], where,
            )

    def _bring_into_band(self, index: int, attempts: int = limits.MAX_SWIPES) -> bool:
        """把第 index 个输入框滚到可点区间。双向滚动，每次重新查找避免 stale。"""
        h = self.driver.get_window_size()["height"]
        for _ in range(attempts):
            edits = self._edit_texts()
            if index >= len(edits):
                self._swipe_up()
                continue
            try:
                r = edits[index].rect
                cy = r["y"] + r["height"] / 2
            except Exception:  # noqa: BLE001
                self._swipe_up()
                continue
            if h * self._BAND_TOP <= cy <= h * self._BAND_BOTTOM:
                return True
            if cy > h * self._BAND_BOTTOM:
                self._swipe_up()
            else:
                self._swipe_down()
        return False

    def _fill_empty_inputs(
        self,
        values: list[str],
        max_rounds: int = limits.MAX_ROUNDS,
        allow_multiline: bool = False,
    ) -> int:
        """填所有空输入框：先滚到可点区间，再输入，每填一个收一次键盘并回读校验。

        旧实现两个坑，都会表现为「一直滑屏、不写字」：
          1. 点不中只跳过、不滚动；
          2. 用「text 非空 = 已填」判断 —— 空框的 text 其实是占位示例文案，
             导致整页输入框被当成已填全部跳过。
        """
        used = 0
        for _ in range(max_rounds):
            progressed = False
            targets = [
                i for i, e in enumerate(self._edit_texts())
                if self._is_fillable(e, allow_multiline=allow_multiline)
            ]
            if targets:
                log.info("[QC] 待填输入框序号=%s（含多行=%s）", targets, allow_multiline)
            for idx in targets:
                val = values[used] if used < len(values) else f"QA-auto-{used + 1}"
                if not self._bring_into_band(idx):
                    log.warning("[QC] 第 %s 个输入框滚不进可点区，跳过", idx)
                    continue
                fresh = self._edit_texts()
                if idx >= len(fresh) or not self._is_fillable(
                    fresh[idx], allow_multiline=allow_multiline
                ):
                    continue
                el = fresh[idx]
                before = self._attr(el, "text")
                if not self._click_safely(el):
                    log.warning("[QC] 第 %s 个输入框点击未生效", idx)
                    continue
                try:
                    el.clear()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    el.send_keys(val)
                except Exception as exc:  # noqa: BLE001
                    log.warning("[QC] 第 %s 个输入框输入失败：%s", idx, exc)
                    self._dismiss_keyboard()
                    continue
                time.sleep(0.2)
                if not self._typed_ok(idx, val, before):
                    log.warning("[QC] 第 %s 个输入框写入未生效（期望 %r）", idx, val)
                    self._dismiss_keyboard()
                    continue
                used += 1
                progressed = True
                self._dismiss_keyboard()  # 键盘挡住下一个输入框
                log.info("[QC] 已填第 %s 个输入框 = %r", idx, val)
            if not progressed:
                break
        return used

    def _typed_ok(self, idx: int, val: str, before: str) -> bool:
        """回读确认内容真写进去了：仍是占位符 = 没写进去。"""
        edits = self._edit_texts()
        if idx >= len(edits):
            return False
        meta = self._meta(edits[idx])
        if input_probe.is_empty_value(meta["text"], meta["hint"], meta["showing_hint"]):
            return False
        after = meta["text"].strip()
        return after != before.strip() or val in after

    def _submit_button(self):
        try:
            els = self.driver.find_elements(*self.QC_SUBMIT)
        except Exception:  # noqa: BLE001
            return None
        return els[0] if els else None

    def _submit_enabled(self) -> bool:
        btn = self._submit_button()
        if btn is None:
            return False
        try:
            return bool(btn.is_enabled())
        except Exception:  # noqa: BLE001
            return False

    def _qc_hints(self) -> str:
        hints: list[str] = []
        for kw in ("不足", "请选择", "必填", "未选", "失败"):
            try:
                els = self.driver.find_elements(
                    AppiumBy.XPATH,
                    f'//*[contains(@text,"{kw}") or contains(@content-desc,"{kw}")]',
                )
            except Exception:  # noqa: BLE001
                continue
            for e in els:
                try:
                    t = (e.get_attribute("text") or e.get_attribute("content-desc") or "").strip()
                except Exception:  # noqa: BLE001
                    continue
                if t and t not in hints:
                    hints.append(t)
        return " | ".join(hints[:6]) or "<无明显提示>"

    def _scroll_to_submit(self, max_swipes: int = limits.MAX_SWIPES) -> bool:
        for _ in range(max_swipes + 1):
            if self._submit_button() is not None:
                return True
            self._swipe_up()
        return self._submit_button() is not None

    def submit_qc(
        self,
        lighting: str = "自然光",
        tools: str = "无",
        env_l1: str | None = None,
        skill: str | None = None,
        l2: str = "办公室",
        l3: str = "整理货架",
        timeout: int = limits.QC_TIMEOUT,
    ) -> None:
        """填完 QC 必填项并提交：先按配置值点，失败再自适应补齐。

        全程受 QC_TIMEOUT 约束：到点无论填到哪一步都立即失败并留证，
        不允许在真机上空转。
        """
        started = time.time()

        def remaining() -> float:
            return timeout - (time.time() - started)

        def ensure_budget(where: str) -> None:
            if remaining() <= 0:
                raise AssertionError(
                    f"QC 填答超出预算 {timeout}s（{where}）。页面提示：{self._qc_hints()}\n"
                    f"界面标签：{self.screen_labels()}"
                )

        self._guard("进入 QC", expect="qc")
        self._log_inputs("进入 QC 时")

        # 1) 优先使用配置值（可预期、可复现），候选数受 MAX_CANDIDATES 限制
        for c in list(dict.fromkeys([lighting, "自然光", "室内灯光", "混合光"]))[
            : limits.MAX_CANDIDATES
        ]:
            ensure_budget("选光线")
            if self._tap_chip(c):
                break
        for c in list(dict.fromkeys([tools, "无", "扫码枪"]))[: limits.MAX_CANDIDATES]:
            ensure_budget("选工具")
            if self._tap_chip(c):
                break
        if env_l1:
            self._tap_chip(env_l1)
        if skill:
            self._tap_chip(skill)
        self._fill_empty_inputs([l2, l3])
        log.info("[QC] 首轮填答完成（%.0fs），提交可用=%s",
                 time.time() - started, self._submit_enabled())

        # 2) 自适应补齐，轮数受 MAX_ROUNDS 限制
        for rnd in range(limits.MAX_ROUNDS):
            if self._submit_enabled():
                break
            ensure_budget(f"自适应第 {rnd + 1} 轮")
            log.info("[QC] 第 %s 轮自适应补齐", rnd + 1)
            self._autofill_chips()
            self._fill_empty_inputs([l2, l3])
            self._dismiss_keyboard()
            self._scroll_to_submit()
            time.sleep(0.3)

        # 3) 兜底：仍不可用时，连多行备注也补上（备注非必填，但补上不影响提交口径）
        if not self._submit_enabled():
            ensure_budget("兜底补填备注")
            log.info("[QC] 单行栏目已填仍不可提交，兜底补多行备注")
            self._autofill_chips()
            self._fill_empty_inputs([l2, l3, "QA 自动化补填"], allow_multiline=True)
            self._dismiss_keyboard()
            self._scroll_to_submit()
            time.sleep(0.3)

        self._dismiss_keyboard()
        self._scroll_to_submit()
        btn = self._submit_button()
        if btn is None or not self._submit_enabled():
            self._log_inputs("提交失败时")
            detail = (
                f"QC 提交按钮仍不可用（用时 {time.time() - started:.0f}s）。"
                f"页面提示：{self._qc_hints()}\n界面标签：{self.screen_labels()}"
            )
            check(
                "R-QC-06", False,
                expected="光线/工具/L2 具体场所/L3 具体操作齐全后提交可点",
                actual=detail,
                layer="ui",
                message=detail,
            )
            raise AssertionError(detail)
        check(
            "R-QC-06", True,
            expected="必填项齐全后提交按钮可点",
            actual=f"提交可点，用时 {time.time() - started:.0f}s",
            layer="ui",
        )
        btn.click()
        log.info("[QC] 已提交（用时 %.0fs）", time.time() - started)
