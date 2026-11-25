"""UI 视觉回归：截图与基线对比，抓「无障碍属性看不出来」的问题。

能发现：
  - 黑屏 / 白屏 / 空白页（渲染失败、崩溃遮罩）
  - 页面骨架错位（标题区 / 底部固定区缺失、挪位、被遮挡）
  - 骨架上的文案/配色被意外改动

不能发现（需要人工或模型）：
  - 中间业务内容的正确性（时长、通过概率、任务名、缩略图每次都会变）
  - 相机取景页的实时画面（calib/record，拍的是真实场景，两次必然不同）

对比口径（2026-11-20 真机实证后调整）：
  1. **不做整屏对比** —— 首页的问候语/任务名、QC 的 72%/0:39、状态栏时钟
     每轮都在变，整屏对比必然误报（实测 calib 页差异 80%）；
  2. 只比「稳定骨架」：顶部标题区（3%~15%）+ 底部固定区（86%~98%），
     由 `CHROME_REGIONS` 定义，中间业务内容不参与；
  3. 取景页 `DYNAMIC_PAGES` 不做像素对比，只保留黑屏/白屏检测。

基线目录：screenshots/baseline/<platform>/<name>.png
首次运行自动建立基线（记为 skip）；设 QA_VISION_UPDATE=1 时用当前截图覆盖基线。
基线存整屏截图，比对时按区域裁剪，所以口径调整后无需重拍基线。
"""
from __future__ import annotations

import time
from pathlib import Path

from core.assertions import check, skip
from utils.logger import log

RULE = "R-UI-01"

# 黑屏/白屏判定阈值（0-255）
MIN_MEAN = 8.0      # 平均亮度低于此值视为黑屏
MIN_STD = 3.0       # 标准差低于此值视为纯色（白屏/空白）
DEFAULT_TOL = 0.02  # 允许的差异像素占比

# 取景页：画面是真实场景，像素对比无意义，只做黑屏/白屏检测
DYNAMIC_PAGES = {"calib", "record"}

# 稳定骨架区域（相对坐标 x0, y0, x1, y1）：标题区 + 底部固定区
CHROME_REGIONS: tuple[tuple[float, float, float, float], ...] = (
    (0.0, 0.03, 1.0, 0.15),
    (0.0, 0.86, 1.0, 0.98),
)


def available() -> bool:
    """Pillow 是否可用。缺失时视觉检查降级为跳过，不影响主链路。"""
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def _pil():
    from PIL import Image, ImageChops, ImageStat  # 延迟导入，避免缺依赖时整个收集失败

    return Image, ImageChops, ImageStat


def _load(path: Path):
    Image = _pil()[0]
    return Image.open(path).convert("RGB")


def compare(
    current: Path,
    baseline: Path,
    tolerance: float = DEFAULT_TOL,
    diff_threshold: int = 16,
    crop_top: float = 0.03,
    crop_bottom: float = 0.02,
    regions: tuple[tuple[float, float, float, float], ...] | None = None,
    check_diff: bool = True,
) -> dict:
    """对比两张截图。返回 {ratio, mean, std, ok, reason, compared_px}。

    - 裁掉顶部 3% / 底部 2%，避免状态栏时钟、电量、手势条造成假差异
    - regions：只在这些相对区域内统计差异；None = 整屏（裁边后）
    - check_diff=False：不统计差异（取景页），只做黑屏/白屏检测
    - ratio：差异像素占比（逐通道差值 > diff_threshold 的像素 / 参与比对的像素）
    - mean/std：在裁边后的整屏上计算，用于黑屏/白屏判定
    """
    cur = _load(current)
    base = _load(baseline)
    Image, ImageChops, ImageStat = _pil()
    if cur.size != base.size:
        cur = cur.resize(base.size)

    w, h = base.size
    box = (0, int(h * crop_top), w, int(h * (1 - crop_bottom)))
    cur_c = cur.crop(box)
    base_c = base.crop(box)

    gray = cur_c.convert("L")
    stat = ImageStat.Stat(gray)
    mean, std = float(stat.mean[0]), float(stat.stddev[0])

    ratio = None
    compared_px = 0
    if check_diff:
        boxes = [
            (
                int(w * x0), int(h * y0),
                int(w * x1), int(h * y1),
            )
            for x0, y0, x1, y1 in (regions or ((0.0, crop_top, 1.0, 1 - crop_bottom),))
        ]
        changed = 0
        for b in boxes:
            a = cur.crop(b)
            bb = base.crop(b)
            diff = ImageChops.difference(a, bb).convert("L")
            changed += sum(diff.histogram()[diff_threshold + 1:])
            compared_px += a.size[0] * a.size[1]
        ratio = changed / (compared_px or 1)

    reason = ""
    ok = True
    if mean < MIN_MEAN:
        ok, reason = False, f"疑似黑屏（平均亮度 {mean:.1f}）"
    elif std < MIN_STD:
        ok, reason = False, f"疑似空白页（像素标准差 {std:.1f}）"
    elif check_diff and ratio > tolerance:
        ok, reason = False, f"与基线差异 {ratio:.2%} 超过容差 {tolerance:.2%}"

    return {
        "ratio": None if ratio is None else round(ratio, 4),
        "mean": round(mean, 1),
        "std": round(std, 1),
        "ok": ok,
        "reason": reason,
        "compared_px": compared_px,
    }


def capture(driver, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    driver.get_screenshot_as_file(str(path))
    return path


def check_screen(
    driver,
    name: str,
    baseline_dir: Path,
    run_dir: Path,
    tolerance: float = DEFAULT_TOL,
    update_baseline: bool = False,
) -> dict:
    """截取当前屏幕并和基线比对；返回结果（含截图路径）。"""
    if not available():
        skip(RULE, "未安装 Pillow，视觉检查跳过（pip install -r requirements.txt）",
             layer="L1-UI")
        return {"name": name, "skipped": True, "reason": "PIL not installed"}

    current = capture(driver, run_dir, name)
    baseline = baseline_dir / f"{name}.png"

    if update_baseline or not baseline.exists():
        baseline.parent.mkdir(parents=True, exist_ok=True)
        _load(current).save(baseline)
        skip(RULE, f"首次建立视觉基线：{name}", layer="L1-UI")
        log.info("[vision] 建立基线 %s", baseline)
        return {"name": name, "baseline_created": True, "path": str(current)}

    dynamic = name in DYNAMIC_PAGES
    result = compare(
        current,
        baseline,
        tolerance=tolerance,
        regions=None if dynamic else CHROME_REGIONS,
        check_diff=not dynamic,
    )
    result.update({"name": name, "current": str(current), "baseline": str(baseline)})
    if dynamic:
        expected = "非黑屏/空白（取景页画面为实时场景，不做像素对比）"
        actual = f"亮度 {result['mean']}，标准差 {result['std']} {result['reason']}"
    else:
        expected = f"骨架区（标题区+底部区）与基线差异 ≤{tolerance:.0%} 且非黑屏/空白"
        actual = (f"骨架区差异 {result['ratio']:.2%}，亮度 {result['mean']}，"
                  f"标准差 {result['std']} {result['reason']}")
    check(
        RULE,
        result["ok"],
        expected=expected,
        actual=actual,
        layer="L1-UI",
        message=f"页面「{name}」视觉异常：{result['reason']}" if not result["ok"] else "",
    )
    return result


def run_dir_for(settings) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return Path(settings.vision_dir) / "current" / stamp
