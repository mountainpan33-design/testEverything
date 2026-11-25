"""视觉层的结构守卫（不依赖设备/网络）：pytest -m gate。

这些检查不验产品行为，验的是「框架自己的安全网还在不在」。
它们防的都是已经真实发生过的事故：

  - 裸 `agent.aiWaitFor(...)` → 屏幕在通知中心也会判过（2026-11-20 误判事故）
  - 障碍表里出现「立即更新」「确定」这类有副作用的按钮 → 点下去会改变被测状态
  - 障碍条目缺 attribution → 失败归因失真，环境问题被报成产品缺陷
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.assertions import check

R = "R-GATE-04"

VISION_SRC = Path(__file__).resolve().parent.parent / "vision" / "src"
OBSTACLES_FILES = [VISION_SRC / "obstacles.ts", VISION_SRC / "obstacles.project.ts"]

# 允许出现裸 aiWaitFor 的文件：
#   obstacles.ts —— 障碍排除自身的实现（它就是这个能力的底层）
#   run.ts       —— 执行层：等待条件来自 cases/*.yaml 的声明，执行器只负责照做
BARE_WAIT_ALLOWED = {"obstacles.ts", "run.ts"}

# 有副作用的按钮，绝不能出现在「自动排除」动作里
DANGEROUS_REMEDY = ("立即更新", "确定", "确认", "同意", "删除", "卸载", "重装", "退出登录")


def _ts_files() -> list[Path]:
    return sorted(p for p in VISION_SRC.rglob("*.ts") if p.is_file())


@pytest.mark.gate
def test_no_bare_aiwaitfor():
    """除障碍实现外，一律用 waitForAppState —— 它每轮会先确认屏幕还在 App 里。"""
    offenders: list[str] = []
    for f in _ts_files():
        if f.name in BARE_WAIT_ALLOWED:
            continue
        text = f.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "agent.aiWaitFor(" in line:
                offenders.append(f"{f.relative_to(VISION_SRC)}:{i}")
    check(
        R,
        not offenders,
        expected="除 obstacles.ts 外不使用裸 aiWaitFor",
        actual=f"裸调用：{offenders}",
        layer="L1-UI",
        message="改用 waitForAppState()：它在轮询前会先清障碍，避免在通知中心/弹窗上误判成功",
    )


@pytest.mark.gate
def test_obstacle_table_is_complete():
    """障碍表每条都要有 detect / attribution，否则识别与归因都会失真。"""
    text = "\n".join(f.read_text(encoding="utf-8") for f in OBSTACLES_FILES)
    blocks = re.findall(r"\{\s*id: '([a-z-]+)',(.*?)\n  \},", text, re.S)
    check(
        R,
        len(blocks) >= 3,
        expected="障碍表至少 4 条（模态弹窗 / 通知中心 / 系统权限框 / 系统设置）",
        actual=f"{len(blocks)} 条",
        layer="L1-UI",
    )
    for obstacle_id, body in blocks:
        check(
            R,
            "detect:" in body and "attribution:" in body,
            expected=f"{obstacle_id} 有 detect 和 attribution",
            actual=body.strip()[:80],
            layer="L1-UI",
        )


@pytest.mark.gate
def test_obstacle_remedy_has_no_side_effects():
    """自动排除只许点「取消/暂不/返回」这类无副作用按钮。"""
    text = "\n".join(f.read_text(encoding="utf-8") for f in OBSTACLES_FILES)
    remedies = re.findall(r"remedy: '([^']*)'", text)
    bad = [
        r for r in remedies
        if any(word in r for word in DANGEROUS_REMEDY) and not re.search(r"暂不|取消|下次", r)
    ]
    check(
        R,
        not bad,
        expected="排除动作无副作用",
        actual=f"有副作用的 remedy：{bad}",
        layer="L1-UI",
        message="自动排除点下去不能改变被测状态，否则工况就被自己改掉了",
    )


# 自愈允许写出的目标：障碍数据文件、分析报告（md / html）。除此之外一律不许写。
# 判据是「写的是不是数据/报告」，不是变量名——analyze.ts 后来补了 HTML 报告，
# 这里要跟着放开；放开的是报告，不是代码。
SELF_HEAL_ALLOWED_WRITES = {"GENERATED_FILE", "reportPath", "htmlPath"}


@pytest.mark.gate
def test_self_heal_writes_data_not_code():
    """analyze.ts 只能写 JSON 数据和 md 报告，不能自动改代码。

    这是自愈的边界：写错一条障碍最多是「下次没拦住」，
    而自动改 .ts 一旦改坏就是整个框架起不来，机器不该有这种权限。
    """
    analyze = VISION_SRC / "analyze.ts"
    if not analyze.exists():
        return
    text = analyze.read_text(encoding="utf-8")
    targets = [t.strip() for t in re.findall(r"writeFileSync\(\s*([^,]+),", text)]
    bad = [t for t in targets if t not in SELF_HEAL_ALLOWED_WRITES]
    check(
        R,
        not bad,
        expected="自愈只写 GENERATED_FILE / reportPath",
        actual=f"越界写入：{bad}",
        layer="L1-UI",
        message="机器只能写数据不能改代码；改代码的修复只输出建议，由人来做",
    )


# 定位符清单是生成的，不是手写的
VISION_DIR = Path(__file__).resolve().parent.parent / "vision"
LOCATORS = VISION_DIR.parent / "pages" / "ui_locators.py"


@pytest.mark.gate
def test_locators_match_source():
    """pages/ui_locators.py 必须和源码里的 accessibilityLabel 一致。

    Appium 用例靠这份清单定位元素。界面加了或改了 label 却没重新生成，
    用例会引用到不存在的定位符——跑起来报「找不到元素」，看着像产品坏了。
    """
    if shutil.which("npx") is None or not (VISION_DIR / "node_modules").is_dir():
        pytest.skip("没有 npx 或 vision/node_modules，跳过生成物一致性检查")
    assert LOCATORS.is_file(), f"找不到生成文件 {LOCATORS}，先跑 npx tsx src/cli.ts --gen-pages --write"

    cp = subprocess.run(
        ["npx", "tsx", "src/cli.ts", "--gen-pages"],
        cwd=VISION_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    check(
        R,
        cp.returncode == 0,
        expected="定位符清单与源码一致",
        actual=(cp.stdout or cp.stderr).strip()[-300:],
        layer="L1-UI",
        message="源码里的 accessibilityLabel 变了：在 vision/ 跑 npx tsx src/cli.ts --gen-pages --write",
    )
