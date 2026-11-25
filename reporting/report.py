"""生成测试报告（自包含 HTML + JSON）。

内容：
  - 环境：平台、设备、账号（脱敏）、API 地址、被测 OTA 版本、运行时间
  - 结论：通过/失败/跳过数量与总体判定
  - 明细：每条断言 → 规则编号、层、期望 vs 实际、失败原因
  - 规则对照：本次涉及规则的「对/错」定义与源码出处
"""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

from core import results, rules
from utils.logger import log


def _mask(value: str) -> str:
    if not value:
        return "-"
    return value if len(value) < 6 else f"{value[:3]}***{value[-2:]}"


def _ota_info(platform: str) -> dict:
    try:
        from core.ota import latest_update

        return latest_update("ios" if platform == "ios" else "android") or {}
    except Exception:  # noqa: BLE001
        return {}


def build(settings) -> dict:
    summary = results.summary()
    referenced = sorted({c.rule for c in results.CHECKS if c.rule})
    rule_rows = [rules.RULES[r] for r in referenced if r in rules.RULES]
    unknown_rules = [r for r in referenced if r not in rules.RULES]
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": settings.platform,
        "device": settings.android_udid or settings.ios_udid or "-",
        "account": _mask(settings.username),
        "api_base": settings.api_base or "-",
        "ota": _ota_info(settings.platform),
        "summary": summary,
        "checks": [c.__dict__ for c in results.CHECKS],
        "rules": [r.__dict__ for r in rule_rows],
        "unknown_rules": unknown_rules,
    }


_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>App 自动化测试报告 · {generated_at}</title>
<style>
:root {{ color-scheme: light }}
body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       margin: 32px; color: #111; background:#fff }}
h1 {{ font-size: 22px; margin: 0 0 4px }}
h2 {{ font-size: 16px; margin: 28px 0 8px }}
.meta {{ color:#555; font-size: 13px; line-height: 1.7 }}
.badge {{ display:inline-block; padding:2px 10px; border-radius: 999px; font-size: 12px; font-weight:600 }}
.pass {{ background:#e7f6ec; color:#11663a }}
.fail {{ background:#fdecec; color:#9b1c1c }}
.skip {{ background:#f1f3f5; color:#555 }}
table {{ border-collapse: collapse; width:100%; font-size:13px; margin-top:8px }}
th, td {{ border:1px solid #e5e7eb; padding:8px 10px; text-align:left; vertical-align:top }}
th {{ background:#f9fafb; font-weight:600 }}
tr.fail td {{ background:#fff7f7 }}
tr.skip td {{ color:#777 }}
code {{ background:#f3f4f6; padding:1px 5px; border-radius:4px; font-size:12px }}
</style></head><body>
<h1>App 自动化测试报告</h1>
<div class="meta">
生成时间：{generated_at}　|　平台：{platform}　|　设备：{device}　|　账号：{account}<br>
API：{api_base}　|　被测 OTA：{ota_id}（{ota_time}）<br>
结论：<span class="badge {verdict_cls}">{verdict}</span>
　通过 {passed}　失败 {failed}　跳过 {skipped}　共 {total}
</div>
<h2>一、断言明细（按用例）</h2>
{check_table}
<h2>二、规则对照（什么是对 / 什么是错）</h2>
{rule_table}
<h2>三、失败详情</h2>
{failures}
</body></html>"""


def render_html(data: dict) -> str:
    checks = data["checks"]
    by_case: dict[str, list[dict]] = {}
    for c in checks:
        by_case.setdefault(c["case"], []).append(c)

    rows = []
    for case, items in by_case.items():
        for c in items:
            cls = c["status"]
            rows.append(
                "<tr class='{cls}'><td><code>{case}</code></td><td>{rule}</td><td>{layer}</td>"
                "<td><span class='badge {cls}'>{status}</span></td>"
                "<td>{expected}</td><td>{actual}</td></tr>".format(
                    cls=cls,
                    case=html.escape(case.split("::")[-1]),
                    rule=html.escape(c["rule"] or "-"),
                    layer=html.escape(c["layer"] or "-"),
                    status={"pass": "通过", "fail": "失败", "skip": "跳过"}.get(cls, cls),
                    expected=html.escape((c["expected"] or c["message"] or "-")[:160]),
                    actual=html.escape((c["actual"] or "-")[:160]),
                )
            )
    check_table = (
        "<table><tr><th>用例</th><th>规则</th><th>层</th><th>结果</th><th>期望</th><th>实际</th></tr>"
        + "".join(rows)
        + "</table>"
        if rows
        else "<p>本次没有任何断言记录。</p>"
    )

    rule_rows = "".join(
        "<tr><td><code>{id}</code></td><td>{title}</td><td>{expected}</td>"
        "<td>{negative}</td><td>{src}</td><td>{sev}</td></tr>".format(
            id=html.escape(r["id"]),
            title=html.escape(r["title"]),
            expected=html.escape(r["expected"]),
            negative=html.escape(r["negative"]),
            src=html.escape(r["source"]),
            sev=html.escape(r["severity"]),
        )
        for r in data["rules"]
    )
    rule_table = (
        "<table><tr><th>规则</th><th>名称</th><th>正确（应通过）</th>"
        "<th>错误（应失败）</th><th>源码出处</th><th>级别</th></tr>"
        + rule_rows
        + "</table>"
        if rule_rows
        else "<p>本次没有引用规则。</p>"
    )

    failures = [
        "<p><b>{case}</b> · <code>{rule}</code><br>期望：{expected}<br>实际：{actual}</p>".format(
            case=html.escape(c["case"]),
            rule=html.escape(c["rule"] or "-"),
            expected=html.escape(c["expected"] or "-"),
            actual=html.escape(c["actual"] or c["message"] or "-"),
        )
        for c in checks
        if c["status"] == "fail"
    ]
    failures_html = "".join(failures) or "<p>无失败。</p>"

    ota = data.get("ota") or {}
    summary = data["summary"]
    return _HTML.format(
        generated_at=data["generated_at"],
        platform=data["platform"],
        device=html.escape(data["device"]),
        account=html.escape(data["account"]),
        api_base=html.escape(data["api_base"]),
        ota_id=html.escape(str(ota.get("id") or "-")),
        ota_time=html.escape(str(ota.get("createdAt") or "-")),
        verdict=summary["verdict"],
        verdict_cls="pass" if summary["verdict"] == "PASS" else "fail",
        passed=summary["passed"],
        failed=summary["failed"],
        skipped=summary["skipped"],
        total=summary["total"],
        check_table=check_table,
        rule_table=rule_table,
        failures=failures_html,
    )


def write(settings) -> Path:
    data = build(settings)
    out_dir = Path(settings.evidence_dir).parent / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    html_path = out_dir / f"report_{stamp}.html"
    json_path = out_dir / f"report_{stamp}.json"
    html_path.write_text(render_html(data), encoding="utf-8")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # 注意：不要在这里写 log —— sessionfinish 阶段 pytest 已关闭捕获流，
    # 会抛 "I/O operation on closed file"。路径由 conftest 的 terminal summary 打印。
    return html_path
