"""资源包产物校验（L3）。

视觉层只能看界面，看不出「这个包到底对不对」。但包里每个文件都在服务器上，
用**被测账号自己的 token** 就能拉下来——不需要浏览器凭据。

这个模块做的是：拿到最新的 COMPLETED 上传，把包当一个整体校验：

  R-UP-01  上传完整性：状态 COMPLETED、每个文件 size == expectedSize
  R-QC-01  包结构：metadata.json / streams_manifest.json / videos/headcam.mp4 /
           imu/imu.csv / timestamps/camera.csv / pose.csv / calibration/*.yaml 齐全
  R-QC-02  metadata 必填字段存在且非空
  R-QC-03  manifest 声明了 video 与 imu 两条 required 流
  R-CAP-01 各产物非空（视频 > 0、csv 行数 > 0）
  R-QC-04  视频可解码（需要 ffprobe；没有就跳过，不判失败）

另外做两项**交叉一致性**校验，这两项正是人工最容易漏的：

  视频实际分辨率 == metadata.resolution == manifest width×height
  视频实际时长 ≈ camera.csv 首尾时间差 ≈ metadata 时长

一旦不一致就报出来——2026-11-23 那个「声明 1920×1080、实际 1280×720」的包，
就是这条能自动抓住。

用法：
    python -m verification.artifacts                 # 校验最近一次上传
    python -m verification.artifacts --assignment <id>
    python -m verification.artifacts --no-video      # 跳过下载 MP4
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

REQUIRED_FILES = [
    "metadata.json",
    "streams_manifest.json",
    "videos/headcam.mp4",
    "imu/imu.csv",
    "timestamps/camera.csv",
    "pose.csv",
    "calibration/extrinsics.yaml",
    "calibration/intrinsics.yaml",
]

REQUIRED_METADATA = [
    "schema_version",
    "episode_uuid",
    "start_time_unix",
    "end_time_unix",
    "resolution",
    "fps",
    "device_id",
    "client_qc",
    "file_hash",
]


class Check:
    """一条校验结果。rule 对应 core/rules.py。"""

    def __init__(self, rule: str, name: str, ok: bool, detail: str = ""):
        self.rule = rule
        self.name = name
        self.ok = ok
        self.detail = detail

    def as_dict(self) -> dict:
        return {"rule": self.rule, "name": self.name, "ok": self.ok, "detail": self.detail}


def _base_url(path: str, client) -> str:
    return client._dcp_url(path)  # noqa: SLF001 - 复用同一套 base 拼接


def fetch_file_index(client, assignment_id: str) -> list[dict]:
    """该派工下的上传记录，最新在前。"""
    r = client.session.get(
        _base_url(f"/api/v1/collection/assignments/{assignment_id}/uploads", client),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_content(client, upload: dict, file: dict) -> bytes:
    """取一个文件的原始字节。文本走 preview/content；大文件走 preview 拿预签名地址。"""
    base = (
        f"/api/v1/tasks/{upload['taskId']}/collection/uploads/{upload['id']}"
        f"/files/{file['id']}"
    )
    r = client.session.get(_base_url(f"{base}/preview/content", client), timeout=120)
    if r.status_code >= 400:
        # 超过在线预览上限（视频/大 IMU）时，preview 只返回一个短时效下载地址
        r = client.session.get(_base_url(f"{base}/preview", client), timeout=60)
        r.raise_for_status()
        doc = r.json()
        url = doc.get("url")
        if not isinstance(url, str):
            raise RuntimeError(f"预览接口没有返回下载地址：{str(doc)[:120]}")
        return download(client, url, timeout=600)
    ctype = r.headers.get("content-type", "")
    if "application/json" in ctype:
        doc = r.json()
        content = doc.get("content")
        if isinstance(content, str):
            return content.encode("utf-8")
        if isinstance(doc.get("url"), str):
            return download(client, doc["url"], timeout=600)
    return r.content


def download(client, url: str, timeout: int = 300) -> bytes:
    """下载预签名地址。这个 URL 自带授权，不带 Authorization 头。"""
    with client.session.get(url, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        buf = io.BytesIO()
        for chunk in r.iter_content(1 << 20):
            buf.write(chunk)
        return buf.getvalue()


def _ffprobe(data: bytes) -> dict | None:
    if not shutil.which("ffprobe"):
        return None
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
        fh.write(data)
        path = fh.name
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,width,height,nb_frames:format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=120,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout or "{}")
    finally:
        os.unlink(path)


def _norm_path(relative_path: str) -> str:
    """relativePath 前面带一段 episode uuid，去掉它才是包内的相对路径。"""
    parts = (relative_path or "").replace("\\", "/").split("/")
    if len(parts) > 1 and "-" in parts[0] and len(parts[0]) >= 32:
        return "/".join(parts[1:])
    return "/".join(parts)


def verify_upload(client, upload: dict, with_video: bool = True) -> list[Check]:
    checks: list[Check] = []
    files = upload.get("files") or []
    by_name = {_norm_path(f.get("relativePath") or f.get("fileName", "")): f for f in files}

    checks.append(Check(
        "R-UP-01", "上传状态为 COMPLETED", upload.get("status") == "COMPLETED",
        f"status={upload.get('status')}",
    ))

    missing = [p for p in REQUIRED_FILES if p not in by_name]
    checks.append(Check(
        "R-QC-01", "资源包必需文件齐全", not missing,
        "缺少：" + ", ".join(missing) if missing else f"{len(files)} 个文件",
    ))

    bad_size = [
        f"{p}: {by_name[p].get('size')}≠{by_name[p].get('expectedSize')}"
        for p in REQUIRED_FILES if p in by_name
        and by_name[p].get("size") != by_name[p].get("expectedSize")
    ]
    checks.append(Check(
        "R-UP-01", "每个文件大小与预期一致", not bad_size, "; ".join(bad_size) or "全部一致",
    ))

    if missing:
        return checks

    meta = json.loads(fetch_content(client, upload, by_name["metadata.json"]))
    man = json.loads(fetch_content(client, upload, by_name["streams_manifest.json"]))

    empty = [k for k in REQUIRED_METADATA if meta.get(k) in (None, "", [])]
    checks.append(Check(
        "R-QC-02", "metadata 必填字段完整", not empty, "缺少：" + ", ".join(empty) if empty else "齐全",
    ))

    streams = {s.get("stream_id"): s for s in man.get("streams", [])}
    has_video = streams.get("head_camera", {}).get("type") == "video"
    has_imu = streams.get("ego_imu", {}).get("type") == "imu"
    checks.append(Check(
        "R-QC-03", "manifest 声明 video 与 imu 两条流", has_video and has_imu,
        f"streams={sorted(streams)}",
    ))

    # 非空校验：只判 size>0 不够——只有表头的 csv 也是「非空」。
    # 录制必须产生完整数据（R-CAP-01），所以要求 csv 至少有一行数据。
    empty_or_header_only = []
    csv_rows = {}
    for path in REQUIRED_FILES:
        f = by_name.get(path)
        if not f:
            continue
        size = f.get("size") or 0
        if size <= 0:
            empty_or_header_only.append(f"{path}=0B")
            continue
        if path.endswith(".csv"):
            try:
                body = fetch_content(client, upload, f).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue
            rows = [ln for ln in body.splitlines() if ln.strip()]
            csv_rows[path] = max(0, len(rows) - 1)
            if len(rows) <= 1:
                empty_or_header_only.append(f"{path}=只有表头({size}B)")
    checks.append(Check(
        "R-CAP-01", "各产物非空且 csv 有数据行", not empty_or_header_only,
        "; ".join(empty_or_header_only) if empty_or_header_only
        else ", ".join(f"{p}={n}行" for p, n in csv_rows.items()),
    ))

    # 交叉校验 1：声明的分辨率是否一致
    declared_meta = str(meta.get("resolution") or "")
    vstream = streams.get("head_camera", {})
    declared_man = f"{vstream.get('width')}x{vstream.get('height')}"
    checks.append(Check(
        "R-QC-03", "metadata 与 manifest 的分辨率声明一致",
        declared_meta.replace("×", "x") == declared_man,
        f"metadata={declared_meta} manifest={declared_man}",
    ))

    # 交叉校验 2：视频实际参数 vs 声明（需要 ffprobe）
    if with_video:
        try:
            video = fetch_content(client, upload, by_name["videos/headcam.mp4"])
            probe = _ffprobe(video)
            if probe is None:
                checks.append(Check(
                    "R-QC-04", "视频可解码", False,
                    "本机没有 ffprobe 或探测失败，无法判定（不当作通过）",
                ))
            else:
                vs = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
                if not vs:
                    checks.append(Check("R-QC-04", "视频包含视频流", False, "没有 video stream"))
                else:
                    s = vs[0]
                    actual = f"{s.get('width')}x{s.get('height')}"
                    checks.append(Check(
                        "R-QC-04", "视频实际分辨率与声明一致",
                        actual == declared_meta.replace("×", "x"),
                        f"实际={actual} 声明={declared_meta}",
                    ))
                    dur = float(probe.get("format", {}).get("duration") or 0)
                    md_dur = float(meta.get("end_time_unix", 0)) - float(meta.get("start_time_unix", 0))
                    checks.append(Check(
                        "R-QC-05", "视频时长与 metadata 时长一致（差 ≤ 2s）",
                        abs(dur - md_dur) <= 2.0,
                        f"视频={dur:.2f}s metadata={md_dur:.2f}s",
                    ))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("R-QC-04", "视频可解码", False, f"拉取失败：{exc}"))

    # 交叉校验 3：camera.csv 时间范围 vs metadata
    csv_bytes = fetch_content(client, upload, by_name["timestamps/camera.csv"])
    lines = csv_bytes.decode("utf-8", "replace").strip().splitlines()
    times = []
    for line in lines[1:]:
        try:
            times.append(float(line.split(",")[0]))
        except (ValueError, IndexError):
            continue
    if times:
        span = times[-1] - times[0]
        md_span = float(meta.get("end_time_unix", 0)) - float(meta.get("start_time_unix", 0))
        checks.append(Check(
            "R-QC-05", "camera.csv 时间跨度与 metadata 一致（差 ≤ 2s）",
            abs(span - md_span) <= 2.0,
            f"csv={span:.2f}s metadata={md_span:.2f}s 行数={len(times)}",
        ))
    else:
        checks.append(Check("R-QC-05", "camera.csv 有有效时间戳", False, f"只读到 {len(lines)} 行"))

    # 交叉校验 4：哈希
    declared = (meta.get("file_hash") or {}).get("files") or {}
    mismatched = []
    for path in REQUIRED_FILES:
        if path == "metadata.json" or path not in declared or path not in by_name:
            continue
        if path == "videos/headcam.mp4" and not with_video:
            continue
        try:
            data = fetch_content(client, upload, by_name[path])
        except Exception:  # noqa: BLE001
            continue
        if hashlib.sha256(data).hexdigest() != declared[path]:
            mismatched.append(path)
    checks.append(Check(
        "R-QC-01", "文件内容与 metadata 记录的 SHA-256 一致",
        not mismatched, "不一致：" + ", ".join(mismatched) if mismatched else "全部一致",
    ))

    return checks


def render_html(upload: dict, checks: list[Check]) -> str:
    failed = [c for c in checks if not c.ok]
    verdict = (
        '<div class="v ok">全部通过</div>' if not failed
        else f'<div class="v bad">{len(failed)} 项未通过</div>'
    )
    rows = "\n".join(
        f'<tr class="{"bad" if not c.ok else ""}"><td>{"✗" if not c.ok else "✓"}</td>'
        f'<td class="mono">{c.rule}</td><td>{c.name}</td><td>{c.detail}</td></tr>'
        for c in checks
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>资源包产物校验</title>
<style>:root{{color-scheme:light}}body{{margin:0;padding:28px;background:#f5f7fb;color:#18222d;
font:15px/1.65 -apple-system,"PingFang SC",system-ui,sans-serif}}.wrap{{max-width:960px;margin:auto}}
h1{{font-size:23px;margin:0 0 6px}}.sub{{color:#63758b;font-size:13px;margin-bottom:16px}}
.v{{display:inline-block;padding:6px 14px;border-radius:99px;font-weight:600;margin-bottom:18px}}
.v.ok{{background:#e7f6ec;color:#12663a}}.v.bad{{background:#fdeaea;color:#a02020}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e3e6ea;border-radius:10px;overflow:hidden}}
th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid #eef1f4;font-size:14px;vertical-align:top}}
th{{background:#f8faff;color:#4d6279;font-weight:500;font-size:12px}}
tr.bad td{{background:#fffafa}}.mono{{font-family:ui-monospace,Menlo,monospace;white-space:nowrap}}
</style></head><body><div class="wrap"><h1>资源包产物校验</h1>
<div class="sub">上传 {upload.get('id')} · 完成于 {upload.get('completedAt')} · 共 {len(checks)} 项</div>
{verdict}<table><thead><tr><th></th><th>规则</th><th>检查项</th><th>结果</th></tr></thead>
<tbody>{rows}</tbody></table></div></body></html>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验一次上传的资源包")
    parser.add_argument("--assignment", help="派工 id；不给就用 my-assignments 的第一个")
    parser.add_argument("--no-video", action="store_true", help="不下载 MP4（省时间）")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    parser.add_argument("--html", help="把结果写成 HTML 报告")
    args = parser.parse_args(argv)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from apis.collector_client import CollectorClient

    base = os.environ.get("QA_API_BASE") or os.environ.get("ANDROID_API_BASE") or ""
    if not base:
        print("缺 QA_API_BASE，先加载 app-automation/.env", file=sys.stderr)
        return 2

    client = CollectorClient(base, os.environ.get("QA_MAIN_SITE_HOST", ""))
    client.login(os.environ["QA_USERNAME"], os.environ["QA_PASSWORD"])

    assignment_id = args.assignment
    if not assignment_id:
        items = client.my_assignments()
        if not items:
            print("这个账号没有派工", file=sys.stderr)
            return 2
        assignment_id = items[0]["id"]

    uploads = fetch_file_index(client, assignment_id)
    if not uploads:
        print("这个派工还没有上传记录", file=sys.stderr)
        return 2

    upload = uploads[0]
    checks = verify_upload(client, upload, with_video=not args.no_video)

    if args.html:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(render_html(upload, checks))
        print(f"报告：{args.html}")

    if args.json:
        print(json.dumps(
            {"uploadId": upload.get("id"), "checks": [c.as_dict() for c in checks]},
            ensure_ascii=False, indent=2,
        ))
    else:
        print(f"上传 {upload.get('id')}  {upload.get('completedAt')}")
        for c in checks:
            print(f"  {'✓' if c.ok else '✗'} {c.rule} {c.name}  {c.detail}")
        failed = [c for c in checks if not c.ok]
        print(f"\n{len(checks) - len(failed)}/{len(checks)} 通过")
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
