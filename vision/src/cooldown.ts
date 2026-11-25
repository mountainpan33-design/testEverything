/**
 * 冷却期：会破坏共享状态的用例跑完之后，整个环境有一段时间不能重跑。
 *
 * 为什么需要：AUTH-04 会把测试账号锁 15 分钟。它排在最后跑，本轮不受影响，
 * 但如果紧接着再跑一轮，所有依赖登录的用例都会挂——而且看起来像产品坏了。
 * 与其让人对着 6 条「登录失败」发呆，不如启动时直接说清楚「账号还在冷却，还剩 7 分钟」。
 *
 * 冷却信息存成 JSON（数据，不是代码），过期自动失效，不需要人工清理。
 */
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import { VISION_DIR } from './config.js';
import type { Plan } from './plan.js';

const FILE = resolve(VISION_DIR, 'midscene_run', 'cooldown.json');

export interface Cooldown {
  /** 造成冷却的用例 */
  caseId: string;
  why: string;
  /** ISO 时间，到这个点之后才允许重跑 */
  until: string;
}

/** 当前是否在冷却期。过期或文件坏了都返回 null。 */
export function readCooldown(): Cooldown | null {
  try {
    if (!existsSync(FILE)) return null;
    const raw = JSON.parse(readFileSync(FILE, 'utf8')) as Cooldown;
    if (!raw?.until) return null;
    return Date.parse(raw.until) > Date.now() ? raw : null;
  } catch {
    return null;
  }
}

/** 用例跑完后开始冷却。没配 cooldown-minutes 就什么都不做。 */
export function startCooldown(plan: Plan): Cooldown | null {
  const minutes = plan.policy?.cooldownMinutes;
  if (!minutes || minutes <= 0) return null;
  const cd: Cooldown = {
    caseId: plan.id,
    why: plan.policy?.why ?? '这条用例改变了共享状态',
    until: new Date(Date.now() + minutes * 60_000).toISOString(),
  };
  mkdirSync(dirname(FILE), { recursive: true });
  writeFileSync(FILE, JSON.stringify(cd, null, 2), 'utf-8');
  return cd;
}

export function clearCooldown(): void {
  try {
    rmSync(FILE, { force: true });
  } catch {
    // 删不掉不影响跑
  }
}

export function remainingMinutes(cd: Cooldown): number {
  return Math.max(0, Math.ceil((Date.parse(cd.until) - Date.now()) / 60_000));
}
