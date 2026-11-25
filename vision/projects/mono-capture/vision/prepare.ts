/**
 * 用例之间的状态准备。
 *
 * 为什么必须有这一层：Midscene 用例不是各自独立的，它们对「进来时 App 处于什么状态」有要求。
 * 按顺序裸跑会这样：
 *   ONB-01 登录成功（离开登录页）→ AUTH-01 要求「停在登录页」→ 直接挂。
 * 之前 `--all` 跑到第 3 条就红，就是这个原因，跟 App 无关。
 *
 * adb 一律走子进程，不用 agent.runAdbShell()——
 * 那个能力一旦打开，模型也能自己发明 adb 命令，风险不值得。
 */
import type { AndroidAgent } from '@midscene/android';

import { adbShell } from '../../../src/adb.js';
import { launchApp } from '../../../src/agent.js';
import { waitForAppState } from '../../../src/obstacles.js';
import { isOnLoginPage, type Ctx } from './login.js';

/** 用例对初始状态的要求。 */
export type Precondition =
  | 'fresh-install'          // 清空 App 数据，模拟首次安装
  | 'login-page'             // 停在登录页
  | 'login-page-old-server'  // 停在登录页且选中旧服务器
  | 'logged-in'              // 已登录（用例自己会处理）
  | 'fresh-install-no-camera'; // 清数据，但相机权限不授予（验证权限门禁）

async function adb(deviceId: string, args: string[]): Promise<string> {
  return adbShell(deviceId, args);
}

/** 采集链路需要的运行时权限。pm clear 会把它们一并清掉，清完要补回来。 */
const PERMISSIONS = [
  'android.permission.CAMERA',
  'android.permission.RECORD_AUDIO',
  'android.permission.ACCESS_FINE_LOCATION',
  'android.permission.ACCESS_COARSE_LOCATION',
  'android.permission.ACTIVITY_RECOGNITION',
  'android.permission.BODY_SENSORS',
];

/** 逐条授予，失败不抛——权限页自己会显示「未开启」，用例两条路径都处理了。 */
async function grantPermissions(
  deviceId: string,
  pkg: string,
  skip: string[] = [],
): Promise<void> {
  for (const perm of PERMISSIONS) {
    if (skip.includes(perm)) continue;
    await adb(deviceId, ['shell', 'pm', 'grant', pkg, perm]).catch(() => '');
  }
}

/** 清数据 + 重开：模拟一次全新安装。登录态、协议同意、权限都会被清掉。 */
export async function clearAppData(
  agent: AndroidAgent,
  deviceId: string,
  ctx: Ctx,
  opts: { skipPermissions?: string[] } = {},
): Promise<void> {
  await agent.terminate(ctx.packageName).catch(() => {});
  await adb(deviceId, ['shell', 'pm', 'clear', ctx.packageName]);
  // 数据清空后服务器选择回到默认（旧服务器），缓存作废
  serverIsNew = false;
  // pm clear 会连带清掉运行时权限；不补回来的话权限页会停在「开启权限」，
  // 后面的流程就要去点系统弹窗，受厂商 ROM 影响大。
  await grantPermissions(deviceId, ctx.packageName, opts.skipPermissions ?? []);
  // 不预先扫障碍：真被挡住，下面的等待会卡住，那时才叫模型认现场
  await launchApp(agent, ctx.packageName);
  // pm clear 之后冷启动要几秒才出首帧，等登录页出现再往下走
  await waitForAppState(agent, '当前界面是登录页，能看到「用户名」「密码」输入框', 20000);
}

/** 退出登录回到登录页。退不掉就清数据兜底（会顺带清掉协议同意，AUTH 用例能接受）。 */
export async function ensureLoginPage(
  agent: AndroidAgent,
  deviceId: string,
  ctx: Ctx,
): Promise<void> {
  await launchApp(agent, ctx.packageName);

  if (await isOnLoginPage(agent)) return;

  // 我的 → 退出登录 → 确认
  try {
    await agent.aiTap('底部导航栏里的「我的」tab');
    await agent.aiTap('页面底部的「退出登录」按钮');
    // 确认弹窗的按钮文案就是「退出」
    await agent.aiTap('弹窗里确认退出的「退出」按钮');
    await waitForAppState(agent, '当前界面是登录页，能看到「用户名」「密码」输入框', 15000);
    return;
  } catch {
    // 退出登录受页面改动影响大，退不掉就走清数据的硬路径
  }

  await clearAppData(agent, deviceId, ctx);
}

/** 切到旧服务器。AUTH-02 专用。 */
export async function ensureOldServer(agent: AndroidAgent): Promise<void> {
  const alreadyOld = await agent.aiBoolean(
    '登录页顶部或设置入口处，当前选中的服务器是「旧服务器（52.39）」',
  );
  if (!alreadyOld) {
    await agent.aiTap('登录页上的服务器切换入口');
    await agent.aiTap('「旧服务器（52.39）」这个选项');
    await waitForAppState(agent, '当前服务器已经显示为「旧服务器（52.39）」', 10000);
  }
  // 服务器被改过了，缓存作废
  serverIsNew = false;
}

/**
 * 切到新服务器。
 *
 * 2026-11-20 回归教训：把登录流程搬进 YAML 时漏了这一步，结果所有用例都在旧服务器上登录，
 * 页面报 `fetch failed: java.net.ConnectException`，被误判成产品缺陷。
 * 这个 App 默认连的是旧服务器（52.39），测试账号在新服务器（118.196）上。
 *
 * 服务器是 App 级设置，退出登录不会变，所以本进程里确认过一次就记住；
 * `pm clear` 和切旧服务器会把它作废。
 */
export async function ensureNewServer(agent: AndroidAgent): Promise<void> {
  if (serverIsNew) return;
  const alreadyNew = await agent.aiBoolean(
    '登录页顶部显示的当前服务器是「新服务器」，并且处于选中高亮状态',
  );
  if (!alreadyNew) {
    await agent.aiTap('登录页顶部切换到「新服务器（118.196）」的按钮或选项');
    await waitForAppState(agent, '登录页顶部显示的当前服务器已经变成「新服务器」', 10000);
  }
  serverIsNew = true;
}

/** 本进程内是否已确认过服务器 = 新服务器 */
let serverIsNew = false;

export async function prepare(
  agent: AndroidAgent,
  deviceId: string,
  ctx: Ctx,
  pre: Precondition,
): Promise<void> {
  switch (pre) {
    case 'fresh-install':
      await clearAppData(agent, deviceId, ctx);
      // pm clear 之后服务器回到默认（旧服务器），必须重新切
      await ensureNewServer(agent);
      return;
    case 'login-page':
      await ensureLoginPage(agent, deviceId, ctx);
      // 停在登录页就已经是登录页了；不在登录页（例如协议页）就别乱点
      if (await isOnLoginPage(agent)) await ensureNewServer(agent);
      return;
    case 'login-page-old-server':
      await ensureLoginPage(agent, deviceId, ctx);
      await ensureOldServer(agent);
      return;
    case 'logged-in':
      // 已安装的机器上权限可能被拒过，拉起前先补授，否则会弹系统权限框把流程卡住
      await grantPermissions(deviceId, ctx.packageName);
      await launchApp(agent, ctx.packageName);
      return;
    case 'fresh-install-no-camera':
      await clearAppData(agent, deviceId, ctx, {
        skipPermissions: ['android.permission.CAMERA'],
      });
      await ensureNewServer(agent);
      return;
  }
}
