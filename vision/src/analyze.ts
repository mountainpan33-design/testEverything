/**
 * 跑完之后自己读日志、自己找原因、自己修。
 *
 * 这是把「人盯着日志推理」这件事变成程序：
 *   1. 把本次失败用例相关的那一段日志（模型看到什么、点了哪里）抽成证据
 *   2. 连同断言、诊断、源码片段一起交给模型，要求输出结构化结论
 *   3. 能机器修的直接修（障碍表），修不了的给出明确的改法
 *   4. 可选：修完立刻重跑失败用例，用结果验证修对了没有
 *
 * 为什么只自动修「障碍」这一类：
 *   - 障碍是数据，写进 JSON，最坏是「下次没拦住」
 *   - 改断言/改流程是改代码，最坏是把框架改坏
 *   所以其余类别只出建议，不落盘。
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { VISION_DIR } from './config.js';
import { OBSTACLES, knownObstacleIds, reloadObstacles } from './obstacles.js';
import { renderRunReport } from './report.js';
import type { CaseResult, RunOutput } from './types.js';

const RUN_DIR = resolve(VISION_DIR, 'midscene_run');
const LOG_DIR = resolve(RUN_DIR, 'log');
const ANALYSIS_DIR = resolve(RUN_DIR, 'analysis');
const GENERATED_FILE = resolve(VISION_DIR, 'obstacles.generated.json');

// ---------------------------------------------------------------- 证据抽取

interface LogStep {
  at: string;
  kind: '观察' | '点击' | '判定';
  text: string;
}

function parseTs(line: string): string | null {
  const m = line.match(/^\[(\d{4}-\d\d-\d\dT[\d:.]+[+-]\d\d:\d\d)\]/);
  return m ? m[1]! : null;
}

/**
 * 把 ai-call.log 拆成「模型看到了什么 / 点了哪里 / 判了什么」。
 *
 * 一个响应块里常常同时有 observation 和判定 JSON（如 StatementIsTruthy:false），
 * 两个都要留：判定说明这一步没通过，observation 说明模型看到的是什么造成的。
 */
export function parseAiCallLog(): LogStep[] {
  const file = resolve(LOG_DIR, 'ai-call.log');
  if (!existsSync(file)) return [];
  const text = readFileSync(file, 'utf8');
  const blocks = text.split(/(?=\[\d{4}-\d\d-\d\dT)/).filter((b) => b.trim());

  const steps: LogStep[] = [];
  for (const b of blocks) {
    const at = parseTs(b);
    if (!at) continue;

    const obs = b.match(/<observation>([\s\S]*?)<\/observation>/);
    if (obs) steps.push({ at, kind: '观察', text: obs[1]!.replace(/\s+/g, ' ').trim() });

    const point = b.match(/point｜｜>\[\[(\d+),\s*(\d+)\]\]/);
    if (point) steps.push({ at, kind: '点击', text: `(${point[1]}, ${point[2]})` });

    for (const m of b.matchAll(/\{\s*"(\w+)":\s*(true|false|"[^"]*")\s*\}/g)) {
      // 只留跟判定有关的键，其余（例如控件的 type="disabled"）是噪声，会把证据淹掉
      if (!KEEP_VERDICT_KEYS.has(m[1]!)) continue;
      steps.push({ at, kind: '判定', text: `${m[1]}=${m[2]}` });
    }
  }
  return steps;
}

/** 这些键的取值才反映「模型判了什么」 */
const KEEP_VERDICT_KEYS = new Set([
  'StatementIsTruthy',
  'Boolean',
  'value',
  'answer',
  'result',
  'obstacle',
  'index',
]);

/**
 * action 序列（点了什么、输入了什么），来自 agent.log。
 *
 * 重点是输入类动作的**实际下发的值**——2026-11-20 那次就是
 * 下发 pss2、设备只打进去「2」，日志里一眼能看到，但当时没人看。
 * 密码本身不回显，只留长度。
 */
export function parseActions(): string[] {
  const file = resolve(LOG_DIR, 'agent.log');
  if (!existsSync(file)) return [];
  const lines = readFileSync(file, 'utf8').split('\n');
  const secret = process.env.EGO_PASSWORD ?? '';
  const out: string[] = [];

  for (let i = 0; i < lines.length; i += 1) {
    const t = lines[i]!.match(/^\s*type: '(\w+)',/);
    if (!t) continue;
    const type = t[1]!;

    let value: string | null = null;
    for (let j = i + 1; j < Math.min(i + 6, lines.length); j += 1) {
      const v = lines[j]!.match(/^\s*value: '([^']*)',?$/);
      if (v) {
        value = v[1]!;
        break;
      }
    }

    if (value === null) {
      out.push(type);
    } else {
      const shown = secret && value === secret ? '<密码>' : value;
      out.push(`${type} 输入="${shown}"（${value.length} 字符）`);
    }
  }
  return out;
}

function stepsInWindow(steps: LogStep[], fromIso: string, toIso: string): LogStep[] {
  const from = Date.parse(fromIso);
  const to = Date.parse(toIso);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return steps.slice(-25);
  return steps.filter((s) => {
    const t = Date.parse(s.at);
    return Number.isFinite(t) && t >= from && t <= to;
  });
}

export interface Evidence {
  caseId: string;
  title: string;
  error: string;
  diagnosis?: CaseResult['diagnosis'];
  assertions: CaseResult['assertions'];
  timeline: LogStep[];
  actions: string[];
}

/**
 * 把一次失败压缩成「模型能读、又不烧钱」的证据。
 *
 * 时间窗往回多看 3 分钟：很多用例是「前面的准备动作」把状态搞坏的
 * （比如登录时输入被截断），只截用例执行期会看不到真凶。
 */
export function buildEvidence(
  run: RunOutput,
  caseResult: CaseResult,
  lookbackMs = 180_000,
): Evidence {
  const allSteps = parseAiCallLog();
  const startMs = Date.parse(caseResult.startedAt ?? run.generatedAt) - lookbackMs;
  const endMs = Date.parse(caseResult.finishedAt ?? run.generatedAt) + 2_000;

  return {
    caseId: caseResult.caseId,
    title: caseResult.title ?? '',
    error: caseResult.error ?? '',
    diagnosis: caseResult.diagnosis,
    assertions: caseResult.assertions,
    // 只取该用例时间窗内的最后 25 步——更早的步骤对定因没帮助
    timeline: stepsInWindow(
      allSteps,
      new Date(startMs).toISOString(),
      new Date(endMs).toISOString(),
    ).slice(-25),
    actions: parseActions().slice(-15),
  };
}

function evidenceToText(ev: Evidence): string {
  const lines: string[] = [];
  lines.push(`## 失败用例 ${ev.caseId} ${ev.title}`);
  lines.push(`错误：${ev.error}`);
  if (ev.diagnosis) {
    lines.push(`自动归因：${ev.diagnosis.attribution}（屏幕=${ev.diagnosis.screen}）`);
    lines.push(`现场描述：${ev.diagnosis.detail}`);
  }
  if (ev.assertions.length) {
    lines.push('断言：');
    for (const a of ev.assertions.slice(-6)) {
      lines.push(`  [${a.ok ? 'PASS' : 'FAIL'}] ${a.rule} 期望「${a.expected}」实际「${a.actual}」`);
    }
  }
  lines.push('模型在失败前的观察与动作（按时间）：');
  for (const s of ev.timeline) lines.push(`  ${s.at.slice(11, 19)} ${s.kind}: ${s.text}`);
  if (ev.actions.length) {
    lines.push('设备动作序列（最后 15 条）：');
    for (const a of ev.actions) lines.push(`  ${a}`);
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------- 模型分析

export interface Analysis {
  rootCause:
    | 'input-truncated'
    | 'obstacle-missing'
    | 'assertion-wrong'
    | 'precondition-wrong'
    | 'product-defect'
    | 'flaky'
    | 'unknown';
  reasoning: string;
  evidence: string[];
  confidence: number;
  fix: {
    kind: 'obstacle' | 'assertion' | 'none';
    obstacle?: {
      id: string;
      detect: string;
      remedy: string;
      verify: string;
      attribution: 'environment' | 'product';
    };
    assertion?: { caseId: string; from: string; to: string };
    note?: string;
  };
}

const ANALYSIS_PROMPT = `你是一名资深自动化测试工程师。下面是一次 UI 自动化失败的完整现场。
请判断根因并给出可执行的修复方案。

根因只能从这些里选一个：
- obstacle-missing：屏幕被弹窗/通知中心/系统界面挡住，导致动作落空
- input-truncated：输入框内容不完整（丢字符、被截断、被转义吃掉）
- assertion-wrong：断言本身写错了（例如用了负面断言，错误页面也能满足）
- precondition-wrong：前置状态不对（例如连错服务器、onboarding 没走完、网络不通）
- product-defect：界面在 App 内，行为确实不符合预期
- flaky：同样操作结果不一致，时序问题
- unknown：证据不足

注意：出现 fetch failed、java.net.ConnectException、连接超时这类网络错误时，
不要判成 product-defect——先怀疑服务器选择（旧服务器/新服务器）或网络环境，归为 precondition-wrong。

要求：
1. reasoning 里必须引用日志中的具体片段，不要泛泛而谈。
2. 判断 input-truncated 时，对比「设备动作序列」里下发的值 和「模型观察」里输入框实际显示的内容：
   字符数不一致（例如下发 pss2、框里只有 2）就是输入被截断。
3. 如果根因是 obstacle-missing，给出障碍条目的 id/detect/remedy/verify/attribution。
   detect 要描述**界面角色**（长什么样、有哪些按钮语义），不要只写死文案。
   remedy 绝不能点「立即更新/确定/同意/删除」这类有副作用的按钮。
4. 如果根因是 assertion-wrong，给出原断言和建议的正面断言。
5. 如果断言列表里出现了负面断言（「看不到 X」「没有 Y」），即使它不是本次主因，
   也要在 fix.note 里点出来——负面断言在通知中心/锁屏/黑屏上也会成立。
6. confidence 是 0 到 1 的数字，证据不足就给低分。

只输出 JSON，不要任何解释文字，格式：
{
  "rootCause": "...",
  "reasoning": "≤200字",
  "evidence": ["日志片段", "..."],
  "confidence": 0.0,
  "fix": {
    "kind": "obstacle|assertion|none",
    "obstacle": {"id":"...","detect":"...","remedy":"...","verify":"...","attribution":"environment|product"},
    "assertion": {"caseId":"...","from":"...","to":"..."},
    "note": "..."
  }
}`;

async function callModel(digest: string): Promise<Analysis> {
  const base = process.env.MIDSCENE_MODEL_BASE_URL?.trim();
  const key = process.env.MIDSCENE_MODEL_API_KEY?.trim();
  const model = process.env.MIDSCENE_MODEL_NAME?.trim();
  if (!base || !key || !model) {
    throw new Error('缺模型配置，无法做自愈分析（需要 MIDSCENE_MODEL_BASE_URL / API_KEY / NAME）');
  }

  const res = await fetch(`${base.replace(/\/+$/, '')}/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key}` },
    body: JSON.stringify({
      model,
      temperature: 0,
      messages: [
        { role: 'system', content: ANALYSIS_PROMPT },
        { role: 'user', content: digest },
      ],
    }),
  });
  if (!res.ok) {
    throw new Error(`分析请求失败 HTTP ${res.status}：${(await res.text()).slice(0, 300)}`);
  }
  const data = (await res.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const content = data.choices?.[0]?.message?.content ?? '';
  const jsonText = content.slice(content.indexOf('{'), content.lastIndexOf('}') + 1);
  if (!jsonText) throw new Error(`模型没返回 JSON：${content.slice(0, 200)}`);
  return JSON.parse(jsonText) as Analysis;
}

// ---------------------------------------------------------------- 应用修复

export interface ApplyResult {
  applied: boolean;
  reason: string;
}

/**
 * 只自动应用「障碍」这一类修复。
 * 门槛：confidence ≥ 0.6，且 id 不在已有障碍里（避免重复堆积）。
 */
export function applyObstacleFix(analysis: Analysis): ApplyResult {
  if (analysis.fix.kind !== 'obstacle' || !analysis.fix.obstacle) {
    return { applied: false, reason: `修复类型是 ${analysis.fix.kind}，需要人工改代码` };
  }
  if (analysis.confidence < 0.6) {
    return { applied: false, reason: `置信度 ${analysis.confidence} 低于 0.6，不敢自动写` };
  }

  const fix = analysis.fix.obstacle;
  const known = knownObstacleIds();
  if (known.has(fix.id)) {
    return { applied: false, reason: `障碍 ${fix.id} 已存在，不重复添加` };
  }

  let existing: unknown[] = [];
  if (existsSync(GENERATED_FILE)) {
    try {
      const parsed = JSON.parse(readFileSync(GENERATED_FILE, 'utf8'));
      if (Array.isArray(parsed)) existing = parsed;
    } catch {
      existing = [];
    }
  }
  existing.push({
    id: fix.id,
    detect: fix.detect,
    remedy: fix.remedy,
    verify: fix.verify,
    attribution: fix.attribution ?? 'environment',
    addedBy: 'self-heal',
    addedAt: new Date().toISOString(),
    reason: analysis.reasoning.slice(0, 200),
  });
  writeFileSync(GENERATED_FILE, JSON.stringify(existing, null, 2), 'utf-8');
  // 同进程回跑要用上新表，否则「修好了但重跑还是老样子」
  const count = reloadObstacles();
  return { applied: true, reason: `已写入 ${GENERATED_FILE}（障碍表共 ${count} 条）` };
}

// ---------------------------------------------------------------- 对外入口

/** 一条失败用例的分析结果，报告直接消费这个结构。 */
export interface AnalysisEntry {
  caseId: string;
  title: string;
  /** 交给模型的证据原文，报告里折叠展示 */
  digest: string;
  analysis?: Analysis;
  applied: boolean;
  applyReason?: string;
  /** 没跑成分析时的原因 */
  note?: string;
}

export interface AnalyzeOptions {
  /** 结果文件路径，或直接给内存里的结果（跑完还没落盘时用） */
  run: RunOutput | string;
  apply: boolean;
}

export interface AnalyzeResult {
  entries: AnalysisEntry[];
  mdPath: string;
  htmlPath: string;
}

/** 逐条分析失败用例，返回结构化结论（不写文件）。修正层直接用这个。 */
export async function analyzeCases(
  run: RunOutput,
  apply: boolean,
): Promise<{ entries: AnalysisEntry[]; sections: string[] }> {
  const failed = run.cases.filter((c) => c.status === 'failed');
  const entries: AnalysisEntry[] = [];
  const sections: string[] = [];

  if (failed.length === 0) return { entries, sections };

  sections.push(`失败 ${failed.length} 条，逐条分析。`, '');

  for (const c of failed) {
    const ev = buildEvidence(run, c);
    const digest = evidenceToText(ev);
    console.log(`\n▶ 分析 ${c.caseId} …`);

    let analysis: Analysis;
    try {
      analysis = await callModel(digest);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.log(`  分析失败：${msg}`);
      entries.push({
        caseId: c.caseId,
        title: c.title ?? '',
        digest,
        applied: false,
        note: `分析失败：${msg}`,
      });
      sections.push(
        `## ${c.caseId}\n\n分析失败：${msg}\n\n<details><summary>证据</summary>\n\n\`\`\`\n${digest}\n\`\`\`\n</details>\n`,
      );
      continue;
    }

    const applyResult = apply
      ? applyObstacleFix(analysis)
      : { applied: false, reason: '未开启 --apply' };

    console.log(`  根因：${analysis.rootCause}（置信度 ${analysis.confidence}）`);
    console.log(`  推理：${analysis.reasoning}`);
    if (applyResult.applied) console.log(`  ✅ 已自动修复：${applyResult.reason}`);
    else console.log(`  ℹ 未自动修复：${applyResult.reason}`);

    entries.push({
      caseId: c.caseId,
      title: c.title ?? '',
      digest,
      analysis,
      applied: applyResult.applied,
      applyReason: applyResult.reason,
    });

    sections.push(
      [
        `## ${c.caseId} ${c.title ?? ''}`,
        '',
        `- 根因：**${analysis.rootCause}**（置信度 ${analysis.confidence}）`,
        `- 推理：${analysis.reasoning}`,
        `- 证据：${analysis.evidence.map((x) => `「${x}」`).join('；')}`,
        `- 修复类型：${analysis.fix.kind}`,
        `- 自动应用：${applyResult.applied ? '是' : '否'} —— ${applyResult.reason}`,
        analysis.fix.obstacle ? `- 障碍条目：\`${JSON.stringify(analysis.fix.obstacle)}\`` : '',
        analysis.fix.assertion
          ? `- 断言改法：\`${analysis.fix.assertion.from}\` → \`${analysis.fix.assertion.to}\``
          : '',
        analysis.fix.note ? `- 备注：${analysis.fix.note}` : '',
        '',
        '<details><summary>失败现场</summary>',
        '',
        '```',
        digest,
        '```',
        '</details>',
        '',
      ]
        .filter(Boolean)
        .join('\n'),
    );
  }

  return { entries, sections };
}

export async function analyzeRun(opts: AnalyzeOptions): Promise<AnalyzeResult> {
  const run =
    typeof opts.run === 'string'
      ? (JSON.parse(readFileSync(resolve(opts.run), 'utf8')) as RunOutput)
      : opts.run;

  mkdirSync(ANALYSIS_DIR, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const reportPath = resolve(ANALYSIS_DIR, `analysis-${stamp}.md`);
  const htmlPath = resolve(ANALYSIS_DIR, `report-${stamp}.html`);

  const { entries, sections } = await analyzeCases(run, opts.apply);

  if (entries.length === 0) {
    writeFileSync(reportPath, `# 自愈分析 ${stamp}\n\n本次没有失败用例，无需分析。\n`, 'utf-8');
    console.log('没有失败用例，跳过分析。');
  } else {
    writeFileSync(
      reportPath,
      [`# 自愈分析 ${stamp}`, '', ...sections].join('\n'),
      'utf-8',
    );
  }
  writeFileSync(htmlPath, renderRunReport(run, entries), 'utf-8');
  console.log(`\n分析报告：${htmlPath}`);
  return { entries, mdPath: reportPath, htmlPath };
}

/** 当前障碍表快照，写进报告方便对照。 */
export function obstacleSnapshot(): string {
  return OBSTACLES.map((o) => `${o.id}: ${o.detect.slice(0, 40)}…`).join('\n');
}
