"""一条命令跑完所有层，出一份按用例编号归拢的 HTML 报告。

为什么需要它：50 条用例分散在四个执行器里——
  Midscene（23 条 UI）、jest（14 条单元）、pytest golden（6 条产物）、人工（4 条）。
分开跑就得看四份结果，还得自己对「哪条测了、哪条没测」。

这个脚本按 `verification/coverage.yaml` 的归属表，把各层结果合并到用例编号上。

用法：
    python -m verification.run_all                    # 单元 + 门禁 + 视觉
    python -m verification.run_all --no-vision        # 不跑真机（只要单元+接口）
    python -m verification.run_all --with-artifact    # 额外跑产物校验（要账号）
    python -m verification.run_all --with-golden      # 额外跑黄金链路（要真机+额度）
    python -m verification.run_all --vision-only

退出码：任何一条 failed → 1；全部 passed/skipped/manual/pending → 0。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # app-automation
REPO = ROOT.parent            # App 仓库根；stage_jest 里会用项目配置覆盖
VISION = ROOT / "vision"
TMP = Path(os.environ.get("TMPDIR", "/tmp")) / "ego-run-all"
TMP.mkdir(parents=True, exist_ok=True)
LOGS = VISION / "midscene_run" / "logs"

PASSED, FAILED, SKIPPED, NOTRUN, MANUAL, PENDING = (
    "passed", "failed", "skipped", "not-run", "manual", "pending",
)
BAD = {FAILED}


def run(cmd: list[str], cwd: Path, timeout: int = 3600, name: str = "") -> tuple[int, str]:
    print(f"  $ {' '.join(cmd)}  (cwd={cwd.name})", flush=True)
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd), timeout=timeout, capture_output=True, text=True
        )
        log = (p.stdout or "") + (p.stderr or "")
        code = p.returncode
    except subprocess.TimeoutExpired:
        code, log = 124, f"超时（{timeout}s）"
    if name:
        # 完整日志落盘，出错时不用翻终端
        LOGS.mkdir(parents=True, exist_ok=True)
        (LOGS / f"{name}.log").write_text(log, encoding="utf-8")
        if code not in (0, 5):
            print(f"    （完整日志：{LOGS / f'{name}.log'}）")
    return code, log


# ---------------------------------------------------------------- 各层执行

def stage_jest(results: dict, out: Path) -> None:
    from verification.project import app_repo

    repo = app_repo()
    before = dict(results)
    jest_out = TMP / "jest.json"
    jest_out.unlink(missing_ok=True)          # 删掉上一轮残留，别把旧结果当新结果
    code, log = run(
        ["npx", "jest", "--silent", "--json", f"--outputFile={jest_out}"], repo, name="jest"
    )
    if code != 0:
        print(f"  ✗ jest 退出码 {code}，日志尾部：")
        print("\n".join("    " + ln for ln in log.strip().splitlines()[-18:]))
    if not jest_out.is_file():
        print(f"  ⚠ jest 没有产出结果（exit={code}）")
        return
    doc = json.loads(jest_out.read_text(encoding="utf-8"))
    for tr in doc.get("testResults", []):
        name = tr.get("name", "")
        status = "passed" if tr.get("status") == "passed" else "failed"
        # 一个文件里可能有失败也可能全过；按文件取最差状态
        results[name] = status
    added = {k: v for k, v in results.items() if k not in before}
    stage_health(results, "__stage:jest", added)


def _pytest_stage(results: dict, marker: str, name: str) -> None:
    xml = TMP / f"pytest-{name}.xml"
    xml.unlink(missing_ok=True)               # 同上：上一轮的 xml 不能当这一轮用
    code, log = run(
        [sys.executable, "-m", "pytest", "-m", marker, "-q", f"--junitxml={xml}"],
        ROOT,
        name=f"pytest-{name}",
    )
    if code not in (0, 5):
        print(f"  ✗ pytest -m {marker} 退出码 {code}，日志尾部：")
        print("\n".join("    " + ln for ln in log.strip().splitlines()[-20:]))
    if not xml.is_file():
        print(f"  ⚠ pytest -m {marker} 没有产出结果（exit={code}）")
        return
    tree = ET.parse(xml)
    for tc in tree.iter("testcase"):
        cls = tc.get("classname", "")
        fn = tc.get("name", "")
        key = f"{cls.split('.')[-1]}::{fn}"
        status = PASSED
        if tc.find("failure") is not None or tc.find("error") is not None:
            status = FAILED
        elif tc.find("skipped") is not None:
            status = SKIPPED
        results[key] = status


def stage_pytest_markers(results: dict) -> None:
    for marker, name in (("gate", "gate"), ("api", "api")):
        before = dict(results)
        _pytest_stage(results, marker, name)
        added = {k: v for k, v in results.items() if k not in before}
        stage_health(results, f"__stage:{marker}", added)


def stage_health(results: dict, key: str, items: dict[str, str]) -> None:
    """把一层整体状态记下来：50 条用例没映射到的失败也要能看见。"""
    if not items:
        results[key] = NOTRUN
    elif any(v == FAILED for v in items.values()):
        results[key] = FAILED
    else:
        results[key] = PASSED


def stage_artifact(results: dict) -> None:
    _pytest_stage(results, "artifact", "artifact")


def stage_golden(results: dict) -> None:
    _pytest_stage(results, "golden", "golden")


def stage_vision(results: dict, device: str = "") -> None:
    out = TMP / "vision.json"
    # 上一轮跑挂时 vision.json 会留在 tmp 里；不删的话，这次视觉层没跑成
    # 也会读到上一轮的结果，报告看起来「有数据」，其实一整天没跑过。
    out.unlink(missing_ok=True)
    cmd = ["npx", "tsx", "src/cli.ts", "--tier", "full", "--no-heal", "--out", str(out)]
    if device:
        cmd += ["--device", device]
    code, log = run(cmd, VISION, timeout=7200, name="vision")
    if not out.is_file():
        tail = "\n".join("    " + ln for ln in log.strip().splitlines()[-12:])
        print(f"  ✗ 视觉层没跑起来（exit={code}）：\n{tail}")
        results["__vision_skip"] = f"exit={code}（见终端日志）"
        return
    doc = json.loads(out.read_text(encoding="utf-8"))
    for c in doc.get("cases", []):
        cid = c["caseId"]
        results[cid] = c["status"]
        # 跳过/失败的原因要带出来，不然报告只显示「跳过」两个字。
        # 通过的用例这两个字段都是空的，splitlines() 会返回空列表，不能直接取 [0]。
        lines = (c.get("skipReason") or c.get("error") or "").splitlines()
        if lines:
            results[f"{cid}:detail"] = lines[0][:180]


# ---------------------------------------------------------------- 合并

def resolve(case_id: str, cov: dict, raw: dict, seen: set[str]) -> tuple[str, str]:
    """返回 (状态, 说明)。"""
    entry = cov.get(case_id)
    if not entry:
        return NOTRUN, "coverage.yaml 里没有登记"
    layer = entry.get("layer")
    if layer in (MANUAL, PENDING):
        return layer, entry.get("note", "")
    if layer == "covered":
        target = entry.get("spec", "")
        if target in seen:
            return NOTRUN, "覆盖链有环"
        status, why = resolve(target, cov, raw, seen | {case_id})
        return status, f"由 {target} 覆盖{('：' + why) if why else ''}"
    if layer == "vision":
        return raw.get(case_id, NOTRUN), raw.get(f"{case_id}:detail", "")
    if layer == "jest":
        spec = entry.get("spec", "")
        for name, status in raw.items():
            if name.endswith(spec):
                return status, spec
        return NOTRUN, f"没有跑到 {spec}"
    if layer == "pytest":
        return raw.get(entry.get("spec", ""), NOTRUN), entry.get("spec", "")
    return NOTRUN, f"未知层 {layer}"


STATUS_LABEL = {
    PASSED: "通过", FAILED: "失败", SKIPPED: "跳过",
    NOTRUN: "未跑", MANUAL: "人工", PENDING: "待测",
}
STATUS_CLASS = {
    PASSED: "ok", FAILED: "bad", SKIPPED: "skip",
    NOTRUN: "muted", MANUAL: "manual", PENDING: "pending",
}
LAYER_LABEL = {
    "vision": "视觉", "jest": "单元", "pytest": "产物",
    "covered": "覆盖", "manual": "人工", "pending": "待测",
}


def render(rows: list[dict], elapsed: float, infra: dict | None = None,
           device: str = "", vision_skipped: str = "") -> str:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    tiles = "".join(
        f'<div class="tile"><b>{counts.get(k, 0)}</b><span>{STATUS_LABEL[k]}</span></div>'
        for k in (PASSED, FAILED, SKIPPED, NOTRUN, MANUAL, PENDING)
    )
    TIER_LABEL = {"normal": "普通", "costly": "耗额度", "destructive": "破坏共享"}
    REVIEW_LABEL = {"approved": "已审", "draft": "未审", "rejected": "驳回"}
    REVIEW_CLASS = {"approved": "rok", "draft": "rdraft", "rejected": "rrej"}

    def review_cell(r: dict) -> str:
        # 只有会跑视觉层的用例才需要审核；单元/接口/人工类不适用
        if r.get("layer") not in ("vision",):
            return ""
        rv = r.get("review") or "draft"
        return f'<span class="rchip {REVIEW_CLASS.get(rv, "rdraft")}">{REVIEW_LABEL.get(rv, rv)}</span>'

    def order_cell(r: dict) -> str:
        tier = r.get("tier") or ""
        if not tier:
            return ""
        idx = f'#{r["exec"]}' if r.get("exec") else ""
        return f'<span class="ord t-{tier}">{idx} {TIER_LABEL.get(tier, tier)}</span>'

    body = "".join(
        f'<tr class="{STATUS_CLASS[r["status"]]}">'
        f'<td class="cid">{r["id"]}</td>'
        f'<td class="ordcell">{order_cell(r)}</td>'
        f'<td>{r["title"]}</td>'
        f'<td>{LAYER_LABEL.get(r["layer"], r["layer"])}</td>'
        f'<td>{review_cell(r)}</td>'
        f'<td><span class="chip {STATUS_CLASS[r["status"]]}">'
        f'{STATUS_LABEL[r["status"]]}</span></td>'
        f'<td class="detail">{r["detail"]}</td></tr>'
        for r in rows
    )
    verdict = (
        '<div class="v ok">全部通过</div>' if not counts.get(FAILED)
        else f'<div class="v bad">{counts[FAILED]} 条失败</div>'
    )
    unreviewed = sum(1 for r in rows if r.get("review") in ("draft", "rejected", None))
    banner = (
        f'<div class="banner"><strong>{unreviewed} / {len(rows)} 条用例没过人工审核。</strong>'
        f'生成出来的断言是推测，绿了不代表产品对。先用 '
        f'<span class="mono">npx tsx src/cli.ts --review-page</span> 过一遍再看结论。</div>'
        if unreviewed else ''
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>全量测试报告</title>
<style>:root{{color-scheme:light}}body{{margin:0;padding:28px;background:#f5f7fb;color:#18222d;
font:15px/1.65 -apple-system,"PingFang SC",system-ui,sans-serif}}.wrap{{max-width:1080px;margin:auto}}
h1{{font-size:24px;margin:0 0 6px}}.sub{{color:#63758b;font-size:13px;margin-bottom:18px}}
.v{{display:inline-block;padding:6px 14px;border-radius:99px;font-weight:600;margin-bottom:16px}}
.v.ok{{background:#e7f6ec;color:#12663a}}.v.bad{{background:#fdeaea;color:#a02020}}
.tiles{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}}
.tile{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:10px 16px;min-width:86px}}
.tile b{{display:block;font-size:21px;line-height:1.2}}.tile span{{color:#5b6472;font-size:12px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e3e6ea;border-radius:10px;overflow:hidden;table-layout:fixed}}
th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid #eef1f4;font-size:14px;vertical-align:top;word-break:break-word}}
th{{background:#f8faff;color:#4d6279;font-weight:500;font-size:12px}}
th:nth-child(1),td:nth-child(1){{width:88px}}th:nth-child(2),td:nth-child(2){{width:86px}}
th:nth-child(4),td:nth-child(4){{width:46px}}th:nth-child(5),td:nth-child(5){{width:52px}}
th:nth-child(6),td:nth-child(6){{width:56px}}th:nth-child(7),td:nth-child(7){{width:24%}}
.ord{{font-size:11px;color:#5b6472;background:#f1f3f5;border-radius:4px;padding:1px 5px;white-space:nowrap}}
.ord.t-costly{{background:#fff4e6;color:#8a4b00}}.ord.t-destructive{{background:#fdeaea;color:#a02020}}
.rchip{{font-size:11px;padding:1px 7px;border-radius:99px;white-space:nowrap}}
.rchip.rok{{background:#e7f6ec;color:#12663a}}.rchip.rdraft{{background:#fff8e6;color:#8a4b00;border:1px solid #f0dca8}}
.rchip.rrej{{background:#fdeaea;color:#a02020}}
.banner{{background:#fff8e6;border:1px solid #f0dca8;border-radius:8px;padding:10px 14px;
font-size:13.5px;color:#7a5300;margin-bottom:16px}}.banner strong{{color:#a04000}}
.mono{{font-family:ui-monospace,Menlo,monospace}}
tr.bad td{{background:#fffafa}}.cid{{font-family:ui-monospace,Menlo,monospace;white-space:nowrap;font-size:13px}}
.detail{{color:#5b6472;font-size:12.5px}}
.chip{{font-size:12px;padding:2px 9px;border-radius:99px;background:#eef0f3;color:#42474e;white-space:nowrap}}
.chip.ok{{background:#e7f6ec;color:#12663a}}.chip.bad{{background:#fdeaea;color:#a02020}}
.chip.skip{{background:#fdf6e3;color:#7a5c00}}.chip.muted{{background:#f1f3f5;color:#7a828d}}
.chip.manual{{background:#eef2fb;color:#33518f}}.chip.pending{{background:#f6effb;color:#6b3f92}}
</style></head><body><div class="wrap"><h1>全量测试报告</h1>
<div class="sub">生成于 {time.strftime('%Y-%m-%d %H:%M:%S')} · 耗时 {elapsed / 60:.1f} 分钟 · 共 {len(rows)} 条
{('· 设备 ' + device) if device else ''}
{('· 基础检查：' + '、'.join(f'{k} {STATUS_LABEL.get(v, "未跑")}' for k, v in infra.items())) if infra else ''}
{('· 视觉层未跑：' + vision_skipped) if vision_skipped else ''}</div>
{banner}{verdict}<div class="tiles">{tiles}</div>
<table><thead><tr><th>用例</th><th>顺序</th><th>标题</th><th>层</th><th>审核</th><th>结果</th><th>说明</th></tr></thead>
<tbody>{body}</tbody></table></div></body></html>"""


def main(argv: list[str] | None = None) -> int:
    if not (ROOT / "verification").is_dir():
        print(f"请在 app-automation 目录下运行（当前看起来不是：{ROOT}）", file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser(description="一条命令跑完所有层")
    ap.add_argument("--no-vision", action="store_true", help="不跑真机视觉层")
    ap.add_argument("--vision-only", action="store_true", help="只跑视觉层")
    ap.add_argument("--with-artifact", action="store_true", help="额外跑产物校验")
    ap.add_argument("--with-golden", action="store_true", help="额外跑黄金链路")
    ap.add_argument("--device", default="", help="指定真机序列号（多台在线时必填）")
    ap.add_argument("--html", default=str(VISION / "midscene_run" / "reports" / "all-latest.html"))
    args = ap.parse_args(argv)

    from verification.coverage import COVERAGE as _COV

    # derived.yaml 里的结构性冒烟是源码派生的，数量随页面增减，
    # 不适合写死在 coverage.py 里——这里按视觉层动态并入。
    cov: dict = dict(_COV)
    from verification.project import cases_dir
    derived_yml = cases_dir() / "derived.yaml"
    if derived_yml.is_file():
        for line in derived_yml.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^- id:\s*(\S+)", line)
            if m and m.group(1) not in cov:
                cov[m.group(1)] = {"layer": "vision", "note": "源码派生的结构性冒烟"}

    orders: dict[str, str] = {}
    pol_text = (cases_dir() / "policy.yaml").read_text(encoding="utf-8")
    # 逐块取 order：先按用例编号切，再在块里找 order
    parts = re.split(r"^([A-Z0-9]+-\d+):\s*$", pol_text, flags=re.M)
    for i in range(1, len(parts) - 1, 2):
        cid, body = parts[i], parts[i + 1]
        m = re.search(r"^\s+order:\s*(\w+)", body, re.M)
        if m:
            orders[cid] = m.group(1)

    titles = {}
    # 审核状态：未审的照样跑，但报告里要标出来（用户明确要求「都跑，但标未审核」）
    reviews: dict[str, str] = {}

    def read_case_file(f: Path) -> None:
        if not f.is_file():
            return
        last_id = None
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^- id:\s*(\S+)", line)
            if m:
                last_id = m.group(1)
                continue
            if not last_id:
                continue
            m = re.match(r"^\s+title:\s*(.+)$", line)
            if m:
                titles[last_id] = m.group(1).strip().strip("'\"")
                continue
            # 只认 review 块下 4 空格的 status，别把 policy 里的其他 status 读进来
            m = re.match(r"^\s{4}status:\s*(\w+)", line)
            if m:
                reviews[last_id] = m.group(1)

    for f in (
        cases_dir() / "cases.yaml",
        cases_dir() / "derived.yaml",
        cases_dir() / "planned.yaml",
    ):
        read_case_file(f)


    raw: dict[str, str] = {}
    started = time.time()

    try:
        from verification.project import app_source, project_name
        print(f"项目：{project_name()} ｜ App 源码：{app_source() or '<未配置>'}")
    except SystemExit as e:
        print(f"项目配置有问题：{e}", file=sys.stderr)
        return 2

    print("== 执行 ==")
    if not args.vision_only:
        print("[单元测试]"); stage_jest(raw, TMP)
        print("[门禁 + 接口]"); stage_pytest_markers(raw)
        if args.with_artifact:
            print("[产物校验]"); stage_artifact(raw)
        if args.with_golden:
            print("[黄金链路]"); stage_golden(raw)
    if not args.no_vision:
        print("[视觉层]"); stage_vision(raw, args.device)

    infra = {
        label: raw.get(key)
        for key, label in (
            ("__stage:jest", "单元测试"),
            ("__stage:gate", "门禁纯函数"),
            ("__stage:api", "接口层"),
        )
    }
    infra_bad = [k for k, v in infra.items() if v == FAILED]

    # 视觉层的执行顺序：档位 → 文件顺序；和执行器 sortByPolicy 一致
    rank = {"normal": 0, "costly": 1, "destructive": 2}
    vision_ids = [c for c in cov if cov[c].get("layer") == "vision"]
    vision_order = sorted(
        enumerate(vision_ids),
        key=lambda x: (rank.get(orders.get(x[1], "normal"), 0), x[0]),
    )
    exec_index = {cid: i + 1 for i, (_, cid) in enumerate(vision_order)}

    rows = []
    for cid in sorted(cov):
        status, detail = resolve(cid, cov, raw, set())
        tier = orders.get(cid, "normal") if cov[cid].get("layer") == "vision" else ""
        rows.append({
            "id": cid,
            "title": titles.get(cid, ""),
            "layer": cov[cid].get("layer", ""),
            "status": status,
            "detail": detail,
            "tier": tier,
            "exec": exec_index.get(cid, 0),
            "review": reviews.get(cid, "draft"),
        })

    elapsed = time.time() - started
    Path(args.html).parent.mkdir(parents=True, exist_ok=True)
    Path(args.html).write_text(
        render(rows, elapsed, infra, args.device, raw.get("__vision_skip", "")),
        encoding="utf-8",
    )

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("\n== 基础检查（不对应用例，但挂了要修） ==")
    for key, label in (("__stage:jest", "单元测试"), ("__stage:gate", "门禁纯函数"), ("__stage:api", "接口层")):
        st = raw.get(key)
        print(f"  {label}: {STATUS_LABEL.get(st, '未跑') if st else '未跑'}")

    basis = counts.get(PASSED, 0) + counts.get(FAILED, 0)

    print("\n== 汇总 ==")
    print(f"  覆盖 {len(rows)} 条中已执行 {basis} 条：通过 {counts.get(PASSED,0)}、失败 {counts.get(FAILED,0)}")
    print("  未执行 " + "、".join(
        f"{STATUS_LABEL[k]} {counts.get(k, 0)}" for k in (SKIPPED, NOTRUN, MANUAL, PENDING)
    ))
    vision_rows = [r for r in rows if r["layer"] == "vision"]
    un_reviewed = sum(1 for r in vision_rows if r["review"] != "approved")
    if un_reviewed:
        print(f"  ⚠ 视觉层 {un_reviewed}/{len(vision_rows)} 条没过人工审核，结论仅供参考"
              f"（--review-page 生成审核页）")
    if infra_bad:
        print(f"  基础检查失败：{'、'.join(infra_bad)}（不代表用例失败，但必须先修）")
    print(f"  报告：{args.html}")
    for r in rows:
        if r["status"] == FAILED:
            print(f"  ✗ {r['id']} {r['title']}  {r['detail']}")
    return 1 if (counts.get(FAILED) or infra_bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
