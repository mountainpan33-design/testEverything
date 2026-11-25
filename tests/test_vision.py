"""视觉回归的纯函数单测（不依赖设备）：pytest -m gate。"""
from __future__ import annotations

import pytest

pytest.importorskip("PIL", reason="未安装 Pillow，视觉单测跳过")

from PIL import Image, ImageDraw

from core.assertions import check
from core.vision import CHROME_REGIONS, compare

R = "R-UI-01"


def _make(path, color=(240, 240, 240), size=(400, 800), lines: int = 3) -> None:
    img = Image.new("RGB", size, color)
    d = ImageDraw.Draw(img)
    for i in range(lines):
        d.rectangle([40, 200 + i * 120, 360, 280 + i * 120], fill=(60, 60, 90))
    img.save(path)


def _page(path, middle=(230, 235, 240), chrome=(60, 60, 90), drop_bottom=False) -> None:
    """模拟一页 App：稳定骨架（标题区 + 底部操作区）+ 会变的中间业务内容。"""
    img = Image.new("RGB", (400, 800), (245, 245, 245))
    d = ImageDraw.Draw(img)
    d.rectangle([20, 48, 380, 108], fill=chrome)          # 标题区（3%~15%）
    d.rectangle([0, 200, 400, 600], fill=middle)          # 中间业务内容（每次都会变）
    if not drop_bottom:
        d.rectangle([20, 700, 380, 760], fill=chrome)     # 底部操作区（86%~98%）
    img.save(path)


@pytest.mark.gate
def test_same_image_passes(tmp_path):
    a = tmp_path / "a.png"
    _make(a)
    res = compare(a, a)
    check(R, res["ok"] is True, expected="同图无差异", actual=str(res))
    check(R, res["ratio"] <= 0.01, expected="差异≈0", actual=f"{res['ratio']:.4f}")


@pytest.mark.gate
def test_black_screen_detected(tmp_path):
    cur = tmp_path / "black.png"
    base = tmp_path / "base.png"
    _make(base)
    Image.new("RGB", (400, 800), (0, 0, 0)).save(cur)
    res = compare(cur, base)
    check(R, res["ok"] is False, expected="黑屏判失败", actual=str(res))
    check(R, "黑屏" in res["reason"], expected="原因标注黑屏", actual=res["reason"])


@pytest.mark.gate
def test_blank_page_detected(tmp_path):
    cur = tmp_path / "white.png"
    base = tmp_path / "base.png"
    _make(base)
    Image.new("RGB", (400, 800), (250, 250, 250)).save(cur)
    res = compare(cur, base)
    check(R, res["ok"] is False, expected="空白页判失败", actual=str(res))
    check(R, "空白" in res["reason"], expected="原因标注空白", actual=res["reason"])


@pytest.mark.gate
def test_layout_change_detected(tmp_path):
    cur = tmp_path / "cur.png"
    base = tmp_path / "base.png"
    _make(base, lines=3)
    _make(cur, lines=1)
    res = compare(cur, base, tolerance=0.02)
    check(R, res["ok"] is False, expected="大面积差异判失败", actual=str(res))
    check(R, res["ratio"] > 0.02, expected="差异超过容差", actual=f"{res['ratio']:.3f}")


@pytest.mark.gate
def test_size_mismatch_is_resized(tmp_path):
    cur = tmp_path / "cur.png"
    base = tmp_path / "base.png"
    _make(base, size=(400, 800))
    _make(cur, size=(800, 1600))
    res = compare(cur, base)
    check(R, isinstance(res["ratio"], float), expected="尺寸不同也能比较", actual=str(res["ratio"]))


@pytest.mark.gate
def test_chrome_ignores_dynamic_middle(tmp_path):
    """中间业务内容变了（时长/概率/任务名），骨架没变 → 不应误报。"""
    base = tmp_path / "base.png"
    cur = tmp_path / "cur.png"
    _page(base, middle=(230, 235, 240))
    _page(cur, middle=(120, 160, 200))
    full = compare(cur, base)
    chrome = compare(cur, base, regions=CHROME_REGIONS)
    check(R, chrome["ok"] is True, expected="骨架一致判通过", actual=str(chrome))
    check(R, chrome["ratio"] <= 0.02, expected="骨架差异≈0", actual=f"{chrome['ratio']:.3f}")
    check(
        R, full["ok"] is False,
        expected="整屏对比会误报（说明只比骨架是必要的）",
        actual=f"整屏差异 {full['ratio']:.2%}",
    )


@pytest.mark.gate
def test_chrome_detects_missing_footer(tmp_path):
    """底部操作区消失（按钮没渲染）→ 骨架对比必须抓到。"""
    base = tmp_path / "base.png"
    cur = tmp_path / "cur.png"
    _page(base)
    _page(cur, drop_bottom=True)
    res = compare(cur, base, regions=CHROME_REGIONS)
    check(R, res["ok"] is False, expected="底部区缺失判失败", actual=str(res))
    check(R, res["ratio"] > 0.02, expected="骨架差异超过容差", actual=f"{res['ratio']:.3f}")


@pytest.mark.gate
def test_dynamic_page_skips_diff_but_detects_black(tmp_path):
    """取景页不做像素对比，但仍要能抓到黑屏（相机没出图）。"""
    base = tmp_path / "base.png"
    live1 = tmp_path / "live1.png"
    black = tmp_path / "black.png"
    _page(base, middle=(230, 235, 240))
    _page(live1, middle=(90, 40, 30))
    Image.new("RGB", (400, 800), (0, 0, 0)).save(black)

    ok = compare(live1, base, check_diff=False)
    check(R, ok["ok"] is True, expected="取景页不同画面不判失败", actual=str(ok))
    check(R, ok["ratio"] is None, expected="取景页不统计差异", actual=str(ok["ratio"]))

    bad = compare(black, base, check_diff=False)
    check(R, bad["ok"] is False, expected="取景页黑屏仍判失败", actual=str(bad))
    check(R, "黑屏" in bad["reason"], expected="原因标注黑屏", actual=bad["reason"])
