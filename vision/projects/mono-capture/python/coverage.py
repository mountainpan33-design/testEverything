"""50 条用例分别由哪一层验证。

为什么需要这张表：用例分散在四个执行器里（Midscene / jest / pytest / 人工），
没有一个统一入口的话，「50 条到底测了几条」只能靠人对。

字段：
  layer  vision | jest | pytest | covered | pending | manual
  spec   jest → 测试文件相对仓库根；pytest → 文件名::测试函数；covered → 被哪条覆盖
  note   说明（人工/待测时必填）
"""

COVERAGE: dict[str, dict[str, str]] = {
    # ---------------- 视觉层：npx tsx src/cli.ts ----------------
    "ONB-01": {"layer": "vision"},
    "ONB-02": {"layer": "vision"},
    "ONB-04": {"layer": "vision"},
    "ONB-05": {"layer": "vision"},
    "AUTH-01": {"layer": "vision"},
    "AUTH-02": {"layer": "vision"},
    "AUTH-03": {"layer": "vision"},
    "AUTH-04": {"layer": "vision"},
    "AUTH-05": {"layer": "vision"},
    "AUTH-06": {"layer": "vision"},
    "TASK-01": {"layer": "vision"},
    "TASK-02": {"layer": "vision"},
    "TASK-03": {"layer": "vision"},
    "CAP-01": {"layer": "vision"},
    "CAP-02": {"layer": "vision"},
    "CAP-05": {"layer": "vision"},
    "QC-09": {"layer": "vision"},
    "UP-04": {"layer": "vision"},
    "I18N-01": {"layer": "vision"},
    "FLOW-01": {"layer": "vision"},
    "LP-01": {"layer": "vision"},
    "LP-04": {"layer": "vision"},
    "LP-05": {"layer": "vision"},

    # ---------------- 单元测试：npm test (jest) ----------------
    "QC-02": {"layer": "jest", "spec": "src/__tests__/packageValidation-test.ts"},
    "QC-04": {"layer": "jest", "spec": "src/__tests__/packageValidation-test.ts"},
    "QC-08": {"layer": "jest", "spec": "src/__tests__/packageValidation-test.ts"},
    "TASK-04": {"layer": "jest", "spec": "src/__tests__/uploadBinding-test.ts"},
    "UP-01": {"layer": "jest", "spec": "src/__tests__/collectionUpload-test.ts"},
    "UP-02": {"layer": "jest", "spec": "src/__tests__/uploadBinding-test.ts"},
    "UP-03": {"layer": "jest", "spec": "src/__tests__/runConcurrentFileUploads-test.ts"},
    "UP-05": {"layer": "jest", "spec": "src/__tests__/uploadQueue-test.ts"},
    "UP-06": {"layer": "jest", "spec": "src/__tests__/collectionUpload-test.ts"},
    "UP-07": {"layer": "jest", "spec": "src/__tests__/uploadProgress-test.ts"},
    "UP-08": {"layer": "jest", "spec": "src/__tests__/collectionUpload-test.ts"},
    "CAP-06": {"layer": "jest", "spec": "src/__tests__/recordingEndCause-test.ts"},
    "LP-02": {"layer": "jest", "spec": "src/__tests__/recoverInterruptedEpisode-test.ts"},
    "LP-03": {"layer": "jest", "spec": "src/__tests__/sensorSpill-test.ts"},

    # ---------------- 产物层：真机录一遍再拉包（pytest -m golden） ----------------
    "QC-01": {"layer": "pytest", "spec": "test_capture_flow.py::test_golden_package_structure"},
    "QC-03": {"layer": "pytest", "spec": "test_capture_flow.py::test_golden_metadata_identity"},
    "QC-05": {"layer": "pytest", "spec": "test_capture_flow.py::test_golden_sensor_series_have_rows"},
    "QC-06": {"layer": "pytest", "spec": "test_capture_flow.py::test_golden_video_is_mp4"},
    "QC-07": {"layer": "pytest", "spec": "test_capture_flow.py::test_golden_gps_placeholder_consistency"},
    "CAP-04": {"layer": "pytest", "spec": "test_capture_flow.py::test_golden_sensor_series_have_rows"},

    # ---------------- 已被别的用例覆盖 ----------------
    "TASK-05": {"layer": "covered", "spec": "TASK-01", "note": "TASK-01 同时接受「有派工」和「明确空态」"},
    "I18N-02": {"layer": "covered", "spec": "I18N-01", "note": "I18N-01 已含切换 + 重开持久化"},

    # ---------------- 待版本 ----------------
    "ONB-03": {"layer": "pending", "note": "需要旧版 App 先同意一次再升级，等有版本更新时测"},

    # ---------------- 只能人工 ----------------
    "CAP-03": {"layer": "manual", "note": "需读原生 FrameOutput 挂载状态，自动化拿不到"},
    "CAP-07": {"layer": "manual", "note": "需另一 App 抢占相机复现 -11818；识别逻辑已有单测"},
    "CAP-08": {"layer": "manual", "note": "需长时间观察屏幕常亮，可配合 dumpsys power"},
    "CAP-09": {"layer": "manual", "note": "需真实说话触发语音口令"},
}
