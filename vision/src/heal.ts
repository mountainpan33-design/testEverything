/**
 * 修正层：跑 → 卡住 → 读日志找原因 → 生成用例补丁 → 重跑验证 → 通过才合并，最多 3 轮。
 *
 * 关键设计（2026-11-23 改）：
 *   修正**直接改用例本身**（cases.yaml），不再往旁路的 fixes.yaml 塞前置动作。
 *   但改完之后不立刻算数——先把补丁写进去、重跑那一条、**跑通了才留下**，
 *   没跑通就退回原文。这样用例始终只有一份真相，仓库里不会留下没验证过的改动。
 *
 * 三条硬边界：
 *   1. 只写数据（cases.yaml），不改代码。
 *   2. 只修环境类阻塞（弹窗挡住这类），断言写错、产品缺陷一律只出报告。
 *   3. 最多 3 轮。修不好的东西，第四轮也修不好。
 */
import { resolve } from 'node:path';

import type { AndroidAgent } from '@midscene/android';

import { analyzeCases } from './analyze.js';
import { startCooldown } from './cooldown.js';
import { VISION_DIR } from './config.js';
import { casesDir } from './project.js';
import type { Ctx } from './project-login.js';
import { captureScreenshot, startVideo, stopVideo, type CaseMedia } from './media.js';
import {
  applyInsertions,
  diffOf,
  keepOnly,
  planInsertion,
  readText,
  writeText,
  type Insertion,
} from './patch.js';
import { loadPlans, sortByPolicy, type Plan } from './plan.js';
import { prepare } from './project-prepare.js';
import { runPlan, type RunVars } from './run.js';
import type { CaseResult, RunOutput } from './types.js';

const CASES_FILE = () => resolve(casesDir(), 'cases.yaml');

export interface FixRecord {
  round: number;
  caseId: string;
  rootCause: string;
  reasoning: string;
  /** 最终是否合并进了 cases.yaml */
  applied: boolean;
  /** 补丁过了验证（即使后来因为别的轮次被丢弃也会是 true） */
  verified?: boolean;
  /** 给人看的一句话 */
  action: string;
  /** 合并时的新增行 diff */
  diff?: string;
}

export interface HealRound {
  round: number;
  results: CaseResult[];
  fixes: FixRecord[];
}

export interface HealOutcome {
  rounds: HealRound[];
  final: CaseResult[];
  stoppedBecause: string;
}

/** 这条结果算不算「阻塞」——只有阻塞才值得再来一轮。 */
function isBlocked(r: CaseResult): boolean {
  if (r.status === 'skipped') return true;
  if (r.status !== 'failed') return false;
  // 明确判成产品缺陷的不重试：重试改变不了产品
  return r.diagnosis?.attribution !== 'product';
}

/** 从「点「暂不更新」按钮」里抽取按钮文案；抽不出来就说明这个修正没法自动套用。 */
function buttonLabel(remedy: string): string | null {
  const text = remedy.trim();
  if (!text.startsWith('点')) return null;
  const m = text.match(/^点\s*[「"']?([^「」"'（(，,。]{1,14})[」"']?/);
  const label = m?.[1]?.trim();
  if (!label) return null;
  // 太长的多半是整段说明，机器照着点会点偏
  if (label.length > 14) return null;
  return label;
}

export interface HealOptions {
  agent: AndroidAgent;
  plans: Plan[];
  vars: RunVars;
  ctx: Ctx;
  deviceId: string;
  maxRounds?: number;
  onRound?: (round: HealRound) => void;
  video?: boolean;
  reportDir?: string;
  mediaDir?: string;
  media?: Map<string, CaseMedia>;
}

async function runOnce(
  opts: HealOptions,
  plans: Plan[],
  poisoned: Map<string, string>,
): Promise<CaseResult[]> {
  const results: CaseResult[] = [];
  const mediaDir = opts.mediaDir ?? resolve(VISION_DIR, 'midscene_run');
  const videosDir = resolve(mediaDir, 'videos');
  const shotsDir = resolve(mediaDir, 'screenshots');
  const reportDir = opts.reportDir ?? resolve(mediaDir, 'reports');

  const done = new Map<string, CaseResult>();

  for (const plan of plans) {
    // 依赖的用例没通过，这条跑出来的结果没有意义——跳过并写明原因
    const deps = plan.policy?.dependsOn ?? [];
    const unmet = deps.filter((d) => done.get(d)?.status !== 'passed');
    if (unmet.length > 0) {
      const why = `依赖的 ${unmet.join('、')} 没有通过`;
      console.log(`⏭ ${plan.id} 跳过：${why}`);
      const skipped = {
        caseId: plan.id,
        title: plan.title,
        status: 'skipped' as const,
        assertions: [],
        skipReason: why,
        durationMs: 0,
        startedAt: new Date().toISOString(),
        finishedAt: new Date().toISOString(),
      };
      results.push(skipped);
      done.set(plan.id, skipped);
      continue;
    }

    // 前面刚跑过会破坏共享状态的用例，这条现在跑也没意义
    const poison = poisoned.get(plan.id);
    if (poison) {
      console.log(`⏭ ${plan.id} 跳过：${poison}`);
      results.push({
        caseId: plan.id,
        title: plan.title,
        status: 'skipped',
        assertions: [],
        skipReason: poison,
        durationMs: 0,
        startedAt: new Date().toISOString(),
        finishedAt: new Date().toISOString(),
      });
      continue;
    }

    process.stdout.write(`▶ ${plan.id} ${plan.title} … `);
    const started = Date.now();

    // 录屏要在准备动作之前开始，否则看不到「状态是怎么被摆出来的」
    const videoHandle = opts.video ? await startVideo(opts.deviceId) : null;

    try {
      await prepare(opts.agent, opts.deviceId, opts.ctx, plan.precondition);
    } catch (e) {
      const reason = e instanceof Error ? e.message.split('\n')[0] : String(e);
      const video = await stopVideo(opts.deviceId, videoHandle, plan.id, videosDir, reportDir, started);
      if (video) opts.media?.set(plan.id, video);
      console.log(`⏭ skipped (前置准备失败：${reason})`);
      results.push({
        caseId: plan.id,
        title: plan.title,
        status: 'skipped',
        assertions: [],
        skipReason: `前置准备失败（${plan.precondition}）：${reason}`,
        durationMs: Date.now() - started,
        startedAt: new Date(started).toISOString(),
        finishedAt: new Date().toISOString(),
      });
      continue;
    }

    const res = await runPlan(opts.agent, plan, opts.vars);
    res.startedAt = new Date(started).toISOString();
    res.finishedAt = new Date().toISOString();

    // 先截图再停录屏：截的是「这一刻」的屏幕
    const shot =
      res.status === 'failed'
        ? await captureScreenshot(opts.deviceId, plan.id, shotsDir)
        : undefined;
    const video = await stopVideo(opts.deviceId, videoHandle, plan.id, videosDir, reportDir, started);
    const media: CaseMedia = { ...(video ?? {}) };
    if (shot) media.screenshot = shot;
    if (media.screenshot || media.video) opts.media?.set(plan.id, media);

    const mark = res.status === 'passed' ? '✅' : res.status === 'skipped' ? '⏭' : '❌';
    console.log(`${mark} ${res.status} (${((Date.now() - started) / 1000).toFixed(1)}s)`);
    if (res.error) console.log(`   ${res.error.split('\n')[0]}`);

    // 真的跑过了，才会留下副作用（锁账号、吃额度…），把受影响的用例标掉
    if (plan.policy?.kind === 'destructive' && res.status !== 'skipped') {
      const why = `${plan.id} 刚跑过：${plan.policy.why ?? '改变了共享状态'}`;
      const affects = plan.policy.affects ?? [];
      if (affects.includes('*')) {
        // '*' = 除自己以外全部：新增用例自动被保护，不用回来补声明
        for (const other of plans) {
          if (other.id !== plan.id) poisoned.set(other.id, why);
        }
      } else {
        for (const id of affects) poisoned.set(id, why);
      }
      console.log(`   ⚠ 已标记 ${plan.policy.affects?.length ?? 0} 条受影响用例本轮不跑`);
      const cd = startCooldown(plan);
      if (cd) {
        console.log(`   ⏳ 环境进入冷却，${plan.policy.cooldownMinutes} 分钟内不要再跑`);
      }
    }

    results.push(res);
    done.set(plan.id, res);
  }
  return results;
}

/** 把补丁候选写盘并用 plan.ts 校验；不合法就还原原文。 */
function writeAndValidate(text: string, original: string): { ok: boolean; reason: string } {
  writeText(CASES_FILE(), text);
  const { errors } = loadPlans();
  if (errors.length) {
    writeText(CASES_FILE(), original);
    return { ok: false, reason: `补丁让用例不合法：${errors[0]}` };
  }
  return { ok: true, reason: '' };
}

export async function runWithHeal(opts: HealOptions): Promise<HealOutcome> {
  const maxRounds = opts.maxRounds ?? 3;
  const rounds: HealRound[] = [];
  // 会破坏共享状态的用例排到最后；跑过之后受影响的用例记在这里，本轮不再跑
  const poisoned = new Map<string, string>();
  let pending = sortByPolicy(opts.plans);
  let stoppedBecause = '跑完了';

  for (let round = 1; round <= maxRounds; round += 1) {
    if (pending.length === 0) break;

    console.log(`\n──────── 第 ${round} 轮（${pending.length} 条） ────────`);
    const results = await runOnce(opts, pending, poisoned);
    const blocked = results.filter(isBlocked);
    const current: HealRound = { round, results, fixes: [] };
    rounds.push(current);
    opts.onRound?.(current);

    if (blocked.length === 0) {
      stoppedBecause = `第 ${round} 轮后没有阻塞`;
      break;
    }
    if (round === maxRounds) {
      stoppedBecause = `已达 ${maxRounds} 轮上限，仍有 ${blocked.length} 条阻塞`;
      break;
    }

    const runOutput: RunOutput = {
      generatedAt: new Date().toISOString(),
      deviceId: opts.deviceId,
      packageName: opts.vars.package,
      modelName: process.env.MIDSCENE_MODEL_NAME ?? '',
      cases: results,
    };
    console.log(`\n⛑ 读日志：分析 ${blocked.length} 条阻塞…`);
    const { entries } = await analyzeCases(runOutput, false);

    // ---- 生成补丁候选
    const original = readText(CASES_FILE());
    const insertions: Insertion[] = [];

    for (const e of entries) {
      const a = e.analysis;
      const reason = a?.reasoning ?? e.note ?? '分析失败';
      const cause = a?.rootCause ?? 'unknown';

      if (!a) {
        current.fixes.push({
          round,
          caseId: e.caseId,
          rootCause: cause,
          reasoning: reason,
          applied: false,
          action: '分析没跑通，不改',
        });
        continue;
      }

      if (a.fix?.kind !== 'obstacle' || !a.fix.obstacle) {
        current.fixes.push({
          round,
          caseId: e.caseId,
          rootCause: cause,
          reasoning: reason,
          applied: false,
          action: `根因是 ${cause}，不是环境阻塞，交给人`,
        });
        continue;
      }

      if (a.confidence < 0.6) {
        current.fixes.push({
          round,
          caseId: e.caseId,
          rootCause: cause,
          reasoning: reason,
          applied: false,
          action: `置信度 ${a.confidence} 太低，不改`,
        });
        continue;
      }

      const label = buttonLabel(a.fix.obstacle.remedy ?? '');
      if (!label) {
        current.fixes.push({
          round,
          caseId: e.caseId,
          rootCause: cause,
          reasoning: reason,
          applied: false,
          action: `修正动作「${a.fix.obstacle.remedy ?? '空'}」没法落成一次点击，交给人`,
        });
        continue;
      }

      const p = planInsertion(original, e.caseId, `dismiss: [${label}]`);
      if ('reason' in p) {
        current.fixes.push({
          round,
          caseId: e.caseId,
          rootCause: cause,
          reasoning: reason,
          applied: false,
          action: p.reason,
        });
        continue;
      }

      insertions.push(p);
      current.fixes.push({
        round,
        caseId: e.caseId,
        rootCause: cause,
        reasoning: reason,
        applied: false, // 还要过重跑验证
        action: `补一步：出现「${label}」就点掉（待验证）`,
      });
      console.log(`   ✎ ${e.caseId}：${p.note}「${label}」`);
    }

    if (insertions.length === 0) {
      stoppedBecause = '这一轮没有可自动套用的补丁，停下等人看';
      break;
    }

    // ---- 写进去并用 loadPlans 校验
    const candidate = applyInsertions(original, insertions);
    const check = writeAndValidate(candidate, original);
    if (!check.ok) {
      writeText(CASES_FILE(), original);
      stoppedBecause = `补丁没通过校验，已还原：${check.reason}`;
      break;
    }

    // ---- 重新加载计划，只重跑打了补丁的用例
    const reloaded = loadPlans().plans;
    const patchedIds = new Set(insertions.map((i) => i.caseId));
    const retry = reloaded.filter((p) => patchedIds.has(p.id));

    console.log(`\n🔁 验证补丁：重跑 ${retry.map((p) => p.id).join(', ')}`);
    const verifyResults = await runOnce(opts, retry, poisoned);
    const verifiedIds = new Set(
      verifyResults.filter((r) => r.status === 'passed').map((r) => r.caseId),
    );

    // ---- 通过的留下，没通过的退回去
    const finalText = applyInsertions(original, keepOnly(insertions, verifiedIds));
    writeText(CASES_FILE(), finalText);
    loadPlans(); // 让内存里的计划与磁盘一致

    for (const ins of insertions) {
      const rec = current.fixes.find((f) => f.caseId === ins.caseId);
      if (!rec) continue;
      if (verifiedIds.has(ins.caseId)) {
        rec.applied = true;
        rec.verified = true;
        rec.action = `已合并：${ins.note}`;
        rec.diff = diffOf(original, ins);
        console.log(`   ✅ ${ins.caseId}：补丁验证通过，已合并进 cases.yaml`);
      } else {
        rec.applied = false;
        rec.verified = false;
        rec.action = '补丁没让用例通过，已丢弃';
        console.log(`   ↩ ${ins.caseId}：补丁没生效，已还原`);
      }
    }

    // 补丁已验证通过的用例，用重跑结果替换本轮结果
    for (const r of verifyResults) {
      const idx = current.results.findIndex((x) => x.caseId === r.caseId);
      if (idx >= 0 && r.status === 'passed') current.results[idx] = r;
    }

    pending = reloaded.filter(
      (p) => blocked.some((b) => b.caseId === p.id) && !verifiedIds.has(p.id),
    );
    if (pending.length === 0) {
      stoppedBecause = `第 ${round} 轮补丁全部验证通过`;
      break;
    }
  }

  const last = rounds[rounds.length - 1];
  return { rounds, final: last?.results ?? [], stoppedBecause };
}
