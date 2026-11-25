# App 真机自动化骨架（Appium · 安卓 + iOS）

单人维护的三层自动化（接口 pytest / Web Playwright / App Appium）里的 **App 层**骨架。
技术选型：**Appium 跨端统一 + 本地/云混合**——安卓以本地真机为主、云真机补机型；iOS 主走云真机（本地 iOS 需 Mac + 开发者证书，成本高）。

## 目录结构

```
app-automation/
├── conftest.py               # driver/run_id/evidence fixture + 失败留证 hook
├── config/                   # 配置层
│   ├── settings.py           #   读 .env，单一数据源
│   ├── caps_android_local.py #   安卓本地真机 caps（UiAutomator2）
│   └── caps_ios_cloud.py     #   iOS 云真机 caps（XCUITest，预留签名）
├── core/                     # 核心层
│   ├── driver_factory.py     #   本地/云、双平台 driver 创建
│   ├── assertions.py         #   四层断言封装
│   ├── run_id.py             #   每条用例唯一 run_id
│   ├── evidence.py           #   失败留证 / 成功清理
│   └── gates.py              #   门禁纯函数（下沉单测，不依赖设备）
├── pages/                    # 页面对象
│   ├── base_page.py
│   ├── login_page.py
│   └── capture_page.py
├── apis/                     # 采集端 API 客户端（接口层断言用）
│   └── collector_client.py
├── tests/                    # 用例
│   ├── test_login.py         #   登录链路冒烟（UI + 接口双层断言）
│   └── test_capture_flow.py  #   录制→产物→上传 黄金链路（标 TODO）
└── utils/logger.py
```

## 卡住了怎么排查

按这个顺序看，通常两分钟能定位：

1. **看日志的 `[screen] xxx`** —— 现在停在哪个页面，是不是跑偏了（跳登录 = 会话失效，跳自检 = 误触放弃）。
2. **看 `evidence/<run_id>/screenshot.png`** —— 失败那一刻屏幕上是什么，键盘是否挡住按钮。
3. **看报告的失败规则** —— 是 UI 找不到、产物不对、还是接口失败。
4. **常见卡点与对策**：
   - 元素在屏幕下方没滚动到 → 脚本会先滚到「可交互带」（屏高 8%~68%）再点；
   - 选项/按钮在底部 footer 被安全区拒绝 → 主 CTA 需要 `allow_bottom=True`；
   - 键盘遮挡输入框/按钮 → 每填一个字段就收一次键盘（点非交互标题，不按 BACK）；
   - 页面文案被热更新改掉 → 定位全用关键词包含，失败时报错会 dump 当前所有标签。

所有循环都有预算上限，不会无限滑动：找元素最多 `QA_MAX_SWIPES` 次，自适应补答
`QA_MAX_ROUNDS` 轮，候选文案 `QA_MAX_CANDIDATES` 个，QC 填答整体 `QA_QC_TIMEOUT` 秒。
到点立即失败并留下 screenshot / page_source / logcat。日志里每滑动 5 次会打一行
`[flow] 已累计滑动 N 次`，可判断它是在推进还是在磨。

## 视觉回归

黄金链路会截取关键页面（首页 / 校准 / 剪辑 / QC / 完成页）做检查：

- **能发现**：黑屏、白屏、崩溃遮罩，标题区/底部操作区缺失或错位，骨架文案被意外改动
- **不能发现**：中间业务内容的正确性（时长、通过概率、任务名、缩略图每轮都不同）→ 靠断言与人工

机制（2026-11-20 按真机实测调整）：

1. **不做整屏对比**。App 中间区域一直在变（首页任务名、QC 的「72%」「0:39」、状态栏时钟），
   整屏比必然误报——实测校准页差异 80%，而页面本身完全正常。
2. 只比**稳定骨架**：顶部标题区 3%~15% + 底部固定区 86%~98%（`core/vision.py: CHROME_REGIONS`）。
   基线仍存整屏截图，比对时按区域裁剪，改口径不用重拍基线。
3. **相机取景页**（calib/record）拍的是真实场景，两次必然不同，**不做像素对比**，
   只保留黑屏/白屏检测（相机没出图、预览空白）。
4. 黑屏判定：平均亮度 < 8；空白判定：像素标准差 < 3。

调参：`QA_VISION=0` 关闭；`QA_VISION_TOLERANCE=0.02` 调整骨架区容差；
`QA_VISION_UPDATE=1` 用当前截图覆盖基线（确认改动符合预期后再开）。
规则编号 `R-UI-01`，单测在 `tests/test_vision.py`。

## 规则库（什么是对 / 什么是错）

`core/rules.py` 是判定的唯一出处：每条规则写明

- `expected`：正确表现（断言通过的条件）
- `negative`：错误表现（出现即失败）
- `source`：源码出处（文件:行），口径随代码走

用例里的断言一律带规则编号（如 `R-QC-05`），报告按规则汇总，谁对谁错一目了然。
新增规则只需加一条定义，用例引用即可。

## 测试报告

每次 pytest 结束自动生成：

- `reports/report_<时间>.html` —— 环境（平台/设备/账号脱敏/API/被测 OTA 版本）、
  结论（通过/失败/跳过）、逐条断言（规则、层、期望 vs 实际）、规则对照表、失败详情
- `reports/report_<时间>.json` —— 同内容结构化数据，供 CI/看板使用

失败时的截图、page_source、logcat（含 401 关键行）保存在 `evidence/<run_id>/`。

## 四层断言（对齐接口层「HTTP/字段/副作用/不应返回」）

| 层 | App 层映射 | 用途 |
|----|-----------|------|
| L1 UI | 元素存在 / 可见 / 文本 / 状态 | 登录成功进首页、按钮可点 |
| L2 接口 | 调采集端 API 验证副作用 | 登录后 token 有效、assignment 数据一致 |
| L3 产物 | 录制产物 ffprobe 校验（时长/分辨率） | 黄金链路的核心验收 |
| L4 负向 | 不应出现的东西 | 未登录看不到任务、已删除数据不返回 |

## 一条命令

```bash
cd app-automation
./go.sh                 # 装环境（如需要）→ 跑全部 50 条 → 出报告 → 自动打开
./go.sh --quick         # 只跑代码层（单元+门禁+接口），不碰设备，几十秒
./go.sh --check         # 只检查环境
./go.sh --apk app.apk   # 先装被测包再跑
./go.sh --golden        # 额外跑黄金链路（真机 + 录制额度）
./go.sh --no-open       # 跑完不自动打开报告
```

报告固定写 `vision/midscene_run/reports/all-latest.html`，50 条按用例编号排好，
标明执行层与结果（通过/失败/跳过/未跑/人工/待测）。

## 快速开始

**一条命令装环境**（建 venv、装依赖、检查设备与配置，幂等可重复跑）：

```bash
cd app-automation
./setup.sh                  # 装 + 检查
./setup.sh --check-only     # 只检查，不动任何东西
./setup.sh --skip-node      # 跳过 node_modules
```

它会报出：缺哪个基础工具、venv 是否可用、Python 依赖是否齐全、
node_modules 是不是别的平台装的（esbuild 跨平台会炸，这条能提前发现）、
.env 是否缺项、有没有已授权设备。全部通过才返回 0。

手动版本（等价）：

```bash
cd app-automation
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # 填 QA_USERNAME / QA_PASSWORD / ANDROID_UDID 等
appium                          # 起 Appium server（另开终端）

pytest                          # 默认：gate + api + smoke
pytest -m gate                  # 门禁纯函数单测，不依赖设备/网络
pytest -m api                   # 接口层（只需网络）
pytest -m smoke                 # UI 冒烟（需真机 + Appium）
pytest -m golden                # 黄金链路（需真机 + ffmpeg）
```

## 多台设备

设备不绑死。`.env` 里的 `ANDROID_UDID` 只是**默认偏好**：

- 它在线 → 用它
- 它不在线、只有一台在线 → 自动用那台，并打一行警告
- 多台同时在线 → 必须 `--device <序列号>` 指定，不会瞎猜

```bash
adb devices                                  # 看当前有哪些
./go.sh --device 11478404BV100148            # 指哪台跑哪台
./install_app.sh app.apk --all               # 所有在线设备都装
./install_app.sh app.apk --device X          # 只装一台
```

多台并行测试时，建议每台单独跑一轮并各自出报告：

```bash
for d in $(adb devices | awk 'NR>1 && $2=="device"{print $1}'); do
  ./go.sh --device "$d" --no-open
  cp vision/midscene_run/reports/all-latest.html "reports/all-$d.html"
done
```

## 装测 App 到设备

```bash
./install_app.sh ../build/app-release.apk        # 装 + 打开 + 确认在前台
./install_app.sh app.apk --device 4aff97de       # 多台设备时指定
./install_app.sh app.apk --clean                 # 装完清数据（首次安装状态）
./install_app.sh app.apk --no-launch             # 只装
./install_app.sh --uninstall                     # 卸载
```

包名和设备默认从 `.env` 的 `ANDROID_APP_PACKAGE` / `ANDROID_UDID` 取，
装完会打印 versionName 并确认 App 真的在前台。

## 黄金链路（CAP-04 / QC-01）前置

`pytest -m golden` 会真实跑一遍：首页选任务 → precheck → calib → 录制 → trim → QC → done，
再把产物从设备拉回本地校验。需要：

1. **Appium server** 在跑，`ANDROID_HOME` 指向真实 SDK 根目录（不是 adb 文件路径）；
2. **真机**已连（`adb devices` 可见），且安装的是 **debuggable 构建**——脚本用
   `adb exec-out run-as <包名>` 读应用私有目录。**release 包会报 `package not debuggable`**，
   解决方式任选：装 debug 构建（`npx expo run:android`）、让研发出一个 `android:debuggable=true`
   的 QA 包、或改用云真机的文件导出能力。脚本会在开录前先探测，通道不通立即失败，不浪费录制；
3. **ffmpeg**（提供 ffprobe）：`brew install ffmpeg`；
4. **相机/麦克风权限已授予**，首页 **有可用派工**（不可用或考核审核中的任务点不动）；
5. 默认录制 **35 秒**（QC 要求 ≥30 秒），可用 `QA_GOLDEN_RECORD_SECONDS` 调整；
6. 视频验收规格默认 **1920x1080@30**，可用 `QA_VIDEO_WIDTH/HEIGHT/FPS` 覆盖；
7. 若该任务配置了必填分类（分类题），QC 提交按钮会禁用——需要人工先选一次或扩展脚本。

产物会拉到 `evidence/golden/<uuid>/` 供排查，包含 8 个官方文件。

黄金链路拆成两部分，互不阻塞：
- `pytest -m golden -k ui_flow` —— 只跑 UI 全流程（登录 → 同意页 → 权限页 → 录制 → QC → done），
  release 包也能跑；
- `pytest -m golden` —— UI 流程 + 产物校验；release 包读不了应用私有目录时，产物断言自动
  skip 并给出原因，不会把 UI 结论一起带挂。

## 自适应层（应对界面变数）

`core/screen.py` + `pages/capture_flow.py` 不再按固定顺序盲点，而是：

- **页面识别**：每步先判断当前在哪个页面（登录/同意/权限/首页/自检/校准/录制/剪辑/QC/完成），
  再决定动作；日志会打 `[screen] xxx`。
- **偏航可解释**：跳到登录页 → 报「会话失效（401）」；退回自检 → 报「误触放弃/返回」；
  其他意外 → 报出期望页面、实际页面和当前界面全部标签。
- **QC 自适应填答**：先按 `.env` 配置值点选项；若提交仍不可用，则把选项 chip 按行分组，
  每组补选一个、填所有空的单行输入框（跳过多行备注），轮数受 `QA_MAX_ROUNDS` 限制，
  仍不行再兜底补多行备注，直到提交按钮可用。
- **空输入框怎么判**：Android 上空框的 `text` 属性**不是空串，而是占位示例文案**
  （`text="例如：电子厂、厨房、超市" showing-hint="true"`），所以判空走 `core/inputs.py`
  （showing-hint / hint 比对），不能只看 text 非空；写完后会回读校验，占位符还在就当没写进去。
  排查时看日志里 `[QC] 进入 QC 时 输入框#n text=… hint=… multiline=…` 这组行。
  这样即使任务新增必填分类题、文案变化，也能自己补齐。
- **安全点击**：底部 22% 是固定 footer（放弃并重录/提交），点击前校验落点，避免误触导致录制作废。
- **不用 BACK 收键盘**：Android 上 `hide_keyboard()` 会发 BACK（会退出页面），改为点非交互标题收起。

## 热更新导致 UI 文案漂移（重要）

App 的 JS 走 expo-updates 热更新，**设备上的文案可能与仓库代码不一致**（已实际发生：
设备显示「录制作业视频」，仓库只有「录制考核视频」，全部分支/历史都搜不到）。因此：

- 按钮类定位一律用关键词包含（如「录制…视频」），不写整句；
- 定位失败时会把当前屏幕的可读标签 dump 进报错；
- 每轮 UI 用例会记录被测 OTA 的 updateId（`core/ota.py`）；
- 文案改动后可用 `python tools/dump_labels.py` 快速重新校准；
- 查当前线上 bundle：`python tools/ota_manifest.py`。

根治仍需「安装包与仓库对齐」：发 OTA 前先提交代码，并告知测试发了哪一版。

## 登录态与登出策略

- 用例**结束时不会登出**。会话保留在设备上，下一轮直接进首页，省掉登录和权限引导。
- 唯一会触发登出的情况：进入首页后发现是内置演示身份「林晓雨」（说明当时没有真实会话），
  脚本会自动「我的 → 退出登录 → 退出」，再用 `.env` 里的账号重新登录。
- 如果你在运行过程中看到登录页，通常是上面这个自动纠正动作，不是测试结束登出。
- 需要每轮都从干净登录态开始时，可手动在 App 里退出，或告诉我加 `QA_LOGOUT_AFTER=1` 开关
  （注意：登出会清掉 session，`onboardingComplete` 是按会话记录的，下一轮会重新走权限引导）。

## 合并进 qa-automation

本骨架是独立的 `app-automation/`，可直接整体拷到 `mono-capture-main/qa-automation/` 下，或把
`app-automation/` 里的目录（config/core/pages/apis/tests/utils + conftest.py）平铺进现有 App 层。
注意三点：

1. `.env` 里的 `QA_API_BASE` 必须和接口层指向同一个环境，避免 UI 与接口断言对不上；
2. `pytest.ini` 的默认 `-m "smoke or gate or api"` 是按本骨架的口径，合并时若接口层已有统一配置需对齐；
3. 真机 UDID / 账号密码只进本地 `.env`，绝不提交。

## iOS 前置（重要）

iOS 真机自动化要求被测 app 是 **development 签名**，且测试真机 UDID 在 provisioning profile 里。
**TestFlight 包（distribution 签名）无法被 XCUITest 驱动**。所以 iOS 侧必须先拿到研发的
development 签名 ipa，再决定本地跑（Mac + 开发者账号）还是交给云真机重签安装。本骨架 iOS 驱动层已按
「云真机」预留，等 ipa 到位即可填。
