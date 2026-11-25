"""设备文件读取：从真机拉采集产物 + ffprobe 解析。

Android 走 `adb exec-out run-as`，要求安装的是 debuggable 构建（expo run:android
出来的 debug 包即可）；release 包 run-as 会被拒绝，需要在研发侧开 android:debuggable
或改用云真机的文件导出能力。

iOS 暂未实现（真机需 devicectl 导出容器，等 iOS 链路接入再补）。
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

from utils.logger import log

# 官方包结构（api 新命名，见 episodePackageLayout.ts PACKAGE_PATHS）
PACKAGE_FILES = [
    "metadata.json",
    "streams_manifest.json",
    "videos/headcam.mp4",
    "timestamps/camera.csv",
    "imu/imu.csv",
    "calibration/intrinsics.yaml",
    "calibration/extrinsics.yaml",
    "pose.csv",
]


class DeviceFileError(RuntimeError):
    pass


class NotDebuggableError(DeviceFileError):
    """安装的是 release 包，run-as 被系统拒绝 —— 属于环境限制，不是用例失败。"""


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _adb(udid: str, *args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    cp = _run(["adb", "-s", udid, *args], timeout=timeout)
    if cp.returncode != 0:
        raise DeviceFileError(
            f"adb {' '.join(args)} 失败: {cp.stderr.decode(errors='replace').strip()[:500]}"
        )
    return cp


def list_episodes(udid: str, package: str) -> list[str]:
    """列出设备上 Documents/episodes 下的包目录（uuid），按名称排序。"""
    cp = _run(["adb", "-s", udid, "shell", f"run-as {package} ls -1 files/episodes"])
    if cp.returncode != 0:
        err = cp.stderr.decode(errors="replace").strip()
        if "not debuggable" in err:
            raise NotDebuggableError(
                f"设备上的 {package} 不是 debuggable 构建，run-as 被系统拒绝，无法读取应用私有目录。\n"
                "三种解决方式（任选其一）：\n"
                "  1) 装 debug/development 构建：npx expo run:android（本机连着真机）\n"
                "  2) 让研发出一个 android:debuggable=true 的 QA 包（不要用于发布）\n"
                "  3) 改用云真机的文件导出能力（优测/TestMu）\n"
                f"原始错误：{err[:200]}"
            )
        raise DeviceFileError(f"adb run-as ls 失败: {err[:300]}")
    names = [n.strip() for n in cp.stdout.decode(errors="replace").splitlines() if n.strip()]
    return sorted(n for n in names if n not in {".", ".."})


def probe_app_files(udid: str, package: str) -> int:
    """开跑前探测能否读应用私有目录，返回现有包数量。

    黄金链路要录 30+ 秒，探测放在前面，通道不通就直接失败，不浪费一次录制。
    """
    if not udid:
        raise DeviceFileError("未配置 ANDROID_UDID")
    if shutil.which("adb") is None:
        raise DeviceFileError("找不到 adb，请把 SDK 的 platform-tools 加进 PATH")
    return len(list_episodes(udid, package))


def pull_episode(udid: str, package: str, uuid: str, dest_dir: Path) -> Path:
    """把单个包目录整包拉回本地，返回本地目录。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    cp = _adb(
        udid,
        "exec-out",
        f"run-as {package} tar -cf - files/episodes/{uuid}",
        timeout=300,
    )
    local_root = dest_dir / uuid
    if local_root.exists():
        shutil.rmtree(local_root, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(cp.stdout), mode="r:") as tf:
        # 只解 files/episodes/<uuid>/ 之下的内容，剥掉前缀
        for member in tf.getmembers():
            parts = Path(member.name).parts
            if len(parts) < 4 or parts[0] != "files" or parts[2] != uuid:
                continue
            rel = Path(*parts[3:])
            if rel == Path("."):
                continue
            target = local_root / rel
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            target.write_bytes(src.read())
    log.info("产物已拉取: %s", local_root)
    return local_root


def ffprobe(path: Path) -> dict:
    """返回 {width, height, fps, duration}；ffprobe 不可用时抛异常。"""
    if shutil.which("ffprobe") is None:
        raise DeviceFileError("未安装 ffprobe，请先 `brew install ffmpeg`（校验视频规格需要）")
    cp = _run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate,duration",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ],
        timeout=120,
    )
    if cp.returncode != 0:
        raise DeviceFileError(f"ffprobe 失败: {cp.stderr.decode(errors='replace')[:400]}")
    data = json.loads(cp.stdout.decode() or "{}")
    streams = data.get("streams") or [{}]
    s = streams[0]
    num, _, den = str(s.get("avg_frame_rate", "0/1")).partition("/")
    fps = float(num) / float(den) if den and float(den) else 0.0
    duration = s.get("duration") or (data.get("format") or {}).get("duration") or 0
    return {
        "width": int(s.get("width") or 0),
        "height": int(s.get("height") or 0),
        "fps": round(fps, 2),
        "duration": float(duration or 0),
    }


def has_mp4_ftyp(path: Path) -> bool:
    with path.open("rb") as f:
        return b"ftyp" in f.read(64)


def dump_logcat(udid: str, dest: Path, lines: int = 800) -> Path | None:
    """导出最近的 logcat，用于失败归因（401 / 崩溃 / RN 报错都在这）。"""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        cp = subprocess.run(
            ["adb", "-s", udid, "logcat", "-d", "-t", str(lines)],
            capture_output=True,
            timeout=60,
        )
        if cp.returncode != 0:
            return None
        dest.write_bytes(cp.stdout)
        log.info("logcat 已保存: %s", dest)
        return dest
    except Exception as e:  # noqa: BLE001
        log.warning("导出 logcat 失败: %s", e)
        return None


def grep_logcat(path: Path, keywords: list[str], limit: int = 30) -> list[str]:
    """从 logcat 里捞关键行（如 401 / JWT / expire），便于直接看结论。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    hits = []
    for line in text:
        low = line.lower()
        if any(k.lower() in low for k in keywords):
            hits.append(line.strip())
            if len(hits) >= limit:
                break
    return hits


def count_csv_data_rows(path: Path) -> int:
    """返回除表头外的数据行数。"""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    return max(0, len(lines) - 1)


def missing_package_files(udid: str, package: str, uuid: str) -> list[str]:
    """设备上该包缺失或为空的文件（按官方结构）。"""
    missing = []
    for rel in PACKAGE_FILES:
        cp = _run(
            ["adb", "-s", udid, "shell", f"run-as {package} test -s files/episodes/{uuid}/{rel}"]
        )
        if cp.returncode != 0:
            missing.append(rel)
    return missing


def wait_for_episode(
    udid: str, package: str, timeout: int = 240, poll: float = 3.0
) -> str:
    """等待最新一个包的 8 个文件全部落盘且非空，返回 uuid。

    导出是异步写盘，done 页出现不代表文件已写完，所以按文件是否齐全轮询。
    """
    deadline = time.time() + timeout
    last_state = "尚无任何包目录"
    while time.time() < deadline:
        episodes = list_episodes(udid, package)
        if episodes:
            uuid = episodes[-1]
            missing = missing_package_files(udid, package, uuid)
            if not missing:
                log.info("包已完整落盘: %s", uuid)
                return uuid
            last_state = f"{uuid} 仍缺: {', '.join(missing)}"
        time.sleep(poll)
    raise DeviceFileError(f"等待产物超时（{timeout}s）：{last_state}")
