/**
 * 用例生成层：把声明式的 YAML 编译成可执行计划。
 *
 * 这一层只做三件事，不碰设备、不调模型：
 *   1. 读 `vision/cases/*.yaml`，展开 include 片段
 *   2. 校验（编号唯一、步骤合法、前置状态合法、占位符可解析）
 *   3. 产出 Plan[]，交给执行层
 *
 * 为什么用例是 YAML 而不是 TS：
 *   - 机器只允许改数据，不允许改代码。自动修正要能写东西，能写的就是这里。
 *   - 换项目/换人写用例不需要懂 TypeScript。
 *
 * 可用步骤（写错了会在加载时报错，不会跑到一半才发现）：
 *   - launch: true / terminate: true / back: true
 *   - tap: '「登录」按钮'
 *   - input: { target: '「用户名」输入框', value: '{{username}}' }
 *   - wait: { for: '已经到达首页', timeout: 30000 }
 *   - assert: { rule: R-AUTH-01, expect: '登录后进入首页', fatal: true }
 *   - repeat: { times: 5, steps: [...] }
 *   - if: { when: '条件', then: [...], else: [...] }
 *   - include: login
 */
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import yaml from 'js-yaml';

import { VISION_DIR } from './config.js';
import { casesDir } from './project.js';

export type Precondition =
  | 'fresh-install'
  | 'login-page'
  | 'login-page-old-server'
  | 'logged-in'
  | 'fresh-install-no-camera';

export type Step =
  | { kind: 'launch' }
  | { kind: 'terminate' }
  | { kind: 'back' }
  | { kind: 'open'; route: string }
  | { kind: 'check-route'; route: string; expectAny: string[] }
  | { kind: 'tap'; target: string }
  | { kind: 'input'; target: string; value: string }
  | { kind: 'wait'; for: string; timeoutMs: number }
  | { kind: 'assert'; rule: string; expect: string; fatal: boolean }
  | { kind: 'dismiss'; labels: string[] }
  | { kind: 'sleep'; seconds: number }
  | { kind: 'check-all'; rounds: number }
  | { kind: 'repeat'; times: number; steps: Step[] }
  | { kind: 'if'; when: string; then: Step[]; else: Step[] };

export type PolicyOrder = 'normal' | 'costly' | 'destructive';

export interface Policy {
  /**
   * 执行顺序档位。写清楚它属于哪一档，是「用例排序规则」的落点：
   *   normal      默认。快、无副作用、可任意顺序
   *   costly      要登录、耗额度（真录视频/上传），排在 normal 之后
   *   destructive 破坏共享状态（锁账号/删数据），永远最后
   * 老字段 kind 仍兼容，但 order 优先。
   */
  order?: PolicyOrder;
  /** 兼容旧写法：kind=destructive/costly 等价于 order */
  kind?: string;
  /** 依赖哪些用例的产物/状态；依赖没通过就跳过，而不是硬跑出假失败 */
  dependsOn?: string[];
  /** 副作用说明，显示在报告和 --dry-run 里 */
  why?: string;
  /**
   * 跑完之后这些用例受影响，会被自动跳过。
   * 写 `['*']` 表示「除自己以外全部」——新增用例自动被覆盖，不用回来补这里。
   */
  affects?: string[];
  /** 跑完之后整个环境要冷却多久（分钟） */
  cooldownMinutes?: number;
  /** 分档：smoke = 每次提交跑的快检；不写 = 只进全量 */
  tier?: string;
}

/**
 * 用例的审核状态。
 *
 * 为什么需要它：用例可以由代码生成（结构性断言），但「什么算对」这件事
 * 代码不知道。生成出来的东西必须有人看过才能当正式结果用。
 *
 * 这里**不阻断执行**——用户明确要求「都跑，但报告里标未审核」。
 * 拦住的是报告的可信度，不是执行本身。
 */
export type ReviewStatus = 'draft' | 'approved' | 'rejected';

/**
 * 断言的依据从哪来，决定人审核时要看多仔细：
 *   doc   需求文档里的原文（最可信，人只需确认没理解偏）
 *   code  源码里写着的事实（页面能渲染、label 在、路由可达；测的是「不崩」）
 *   guess 推测出来的业务断言（必须人确认，这是审核的重点）
 *   human 人亲手写的（默认视为可信，但状态仍是 draft，除非显式批准）
 */
export type ReviewSource = 'doc' | 'code' | 'guess' | 'human';

export interface Review {
  status: ReviewStatus;
  source: ReviewSource;
  /** 审核意见 / 生成这条时的疑问，显示在审核页上 */
  note?: string;
  approvedAt?: string;
  approvedBy?: string;
}

export interface Plan {
  id: string;
  title: string;
  precondition: Precondition;
  steps: Step[];
  /** 来源文件，报错时能指回去 */
  source: string;
  /** 来自 cases/policy.yaml 的附加规则 */
  policy?: Policy;
  /** 审核状态；YAML 里没写就当 draft，宁可少信不可多信 */
  review: Review;
}

// 用例目录属于「项目」，不属于框架：换项目就换目录
const CASES_DIR = () => casesDir();
const CASES_FILE = () => resolve(CASES_DIR(), 'cases.yaml');
/**
 * 由源码派生出来的用例放这里，和执行用例分开存。
 *
 * 分文件是为了让「人写的」和「机器生成的」一眼就能分清：derived.yaml 随时可以
 * 整个删掉重生成，cases.yaml 里全是人确认过的东西。
 */
const DERIVED_FILE = () => resolve(CASES_DIR(), 'derived.yaml');
const FRAGMENTS_FILE = () => resolve(CASES_DIR(), 'fragments.yaml');
const POLICY_FILE = () => resolve(CASES_DIR(), 'policy.yaml');

const PRECONDITIONS: Precondition[] = [
  'fresh-install',
  'login-page',
  'login-page-old-server',
  'logged-in',
  'fresh-install-no-camera',
];

const REVIEW_STATUSES: ReviewStatus[] = ['draft', 'approved', 'rejected'];
const REVIEW_SOURCES: ReviewSource[] = ['doc', 'code', 'guess', 'human'];

export const REVIEW_LABEL: Record<ReviewStatus, string> = {
  draft: '未审核',
  approved: '已审核',
  rejected: '已驳回',
};

export const SOURCE_LABEL: Record<ReviewSource, string> = {
  doc: '需求文档',
  code: '源码结构',
  guess: '推测（重点看）',
  human: '人工编写',
};

/** 解析 YAML 里的 review 块；写错值就记错误，不静默降级。 */
function parseReview(raw: unknown, id: string, errors: string[]): Review {
  if (raw === undefined || raw === null) {
    // 没写 = 未审核。这是安全默认：新加的用例不会因为「忘了写」而被当成已审。
    return { status: 'draft', source: 'human' };
  }
  if (typeof raw === 'string') {
    const s = raw.trim() as ReviewStatus;
    if (!REVIEW_STATUSES.includes(s)) {
      errors.push(`${id}：review 状态「${s}」不合法（可用：${REVIEW_STATUSES.join('/')}）`);
      return { status: 'draft', source: 'human' };
    }
    return { status: s, source: 'human' };
  }
  if (typeof raw !== 'object') {
    errors.push(`${id}：review 必须是字符串或对象`);
    return { status: 'draft', source: 'human' };
  }
  const r = raw as Record<string, unknown>;
  const status = (str(r.status) || 'draft') as ReviewStatus;
  const source = (str(r.source) || 'human') as ReviewSource;
  if (!REVIEW_STATUSES.includes(status)) {
    errors.push(`${id}：review.status「${status}」不合法（可用：${REVIEW_STATUSES.join('/')}）`);
  }
  if (!REVIEW_SOURCES.includes(source)) {
    errors.push(`${id}：review.source「${source}」不合法（可用：${REVIEW_SOURCES.join('/')}）`);
  }
  return {
    status: REVIEW_STATUSES.includes(status) ? status : 'draft',
    source: REVIEW_SOURCES.includes(source) ? source : 'human',
    ...(str(r.note) ? { note: str(r.note) } : {}),
    ...(str(r.approvedAt) ? { approvedAt: str(r.approvedAt) } : {}),
    ...(str(r.approvedBy) ? { approvedBy: str(r.approvedBy) } : {}),
  };
}

const DEFAULT_WAIT_MS = 30000;

type RawStep = Record<string, unknown>;
type Fragments = Record<string, RawStep[]>;

function readYaml(file: string): unknown {
  if (!existsSync(file)) return undefined;
  return yaml.load(readFileSync(file, 'utf8'));
}

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : '';
}

/** 把一条原始步骤编译成 Step；不合法就记一条错误并返回 null。 */
function compileStep(
  raw: unknown,
  fragments: Fragments,
  where: string,
  errors: string[],
  depth: number,
): Step | Step[] | null {
  if (depth > 10) {
    errors.push(`${where}：include/repeat 嵌套过深（可能是循环引用）`);
    return null;
  }
  if (typeof raw === 'string') {
    // 只写字符串时按「点这个」处理，写用例时省事
    return { kind: 'tap', target: raw.trim() };
  }
  if (!raw || typeof raw !== 'object') {
    errors.push(`${where}：步骤必须是字符串或对象，实际是 ${JSON.stringify(raw)}`);
    return null;
  }

  const r = raw as RawStep;
  const keys = Object.keys(r);
  const key = keys[0];

  if (keys.length !== 1) {
    errors.push(`${where}：一条步骤只能有一个动作，实际有 ${keys.join('/')}`);
    return null;
  }

  switch (key) {
    case 'launch':
      return { kind: 'launch' };
    case 'terminate':
      return { kind: 'terminate' };
    case 'back':
      return { kind: 'back' };

    case 'open': {
      const route = str(r.open).replace(/^\/+/, '');
      if (!route) {
        errors.push(`${where}：open 需要路由名，比如 open: home`);
        return null;
      }
      return { kind: 'open', route };
    }

    case 'check-route': {
      const p = r['check-route'] as RawStep | undefined;
      // 空串是合法的：表示根路由 '/'。所以判断「有没有写这个字段」，不是「值真不真」
      if (!p || typeof p !== 'object' || !('route' in p)) {
        errors.push(`${where}：check-route 缺 route（根路由写 route: ''）`);
        return null;
      }
      const route = str(p.route).replace(/^\/+/, '');
      const list = Array.isArray(p['expect-any'])
        ? (p['expect-any'] as unknown[]).map((x) => str(x)).filter(Boolean)
        : [];
      if (list.length === 0) {
        errors.push(
          `${where}：check-route 需要 expect-any（至少一个页面上该出现的文案，全是源码里抽的）`,
        );
        return null;
      }
      return { kind: 'check-route', route, expectAny: list };
    }

    case 'tap': {
      const target = str(r.tap);
      if (!target) {
        errors.push(`${where}：tap 需要一个非空的目标描述`);
        return null;
      }
      return { kind: 'tap', target };
    }

    case 'input': {
      const p = r.input as RawStep | undefined;
      const target = str(p?.target);
      const value = str(p?.value);
      if (!target) {
        errors.push(`${where}：input.target 为空（要写清楚填哪个框）`);
        return null;
      }
      if (!value) {
        errors.push(`${where}：input.value 为空`);
        return null;
      }
      return { kind: 'input', target, value };
    }

    case 'wait': {
      const p = r.wait as RawStep | undefined;
      const cond = str(p?.for);
      if (!cond) {
        errors.push(`${where}：wait.for 为空（要写清楚等什么状态）`);
        return null;
      }
      const timeout = typeof p?.timeout === 'number' ? p.timeout : DEFAULT_WAIT_MS;
      return { kind: 'wait', for: cond, timeoutMs: timeout };
    }

    case 'assert': {
      const p = r.assert as RawStep | undefined;
      const rule = str(p?.rule);
      const expect = str(p?.expect);
      if (!rule) {
        errors.push(`${where}：assert.rule 为空（要能对到 core/rules.py 的编号）`);
        return null;
      }
      if (!expect) {
        errors.push(`${where}：assert.expect 为空`);
        return null;
      }
      return { kind: 'assert', rule, expect, fatal: p?.fatal === true };
    }

    case 'check-all': {
      const p = r['check-all'] as RawStep | undefined;
      const rounds = typeof p?.rounds === 'number' ? p.rounds : 3;
      return { kind: 'check-all', rounds };
    }

    case 'sleep': {
      const p = r.sleep as RawStep | undefined;
      const seconds = typeof p?.seconds === 'number' ? p.seconds : 0;
      if (seconds <= 0) {
        errors.push(`${where}：sleep.seconds 必须是正数`);
        return null;
      }
      return { kind: 'sleep', seconds };
    }

    case 'dismiss': {
      const raw = r.dismiss;
      const labels = (Array.isArray(raw) ? raw : [raw])
        .map((x) => str(x))
        .filter(Boolean);
      if (labels.length === 0) {
        errors.push(`${where}：dismiss 至少写一个按钮文案，例如 [暂不更新]`);
        return null;
      }
      return { kind: 'dismiss', labels };
    }

    case 'repeat': {
      const p = r.repeat as RawStep | undefined;
      const times = typeof p?.times === 'number' ? p.times : 0;
      if (times < 1) {
        errors.push(`${where}：repeat.times 必须是正整数`);
        return null;
      }
      const inner = compileSteps(p?.steps, fragments, `${where}.repeat`, errors, depth + 1);
      return { kind: 'repeat', times, steps: inner };
    }

    case 'if': {
      const p = r.if as RawStep | undefined;
      const when = str(p?.when);
      if (!when) {
        errors.push(`${where}：if.when 为空`);
        return null;
      }
      return {
        kind: 'if',
        when,
        then: compileSteps(p?.then, fragments, `${where}.if.then`, errors, depth + 1),
        else: compileSteps(p?.else, fragments, `${where}.if.else`, errors, depth + 1),
      };
    }

    case 'include': {
      const name = str(r.include);
      const frag = fragments[name];
      if (!frag) {
        errors.push(
          `${where}：找不到片段「${name}」（已定义：${Object.keys(fragments).join('、') || '无'}）`,
        );
        return null;
      }
      return compileSteps(frag, fragments, `${where}←${name}`, errors, depth + 1);
    }

    default:
      errors.push(
        `${where}：不认识的动作「${key}」（可用：launch/terminate/back/tap/input/wait/assert/repeat/if/include）`,
      );
      return null;
  }
}

function compileSteps(
  raw: unknown,
  fragments: Fragments,
  where: string,
  errors: string[],
  depth: number,
): Step[] {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw)) {
    errors.push(`${where}：steps 必须是数组`);
    return [];
  }
  const out: Step[] = [];
  raw.forEach((item, i) => {
    const compiled = compileStep(item, fragments, `${where}[${i}]`, errors, depth);
    if (Array.isArray(compiled)) out.push(...compiled);
    else if (compiled) out.push(compiled);
  });
  return out;
}

export interface LoadResult {
  plans: Plan[];
  /** 所有校验问题；空数组表示全部合法 */
  errors: string[];
}

/** 读 policy.yaml：用例编号 → 附加规则。读坏了当没有，人工规则不能挡住跑批。 */
/** 把一段原始对象解析成 Policy。policy.yaml 和用例内联声明共用这一份逻辑。 */
function parsePolicy(v: unknown): Policy {
  if (!v || typeof v !== 'object') return {};
  const r = v as RawStep;
  return {
    kind: str(r.kind) || undefined,
    why: str(r.why) || undefined,
    affects: (() => {
      if (str(r.affects) === '*') return ['*'];
      if (Array.isArray(r.affects)) {
        const list = r.affects.map((x) => str(x)).filter(Boolean);
        return list.includes('*') ? ['*'] : list;
      }
      return undefined;
    })(),
    order: (str(r.order) || undefined) as PolicyOrder | undefined,
    dependsOn: Array.isArray(r['depends-on'])
      ? r['depends-on'].map((x) => str(x)).filter(Boolean)
      : undefined,
    cooldownMinutes:
      typeof r['cooldown-minutes'] === 'number' ? r['cooldown-minutes'] : undefined,
    tier: str(r.tier) || undefined,
  };
}

function loadPolicy(): Record<string, Policy> {
  const raw = readYaml(POLICY_FILE());
  if (!raw || typeof raw !== 'object') return {};
  const out: Record<string, Policy> = {};
  for (const [id, v] of Object.entries(raw as Record<string, unknown>)) {
    out[id] = parsePolicy(v);
  }
  return out;
}

/** 读并校验全部用例。有任何错误都不返回计划——宁可一条不跑，也别跑到一半才炸。 */
export function loadPlans(): LoadResult {
  const errors: string[] = [];
  const fragments = (readYaml(FRAGMENTS_FILE()) ?? {}) as Fragments;
  const policy = loadPolicy();

  // cases.yaml 是人写的，derived.yaml 是源码派生的。分开读、合并执行。
  const sources: Array<{ file: string; raw: unknown }> = [];
  for (const file of [CASES_FILE(), DERIVED_FILE()]) {
    const raw = readYaml(file);
    if (raw === undefined || raw === null) continue;   // derived.yaml 没有或为空都正常
    if (!Array.isArray(raw)) {
      errors.push(`${file} 不是数组`);
      continue;
    }
    sources.push({ file, raw });
  }
  if (sources.length === 0) {
    return { plans: [], errors: [`${CASES_FILE()} 不存在或不是数组`] };
  }

  const plans: Plan[] = [];
  const seen = new Set<string>();

  for (const { file, raw } of sources) {
    (raw as unknown[]).forEach((item, i) => {
      if (!item || typeof item !== 'object') {
        errors.push(`${file} 第 ${i + 1} 条用例不是对象`);
        return;
      }
      const c = item as RawStep;
      const id = str(c.id);
      const title = str(c.title);
      const pre = str(c.precondition) as Precondition;

      if (!id) errors.push(`${file} 第 ${i + 1} 条用例缺 id`);
      else if (seen.has(id)) errors.push(`用例编号重复：${id}`);
      else seen.add(id);

      if (!title) errors.push(`${id || `第 ${i + 1} 条`}：缺 title`);
      if (!PRECONDITIONS.includes(pre)) {
        errors.push(
          `${id || `第 ${i + 1} 条`}：precondition「${pre}」不合法（可用：${PRECONDITIONS.join('/')}）`,
        );
      }

      const steps = compileSteps(c.steps, fragments, id || `第 ${i + 1} 条`, errors, 0);
      if (steps.length === 0 && !errors.length) {
        errors.push(`${id}：steps 为空`);
      }

      // policy.yaml 是权威；派生用例没登记在那里，就允许它把档位写在用例自己身上
      const inline = parsePolicy(c);
      const merged: Policy = { ...inline, ...(policy[id] ?? {}) };
      const hasPolicy = Object.values(merged).some((x) => x !== undefined);

      plans.push({
        id,
        title,
        precondition: pre,
        steps,
        source: file,
        ...(hasPolicy ? { policy: merged } : {}),
        review: parseReview(c.review, id || `第 ${i + 1} 条`, errors),
      });
    });
  }

  // policy 里登记了但用例不存在的，说明写错了编号——直接报出来，别静默失效
  for (const id of Object.keys(policy)) {
    if (!seen.has(id)) errors.push(`policy.yaml 里的 ${id} 在 cases.yaml 中不存在`);
  }

  /*
   * 顺序声明是**必填**的，不是「想写就写」。
   *
   * 理由：一条会录视频、会锁账号的用例，只要漏写 order，它就会以 normal 的身份
   * 插到任意位置，把后面的用例一起带崩。默认值等于没有规则，所以这里直接拦住，
   * 一条都不跑——宁可让人补一行声明，也别让错误顺序偷偷执行。
   */
  for (const p of plans) {
    const declared = p.policy?.order ?? p.policy?.kind;
    if (!declared) {
      errors.push(
        `${p.id}：没有在 cases/policy.yaml 声明 order（normal / costly / destructive）`,
      );
      continue;
    }
    const rank = orderRank(p);
    if (rank > 0 && !p.policy?.why) {
      errors.push(`${p.id}：order=${declared} 必须写 why（说明副作用是什么）`);
    }
    if (rank === 2 && !(p.policy?.affects?.length)) {
      errors.push(`${p.id}：order=destructive 必须写 affects（跑完影响哪些用例）`);
    }
  }

  if (plans.length === 0 && errors.length === 0) errors.push('没有读到任何用例');

  return { plans, errors };
}

/**
 * 按 policy 排序：标了 `order: last` 的排到最后。
 *
 * 会锁账号的用例放在中间跑，后面所有依赖登录的用例都得遭殃；放最后，影响面最小。
 */
/** 用例的排序档位：0 普通 / 1 耗额度 / 2 破坏共享状态。 */
export function orderRank(p: Plan): number {
  const o = p.policy?.order;
  const k = p.policy?.kind;
  if (o === 'destructive' || k === 'destructive') return 2;
  if (o === 'costly' || k === 'costly' || p.policy?.order === ('last' as PolicyOrder)) return 1;
  return 0;
}

/**
 * 按「档位 + 依赖」排序。
 *
 * 规则（对应 rules.py 的 R-GATE-05）：
 *   1. 先跑普通用例，再跑耗额度的，最后跑破坏共享状态的——绝不能反过来，
 *      否则锁账号那条会把后面所有要登录的用例一起拖死（2026-11-24 实际踩过）。
 *   2. 声明了 depends-on 的，必须排在被依赖用例之后。
 */
export function sortByPolicy(plans: Plan[]): Plan[] {
  const sorted = plans
    .map((p, i) => ({ p, i, r: orderRank(p) }))
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .map((x) => x.p);

  // 依赖修正：被依赖的必须在前。最多挪 N 轮，防止环导致死循环。
  for (let pass = 0; pass < plans.length; pass += 1) {
    let moved = false;
    for (let i = 0; i < sorted.length; i += 1) {
      const deps = sorted[i]!.policy?.dependsOn ?? [];
      for (const dep of deps) {
        const di = sorted.findIndex((x) => x.id === dep);
        if (di > i) {
          const [item] = sorted.splice(di, 1);
          sorted.splice(i, 0, item!);
          moved = true;
        }
      }
    }
    if (!moved) break;
  }
  return sorted;
}

/** 把 {{username}} / {{password}} / {{package}} 换成人话。 */
export function resolveValue(
  value: string,
  vars: { username: string; password: string; package: string },
): string {
  return value.replace(/\{\{(\w+)\}\}/g, (whole, key: string) => {
    if (key === 'username') return vars.username;
    if (key === 'password') return vars.password;
    if (key === 'package') return vars.package;
    return whole;
  });
}

/** 计划里剩下的未知占位符（加载时就该发现，别等跑起来）。 */
export function unknownPlaceholders(plan: Plan): string[] {
  const found = new Set<string>();
  const walk = (steps: Step[]) => {
    for (const s of steps) {
      const texts: string[] = [];
      if (s.kind === 'input') texts.push(s.value);
      if (s.kind === 'tap') texts.push(s.target);
      if (s.kind === 'wait') texts.push(s.for);
      if (s.kind === 'assert') texts.push(s.expect);
      if (s.kind === 'if') {
        texts.push(s.when);
        walk(s.then);
        walk(s.else);
      }
      if (s.kind === 'repeat') walk(s.steps);
      for (const t of texts) {
        for (const m of t.matchAll(/\{\{(\w+)\}\}/g)) {
          if (!['username', 'password', 'package'].includes(m[1]!)) found.add(m[1]!);
        }
      }
    }
  };
  walk(plan.steps);
  return [...found];
}

/** 人看的计划摘要，给 --dry-run 用。 */
export function describeSteps(steps: Step[], indent = ''): string[] {
  const lines: string[] = [];
  for (const s of steps) {
    switch (s.kind) {
      case 'launch':
        lines.push(`${indent}· 拉起 App`);
        break;
      case 'terminate':
        lines.push(`${indent}· 杀掉 App`);
        break;
      case 'back':
        lines.push(`${indent}· 返回键`);
        break;
      case 'open':
        lines.push(`${indent}· 用深链直接打开 /${s.route}`);
        break;
      case 'check-route':
        lines.push(
          `${indent}· 深链打开 /${s.route}，读控件树确认页面出来了（不调模型）：` +
            `至少要看到 ${s.expectAny.map((x) => `「${x}」`).join(' 或 ')}`,
        );
        break;
      case 'tap':
        lines.push(`${indent}· ${s.target.startsWith('点') ? s.target : `点 ${s.target}`}`);
        break;
      case 'input':
        lines.push(`${indent}· 填 ${s.target} = ${s.value}`);
        break;
      case 'wait':
        lines.push(`${indent}· 等 ${s.for}（≤${Math.round(s.timeoutMs / 1000)}s）`);
        break;
      case 'assert':
        lines.push(`${indent}· 断言 ${s.rule}${s.fatal ? '（不成立即终止）' : ''}：${s.expect}`);
        break;
      case 'dismiss':
        lines.push(`${indent}· 出现 ${s.labels.map((l) => `「${l}」`).join('/')} 按钮就点掉`);
        break;
      case 'sleep':
        lines.push(`${indent}· 等 ${s.seconds} 秒`);
        break;
      case 'check-all':
        lines.push(`${indent}· 把所有未勾选的复选框都勾上（读控件树点坐标，不调模型）`);
        break;
      case 'repeat':
        lines.push(`${indent}· 重复 ${s.times} 次：`);
        lines.push(...describeSteps(s.steps, `${indent}    `));
        break;
      case 'if':
        lines.push(`${indent}· 如果「${s.when}」：`);
        lines.push(...describeSteps(s.then, `${indent}    是→ `));
        if (s.else.length) lines.push(...describeSteps(s.else, `${indent}    否→ `));
        break;
    }
  }
  return lines;
}
