"""把一次上传的资源包拉到本地目录，方便直接打开看。

为什么需要它：网页端预览接口有 512 KB 上限，超过就报
「文件超过在线预览上限（512 KB）」——imu.csv、pose.csv、视频全都会中招。
但 `/preview` 接口会返回一个带签名的临时下载地址，那里没有这个限制。

用法：
    python -m verification.fetch_package                     # 最近一次上传的全部文件
    python -m verification.fetch_package --only imu,pose,video
    python -m verification.fetch_package --out ./downloads
    python -m verification.fetch_package --upload <uploadId> # 指定某次上传
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

TARGETS = {
    "imu": ["imu/imu.csv"],
    "pose": ["pose.csv"],
    "camera": ["timestamps/camera.csv"],
    "video": ["videos/headcam.mp4"],
    "meta": ["metadata.json", "streams_manifest.json"],
    "calib": ["calibration/extrinsics.yaml", "calibration/intrinsics.yaml"],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="下载一次上传的资源包")
    parser.add_argument("--out", default="downloads", help="输出目录")
    parser.add_argument("--only", help="只下这几类：imu,pose,camera,video,meta,calib（逗号分隔）")
    parser.add_argument("--upload", help="指定 uploadId；默认取最近一次 COMPLETED")
    parser.add_argument("--assignment", help="派工 id；默认 my-assignments 第一个")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    from apis.collector_client import CollectorClient
    from verification.artifacts import _norm_path, fetch_content, fetch_file_index

    client = CollectorClient(
        os.environ["QA_API_BASE"], os.environ.get("QA_MAIN_SITE_HOST", "")
    )
    client.login(os.environ["QA_USERNAME"], os.environ["QA_PASSWORD"])

    assignment = args.assignment
    if not assignment:
        items = client.my_assignments()
        if not items:
            print("这个账号没有派工", file=sys.stderr)
            return 2
        assignment = items[0]["id"]

    uploads = [u for u in fetch_file_index(client, assignment) if u.get("status") == "COMPLETED"]
    if args.upload:
        uploads = [u for u in uploads if u["id"] == args.upload]
    if not uploads:
        print("没有找到 COMPLETED 的上传", file=sys.stderr)
        return 2

    upload = uploads[0]
    wanted: set[str] | None = None
    if args.only:
        wanted = set()
        for key in args.only.split(","):
            wanted.update(TARGETS.get(key.strip(), []))

    out = Path(args.out) / upload["id"][:8]
    out.mkdir(parents=True, exist_ok=True)

    print(f"上传 {upload['id']}  {upload.get('completedAt')}  →  {out}")
    for f in upload.get("files") or []:
        rel = _norm_path(f.get("relativePath") or f.get("fileName", ""))
        if wanted and rel not in wanted:
            continue
        size = f.get("size") or 0
        print(f"  下载 {rel} ({size / 1024:.0f} KB) …", end="", flush=True)
        data = fetch_content(client, upload, f)
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f" ok {len(data)} B")
    print(f"\n完成：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
