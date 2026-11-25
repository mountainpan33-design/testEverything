"""规则库（oracle）：定义「什么是对、什么是错」。

每条规则都来自源码，标注出处，供用例引用与报告对照。
判定口径：
  expected —— 正确的行为（断言应通过的条件）
  negative —— 错误的表现（出现即判失败）
  layer    —— 在哪一层判定：ui / api / artifact / gate / flow

用法：用例里 assert_*(cond, message, rule="R-QC-05")，报告按规则汇总。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    expected: str
    negative: str
    source: str
    layer: str = "ui"
    severity: str = "P0"


RULES: dict[str, Rule] = {
    # ---------------- 登录 / 会话 ----------------
    "R-AUTH-01": Rule(
        "R-AUTH-01", "主站账号登录成功",
        "登录返回 code=200 且 data 为非空 token；用该 token 调 /auth/me 能解析出身份",
        "登录后拿不到 token，或 /auth/me 401/无法解析",
        "src/mainSiteAuth.ts:106-117, src/platformAuth.ts:266-272", "api",
    ),
    "R-AUTH-02": Rule(
        "R-AUTH-02", "错误密码必须被拒绝",
        "code != 200 且返回可读 message，不发放 token",
        "错误密码仍返回 token 或 code=200",
        "src/mainSiteAuth.ts:106-112", "api",
    ),
    "R-AUTH-03": Rule(
        "R-AUTH-03", "连续失败锁定",
        "连续 5 次失败后锁定 15 分钟，锁定期间不再发请求",
        "失败次数不限或可绕过锁定",
        "src/app/login.tsx:40-41,178-181", "ui",
    ),
    "R-AUTH-04": Rule(
        "R-AUTH-04", "会话失效必须回登录",
        "任一业务接口返回 401 时，App 清会话并回到登录页",
        "401 后仍停留在数据页「假装已登录」",
        "src/collectionApi.ts:231-233", "ui",
    ),
    "R-AUTH-05": Rule(
        "R-AUTH-05", "服务器切换标识同步",
        "切到新服务器后，登录页顶部的当前服务器标识同步更新，业务请求打到新基址",
        "标识仍显示旧服务器，或界面切换了但请求仍走旧基址",
        "src/serverProfile.ts, src/collectionConfig.ts", "ui",
    ),
    "R-AUTH-06": Rule(
        "R-AUTH-06", "记住密码持久化",
        "勾选「记住密码」登录成功后退出登录、并冷启动重开，登录页仍预填「用户名」和「密码」两半，"
        "且不会自动登录；不重新输入直接点「登录」能再次登录成功",
        "退出或冷启动后账号/密码任一为空，或记住密码后仍需重新输入，或自动登录进首页",
        "src/rememberedLogin.ts, src/app/login.tsx:105-131", "ui",
    ),
    "R-AUTH-07": Rule(
        "R-AUTH-07", "忘记密码分角色指引",
        "「忘记密码」区分「众包申请人」与「供应商人员」两条找回路径",
        "只给一条通用提示，或直接跳转到一个不可用的页面",
        "src/app/login.tsx", "ui",
    ),
    # ---------------- onboarding ----------------
    "R-ONB-01": Rule(
        "R-ONB-01", "同意版本变更需重新同意",
        "consentVersion 落后于 CURRENT_CONSENT_VERSION 时回到 /consent",
        "旧同意状态直接放行进入采集",
        "src/onboardingState.ts:127-142", "ui",
    ),
    "R-ONB-02": Rule(
        "R-ONB-02", "权限未齐不得进入采集",
        "必需权限缺失时 CTA 为「开启权限」，未授权无法进入校准页",
        "缺权限仍可进入录制",
        "src/app/permissions.tsx:245-251", "ui",
    ),
    # ---------------- 视觉层：首页 / 采集辅助 / 语言 / 会话 ----------------
    "R-TASK-04": Rule(
        "R-TASK-04", "首页派工列表渲染",
        "有待采集派工时，首页渲染出卡片（任务标题 +「录制考核视频」按钮）；"
        "没有派工时显示「当前没有可采集的派工」；两种情况都不会停留在「正在拉取派工…」",
        "一直卡在加载中、显示「派工加载失败」，或空列表却没有任何提示",
        "src/app/(tabs)/home.tsx:37,133,153-269", "ui",
    ),
    "R-CAP-05": Rule(
        "R-CAP-05", "录制页锁定横屏",
        "进入录制页后界面固定为横屏（landscape），不随手机倾斜翻转，取景宽大于高",
        "录制页是竖屏，或录制中随手机朝向翻转",
        "src/app/record.tsx:83, src/useLandscapeLock.ts", "ui",
    ),
    "R-CAP-04": Rule(
        "R-CAP-04", "采集辅助默认关闭且改动可持久化",
        "没有 capture-options.json 时（Android）超广角/手部检测/语音口令/ARKit 标定四项默认关闭；"
        "改动后写入文件，杀进程重开保持改动",
        "首次进入默认开启；或改动后重开恢复默认",
        "src/captureOptionsPolicy.ts:10-15,31-37, src/captureOptions.tsx:14-22", "ui",
    ),
    "R-I18N-01": Rule(
        "R-I18N-01", "语言切换立即生效并持久化",
        "我的 › 语言切到 English 后界面文案立即变英文；杀进程重开仍是 English",
        "切换后界面文案不变，或重开回到中文",
        "src/i18n.tsx:44-60, src/app/(tabs)/me.tsx:198,342-352", "ui",
    ),
    "R-ONB-04": Rule(
        "R-ONB-04", "退出登录清会话但保留本地交付包",
        "退出登录后回到登录页；重新登录后「我的 › 本地交付包」仍能看到退出前的包",
        "退出登录后本地交付包被清空",
        "src/app/(tabs)/me.tsx:160-215, src/app/local-packages.tsx", "ui",
    ),

    "R-ONB-03": Rule(
        "R-ONB-03", "协议未勾选不得继续",
        "协议项未全部勾选时，「同意并继续」保持 disabled；全部勾选后才可点击",
        "未勾选也能点「同意并继续」进入权限页",
        "src/app/consent.tsx:125-135", "ui",
    ),
    # ---------------- 任务 ----------------
    "R-TASK-01": Rule(
        "R-TASK-01", "任务列表结构正确",
        "GET /my-assignments 返回数组，元素含 id/taskId，详情可查且一致",
        "返回对象而非数组、缺字段、列表与详情不一致",
        "src/collectionApi.ts:251-259", "api",
    ),
    "R-TASK-02": Rule(
        "R-TASK-02", "不可用任务不可采集",
        "unavailableReason 非空的任务不进入采集，并提示原因",
        "仍可开始采集或静默忽略该字段",
        "src/app/(tabs)/home.tsx:127-139", "ui",
    ),
    "R-TASK-03": Rule(
        "R-TASK-03", "采集必须绑定选定任务",
        "采集前 beginEpisodeForAssignment 写入 assignmentId，产物 metadata 带该任务",
        "产物没有任务归属，或绑定到别的任务",
        "src/captureSession.ts:164-178", "artifact",
    ),
    # ---------------- 采集 ----------------
    "R-CAP-01": Rule(
        "R-CAP-01", "录制必须产生完整数据",
        "录制后 video、camera.csv、imu.csv、pose.csv 均有内容",
        "视频为空/无 ftyp，CSV 只有表头",
        "src/captureSession.ts:219-291", "artifact",
    ),
    "R-CAP-02": Rule(
        "R-CAP-02", "记录结束原因",
        "metadata/草稿记录 user/max-duration/max-file-size/session-interrupted 等结束原因",
        "结束原因为空或被伪造成正常结束",
        "src/captureSession.ts:88-108", "artifact",
    ),
    "R-CAP-03": Rule(
        "R-CAP-03", "手检测关闭时不伪造手部数据",
        "手检测关闭时 QC 手样本为「未采样」，不是 0% 可见",
        "无采样却报告 0% 或伪造可见率",
        "AGENTS.md:41, src/qcMetrics.ts", "artifact",
    ),
    # ---------------- 产物结构 ----------------
    "R-QC-01": Rule(
        "R-QC-01", "官方包结构完整",
        "包内含 metadata.json / streams_manifest.json / videos/headcam.mp4 / "
        "timestamps/camera.csv / imu/imu.csv / calibration/{intrinsics,extrinsics}.yaml / pose.csv",
        "缺任一文件或文件为空",
        "src/episodePackageLayout.ts:6-15", "artifact",
    ),
    "R-QC-02": Rule(
        "R-QC-02", "metadata 身份字段完整",
        "metadata 含非空 task_id 与 episode_uuid",
        "缺身份字段（后端无法归属）",
        "src/packageValidation.ts:169-178", "artifact",
    ),
    "R-QC-03": Rule(
        "R-QC-03", "manifest 必须声明 streams",
        "streams_manifest.json 是合法 JSON 且含 streams 对象",
        "manifest 无效或缺 streams",
        "src/packageValidation.ts:223-233", "artifact",
    ),
    "R-QC-04": Rule(
        "R-QC-04", "视频必须是有效 MP4",
        "视频头含 ftyp box",
        "缺 ftyp（不可播放容器）",
        "src/packageValidation.ts:110-128", "artifact",
    ),
    "R-QC-05": Rule(
        "R-QC-05", "单条时长与规格达标",
        "裁剪后时长 ≥30 秒；分辨率/帧率满足验收规格（默认 1080p30）",
        "时长 <30 秒或规格不足",
        "src/qcTypes.ts:71, src/qcMetrics.ts:53", "artifact",
    ),
    "R-QC-06": Rule(
        "R-QC-06", "QC 必填项齐全",
        "光线、工具、具体场所(L2)、具体操作(L3) 必填；分类题按任务配置必填",
        "缺任一必填仍可提交",
        "src/app/qc.tsx:225-231", "ui",
    ),
    "R-QC-07": Rule(
        "R-QC-07", "占位定位不得放行",
        "GPS 超时的占位值必须同时标记 Unknown/XX，上传前强制人工填写",
        "0,0 坐标被当作真实定位上传",
        "src/packageValidation.ts:185-210", "artifact",
    ),
    "R-QC-08": Rule(
        "R-QC-08", "缺失与损坏区分处理",
        "可选流缺失=warning 不阻塞；文件存在但损坏=blocking",
        "损坏文件被当 warning 放行，或缺失被当 blocking 卡死",
        "src/packageValidation.ts:243-305", "gate",
    ),
    # ---------------- 上传 ----------------
    "R-UP-01": Rule(
        "R-UP-01", "上传三步协议",
        "create package → create upload(STS) → S3 put → complete，状态推进正确",
        "跳过任一步或 complete 后状态未变",
        "src/collectionApi.ts:303-387", "api",
    ),
    "R-UP-02": Rule(
        "R-UP-02", "fileName 只传 basename",
        "fileName 为纯文件名，目录信息放 relativePath",
        "fileName 含 / 被服务端拒绝",
        "src/collectionApi.ts:30-38", "api",
    ),
    "R-UP-03": Rule(
        "R-UP-03", "上传绑定采集时任务",
        "上传使用 client_upload_binding.json 或采集时选择的 assignment",
        "静默改投第一个 my-assignments 行",
        "AGENTS.md:66, src/uploadBinding.ts", "api",
    ),
    # ---------------- 本地包 / 恢复 ----------------
    "R-LP-01": Rule(
        "R-LP-01", "崩溃可恢复",
        "存在 recording_in_progress.json 的包被标记 needsRecovery 并可恢复",
        "崩溃包不可见或无法恢复",
        "src/recoverInterruptedEpisode.ts", "ui",
    ),
    "R-LP-02": Rule(
        "R-LP-02", "恢复不伪造传感器数据",
        "无 sensors_live 落盘时 IMU 为 header-only 并给 warning",
        "生成凭空捏造的 IMU 样本",
        "AGENTS.md:68", "artifact",
    ),
    # ---------------- 端到端 ----------------
    "R-FLOW-01": Rule(
        "R-FLOW-01", "黄金链路可走通",
        "登录 → onboarding → 选任务 → 自检 → 校准 → 录制 → 剪辑 → QC → 完成页",
        "任一步卡死、跳错页或无法提交",
        "testcases.md P0 链路", "flow",
    ),
    "R-GATE-01": Rule(
        "R-GATE-01", "执行层辅助逻辑正确",
        "页面识别、选项分组、规格判定等纯函数在边界输入下结果正确",
        "分组错行、阈值判定相反、边界输入抛错",
        "core/screen.py, core/gates.py", "gate", "P1",
    ),
    "R-GATE-02": Rule(
        "R-GATE-02", "点击安全区判定正确",
        "默认避开底部 footer（防误触「放弃并重录」）；页面主 CTA 在底部时允许点击；顶部状态栏始终不可点",
        "主 CTA 落在底部被静默挡掉（黄金链路空转超时）、或安全区被整体放开导致误触危险按钮",
        "pages/capture_flow.py is_click_safe()", "gate", "P1",
    ),
    "R-UI-01": Rule(
        "R-UI-01", "关键页面视觉骨架与基线一致",
        "只比稳定骨架（顶部标题区 3%~15% + 底部固定区 86%~98%）差异 ≤ 容差；取景页（calib/record）"
        "画面为实时场景，仅要求非黑屏/空白（平均亮度、像素标准差在正常范围）",
        "骨架区出现黑屏/白屏/崩溃遮罩，标题或底部操作区缺失/错位/文案被改到超出容差；"
        "取景页黑屏（相机未出图）",
        "core/vision.py（区域截图对比）；对应 UI 渲染异常",
        "ui", "P1",
    ),
    "R-GATE-05": Rule(
        "R-GATE-05", "用例执行顺序与副作用声明",
        "每条用例在 cases/policy.yaml 里声明 order（normal/costly/destructive）；"
        "执行顺序必须是 普通 → 耗额度 → 破坏共享状态；声明 depends-on 的用例排在被依赖用例之后，"
        "依赖没通过则跳过而不是硬跑",
        "破坏共享状态的用例排到了它影响的用例之前；或用例没声明副作用就真跑了一次",
        "vision/src/plan.ts(sortByPolicy), vision/cases/policy.yaml", "gate",
    ),
    "R-GATE-04": Rule(
        "R-GATE-04", "视觉层安全网完整",
        "除障碍实现外不使用裸 aiWaitFor；障碍表每条有 detect/attribution；排除动作无副作用",
        "在通知中心/弹窗上误判成功；自动排除点掉「立即更新」「确定」改变工况；障碍缺归因导致误报缺陷",
        "vision/src/obstacles.ts, tests/test_vision_guards.py", "gate", "P1",
    ),
    "R-GATE-03": Rule(
        "R-GATE-03", "视觉层用例清单与实现一致",
        "vision/src/cases/index.ts 的 IMPLEMENTED 与 pytest 侧清单一致；PLANNED 与 IMPLEMENTED 不重号",
        "两侧清单漂移导致用例静默漏跑——报告显示全绿，实际有实现根本没执行",
        "vision/src/cases/index.ts, tests/test_vision_manifest.py", "gate", "P1",
    ),
}


def get(rule_id: str) -> Rule | None:
    return RULES.get(rule_id)


def by_rule_ids(ids: list[str]) -> list[Rule]:
    return [RULES[i] for i in ids if i in RULES]
