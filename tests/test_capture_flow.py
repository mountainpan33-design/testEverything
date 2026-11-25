"""采集黄金链路：UI 全流程 +（可选）产物校验。

拆成两部分，互不阻塞：
  test_golden_ui_flow       —— 登录 → onboarding → 录制 → QC → done，只需真机
  test_golden_*（产物断言）  —— 需能读应用私有目录（debuggable 构建）；release 包自动 skip

对应 testcases.md：AUTH-01(UI) / AUTH-02 / ONB-01 / ONB-02 / CAP-04 / QC-01 / QC-07

前置：
  1. Appium server 在跑，ANDROID_HOME 指向 SDK 根目录
  2. 真机已连，首页有可用派工
  3. 产物校验额外要求：debuggable 构建 + ffmpeg（提供 ffprobe）

运行：pytest -m golden -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import device_files, gates, vision
from core.assertions import LayerAssertionError, assert_artifact, assert_negative, check, skip
from core.evidence import EvidenceCollector
from core.ota import latest_update
from core.permissions import grant_android_permissions
from core.run_id import new_run_id
from apis.collector_client import CollectorClient
from pages.capture_flow import CaptureFlow
from utils.logger import log

pytestmark = pytest.mark.golden


def _vision_check(driver, settings, run_dir, name: str) -> None:
    """截图并做视觉回归；基线不存在时自动建立（记为 skip）。

    视觉判定失败会抛 LayerAssertionError（应当让用例失败）；
    视觉工具本身出错（缺 Pillow、截图失败）只告警，不拖垮主链路。
    """
    if not settings.vision_enabled:
        return
    try:
        vision.check_screen(
            driver,
            name,
            settings.vision_baseline_dir,
            run_dir,
            tolerance=settings.vision_tolerance,
            update_baseline=settings.vision_update,
        )
    except LayerAssertionError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("视觉检查未完成（%s）: %s", name, e)


def _first_taxonomy_options(settings) -> tuple[str | None, str | None]:
    """从任务 config 取分类题第一项（仅当任务配了才需要选）。

    源码 assignmentTaxonomy.ts：environment_l1 / skill_group 是字符串数组，
    缺失或空数组时该题不出现。
    """
    try:
        c = CollectorClient(settings.api_base, settings.main_site_host)
        c.login(settings.username, settings.password)
        for a in c.my_assignments():
            if a.get("unavailableReason"):
                continue
            cfg = c.assignment(a["id"]).get("config") or {}
            if not isinstance(cfg, dict):
                continue
            env = [x for x in (cfg.get("environment_l1") or []) if isinstance(x, str) and x.strip()]
            skill = [x for x in (cfg.get("skill_group") or []) if isinstance(x, str) and x.strip()]
            return (env[0] if env else None, skill[0] if skill else None)
    except Exception as e:  # noqa: BLE001
        log.warning("读取任务分类选项失败（将按无分类题处理）: %s", e)
    return (None, None)


@pytest.fixture(scope="module")
def golden_run(driver, settings) -> dict:
    """跑一遍完整 UI 链路（只跑一次），并尽力拉取产物。

    失败时自己收集截图 + page_source + logcat（module 级 fixture 用不了
    函数级的 evidence fixture）。
    """
    udid = settings.android_udid
    package = settings.android_app_package
    assert udid, "黄金链路需要 ANDROID_UDID"
    assert package, "黄金链路需要 ANDROID_APP_PACKAGE"

    ec = EvidenceCollector(driver, new_run_id("golden"), settings.evidence_dir)
    vrun = vision.run_dir_for(settings)

    try:
        flow = CaptureFlow(driver)
        # 记录本轮被测的 OTA bundle（热更新会改 UI 文案，出问题要能归因到具体版本）
        ota = latest_update("android")
        log.info("被测 OTA: %s", ota)
        flow.ensure_ready(settings.username, settings.password)
        # 先授予运行时权限（系统弹窗在厂商 ROM 上不稳），失败不阻塞
        grant_android_permissions(udid, package)
        _vision_check(driver, settings, vrun, "home")
        flow.start_first_available_assignment()
        flow.confirm_precheck()
        _vision_check(driver, settings, vrun, "calib")
        flow.start_from_calib()
        flow.record_for(settings.golden_record_seconds)
        flow.stop_recording()
        _vision_check(driver, settings, vrun, "trim")
        flow.skip_trim()
        _vision_check(driver, settings, vrun, "qc")
        env_l1, skill = _first_taxonomy_options(settings)
        flow.submit_qc(
            lighting=settings.qc_lighting,
            tools=settings.qc_tools,
            env_l1=env_l1,
            skill=skill,
            l2=settings.qc_l2,
            l3=settings.qc_l3,
        )
        flow.wait_done()
        _vision_check(driver, settings, vrun, "done")
    except Exception:
        ec.collect_on_failure(udid=udid)
        raise

    result: dict = {"ui_ok": True, "package": None, "skip_reason": None}

    # 产物读取是「尽力」：release 包读不了不影响 UI 结论
    try:
        device_files.probe_app_files(udid, package)
        uuid = device_files.wait_for_episode(udid, package)
        result["package"] = device_files.pull_episode(
            udid, package, uuid, Path(settings.evidence_dir) / "golden"
        )
    except device_files.NotDebuggableError as e:
        result["skip_reason"] = str(e)
    return result


@pytest.fixture(scope="module")
def golden_package(golden_run) -> Path:
    if golden_run["skip_reason"]:
        skip("R-QC-01", f"产物校验跳过（环境限制）：{golden_run['skip_reason']}", layer="L3-产物")
        pytest.skip(f"产物校验跳过（环境限制）：{golden_run['skip_reason']}")
    return golden_run["package"]


# ---------------------------------------------------------------- UI 全流程
def test_golden_ui_flow(golden_run):
    """登录 → onboarding → 采一段 → 提交 QC → 到达 done。"""
    check(
        "R-FLOW-01",
        golden_run["ui_ok"] is True,
        expected="登录→自检→校准→录制→剪辑→QC→完成页 全通",
        actual="已到达完成页",
        layer="L1-UI",
    )


# ---------------------------------------------------------------- QC-01 / CAP-04
def test_golden_package_structure(golden_package: Path):
    """官方树 8 个文件齐全且非空。"""
    missing = [rel for rel in device_files.PACKAGE_FILES if not (golden_package / rel).is_file()]
    assert_artifact(not missing, f"包内缺少文件: {missing}", rule="R-QC-01",
                    expected="8 个官方文件齐全", actual=f"缺: {missing}")
    empty = [rel for rel in device_files.PACKAGE_FILES if (golden_package / rel).stat().st_size == 0]
    assert_artifact(not empty, f"包内文件为空: {empty}", rule="R-QC-01",
                    expected="所有文件非空", actual=f"空文件: {empty}")


def test_golden_metadata_identity(golden_package: Path):
    meta = json.loads((golden_package / "metadata.json").read_text(encoding="utf-8"))
    missing = [k for k in ("task_id", "episode_uuid") if not str(meta.get(k) or "").strip()]
    assert_artifact(not missing, f"metadata 缺少身份字段: {missing}", rule="R-QC-02",
                    expected="task_id / episode_uuid 非空", actual=f"缺: {missing}")


def test_golden_manifest_has_streams(golden_package: Path):
    manifest = json.loads((golden_package / "streams_manifest.json").read_text(encoding="utf-8"))
    assert_artifact(isinstance(manifest.get("streams"), dict), "manifest 缺少 streams 定义",
                    rule="R-QC-03", expected="streams 为对象",
                    actual=str(type(manifest.get("streams")).__name__))


def test_golden_video_is_mp4(golden_package: Path):
    video = golden_package / "videos" / "headcam.mp4"
    ok = device_files.has_mp4_ftyp(video)
    assert_artifact(ok, "视频缺少 MP4 ftyp 头", rule="R-QC-04",
                    expected="文件头含 ftyp", actual=f"ftyp={ok}")


def test_golden_video_spec(golden_package: Path, settings):
    """视频规格：可解析、时长 > 0、达到验收规格（默认 1080p30，可用 QA_VIDEO_* 覆盖）。"""
    info = device_files.ffprobe(golden_package / "videos" / "headcam.mp4")
    assert_artifact(info["duration"] > 0, f"视频时长为 0: {info}", rule="R-QC-05",
                    expected="时长 > 0", actual=str(info["duration"]))
    assert_artifact(
        gates.video_meets_spec(
            info["width"], info["height"], info["fps"],
            (settings.video_spec_width, settings.video_spec_height, settings.video_spec_fps),
        ),
        f"视频规格未达验收 {settings.video_spec_width}x{settings.video_spec_height}"
        f"@{settings.video_spec_fps}: 实际 {info}",
        rule="R-QC-05",
        expected=f"{settings.video_spec_width}x{settings.video_spec_height}"
        f"@{settings.video_spec_fps}",
        actual=f"{info['width']}x{info['height']}@{info['fps']}",
    )


def test_golden_sensor_series_have_rows(golden_package: Path):
    """camera.csv / imu.csv 必须有数据行（只有表头视为采集失败）。"""
    camera_rows = device_files.count_csv_data_rows(golden_package / "timestamps" / "camera.csv")
    imu_rows = device_files.count_csv_data_rows(golden_package / "imu" / "imu.csv")
    assert_artifact(camera_rows > 0, "camera.csv 只有表头，没有数据行", rule="R-CAP-01",
                    expected="至少 1 行数据", actual=f"{camera_rows} 行")
    assert_artifact(imu_rows > 0, "imu.csv 只有表头，没有数据行（传感器未启动或未落盘）",
                    rule="R-CAP-01", expected="至少 1 行数据", actual=f"{imu_rows} 行")


def test_golden_gps_placeholder_consistency(golden_package: Path):
    """QC-07：GPS 字段自洽——占位必须带 Unknown/XX 标记，真实定位必须在合法范围内。"""
    meta = json.loads((golden_package / "metadata.json").read_text(encoding="utf-8"))
    gps = meta.get("location_gps") or {}
    lat, lon = gps.get("lat"), gps.get("lon")
    city = str(meta.get("location_city") or "").strip()

    assert isinstance(lat, (int, float)) and isinstance(lon, (int, float)), (
        f"location_gps 坐标类型异常: {gps}"
    )

    if lat == 0 and lon == 0:
        assert_artifact(
            city in ("Unknown", "XX", ""),
            f"坐标是占位值 {gps}，但 location_city={city!r} 未标记为占位，上传前无法拦截",
            rule="R-QC-07",
            expected="占位坐标必须带 Unknown/XX 标记",
            actual=f"lat={lat}, lon={lon}, city={city!r}",
        )
    else:
        assert_negative(
            -90 <= lat <= 90 and -180 <= lon <= 180,
            f"真实定位坐标越界: lat={lat}, lon={lon}",
            rule="R-QC-07",
            expected="经纬度在合法范围",
            actual=f"lat={lat}, lon={lon}",
        )
