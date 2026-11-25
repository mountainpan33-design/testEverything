# 单目采集 App（ApexCollect）自动化测试用例设计

基于 `mono-capture` 源码（AGENTS.md + `src/app/*` + `src/*.ts`）梳理，对齐四层断言框架。
生成时间：2026-11-19；2026-11-20 增加「驱动方式」维度（接入 Midscene.js）。
随代码迭代维护。

## 阅读约定

**断言层**（对齐接口层「HTTP/字段/副作用/不应返回」）：

| 层 | 含义 | 本 App 的落点 |
|----|------|--------------|
| L1 UI | 页面/元素状态 | 登录离开登录页、按钮可点、页面落地 |
| L2 API | 接口副作用 | token 有效、my-assignments 数据、upload 状态 |
| L3 产物 | 文件/包结构校验 | 官方树 7 类文件、ffprobe、packageValidation |
| L4 负向 | 不应出现/应拦截 | 占位 GPS 拦截、不可用任务不可采、锁定期 |

**自动化可行性**：`接口`（CollectorClient，沙箱/本地可跑）· `UI`（真机）· `纯函数`（单测下沉）· `产物`（真机录制 + 文件校验）· `手动`（暂无法自动化）

**驱动方式**（2026-11-20 起，接入 Midscene.js 后新增）：

| 驱动 | 干什么 | 什么时候用它 |
|------|--------|--------------|
| `Midscene` | 视觉驱动，看图找元素，不依赖控件树 | 纯 UI 跳转、表单、列表、i18n——文案改了不用改脚本 |
| `Appium` | 按 `accessibilityLabel` 精确定位 | 相机预览相关页、需要精确控制点击位置的页、要拿产物的链路 |
| `adb` | 进程管理、权限授予、装包、杀进程 | 验证「冷启动」「杀进程重开」「权限被拒」这类系统级前置 |
| `pytest 接口` | `CollectorClient` 直连后端 | L2 接口副作用，不需要界面 |
| `pytest 纯函数` | gate 层单测 | 规格判定、包校验、分组、时长区间——毫秒级 |
| `pytest 产物` | `run-as` 拉包 + ffprobe + 文件检查 | L3 产物事实校验 |
| `手动` | 人来做 | 语音口令、并发体感这类暂无法自动化的 |

**驱动方式不是「哪个更先进」，是「哪个更不容易误判」**：

- 同一能力能落到接口或纯函数层的，**不要**挪到视觉层——慢几十倍、花钱、还会因模型理解偏差假失败。
- 相机预览是 SurfaceView，视觉截图大概率是黑图。凡是要看取景画面的（CAP-01/03/05），一律 Appium。
- **采集页与 QC 页禁用开放式 `aiAct`**：这两页底部有「放弃并重录」，模型一旦理解偏就可能点中，作废一段已录素材、消耗任务额度。必须用 `aiTap` 点明确元素名词。

**优先级**：P0 冒烟/黄金链路必测 · P1 核心边界 · P2 次要

---

## 模块 1：登录与服务器切换（AUTH）

> 源码：`login.tsx`、`mainSiteAuth.ts`、`platformAuth.ts`
> 关键事实：新协议两步登录（主站 auth-center + DCP /auth/me，双重编码）；主站账号登录前须切「新服务器」；5 次失败锁 15 分钟。

### AUTH-01 主站账号登录成功进入 onboarding
- 优先级：P0 ｜ 断言：L1+L2 ｜ 自动化：UI（真机）+ 接口 ｜ 驱动：Midscene + pytest 接口
- 前置：已切「新服务器」；有有效主站账号（如 pss2）
- 步骤：登录页填用户名/密码 → 点「登录」
- 预期：离开登录页；接口返回 `code=200` 且拿到 token；`GET /auth/me` 返回身份

### AUTH-02 登录前自动切新服务器（默认未选中新服务器时）
- 优先级：P0 ｜ 断言：L1 ｜ 自动化：UI（真机） ｜ 驱动：Midscene
- 步骤：登录前点「新服务器（118.196）」→ 用主站账号登录
- 预期：成功登录；server-profile 写为 new

### AUTH-03 错误密码登录失败
- 优先级：P0 ｜ 断言：L1+L2+L4 ｜ 自动化：接口（可本地）+ UI ｜ 驱动：Midscene + pytest 接口
- 步骤：正确账号 + 错误密码 → 登录
- 预期：停留登录页；接口 `code != 200` 且返回主站 message；错误提示展示

### AUTH-04 连续 5 次失败锁 15 分钟
- 优先级：P1 ｜ 断言：L1+L4 ｜ 自动化：UI ｜ 驱动：Midscene
- 步骤：连续 5 次错密码 → 再试
- 预期：第 6 次直接提示「尝试次数过多，请 15 分钟后再试」，不发请求；锁定期间输入/按钮不可用

### AUTH-05 记住密码持久化
- 优先级：P1 ｜ 断言：L1 ｜ 自动化：UI ｜ 驱动：Midscene + adb
- 步骤：勾「记住密码」登录 → 杀进程重开
- 预期：登录页用户名/密码预填，记住勾选态保持；默认不勾时重开为空

### AUTH-06 忘记密码弹窗
- 优先级：P2 ｜ 断言：L1 ｜ 自动化：UI ｜ 驱动：Midscene
- 步骤：点「忘记密码」
- 预期：弹窗区分「众包申请人→跳众包找回」与「供应商人员→联系管理员」两条路径

---

## 模块 2：onboarding 与权限（ONB）

> 源码：`onboardingState.ts`、`consentLedger.ts`、`permissions.tsx`、`consent.tsx`
> 关键事实：冷启动 `login → consent → permissions → home`；consent 按 user 持久化、onboarding 按 session。

### ONB-01 首次登录进入 consent 同意页
- 优先级：P0 ｜ 断言：L1 ｜ 自动化：UI ｜ 驱动：Midscene
- 前置：该账号未同意过当前 consent 版本
- 步骤：登录成功
- 预期：落地 `/consent`，未勾选不能继续

### ONB-02 同意 → 权限引导 → home
- 优先级：P0 ｜ 断言：L1 ｜ 自动化：UI ｜ 驱动：Midscene + adb
- 步骤：同意协议 → 完成权限引导（相机/麦克风/定位/运动健身）
- 预期：落地 `/home`；`onboardingComplete=true` 持久化，冷启动直达 home

### ONB-03 consent 版本升级强制重新同意
- 优先级：P1 ｜ 断言：L1 ｜ 自动化：手动（发版级） ｜ 驱动：手动
- 前置：本地 consentVersion 低于 `CURRENT_CONSENT_VERSION`
- 步骤：冷启动
- 预期：即使已登录也回到 `/consent`
- 说明：**2026-11-20 修正**——原标「Midscene + adb」是错的。纯 UI 造不出「版本落后」这个状态，
  必须装旧版 App 同意一次再升级，属于发版级验证，不适合放进日常批跑。

### ONB-04 拒绝权限后 precheck 再次门禁
- 优先级：P1 ｜ 断言：L1+L4 ｜ 自动化：UI ｜ 驱动：Appium + adb
- 步骤：权限引导中拒绝相机/麦克风 → 进入采集
- 预期：precheck 检测缺失权限并再次请求/阻断；不给权限不能进入录制

### ONB-05 退出登录清 session 但保留本地包
- 优先级：P2 ｜ 断言：L2+L3 ｜ 自动化：UI ｜ 驱动：Midscene + adb + pytest 产物
- 步骤：我的 → 退出登录
- 预期：session 与 onboarding 标志清除回登录页；`Documents/episodes/` 本地包仍在

---

## 模块 3：任务列表（TASK）

> 源码：`collectionApi.ts`、`(tabs)/home.tsx`、`captureSession.ts`、`assignmentTaxonomy.ts`
> 关键事实：采集必须绑定「开始采集时选定的 assignment」；只有 SUPPLIER_MANAGED + 有效 bucket 才能上传。

### TASK-01 首页 my-assignments 列表加载
- 优先级：P0 ｜ 断言：L1+L2 ｜ 自动化：UI + 接口 ｜ 驱动：Midscene + pytest 接口
- 步骤：登录进 home → 查看任务列表
- 预期：UI 展示与 `GET /my-assignments` 一致（id/taskName/config/deliveryMode）

### TASK-02 不可用任务（unavailableReason 非空）不可采集
- 优先级：P1 ｜ 断言：L1+L4 ｜ 自动化：UI + 接口 ｜ 驱动：Midscene + pytest 接口
- 步骤：列表含 unavailableReason 非空的任务 → 尝试点它
- 预期：该任务不可开始采集，展示不可用原因；`pickUploadableAssignment` 不选中它

### TASK-03 选任务开始采集绑定 assignmentId
- 优先级：P0 ｜ 断言：L2 ｜ 自动化：UI + 接口 ｜ 驱动：Appium + pytest 产物
- 步骤：点某任务「开始采集」
- 预期：`beginEpisodeForAssignment` 写入 assignmentId；导出包 metadata 含该 task_id/assignment

### TASK-04 上传绑定在采集时选定的 assignment
- 优先级：P1 ｜ 断言：L2+L4 ｜ 自动化：接口（可本地） ｜ 驱动：pytest 接口
- 步骤：A 任务开始采集 → 尝试上传到 B 任务
- 预期：拒绝或走 `client_upload_binding.json` 绑定，不静默选第一个 my-assignments

### TASK-05 空任务列表状态
- 优先级：P2 ｜ 断言：L1 ｜ 自动化：UI ｜ 驱动：Midscene
- 步骤：用无 assignment 的账号登录
- 预期：空态展示，不崩溃

---

## 模块 4：采集准备与录制（CAP）

> 源码：`captureSession.ts`、`episodeSensors.ts`、`captureCamera.ts`、`captureOptions.tsx`、`precheck.tsx`、`calib.tsx`、`record.tsx`
> 关键事实：传感器先于 GPS 启动；单一 landscape 锁定；5 种结束原因；录制中禁止启动 ARSession；手检测 Android 为 stub。

### CAP-01 precheck 设备检查通过进入采集
- 优先级：P0 ｜ 断言：L1 ｜ 自动化：UI ｜ 驱动：Appium
- 步骤：完成任务 → 进入 precheck
- 预期：检查项（权限/相机/传感器）通过后进入采集准备

### CAP-02 采集辅助选项默认关、独立持久化
- 优先级：P1 ｜ 断言：L1 ｜ 自动化：UI ｜ 驱动：Midscene
- 前置：读取 `Documents/capture-options.json`
- 步骤：查看「采集辅助」三开关
- 预期：手检测/语音命令/ARKit 默认全关；切换后独立持久化，重开保持

### CAP-03 手检测关闭时卸载 FrameOutput、保留核心视频/IMU
- 优先级：P1 ｜ 断言：L1+L3 ｜ 自动化：UI + 产物 ｜ 驱动：Appium + pytest 产物
- 步骤：手检测关 → 录制
- 预期：不加载 FrameOutput；保留 horizon/motion 读数 + 视频 + IMU；QC 手样本显示「not sampled」（非 0% visible）

### CAP-04 录制产生视频 + IMU + 传感器数据
- 优先级：P0 ｜ 断言：L3 ｜ 自动化：产物（真机） ｜ 驱动：Appium + pytest 产物
- 步骤：录制一段 → 停止
- 预期：`imu.csv`/`camera.csv`/`pose.csv` 有数据行；IMU ≥100Hz（实测）；传感器先于 GPS 启动无滞后

### CAP-05 方向锁定单一 landscape
- 优先级：P1 ｜ 断言：L1 ｜ 自动化：UI ｜ 驱动：Appium
- 步骤：进入录制页旋转设备
- 预期：锁定 `LANDSCAPE_RIGHT`，视频不因设备翻转而 L/R 翻转

### CAP-06 录制结束原因记录
- 优先级：P1 ｜ 断言：L3 ｜ 自动化：产物 ｜ 驱动：Appium + pytest 产物
- 步骤：分别触发用户停止/最大时长/最大文件大小
- 预期：metadata 记录对应 `recordingEndCause`（user/max-duration-reached/max-file-size-reached）

### CAP-07 录制中 AVCapture 被抢占（-11818）
- 优先级：P1 ｜ 断言：L3+L4 ｜ 自动化：产物 ｜ 驱动：Appium + pytest 产物
- 步骤：录制中来电/切后台触发 session 抢占
- 预期：记为 `session-interrupted`，包可诊断；不伪装成正常 user 结束

### CAP-08 录制中保持唤醒
- 优先级：P2 ｜ 断言：L1 ｜ 自动化：UI ｜ 驱动：Appium
- 步骤：录制中静置观察
- 预期：iOS 不自动锁屏（expo-keep-awake）

### CAP-09 语音口令 KWS 命中开始录制
- 优先级：P1 ｜ 断言：L1 ｜ 自动化：手动（需真机 mic + 中端安卓） ｜ 驱动：手动
- 步骤：开语音命令 → 说口令
- 预期：KWS 命中触发开始录制；不命中不误触发

---

## 模块 5：QC / 裁剪 / 导出（QC）

> 源码：`packageValidation.ts`、`episodeExport.ts`、`trim.tsx`、`done.tsx`、`qc.tsx`
> 关键事实：官方树 7 类文件；校验分 blocking/warning；占位 GPS 必须人工填；缺失=warning、损坏=blocking。

### QC-01 录制后裁剪导出写官方树
- 优先级：P0 ｜ 断言：L3 ｜ 自动化：产物（真机） ｜ 驱动：Appium + pytest 产物
- 步骤：录制 → trim → done
- 预期：`Documents/episodes/{uuid}/` 含 7 类文件：`{uuid}.json`、`streams_manifest.json`、`videos/{uuid}_headcam.mp4`、`timestamps/camera.csv`、`imu/{uuid}_imu.csv`、`calibration/*_{intrinsics,extrinsics}.yaml`、`pose.csv`

### QC-02 合法包无 blocking 问题可上传
- 优先级：P0 ｜ 断言：L3 ｜ 自动化：纯函数 + 产物 ｜ 驱动：pytest 纯函数
- 步骤：对完整合法包跑 `validatePackage`
- 预期：blocking 为空，可上传

### QC-03 metadata 缺 task_id/episode_uuid → blocking
- 优先级：P1 ｜ 断言：L3+L4 ｜ 自动化：纯函数 ｜ 驱动：pytest 纯函数
- 步骤：构造缺 task_id 或 episode_uuid 的 metadata
- 预期：blocking「缺少字段」，不可上传

### QC-04 JSON 无效/截断 → blocking
- 优先级：P1 ｜ 断言：L3 ｜ 自动化：纯函数 ｜ 驱动：pytest 纯函数
- 步骤：metadata 或 manifest 写成半截 JSON
- 预期：blocking「不是有效的 JSON（可能写入不完整）」

### QC-05 CSV 只有表头/缺列 → blocking
- 优先级：P1 ｜ 断言：L3 ｜ 自动化：纯函数 ｜ 驱动：pytest 纯函数
- 步骤：camera.csv 只有 header；imu.csv 缺 `timestamp` 列
- 预期：分别 blocking「只有表头，没有数据行」「缺少列 timestamp」

### QC-06 视频缺 ftyp 头 → blocking
- 优先级：P1 ｜ 断言：L3 ｜ 自动化：纯函数 ｜ 驱动：pytest 纯函数
- 步骤：视频文件内容不是 MP4（无 ftyp box）
- 预期：blocking「不是有效的 MP4 文件」

### QC-07 GPS 占位 {0,0}+Unknown/XX → blocking 拦截
- 优先级：P0 ｜ 断言：L3+L4 ｜ 自动化：纯函数 + UI ｜ 驱动：pytest 纯函数 + Midscene
- 步骤：GPS 超时导出 `{lat:0,lon:0}` + `Unknown/XX` → 尝试上传
- 预期：`assessLocationGaps` 报 blocking，上传前 LocationFillModal 强制人工填写，占位值不得到达后端

### QC-08 缺失 camera.csv/imu.csv/pose.csv/calibration → warning 不阻塞
- 优先级：P1 ｜ 断言：L3 ｜ 自动化：纯函数 ｜ 驱动：pytest 纯函数
- 步骤：删掉这些文件后校验
- 预期：warning 提示，不阻塞上传（区分「缺失=warning」vs「损坏=blocking」）

### QC-09 QC 问卷写入 sidecar
- 优先级：P2 ｜ 断言：L3 ｜ 自动化：产物 ｜ 驱动：Midscene + pytest 产物
- 步骤：填 lighting/tools/notes/environmentL1-3
- 预期：`postRecord`/`clientQc` 写入 metadata

---

## 模块 6：上传（UP）

> 源码：`collectionApi.ts`、`collectionUpload.ts`、`uploadQueue.ts`、`uploadConcurrency.ts`、`s3SignV4.ts`
> 关键事实：package 三步协议；fileName 只 basename；3 并发；后台队列；绑定采集时 assignment。

### UP-01 package 协议上传走通
- 优先级：P0 ｜ 断言：L2 ｜ 自动化：接口 + 产物 ｜ 驱动：pytest 接口 + pytest 产物
- 步骤：create package → create upload（STS）→ S3 put → complete
- 预期：三步走通，complete 后 package 状态推进，返回 `packageStatus`

### UP-02 fileName 只传 basename（带 `/` 被拒）
- 优先级：P1 ｜ 断言：L2+L4 ｜ 自动化：接口 ｜ 驱动：pytest 接口
- 步骤：create upload 传 `fileName=videos/headcam.mp4`
- 预期：API 拒绝（fileName 只 basename，relativePath 单独传）

### UP-03 3 并发 + 字节加权进度
- 优先级：P1 ｜ 断言：L2 ｜ 自动化：接口/手动 ｜ 驱动：pytest 接口
- 步骤：多文件包上传观察并发与进度
- 预期：并发 ≤3；进度按字节加权

### UP-04 后台队列：离开页面不取消、串行、浮窗位置
- 优先级：P1 ｜ 断言：L1+L2 ｜ 自动化：UI ｜ 驱动：Midscene
- 步骤：上传中离开 done/local-packages → 观察浮窗
- 预期：传输继续；一次一个包串行；浮窗显示批内位置（1/2→2/2）

### UP-05 重传重新 arm 已完成/失败 job
- 优先级：P1 ｜ 断言：L2 ｜ 自动化：接口 ｜ 驱动：pytest 接口
- 步骤：对已上传/失败的包点「再次上传」
- 预期：重新入队执行，不静默 no-op

### UP-06 STS 过期刷新凭证
- 优先级：P1 ｜ 断言：L2 ｜ 自动化：接口 ｜ 驱动：pytest 接口
- 步骤：STS 过期后续传
- 预期：`refresh credentials` 走通，上传继续

### UP-07 iOS bigint vs Android number 进度
- 优先级：P2 ｜ 断言：L2 ｜ 自动化：纯函数 + 双端冒烟 ｜ 驱动：pytest 纯函数 + 双端冒烟
- 步骤：双端各传一次观察进度
- 预期：`toByteCount` 正确处理 bigint，不抛 `Cannot convert BigInt to number`（build 35 iOS 上传全挂教训，改上传路径必须双端冒烟）

### UP-08 durationSeconds 字段向后兼容
- 优先级：P1 ｜ 断言：L2+L4 ｜ 自动化：接口 ｜ 驱动：pytest 接口
- 步骤：后端 DTO 不支持 `durationSeconds` 时上传
- 预期：检测 400 后降级不传，不阻塞上传

---

## 模块 7：本地交付包 / 崩溃恢复（LP）

> 源码：`localEpisodes.ts`、`recoverInterruptedEpisode.ts`、`uploadBinding.ts`
> 关键事实：崩溃留 recording_in_progress.json + recording.tmp.mp4；恢复不伪造传感器样本。

### LP-01 崩溃恢复标记与恢复 CTA
- 优先级：P0 ｜ 断言：L1+L3 ｜ 自动化：UI ｜ 驱动：Appium + adb + pytest 产物
- 步骤：录制中杀进程 → 重开进「本地交付包」
- 预期：该包标 `needsRecovery` 并有「恢复」按钮

### LP-02 恢复 promote headcam + densify camera.csv
- 优先级：P1 ｜ 断言：L3 ｜ 自动化：产物 ｜ 驱动：Appium + pytest 产物
- 步骤：点恢复
- 预期：提升 headcam、densify camera.csv、写近似 calib/metadata/binding、清恢复标记

### LP-03 恢复后真实 IMU 仅 sensors_live 有 spill 才有
- 优先级：P1 ｜ 断言：L3+L4 ｜ 自动化：产物 ｜ 驱动：pytest 产物
- 步骤：恢复一个 sensors_live 未落盘的包
- 预期：IMU 为 header-only，warning 不阻塞；**不伪造样本**（不得发明传感器数据）

### LP-04 本地交付包重新上传绑定
- 优先级：P1 ｜ 断言：L2 ｜ 自动化：接口 ｜ 驱动：pytest 接口
- 步骤：重传本地包
- 预期：优先读 `client_upload_binding.json`；缺失时人工显式选 assignment（不自动选第一个）

### LP-05 App 重启本地包保留
- 优先级：P2 ｜ 断言：L3 ｜ 自动化：产物 ｜ 驱动：pytest 产物
- 步骤：重启 App
- 预期：本地包仍在磁盘（进程丢失 = 重传，不丢素材）

---

## 模块 8：多语言（I18N）

> 源码：`i18n.tsx`、`(tabs)/me.tsx`
> 关键事实：仅 zh/en 两种，默认随设备，可手动覆盖并持久化。

### I18N-01 默认随设备语言
- 优先级：P1 ｜ 断言：L1 ｜ 自动化：UI ｜ 驱动：Midscene + adb
- 步骤：设备语言 zh / en 各冷启动一次
- 预期：界面文案跟随设备语言

### I18N-02 手动切换语言持久化
- 优先级：P1 ｜ 断言：L1 ｜ 自动化：UI ｜ 驱动：Midscene + adb
- 步骤：我的 › 语言 切换 → 杀进程重开
- 预期：切换后立即生效且重开保持

---

## 汇总

### P0 黄金链路（必测）

| 编号 | 用例 | 自动化 | 驱动 |
|------|------|--------|------|
| AUTH-01 | 主站账号登录成功 | UI + 接口 | Midscene + pytest 接口 |
| AUTH-02 | 登录前自动切新服务器 | UI | Midscene |
| AUTH-03 | 错误密码失败 | 接口 + UI | Midscene + pytest 接口 |
| ONB-01 | 首次登录进 consent | UI | Midscene |
| ONB-02 | 同意→权限→home | UI | Midscene + adb |
| TASK-01 | my-assignments 列表 | UI + 接口 | Midscene + pytest 接口 |
| TASK-03 | 选任务绑定 assignmentId | UI + 接口 | Appium + pytest 产物 |
| CAP-01 | precheck 通过进采集 | UI | Appium |
| CAP-04 | 录制产生视频+IMU+传感器 | 产物 | Appium + pytest 产物 |
| QC-01 | 导出写官方树 7 类文件 | 产物 | Appium + pytest 产物 |
| QC-02 | 合法包无 blocking | 纯函数 | pytest 纯函数 |
| QC-07 | 占位 GPS 拦截 | 纯函数 + UI | pytest 纯函数 + Midscene |
| UP-01 | package 协议上传走通 | 接口 + 产物 | pytest 接口 + pytest 产物 |
| LP-01 | 崩溃恢复标记与 CTA | UI | Appium + adb + pytest 产物 |

### 驱动方式分布（49 条，按主驱动计）

| 主驱动 | 条数 | 用例 |
|--------|------|------|
| **Midscene** | 18 | AUTH-01~06、ONB-01/02/03/05、TASK-01/02/05、CAP-02、QC-07/09、UP-04、I18N-01/02 |
| **Appium** | 12 | ONB-04、TASK-03、CAP-01/03/04/05/06/07/08、QC-01、LP-01/02 |
| **pytest 接口** | 8 | TASK-04、UP-01/02/03/05/06/08、LP-04 |
| **pytest 纯函数** | 8 | QC-02~06、QC-08、UP-07、QC-07（与 Midscene 共用） |
| **pytest 产物** | 2 | LP-03、LP-05 |
| **手动** | 1 | CAP-09 |

Midscene 覆盖 18 条，集中在登录 / onboarding / 列表 / i18n 这些**没有相机、没有产物**的纯跳转和表单页。
采集链路（CAP-01/03~08、QC-01、LP-01/02）12 条仍在 Appium——相机预览截图会黑，视觉驱动验不了取景画面。

**尚未纳入 Midscene、但值得评估的**：UP-04 已标 Midscene，但它要验的是「离开页面后传输继续」，视觉只能看到浮窗，真正的传输状态还得从接口或日志侧确认，实际是 Midscene + 接口两条一起看。

### 落地顺序建议

1. **先用 Midscene 打通 ONB-01/02/03**：无相机、无产物、纯 UI 跳转，是视觉驱动最舒服的区间，也正好覆盖 POC 里踩到的「复选框未勾导致按钮置灰、模型反复点录制按钮」那个失败模式。
2. 再扩到 AUTH-01~06 与 TASK-01/02/05、I18N-01/02。i18n 那两条对 Appium 是负担（切英文后中文 `accessibilityLabel` 定位全失效），对 Midscene 零成本。
3. 接口层：AUTH-01/03、TASK-01 已实现并跑通；UP 三步（写操作）待确认后接。
4. 纯函数单测：`core/gates.py` 已有 6 条基础门禁；应用自身的包校验逻辑（QC-02~08）归 jest 单测，不在 pytest 层重复实现。
5. 产物：CAP-04、QC-01 需真机录制 + ffprobe 校验（黄金链路最后补）。

---

## 用例与规则映射（oracle）

规则库在 `core/rules.py`，每条规则写明「正确表现 / 错误表现 / 源码出处」。
用例断言一律带规则编号，报告据此判断对错。主要映射：

| 用例 | 规则 | 判什么 |
|------|------|--------|
| AUTH-01 | R-AUTH-01 | 登录返回 token 且 /auth/me 可解析 |
| AUTH-03 | R-AUTH-02 | 错误密码必须被拒绝 |
| AUTH-04 | R-AUTH-03 | 连续失败锁定 |
| （会话失效） | R-AUTH-04 | 401 必须回登录 |
| ONB-01/03 | R-ONB-01 | 同意版本变更需重新同意 |
| ONB-04 | R-ONB-02 | 权限未齐不得进入采集 |
| TASK-01 | R-TASK-01 | 任务列表结构正确 |
| TASK-02 | R-TASK-02 | 不可用任务不可采集 |
| TASK-03 | R-TASK-03 | 采集必须绑定选定任务 |
| CAP-04 | R-CAP-01 | 录制产生视频 + IMU + camera 数据 |
| CAP-06 | R-CAP-02 | 记录结束原因 |
| CAP-03 | R-CAP-03 | 手检测关闭时不伪造手部数据 |
| QC-01 | R-QC-01 | 官方包 8 文件齐全非空 |
| QC-03 | R-QC-02 | metadata 身份字段完整 |
| QC-04（manifest） | R-QC-03 | manifest 声明 streams |
| QC-06（视频） | R-QC-04 | 视频含 ftyp |
| QC-05/QC-07（时长） | R-QC-05 | 时长 ≥30s、规格达标 |
| QC-07（必填） | R-QC-06 | QC 必填项齐全 |
| QC-07（GPS） | R-QC-07 | 占位定位不得放行 |
| QC-08 | R-QC-08 | 缺失 warning / 损坏 blocking |
| UP-01 | R-UP-01 | 上传三步协议 |
| UP-02 | R-UP-02 | fileName 只 basename |
| TASK-04/LP-04 | R-UP-03 | 上传绑定采集时任务 |
| LP-01 | R-LP-01 | 崩溃包可恢复 |
| LP-03 | R-LP-02 | 恢复不伪造传感器数据 |
| 端到端 | R-FLOW-01 | 黄金链路可走通 |
| 门禁单测 | R-GATE-01 | 辅助纯函数正确 |
| 视觉回归 | R-UI-01 | 关键页面非黑屏/白屏，且与基线差异在容差内 |

## 执行与报告

```bash
pytest                 # 默认 gate + api + smoke
pytest -m golden       # 黄金链路（真机）
```

每次运行结束自动生成报告：`reports/report_<时间>.html`（含环境、OTA 版本、逐条断言、规则对照、失败详情）
和同名 `.json`（供 CI 使用）。失败时的截图/page_source/logcat 在 `evidence/<run_id>/`。

## 实现状态（2026-11-20）

| 状态 | 数量 | 说明 |
|------|------|------|
| 已实现且已执行通过 | 11 | 接口 4（AUTH-01/03、TASK-01/02）+ 门禁 6 + 产物辅助 1 |
| 已实现待真机执行 | 2 | `test_login_ok`（AUTH-01 UI + AUTH-02）、黄金链路 7 条（CAP-04、QC-01、QC-07） |
| 仅有设计文档 | 39 | 需逐条实现 |

### 按驱动方式看进度

| 驱动 | 已标用例 | 已落地 | 说明 |
|------|----------|--------|------|
| Midscene | 18 | **0** | 2026-11-20 只跑通 playground 与一条采集流程，尚无 pytest 化的脚本 |
| Appium | 12 | 2 | `test_login_ok` 已通；黄金链路 7 条已实现待真机复跑 |
| pytest 接口 | 8 | 4 | AUTH-01/03、TASK-01/02 |
| pytest 纯函数 | 8 | 6 | gates 6 条；QC-02~08 归 jest，不在 pytest 重复实现 |
| pytest 产物 | 2 | 1 | `device_files` 已可用，用例待接 |
| 手动 | 1 | 0 | CAP-09 语音口令 |

**Midscene 这 18 条现在还没有一条是脚本。** 标出来的是「该用什么驱动」，不是「已经跑通」。
做 POC 时跑的是 playground 里的自由指令，还没沉淀成可重复执行的断言；下一步是把 ONB-01/02/03 写成第一条带 `aiAssert` 的脚本。

已执行结果（沙箱，`pytest -m "api or gate"`）：**10 passed**。
- 接口 4 条：AUTH-01 登录成功、AUTH-03 错误密码、TASK-01 任务列表与详情一致、TASK-02 不可用标记类型
- 门禁 6 条：IMU 频率、视频规格、时长区间、抽帧整数倍等

黄金链路（需本地真机执行，`pytest -m golden`）：
CAP-04 视频+传感器数据、QC-01 官方树 8 文件、QC-07 GPS 占位自洽，共 7 条断言。
实现文件：`pages/capture_flow.py`（七步 UI 流程）、`core/device_files.py`（run-as 拉包 + ffprobe）。

未覆盖说明：应用自身的包结构校验（`packageValidation.ts`）属于 App 逻辑，正确位置是 jest 单测（`src/__tests__/`），pytest 侧只做「真实产物事实校验」（ffprobe/文件存在性），避免两套实现漂移。


