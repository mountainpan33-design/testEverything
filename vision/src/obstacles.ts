/**
 * 障碍识别与自动排除（跨项目通用）。
 *
 * 解决的问题：自动化跑着跑着，屏幕上盖了一层不属于 App 的东西——
 * 更新弹窗、通知中心、系统权限框、厂商权限引导页、系统设置页。
 * 这些不是产品缺陷，但会让后续每个动作都落空，最后报一个和真相无关的错。
 *
 * 2026-11-20 的实例：pm clear 后冷启动弹「发现新版本」，盖住登录页。
 * 模型判断「登录页顶部被更新弹窗遮挡」，后面三次点击全落在弹窗坐标上，
 * 屏幕滑进了通知中心，最终报的却是「没有出现协议同意页」。
 *
 * 设计要点：
 *   1. **一次调用判完**，不是每个障碍问一遍——每次 aiBoolean 都是一次钱。
 *   2. **表驱动**，新项目的障碍加一行，不改流程代码。
 *   3. **只做无副作用的排除**：绝不点「立即更新」「确定」「同意」这类会改变状态的按钮。
 */
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import type { AndroidAgent } from '@midscene/android';

import { activePackage, foregroundPackage } from './adb.js';
import { VISION_DIR } from './config.js';

import { PROJECT_OBSTACLES } from './project-obstacles.js';

/** 障碍编号。拼进给模型的选项里，也用作日志和归因的键。 */
export type ObstacleId =
  | 'none'
  | 'blocking-modal'
  | 'update-prompt'
  | 'system-panel'
  | 'system-permission'
  | 'system-settings'
  | 'oem-permission-guide'
  | 'other-system-ui';

export interface Obstacle {
  id: ObstacleId;
  /** 给模型看的判定描述 */
  detect: string;
  /** 给模型看的排除动作；null 表示只需等待，不需要点击 */
  remedy: string | null;
  /** 排除后应该看到的状态 */
  verify: string | null;
  /** 这是环境问题还是产品问题——决定失败怎么归因 */
  attribution: 'environment' | 'product';
}

/**
 * 通用障碍表：只描述「界面的角色」，不写任何项目特有的文案。
 *
 * 这是换项目还能自动纠偏的部分——「一个盖住页面的模态弹窗，带取消/稍后/跳过」
 * 换个 App 也是这个长相；而「标题为『发现新版本』的弹窗」换个项目就失效了。
 * 后者放 obstacles.project.ts。
 *
 * 顺序：项目专属的排前面（更具体、更常见），通用的兜底。
 */
export const GENERIC_OBSTACLES: Obstacle[] = [
  {
    id: 'blocking-modal',
    detect:
      '一个盖住页面主体的模态弹窗/浮层（半透明遮罩 + 白色卡片），内容看不清或看不了，' +
      '按钮里有「取消」「稍后」「暂不」「跳过」「关闭」「知道了」这类否定或关闭语义的选项。' +
      '注意：如果弹窗里有「更新」「安装」「下载」字样，也算这一条，但排除动作见项目专属表',
    remedy: '点那个表示否定或关闭的按钮（「取消」/「稍后」/「暂不」/「跳过」/「关闭」/「知道了」）',
    verify: '弹窗已经消失，能看到它下面的页面内容',
    attribution: 'environment',
  },
  {
    id: 'system-panel',
    detect:
      '系统的通知中心或控制中心：顶部显示当前时间，一排快捷开关（Wi-Fi/蓝牙/亮度），' +
      '下面是通知列表，没有 App 自己的界面元素',
    remedy: '按系统返回键收起',
    verify: '已经回到 App 自己的界面',
    attribution: 'environment',
  },
  {
    id: 'system-permission',
    detect:
      '系统权限授权弹窗：询问是否允许某应用访问相机/麦克风/位置/存储，' +
      '按钮是「允许」「仅在使用中允许」「拒绝」，通常带应用图标',
    remedy: '点「允许」或「仅在使用中允许」',
    verify: '权限弹窗已关闭',
    attribution: 'environment',
  },
  {
    id: 'oem-permission-guide',
    detect:
      '手机厂商自己的权限管理页（小米/华为/OPPO/vivo 的设置风格），' +
      '标题类似「权限管理」「应用权限」，不是被测 App 画的',
    remedy: '按系统返回键退回 App',
    verify: '已经回到 App 自己的界面',
    attribution: 'environment',
  },
  {
    id: 'system-settings',
    detect: '跳到了系统的「设置」应用，能看到 Wi-Fi、蓝牙、应用管理、显示等系统条目',
    remedy: '按系统返回键退回 App',
    verify: '已经回到 App 自己的界面',
    attribution: 'environment',
  },
  {
    id: 'other-system-ui',
    detect: '其他明显不属于 App 的系统界面（锁屏、最近任务列表、下拉搜索、音量面板等）',
    remedy: '按系统返回键退回 App',
    verify: '已经回到 App 自己的界面',
    attribution: 'environment',
  },
];

/**
 * 自愈产出物：analyze.ts 分析失败日志后，把「确认能修好」的障碍写进这个 JSON。
 *
 * 为什么是 JSON 不是 TS：机器只能写数据，不能改代码。
 * 写错的障碍条目最坏是「下次没拦住」，而自动改代码最坏是把框架改坏。
 */
const GENERATED_FILE = resolve(VISION_DIR, 'obstacles.generated.json');

function loadGenerated(): Obstacle[] {
  try {
    if (!existsSync(GENERATED_FILE)) return [];
    const raw = JSON.parse(readFileSync(GENERATED_FILE, 'utf8'));
    if (!Array.isArray(raw)) return [];
    return raw.filter(
      (o) => o && typeof o.id === 'string' && typeof o.detect === 'string',
    ) as Obstacle[];
  } catch {
    // 文件坏了就当没有：自愈产物绝不能阻碍正常跑
    return [];
  }
}

/** 自愈新增的在前（最贴近本次踩的坑），项目专属其次，通用兜底。 */
export const OBSTACLES: Obstacle[] = [
  ...loadGenerated(),
  ...PROJECT_OBSTACLES,
  ...GENERIC_OBSTACLES,
];

/** 供 analyze.ts 去重：已经存在的障碍不用重复加。 */
export function knownObstacleIds(): Set<string> {
  return new Set(OBSTACLES.map((o) => o.id));
}

/**
 * 重新读一遍生成文件。
 *
 * 自愈写入新障碍后，同一个进程里的回跑必须用上新表——
 * 模块级数组已经 import 过了，只能原地改内容。
 */
export function reloadObstacles(): number {
  const next = [...loadGenerated(), ...PROJECT_OBSTACLES, ...GENERIC_OBSTACLES];
  OBSTACLES.splice(0, OBSTACLES.length, ...next);
  return OBSTACLES.length;
}

/** 把障碍表拼成一次判定用的提示词。序号 0 固定是「没有障碍」。 */
export function obstaclePrompt(): string {
  const lines = OBSTACLES.map((o, i) => `${i + 1}. ${o.detect}`).join('\n');
  return (
    '判断当前屏幕上有没有遮住 App 的其它界面。从下面选项里选一个，只输出编号数字，不要解释：\n' +
    '0. 没有，当前就是 App 自己的界面\n' +
    `${lines}\n` +
    '如果同时符合多个，选最顶层、最挡视线的那一个。'
  );
}

/** 按序号取障碍定义。 */
function byIndex(n: number): Obstacle | undefined {
  return n >= 1 && n <= OBSTACLES.length ? OBSTACLES[n - 1] : undefined;
}

/**
 * 识别当前障碍。一次模型调用。
 * 模型返回乱七八糟时一律当「没有障碍」，交给后续步骤暴露真实问题，
 * 不要在识别环节把用例判死。
 */
export async function detectObstacle(agent: AndroidAgent): Promise<ObstacleId> {
  try {
    const raw = await agent.aiQuery<number>(obstaclePrompt());
    const n = typeof raw === 'number' ? raw : Number.parseInt(String(raw), 10);
    if (!Number.isFinite(n) || n === 0) return 'none';
    return byIndex(n)?.id ?? 'other-system-ui';
  } catch {
    return 'none';
  }
}

/**
 * 等一个「App 内」的条件成立，期间遇到障碍自动排除。
 *
 * 成本上的关键设计：**「还在不在 App 里」先用 adb 看前台包名判断**，
 * 那是一次免费、几十毫秒的调用；只有真的跑出去了，才花模型调用去认现场。
 * 之前是每一轮都问一次模型，正常等页面切换也要付这笔钱。
 *
 * 前台是 App、但条件迟迟不成立，说明可能是 App 自己弹的更新框/引导蒙层——
 * 这种情况隔一次失败问一次模型，正常切换就完全不问了。
 */
export async function waitForAppState(
  agent: AndroidAgent,
  condition: string,
  timeoutMs = 30000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  const seen: ObstacleId[] = [];
  const pkgName = activePackage();
  let failedPolls = 0;

  while (Date.now() < deadline) {
    const front = await foregroundPackage();
    const inApp = !front || !pkgName || front === pkgName;

    if (!inApp) {
      // 免费信号已经说明屏幕不归 App 管了，先按系统界面处理，不叫模型
      if (/systemui|notification/i.test(front)) {
        seen.push('system-panel');
        await agent.back().catch(() => {});
        continue;
      }
      if (/launcher|\.home$|mihome|everythinghome/i.test(front)) {
        // 还在启动过程中，等 App 自己上来，别按返回键（会退出）
        await new Promise((r) => setTimeout(r, 500));
        continue;
      }
      // 认不出的前台（权限控制器、系统设置、厂商权限页…）才叫模型认
      seen.push(...(await clearObstacles(agent, 1)));
      continue;
    }

    try {
      await agent.aiWaitFor(condition, { timeoutMs: 6000 });
      return;
    } catch {
      failedPolls += 1;
      // 第一次等不到就先问一次模型——这时才可能是被弹层挡住；
      // 之后隔一次再问，避免长等待把调用来回刷。
      if (failedPolls === 1 || failedPolls % 2 === 0) {
        const obstacle = await detectObstacle(agent);
        if (obstacle !== 'none') {
          seen.push(...(await clearObstacles(agent, 1)));
          failedPolls = 0;
        }
      }
    }
  }

  const detail = await describeScreen(agent);
  throw new Error(
    `等待「${condition}」超时（${Math.round(timeoutMs / 1000)}s）。` +
      (seen.length ? `期间排除过的障碍：${[...new Set(seen)].join('、')}。` : '') +
      `当前屏幕：${detail}`,
  );
}

/** 让模型用一句话描述当前屏幕。只用于失败现场，正常流程不调。 */
export async function describeScreen(agent: AndroidAgent): Promise<string> {
  try {
    const text = await agent.aiQuery<string>(
      '用一句话说明当前屏幕上显示的是什么页面，有没有弹窗或遮挡。不超过 40 字。',
    );
    return typeof text === 'string' ? text : JSON.stringify(text);
  } catch {
    return '<描述失败>';
  }
}

export interface Diagnosis {
  /** 当前屏幕分类：app / blank / unknown / 某个障碍 id */
  screen: 'app' | 'blank' | 'unknown' | ObstacleId;
  detail: string;
  /** 失败更像环境问题还是产品问题 */
  attribution: 'environment' | 'product' | 'unknown';
  suggestion: string;
}

/**
 * 失败现场归因。用例挂了之后调一次，把「屏幕上到底是什么」写进结果，
 * 而不是只留一句「断言失败」。
 */
export async function diagnose(agent: AndroidAgent): Promise<Diagnosis> {
  const obstacle = await detectObstacle(agent);
  if (obstacle !== 'none') {
    const def = OBSTACLES.find((o) => o.id === obstacle);
    return {
      screen: obstacle,
      detail: await describeScreen(agent),
      attribution: def?.attribution ?? 'environment',
      suggestion:
        `屏幕被「${obstacle}」挡住了，先排除它再判断用例是否真的失败。` +
        (def?.remedy ? `排除动作：${def.remedy}` : ''),
    };
  }

  const detail = await describeScreen(agent);
  const blank = /黑屏|白屏|空白|纯黑|纯白|灰屏/.test(detail);
  return {
    screen: blank ? 'blank' : 'app',
    detail,
    attribution: blank ? 'environment' : 'product',
    suggestion: blank
      ? '屏幕是空白/黑屏，多半是页面没渲染出来或相机预览（SurfaceView 截不到），先确认 App 是否真的到了这一步。'
      : '屏幕停在 App 界面上，失败更像被测行为的问题，对照界面标签检查断言是否写错。',
  };
}
export async function clearObstacles(
  agent: AndroidAgent,
  rounds = 2,
): Promise<ObstacleId[]> {
  const cleared: ObstacleId[] = [];
  for (let i = 0; i < rounds; i += 1) {
    const id = await detectObstacle(agent);
    if (id === 'none') break;
    const obstacle = OBSTACLES.find((o) => o.id === id);
    if (!obstacle) break;

    try {
      if (obstacle.remedy) {
        await agent.aiTap(obstacle.remedy);
      } else {
        await agent.back();
      }
      if (obstacle.verify) {
        await agent.aiWaitFor(obstacle.verify, { timeoutMs: 8000 });
      }
      cleared.push(id);
    } catch {
      // 排除失败也记录下来：说明这不是一个可自愈的障碍
      cleared.push(id);
      break;
    }
  }
  return cleared;
}
