/**
 * 创建 Midscene Agent。模型配置一律从环境变量读（Midscene 的约定），
 * 这里只做两件事：缺配置时给一条能照着做的报错；把 App 常识挂上去。
 */
import { agentFromAdbDevice, getConnectedDevices } from '@midscene/android';
import type { AndroidAgent } from '@midscene/android';

import { ACT_CONTEXT, APP_CONTEXT } from './project-appcontext.js';

const REQUIRED_ENV = [
  'MIDSCENE_MODEL_BASE_URL',
  'MIDSCENE_MODEL_API_KEY',
  'MIDSCENE_MODEL_NAME',
  'MIDSCENE_MODEL_FAMILY',
] as const;

/** 缺哪个就报哪个，别让用户去翻文档猜。 */
export function assertModelConfig(): void {
  const missing = REQUIRED_ENV.filter((k) => !process.env[k]?.trim());
  if (missing.length === 0) return;
  throw new Error(
    `缺模型配置：${missing.join(', ')}\n` +
      `把 vision/.env.example 复制成 vision/.env 并填好，四项缺一不可。\n` +
      `当前 Base URL=${process.env.MIDSCENE_MODEL_BASE_URL || '<空>'}，` +
      `Model=${process.env.MIDSCENE_MODEL_NAME || '<空>'}\n` +
      `注意：第三方中转的 Base URL 要带 /v1，不带会被 307 跳到登录页。`,
  );
}

/** 选设备：显式给的优先，否则用 adb 里唯一/第一台。 */
/**
 * 选设备。
 *
 * 优先级：显式参数 > 环境变量 > 自动挑。但**配置里的设备不在线时不让整轮直接失败**——
 * 换手机、换机器很常见，锁死序列号只会让人每次手改 .env：
 *   - 只有一台在线 → 自动用它，打一行警告说明和配置不一致
 *   - 多台在线 → 报错并列出候选，让人用 --device 指定（不会瞎猜）
 *   - 一台都没有 → 报错
 */
export async function pickDevice(explicit?: string): Promise<string> {
  const want = explicit?.trim();
  const devices = await getConnectedDevices();
  const ready = devices.filter((d) => d.state === 'device');

  if (ready.length === 0) {
    throw new Error(
      `adb 里没有可用设备（共 ${devices.length} 条，状态：${
        devices.map((d) => d.state).join('/') || '无'
      }）。\n先跑 adb devices 确认，或用 --device 指定。`,
    );
  }

  if (want) {
    if (ready.some((d) => d.udid === want)) return want;
    if (ready.length === 1) {
      console.warn(
        `⚠ 配置的设备 ${want} 不在线，自动改用当前唯一在线的 ${ready[0]!.udid}。` +
          `\n  要固定用它，把 .env 里的 ANDROID_UDID 改成 ${ready[0]!.udid}`,
      );
      return ready[0]!.udid;
    }
    throw new Error(
      `指定的设备 ${want} 不在线。当前在线：\n` +
        ready.map((d) => `  ${d.udid}`).join('\n') +
        `\n用 --device <udid> 指定其中一台。`,
    );
  }

  if (ready.length === 1) return ready[0]!.udid;

  throw new Error(
    `检测到 ${ready.length} 台在线设备，用 --device 指定要跑哪台：\n` +
      ready.map((d) => `  ${d.udid}`).join('\n'),
  );
}

export interface CreateAgentOptions {
  deviceId?: string;
  /** 报告文件名（写到 midscene_run/report/ 下） */
  reportName: string;
}

export async function createAgent(opts: CreateAgentOptions): Promise<{
  agent: AndroidAgent;
  deviceId: string;
}> {
  assertModelConfig();
  const deviceId = await pickDevice(opts.deviceId);

  const agent = await agentFromAdbDevice(deviceId, {
    // 把 App 常识挂上去。default 给所有调用，aiAct 额外给动作约束。
    aiContexts: {
      default: APP_CONTEXT,
      aiAct: ACT_CONTEXT,
    },
    generateReport: true,
    reportFileName: opts.reportName,
    // 采集页/QC 页底部有「放弃并重录」，不能让模型自己发明 adb 命令乱点
    exposeRunAdbShellAction: false,
    /*
     * 输入：绕过输入法。
     *
     * 2026-11-20 真机：账号 pss2 输进去只剩「2」。两种策略都试过——
     * 17:32 一次 `input text 'pss2'`，17:38 改成逐字符 `input text p/s/s/2`，
     * 结果完全一样，只剩最后一个字符。所以不是「灌太快被 JS 线程丢了」，
     * 是 `adb shell input text` 的按键事件被输入法收进了候选区，
     * 只有最后一次提交真正落进输入框。
     *
     * always-yadb 走 app_process 直接注入字符串，完全不经过输入法。
     * 如果哪台设备 yadb 起不来（SELinux 拦 app_process），登录会直接报错，
     * 报错里带着当前输入法名字，别再去猜。
     */
    imeStrategy: 'always-yadb',
    // 逐字符 + 间隔：yadb 也是整串注入，但逐字符能让 App 的受控输入框逐帧跟上
    inputStrategy: 'sequential',
    keyboardTypeDelay: 80,
  });

  return { agent, deviceId };
}

/**
 * 拉起被测 App。已经在前台也不会报错。
 *
 * 拉起后**不主动扫障碍**：冷启动的更新弹窗会挡住后面的等待，
 * 那时 `waitForAppState` 会卡住并叫模型认现场——模型只在真被卡住时才出手。
 */
export async function launchApp(agent: AndroidAgent, packageName: string): Promise<void> {
  await agent.launch(packageName);
}
