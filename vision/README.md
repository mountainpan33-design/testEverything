# vision —— Midscene.js 视觉驱动层

用视觉模型看截图来点界面，不依赖控件树。它是 `app-automation` 的**补充**，不是替换：
接口层、纯函数层、产物层还在原来的 pytest 里，只有「纯 UI 跳转和表单」这类用例挪到这里。

## 它解决什么问题

原来 Appium 那套靠 `accessibilityLabel` 定位，两个地方很痛：

- **文案一改就全废**。`录制考核视频` 改成 `录制作业视频`，脚本里所有中文标签都要跟着改。
- **切语言要写两套**。I18N 用例切到英文后，中文定位器全部失效。

视觉驱动看图找元素，这两类问题都不存在。代价是不确定性——同一个指令可能这次过、下次不过。

## 目录

分成三层，各管一段，互不越界：

```
vision/
├── cases/                    用例定义（改用例只改这里，不用懂 TypeScript）
│   ├── cases.yaml            人写并审核过的用例
│   ├── derived.yaml          从源码派生的结构性冒烟（--derive 生成，可整份删掉重来）
│   ├── review.html           审核页（--review-page 生成）
│   ├── fragments.yaml        可复用片段（bootstrap / login / logout）
│   ├── policy.yaml           执行顺序与副作用声明（order 必填）
│   ├── planned.yaml          已登记但还没实现的（缺口不能藏起来）
├── src/
│   ├── plan.ts               ① 生成层：YAML → 可执行计划 + 校验 + 审核字段
│   ├── derive.ts             从 src/app 的路由和文案派生冒烟用例 + 覆盖缺口矩阵
│   ├── review.ts             审核页（自包含 HTML，勾选后导出 JSON）
│   ├── reviewApply.ts        审核结果写回 YAML（文本级，保留注释，写坏回滚）
│   ├── run.ts                ② 执行层：逐步交给 Midscene，不带守卫
│   ├── heal.ts               ③ 修正层：卡住 → 读日志 → 给用例打补丁 → 验证才合并（≤3 轮）
│   ├── patch.ts              文本级插入补丁（保留 cases.yaml 的注释与排版）
│   ├── analyze.ts            读日志判根因（修正层用的引擎）
│   ├── report.ts             自包含 HTML 报告
│   ├── agent.ts              创建 Agent、模型配置、输入策略
│   ├── prepare.ts            前置状态（清数据 / 回登录页）
│   ├── adb.ts                adb 小工具：前台包名、控件树、输入法
│   ├── recorder.ts           断言 → core/rules.py 的规则编号
│   ├── obstacles.ts          障碍表（失败归因用）
│   ├── appContext.ts         App 常识
│   └── login.ts              登录页判断
├── .env.example
└── package.json
```

## 第一次跑

```bash
cd app-automation/vision
npm install
cp .env.example .env      # 填模型四件套 + 账号

npx tsx src/cli.ts --list                 # 看有哪些用例
npx tsx src/cli.ts --dry-run              # 看执行计划（不碰设备、不花钱）
npx tsx src/cli.ts --cases ONB-01 --out /tmp/v.json   # 先跑一条
npx tsx src/cli.ts --all --out /tmp/v.json            # 全跑
```

## 一次性跑完：前置状态是自动摆的

用例之间**不是独立的**，每条对「进来时 App 是什么状态」有要求。裸跑会互相污染：

```
ONB-01 登录成功（离开登录页）→ AUTH-01 要求「停在登录页」→ 直接挂
```

所以每条用例带一个 `precondition`，CLI 在跑它之前自动摆好：

| precondition | 怎么摆 | 用在哪些用例 |
|---|---|---|
| `fresh-install` | `adb shell pm clear` + 冷启动，等登录页出现 | ONB-01、ONB-02（要「从未同意过协议」） |
| `login-page` | 我的 → 退出登录 → 确认；退不掉就清数据兜底 | AUTH-01/03/04/05/06 |
| `login-page-old-server` | 先回登录页，再切「旧服务器（52.39）」 | AUTH-02 |

**除 AUTH-02 外，摆完状态都会确保连的是「新服务器」。**
这个 App 默认连旧服务器（52.39），而测试账号在新服务器（118.196）上——
漏了这一步，登录会直接报 `fetch failed: java.net.ConnectException`，
看起来像产品挂了，其实是连错了地方。

**摆不出来就跳过，不判失败**——那是环境问题，不是被测行为有问题。跳过原因会写进结果 JSON。

`--dry-run` 会把这张表打出来，不连设备也不花钱，建议每次改动用例先看一眼。

`--all` 会先打一条费用提醒：每个界面动作都要调一次模型，按次计费，整轮通常 10~25 分钟。
中途 Ctrl-C 不丢已跑完的结果。

模型配置四项缺一不可，名字是 Midscene 定的：

```bash
MIDSCENE_MODEL_BASE_URL="https://app.ppapi.us/v1"   # 中转必须带 /v1，否则 307 跳登录页
MIDSCENE_MODEL_API_KEY="..."
MIDSCENE_MODEL_NAME="deepseek-v4.1-flash"
MIDSCENE_MODEL_FAMILY="deepseek"
```

官方 AppControlBench（60 个 iOS 任务）的成绩：豆包 Seed 2.1 Turbo 98% / Qwen3.7 Plus 97% /
DeepSeek V4.1 Flash 90%。预算够就用前两个，别用弱模型试出「能力下限」当成框架不行。

## 和 pytest 的关系

`tests/test_vision_flow.py` 是桥：

```
pytest -m vision
  └─ 检查前置（node / node_modules / 设备 / 模型 Key / 账号），缺就 skip
  └─ adb 预授予采集权限（绕开厂商 ROM 的系统弹窗）
  └─ subprocess 调一次 `npx tsx src/cli.ts --all --out <tmp>/vision.json`
  └─ 把 JSON 里的断言登记进 core.results，和其它层进同一份 HTML 报告
```

不让 pytest 逐条调 Node，是因为每起一个进程都要重连 adb、重建 Agent：慢，而且容易抢设备。

`pytest` 默认**不跑** vision（`addopts` 里没有它）：要真机、要花钱、有不确定性。
它不适合当门禁，适合发版前跑一轮。

## 三层：用例 → 执行 → 修正

**① 生成层（plan.ts）**：读 `cases/*.yaml`，展开 `include` 片段，校验后编译成可执行计划。
校验不过就一条都不跑，把所有问题一次说完——不会跑到第 6 条才发现编号重复。

```yaml
- id: AUTH-01
  title: 主站账号登录成功
  precondition: login-page
  steps:
    - launch: true
    - wait: { for: 当前界面是登录页，能看到「用户名」「密码」输入框, timeout: 20000 }
    - include: login
    - wait: { for: 满足任意一条：① 已离开登录页…；② 仍停在登录页但出现红色错误, timeout: 30000 }
    - assert: { rule: R-AUTH-01, expect: 当前界面是协议页、权限页或首页三者之一, fatal: true }
```

可用动作：`launch / terminate / back / tap / input / wait / assert / repeat / if / include`。
用 `--dry-run` 可以把每条用例展开成中文步骤看一眼，不碰设备。

**② 执行层（run.ts）**：逐步交给 Midscene，一个动作一次调用，和手写脚本一样。
这一层**故意没有**障碍扫描、不变量、读回校验——那些是上一版的成本来源，
卡住的补救统一交给第三层。

**③ 修正层（heal.ts）**：跑完挑出「阻塞」的用例（跳过、失败且不是产品缺陷），
读本次日志判根因，能修的就**直接改用例本身**（`cases/cases.yaml`），然后重跑验证。

三条边界写死在这里：

- **只写数据**。修正只改 `cases.yaml` 里的步骤，不改任何代码。
- **验证通过才合并**。补丁先写进去、重跑那一条；跑通了才留下，跑不通自动还原。
  仓库里不会出现没验证过的改动。
- **只修环境阻塞**。判成产品缺陷、断言写错的不重试——重试改变不了产品。
- **最多 3 轮**。修不好的东西，第四轮也修不好，继续跑只是烧钱。

第 2 轮起只重跑上轮卡住的，通过的不再跑。每轮改了什么、为什么改，都写进 HTML 报告。

```bash
npx tsx src/cli.ts --all --out ./last-run.json     # 默认开启，最多 3 轮
npx tsx src/cli.ts --all --no-heal                 # 只跑一遍
npx tsx src/cli.ts --rounds 2                      # 收紧轮数（上限仍是 3）
```

**报告每轮都出 HTML**，落在 `midscene_run/reports/run-<时间>.html`（`--html` 可指定）。
报告里有自愈过程表（每轮跑了多少、改了什么、为什么改），以及**失败截图和过程录屏**。

- 截图：失败那一刻自动抓，内联进 HTML，报告仍是单文件。
- 录屏：每条用例一段，存到 `midscene_run/videos/<用例编号>.mp4`，报告里用相对路径引用，
  移动报告时把 `videos/` 一起带走。`screenrecord` 单段上限 180s，超时的用例会在报告里标注「被截断」。
- 不想录：`--no-video`（截图仍然抓，它很小）。

**注意：截图和录屏里有测试账号和密码输入过程，带媒体的报告只可内部使用，不要外发。**

## Appium 定位符：从源码生成，不手抄

```bash
npm run gen-pages          # 检查是否过期（有差异退出码 1）
npm run gen-pages:write    # 重新生成
```

产物是 `app-automation/pages/ui_locators.py`，**自动生成、请勿手改**：

```python
APP_LOGIN = {
    "用户名": (AppiumBy.ACCESSIBILITY_ID, "用户名"),
    "密码": (AppiumBy.ACCESSIBILITY_ID, "密码"),
    "登录": (AppiumBy.ACCESSIBILITY_ID, "登录"),
    ...
}
```

为什么这么做：Appium 用例脆在定位符上，`accessibilityLabel` 一改，手抄的常量就断，
而这类改动很常见。定位符本来 100% 由源码决定，交给机器抄。

手写用例这样取定位符：

```python
from pages.ui_locators import APP_LOGIN, locator
self.find(locator(APP_LOGIN, "用户名"))
```

取不到会直接抛 `KeyError` 并列出这个页面有哪些 label，不会静默点错元素。

`tests/test_vision_guards.py::test_locators_match_source` 会在 gate 里跑一次生成检查：
改了 label 没重新生成，直接红。

## 一条命令跑完所有层

50 条用例分散在四个执行器里，分开跑就得看四份结果。统一入口：

在 `app-automation` 目录下、**用 venv 里的 python**（系统只有 `python3`，没有 `python`）：

```bash
cd ~/mono-capture/app-automation
source .venv/bin/activate          # 或直接 .venv/bin/python -m ...
python -m verification.run_all                 # 单元 + 门禁 + 接口 + 视觉层
python -m verification.run_all --no-vision     # 不跑真机
python -m verification.run_all --with-artifact # 外加产物校验（要账号）
python -m verification.run_all --with-golden   # 外加黄金链路（要真机 + 额度）
```

按 `verification/coverage.yaml` 的归属表把各层结果合并到用例编号，出一份
`vision/midscene_run/reports/all-latest.html`：每条用例一行，标明执行层、结果和说明。

状态六种：通过 / 失败 / 跳过 / **未跑** / **人工** / **待测**。
「未跑」是没跑到（没装依赖、没连设备），不是通过——报告里必须能区分这两件事。

某层跑不起来不会中断整体：缺 appium 或缺 node_modules 时该层记未跑，其余照常。

## 产物层校验：界面看不到的，从包本身验

视觉层只能看界面。包对不对，要靠拉下产物来验——用**测试账号自己登录**就能取，不需要浏览器凭据。

```bash
cd app-automation
python -m verification.artifacts                       # 校验最近一次上传
python -m verification.artifacts --no-video            # 跳过 26MB 视频，快
python -m verification.artifacts --html report.html    # 出 HTML 报告
pytest -m artifact                                     # 同一套逻辑接进门禁
```

校验项（都对到 `core/rules.py`）：

| 规则 | 检查 |
|---|---|
| R-UP-01 | 状态 COMPLETED；每个文件 size == expectedSize |
| R-QC-01 | 8 个必需文件齐全；各文件 SHA-256 与 metadata 记录一致 |
| R-QC-02 | metadata 必填字段非空 |
| R-QC-03 | manifest 声明 video + imu 两条 required 流；分辨率声明自洽 |
| R-QC-04 | 视频可解码；**实际分辨率 == 声明分辨率** |
| R-QC-05 | 视频时长 ≈ metadata 时长 ≈ camera.csv 时间跨度 |
| R-CAP-01 | 各产物非空，**csv 至少有一行数据**（只有表头也算缺陷） |

实测抓到过两个真问题：某次上传的 `imu.csv`（54 B）和 `pose.csv`（33 B）**只有表头没有数据**；
另一个包声明 1920×1080、视频实际 1280×720。这两个都是人翻链接很难发现的。

## 审核：生成出来的用例，得先有人看过

代码能读出「页面上写着什么」，读不出「什么叫对」。
所以机器生成的结构性用例一律标 `draft`，人在审核页上过一遍才算数。

```bash
npx tsx src/cli.ts --derive        # 从源码派生结构性冒烟用例 → cases/derived.yaml
npx tsx src/cli.ts --review-page   # 生成 cases/review.html
npx tsx src/cli.ts --import-review ~/Downloads/review-result.json   # 写回
```

或者一步到位：`./go.sh --review`，然后 `./go.sh --import-review <json>`。

**未审核的用例照样会跑**，但报告顶部会写「N / M 条没过人工审核」，
每条用例卡上也有「未审核」标记。理由是拦住执行没有意义——
挡住了就什么都没测；标出来，看报告的人自己决定信几分。

审核页会把每条用例的四类风险直接标红：

| 提示 | 含义 |
|---|---|
| 没有任何断言 | 跑起来永远不会红，等于没测 |
| 只有负向断言 | 通知中心、锁屏、黑屏也能满足它 |
| 标题里承诺的「X」没出现在断言里 | 写得像测了，其实没测（AUTH-05 就是这么漏的） |
| 断言是推测出来的 | 需要对着实现或需求确认 |

审核时要看的是两件事：**这条测的是不是它标题承诺的事**，以及**断言会不会永远绿**。

`derived.yaml` 和 `cases.yaml` 分开放：前者随时可以整个删掉重生成，
后者全是人确认过的。`--derive --force` 重写时会保留已经审过的状态，
不会因为重新派生就把审核成果清零。

## 源码 ↔ 用例 一致性检查

```bash
npx tsx src/cli.js --check-drift
```

不连设备、不调模型，纯扫 `src/`：

- 抽出每个页面的 `accessibilityLabel` 和界面文案
- 检查 `cases.yaml` 里写的每个「按钮/页面文案」在源码里是否还存在
- 列出**没埋 label 的页面**（Appium 没法可靠定位）

界面改了文案、用例没跟着改，这条会直接报出来。跑一次几秒钟，适合放进 CI。

## 分档：冒烟 / 全量

用例分两档，写在 `cases/policy.yaml` 的 `tier` 里：

| 档位 | 跑什么 | 多久 | 什么时候跑 |
|---|---|---|---|
| `smoke` | 登录链路三条主干（AUTH-01/03/06） | 约 4 分钟 | 每次改动后 |
| `full` | 全部 23 条（登录、引导、任务、采集、QC、上传、本地包） | 约 60~80 分钟 | 定时 / 发版前 |

```bash
npx tsx src/cli.ts --tier smoke      # 快检
npx tsx src/cli.ts --tier full       # 全量（默认）
```

分档的意义是**成本可控**：每次改动都跑全量，光模型调用就是两百多次。

## 固定入口：只认两个文件

不管谁触发（手动、git 钩子、CI），跑完都写这两个固定路径：

- `midscene_run/reports/latest.html` —— 最近一次的 HTML 报告
- `midscene_run/last-run.json` —— 最近一次的结构化结果

带时间戳的历史文件也保留着，但下游（通知、看板、钩子）只认 `latest`。

## 用例顺序规则（R-GATE-05）

用例不是随便排的。顺序错了，一条用例能把后面十几条一起拖死。三档：

| order | 含义 | 排在哪 | 例子 |
|---|---|---|---|
| `normal` | 快、无副作用 | 最先 | AUTH-01、TASK-01 |
| `costly` | 要登录、真录视频/上传、耗额度 | 其次 | FLOW-01、CAP-05、LP-01 |
| `destructive` | 锁账号、删数据等破坏共享状态 | **永远最后** | AUTH-04 |

**`order` 是必填项**：没在 `cases/policy.yaml` 声明的用例，`loadPlans()` 直接报错，
一条都不跑。默认值等于没有规则——一条会录视频的用例漏写，就会以 normal 身份插到任意位置。

声明写在 `cases/policy.yaml`：

```yaml
AUTH-04:
  order: destructive
  why: 连续 5 次错误登录会把测试账号锁 15 分钟
  affects: '*'                    # 除自己以外全部：新增用例自动被覆盖
  cooldown-minutes: 15
```

`affects` 可以写 `'*'` 表示「除自己以外全部」。**推荐 destructive 都用 `*`**：
锁账号影响的是整个账号，逐个列用例迟早会漏——新增一条要登录的用例忘了加进去，
它就不会被保护。

还有 `depends-on: [X]`：依赖 X 的产物/状态，X 没通过就跳过而不是硬跑出假失败。

生效在三处：

| 时机 | 机制 | 拦住什么 |
|---|---|---|
| 编写时 | `loadPlans()` 检查每条用例是否声明 order | 新加的用例忘了声明 |
| 执行时 | `sortByPolicy()` 排序 + `affects` 跳过 + 冷却 | 顺序错、跑完污染后续 |
| CI | `tests/test_case_order.py` 六个检查 | 声明成 normal 但实际会录/传 |

**为什么必须写成规则而不是「记得放后面」**：2026-11-24 那轮，AUTH-04 和几条 costly
用例都标了「排最后」，组内按文件顺序排，AUTH-04 排在前面，锁了账号 15 分钟，
后面 6 条全部登不进去，被误判成产品问题。现在由 `sortByPolicy()` 分三档排序，
`tests/test_case_order.py` 在门禁里检查：destructive 必须排在最后、副作用必须声明。

## 会破坏共享状态的用例，写在 policy.yaml

有些用例本身简单，副作用却落在**测试账号**上：连续输错 5 次密码，账号被锁 15 分钟，
这一轮剩下的和下一轮全都登不进去。

这类规则集中在 `cases/policy.yaml`：

```yaml
AUTH-04:
  kind: destructive
  why: 连续 5 次错误登录会把测试账号锁 15 分钟，期间所有依赖登录的用例都会失败
  affects: [ONB-01, ONB-02, AUTH-01, AUTH-02, AUTH-03, AUTH-05, AUTH-06]
  order: last          # 整批跑时排到最后
  cooldown-minutes: 15
```

带来三件事：

- **默认就跑，但排在最后一个**。用例默认不跑等于白写，所以不搞「需要开关才跑」那一套
- 跑过之后，`affects` 里的用例本轮直接跳过，跳过原因写进报告
- 环境进入 15 分钟冷却：**下一次启动会被直接拦下**并说明还剩几分钟，
  而不是让你对着 6 条「登录失败」猜是不是产品挂了。确实要跑加 `--ignore-cooldown`

`policy.yaml` 里写了不存在的用例编号，加载时直接报错——不会静默失效。

## 当前全量覆盖

全量 23 条：登录 6（AUTH）、引导 4（ONB-01/02/04/05）、任务 3（TASK-01/02/03）、
采集 3（CAP-01/02/05）、QC 1（QC-09 必答项）、上传 1（UP-04 浮窗）、i18n 1（I18N-01）、
黄金链路 1（FLOW-01）、本地包 3（LP-01 恢复标记 / LP-04 重传入口 / LP-05 重启保留）。

`testcases.md` 里的 50 条全部有归属：23 条做成视觉用例，27 条登记在 `cases/planned.yaml`
并写明由谁覆盖——产物层（test_capture_flow + verification/artifacts.py）、
纯函数层（packageValidation 等单测）、接口层（CollectorClient），
剩下 4 条（CAP-03/07/08/09）确认只能人工。

## 几条硬规矩

**1. 采集页和 QC 页禁用开放式 `aiAct`。**
这两页底部有「放弃并重录」，模型理解偏了就可能点中——作废一段已录素材、消耗任务额度。
只能用 `aiTap('「xxx」按钮')` 点明确元素。

**2. 相机预览截图大概率是黑的。**
SurfaceView 截不到，所以取景、录制这些页面视觉层验不了，继续留在 Appium。
看到大片黑不要当成「页面异常」。

**3. 灰按钮不能点。**
经历过：合规复选框没勾 → 校准按钮置灰 → 模型以为进错页 → 反复点录制按钮 15 次，进入 Tap/Back 死循环。
现在 `appContext.ts` 里写死了这条，指令也按「先勾复选框，等按钮变深色再点」来写。

**4. 报告不能外发。**
`midscene_run/report/*.html` 有单份到 13MB 的，里面是完整截图，包含测试账号和密码。

**5. 没实现的用例必须登记。**
`testcases.md` 里标了 Midscene 但还没写的用例，要写进 `cases/planned.yaml` 并说明卡点。
`tests/test_vision_manifest.py` 会检查：既没实现、也没登记、又不在表里的 → 直接红。
不这么做，报告会显示全绿，实际一半没跑。

## 已知限制

- **不确定性**。同样的指令，模型可能这次点对、下次点错。不适合做 CI 门禁，适合发版前跑一轮 + 人工看报告。
- **成本**。按次计费，全部 18 条跑一遍不算便宜，别在每次提交都跑。
- **任务额度**。测试账号 0/3 可录制，涉及采集的用例跑几次就把额度用光。
- **iOS 没接**。`@midscene/ios` 走 WDA，需要 ≥7.0 的 WebDriverAgent 和能装的 ipa；TestFlight 包能按 bundleId 拉起，但装包仍要 TestFlight 或 dev ipa。
