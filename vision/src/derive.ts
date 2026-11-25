/**
 * 从源码派生「结构性冒烟」用例。
 *
 * 解决的问题：每加一个页面，就有一片没人测的区域——不是业务逻辑没测，
 * 而是**这个页面根本没被打开过**，白屏、崩溃、文案被改没了都没人知道。
 * 这类问题不需要人判断「什么算对」，代码里就能读出来。
 *
 * 边界（必须说清楚）：
 *   - 只生成「页面能打开 + 关键文案在」这类**结构性**用例
 *   - 一条业务断言都不生成——那是人写的，代码不知道什么叫「对」
 *   - 不调模型：执行靠 `check-route`（深链 + 控件树），几秒钟一页
 *
 * 覆盖判断：把每条有用例里出现的业务文案，和每个路由文件里抽出来的文案求交集。
 * 有交集说明这条用例「碰过」这个页面。这是粗匹配，用来提示缺口，不当作覆盖证明。
 */
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

import yaml from 'js-yaml';

import { VISION_DIR } from './config.js';
import { appSourceDir, casesDir } from './project.js';
import type { Plan } from './plan.js';

/** 派生用例要读 App 源码；没配就明确报错，别扫空目录后生成一堆空用例 */
function appDirOrThrow(): string {
  const src = appSourceDir();
  if (!src) {
    throw new Error(
      'project.json 没配 appSourceDir，也没设 QA_APP_SOURCE：派生用例需要 App 源码',
    );
  }
  return resolve(src, 'app');
}
const APP_DIR = () => appDirOrThrow();
const OUT_FILE = () => resolve(casesDir(), 'derived.yaml');

export interface RouteFacts {
  /** 路由路径，不带开头的 /；index 页是空串 */
  route: string;
  /** 相对仓库根的源码路径 */
  file: string;
  /** 这个文件里抽出来的中文文案 */
  copy: string[];
  /** 内部调试页：-test / demo / smoke / calib / diagnostics */
  debug: boolean;
}

function walk(dir: string): string[] {
  const out: string[] = [];
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const name of entries) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name === 'node_modules' || name.startsWith('.')) continue;
      out.push(...walk(full));
    } else if (/\.tsx?$/.test(name)) {
      out.push(full);
    }
  }
  return out;
}

/** (tabs)/home.tsx → home；index.tsx → ''；_layout.tsx 不是路由。 */
export function routeOf(relPath: string): string | null {
  const base = relPath.replace(/\.tsx?$/, '');
  if (/(^|\/)_layout$/.test(base)) return null;
  const segs = base
    .split('/')
    .filter((s) => !/^\(.*\)$/.test(s))       // 去掉 (tabs) 这类分组
    .filter(Boolean);
  if (segs.length && segs[segs.length - 1] === 'index') segs.pop();
  return segs.join('/');
}

export function isDebugRoute(route: string, file: string): boolean {
  return /(^|[/-])(test|demo|smoke|calib|diagnostics)([/-]|$)/i.test(route) ||
    /(^|[/-])(test|demo|smoke|calib|diagnostics)([/-]|$)/i.test(
      file.replace(/\.tsx?$/, ''),
    );
}

/**
 * 抽页面上的中文文案。
 *
 * 这个项目的中文都在 `t('中文', 'English')` 的第一个参数里，
 * 所以普通正则会漏掉——必须专门认这个双参数形式。
 */
export function copyOf(text: string): string[] {
  const found = new Set<string>();
  const push = (s: string) => {
    const v = s.trim();
    if (v.length < 2 || v.length > 22) return;
    if (!/[\u4e00-\u9fa5]/.test(v)) return;        // 只要带中文
    if (/[{}<>$`]/.test(v)) return;                 // 模板/变量拼出来的跳过
    if (/^[\s.·:：、/|-]+$/.test(v)) return;
    found.add(v);
  };
  for (const m of text.matchAll(/\bt\(\s*'([^'\\]*(?:\\.[^'\\]*)*)'\s*,/g)) push(m[1]!);
  for (const m of text.matchAll(/<Text[^>]*>([^<>{}\n]{1,40})<\/Text>/g)) push(m[1]!);
  return [...found];
}

export function scanRoutes(): RouteFacts[] {
  const out: RouteFacts[] = [];
  for (const file of walk(APP_DIR())) {
    const rel = relative(resolve(appSourceDir(), '..'), file);
    const route = routeOf(relative(APP_DIR(), file));
    if (route === null) continue;
    const copy = copyOf(readFileSync(file, 'utf8'));
    out.push({ route, file: rel, copy, debug: isDebugRoute(route, rel) });
  }
  return out.sort((a, b) => a.route.localeCompare(b.route));
}

/** 用例里出现过的所有文案（tap / wait / expect 的描述里）。 */
function caseCopy(plans: Plan[]): Array<{ id: string; copy: string[] }> {
  return plans.map((p) => {
    const strings: string[] = [];
    const visit = (steps: typeof p.steps) => {
      for (const s of steps) {
        if (s.kind === 'tap') strings.push(s.target);
        else if (s.kind === 'wait') strings.push(s.for);
        else if (s.kind === 'assert') strings.push(s.expect);
        else if (s.kind === 'repeat') visit(s.steps);
        else if (s.kind === 'if') { visit(s.then); visit(s.else); }
      }
    };
    visit(p.steps);
    return { id: p.id, copy: strings };
  });
}

export interface RouteGap {
  route: string;
  file: string;
  debug: boolean;
  /** 文案上和这个页面有交集的用例 */
  touchedBy: string[];
  /** 已存在对应的派生用例吗 */
  derived: boolean;
}

export function findGaps(routes: RouteFacts[], plans: Plan[]): RouteGap[] {
  // 派生用例自己不算「有人测过」——否则第二次以后永远全绿
  const cases = caseCopy(plans.filter((p) => !p.id.startsWith('RT-')));
  const unique = uniqueCopy(routes);
  return routes.map((r) => {
    const own = unique.get(r.route) ?? [];
    const touchedBy: string[] = [];
    for (const c of cases) {
      /*
       * 只有「这个页面独有」的文案出现在用例描述里，才算碰过这个页面。
       * 用全部文案判断会误伤：比如「用户名」在好几个页面都有，
       * 结果是每条登录用例都被算成「碰过 voice-test」。
       * 两个字以内的词（「暂停」「继续」）太泛，一律不参与匹配。
       */
      const hit = own.some(
        (text) => text.length >= 3 && c.copy.some((desc) => desc.includes(text)),
      );
      if (hit) touchedBy.push(c.id);
    }
    return {
      route: r.route,
      file: r.file,
      debug: r.debug,
      touchedBy,
      derived: plans.some((p) => p.id === deriveId(r.route)),
    };
  });
}

/** 每个路由独有的文案：只在这一个文件里出现的那些，用来看「这条用例是不是真碰过它」。 */
function uniqueCopy(routes: RouteFacts[]): Map<string, string[]> {
  const owners = new Map<string, Set<string>>();
  for (const r of routes) {
    for (const c of r.copy) {
      if (!owners.has(c)) owners.set(c, new Set());
      owners.get(c)!.add(r.route);
    }
  }
  const out = new Map<string, string[]>();
  for (const r of routes) {
    out.set(
      r.route,
      r.copy.filter((c) => (owners.get(c)?.size ?? 0) === 1),
    );
  }
  return out;
}

export function deriveId(route: string): string {
  const name = route === '' ? 'ROOT' : route.replace(/[/-]/g, '_').toUpperCase();
  return `RT-${name}`;
}

/**
 * 挑这一页的冒烟期望文案。
 *
 * 优先用「只有这一页才有」的文案——通用文案（「用户名」「取消」）在别的页面也有，
 * 拿它当期望等于没验。再排除条件性文案（失败提示、跳过提示），
 * 那些只在特定状态下出现，正常进页面看不到，会误报失败。
 */

/** 条件性文案：只在某个状态/出错时才出现，拿来当「页面正常打开」的期望会误报。 */
const CONDITIONAL =
  /失败|错误|异常|跳过|无法|不支持|未找到|找不到|不存在|没有|请|如果|否则|重启|回退|过期|超时|未开启/;
/** 瞬时文案：加载中/进行中的提示，页面渲染完就没了。 */
const TRANSIENT = /正在|加载中|…|\.\.\.$/;

function pickExpect(routes: RouteFacts[], route: string, n = 4): string[] {
  const unique = uniqueCopy(routes).get(route) ?? [];
  const all = routes.find((r) => r.route === route)?.copy ?? [];
  // 优先本页独有文案；不足两条就退回全部文案，但那样容易被别的页面也满足
  const base = (unique.length >= 2 ? unique : all).filter(
    (c) => c.length >= 3 && !CONDITIONAL.test(c),
  );
  // 稳定文案优先：先把瞬时文案（正在…/加载中…）排到后面
  const stable = base.filter((c) => !TRANSIENT.test(c));
  const transient = base.filter((c) => TRANSIENT.test(c));
  const pool = [...stable, ...transient];
  // 全部都是瞬时文案时，宁可只给一条 + 让审核时看 note，也不要凑数
  return pool.slice(0, n);
}

/** 本页的期望里有没有瞬时文案——有的话审核时要重点确认「页面稳定后还看得到吗」。 */
function hasTransient(routes: RouteFacts[], route: string): boolean {
  const unique = uniqueCopy(routes).get(route) ?? [];
  const all = routes.find((r) => r.route === route)?.copy ?? [];
  const base = (unique.length >= 2 ? unique : all).filter(
    (c) => c.length >= 3 && !CONDITIONAL.test(c),
  );
  return base.length > 0 && base.every((c) => TRANSIENT.test(c));
}

function titleOf(route: string): string {
  return route === '' ? '首页' : route;
}

function q(s: string): string {
  return `'${s.replace(/'/g, "''")}'`;
}

/**
 * 读现有 derived.yaml 的审核状态。
 *
 * 为什么重要：`--force` 会重写这个文件，如果不保留审核结果，
 * 人审核过一遍的成果每次重新派生就全没了，等于强迫重复劳动。
 */
function existingReview(): Map<
  string,
  { status: string; source?: string; note?: string; approvedAt?: string; approvedBy?: string }
> {
  if (!existsSync(OUT_FILE())) return new Map();
  try {
    const doc = yaml.load(readFileSync(OUT_FILE(), 'utf-8'));
    const out = new Map<
      string,
      { status: string; source?: string; note?: string; approvedAt?: string; approvedBy?: string }
    >();
    if (!Array.isArray(doc)) return out;
    for (const item of doc as Array<Record<string, unknown>>) {
      const id = typeof item?.id === 'string' ? item.id : '';
      const rv = item?.review as Record<string, unknown> | undefined;
      if (!id || !rv || typeof rv !== 'object') continue;
      out.set(id, {
        status: String(rv.status ?? 'draft'),
        ...(rv.source ? { source: String(rv.source) } : {}),
        ...(rv.note ? { note: String(rv.note) } : {}),
        ...(rv.approvedAt ? { approvedAt: String(rv.approvedAt) } : {}),
        ...(rv.approvedBy ? { approvedBy: String(rv.approvedBy) } : {}),
      });
    }
    return out;
  } catch {
    return new Map();
  }
}

export interface DeriveResult {
  routes: RouteFacts[];
  gaps: RouteGap[];
  generated: RouteGap[];
  skippedDebug: number;
  skippedExisting: number;
  skippedNoCopy: number;
  outFile: string;
}

/**
 * 生成 derived.yaml。
 *
 * 默认只生成「没有对应用例、而且抽得到文案」的路由；
 * 调试页（-test/demo/smoke/calib/diagnostics）默认跳过，用 includeDebug 打开。
 */
export function derive(
  plans: Plan[],
  opts: { includeDebug?: boolean; force?: boolean } = {},
): DeriveResult {
  const routes = scanRoutes();
  const gaps = findGaps(routes, plans);
  const unique = uniqueCopy(routes);
  const prior = existingReview();       // --force 重写时保留已经审过的结论
  const generated: RouteGap[] = [];
  let skippedDebug = 0;
  let skippedExisting = 0;
  let skippedNoCopy = 0;

  const blocks: string[] = [];
  for (const g of gaps) {
    if (g.debug && !opts.includeDebug) { skippedDebug += 1; continue; }
    if (g.derived && !opts.force) { skippedExisting += 1; continue; }
    const expect = pickExpect(routes, g.route);
    if (expect.length === 0) { skippedNoCopy += 1; continue; }

    const id = deriveId(g.route);
    const routeLabel = g.route === '' ? '/' : `/${g.route}`;
    // 没有本页独有文案时，期望只能退到通用文案，误判概率高——审核时要重点看这条
    const weak = (unique.get(g.route)?.length ?? 0) < 2;
    const prev = prior.get(id);
    const keepStatus =
      prev?.status === 'approved' || prev?.status === 'rejected' ? prev.status : 'draft';
    blocks.push(
      [
        `- id: ${id}`,
        `  title: ${q(`${titleOf(g.route)}（${routeLabel}）能正常打开`)}`,
        // 登录后的页面最多；登录页/同意页在登录前的状态里也能打开，
        // 深链打开不依赖登录态的话无妨，先统一用 logged-in 最稳
        `  precondition: logged-in`,
        `  order: normal`,
        `  review:`,
        `    status: ${keepStatus}`,
        `    source: code`,
        `    note: ${q(
          `依据 ${g.file} 生成；只验页面能打开、文案还在，不验业务` +
            (weak ? '；本页没有独有文案，期望较弱，审核时重点看' : '') +
            (hasTransient(routes, g.route) ? '；期望里只有瞬时文案（加载中之类），请确认页面稳定后还看得到' : ''),
        )}`,
        ...(keepStatus !== 'draft' && prev?.approvedAt
          ? [`    approvedAt: ${q(prev.approvedAt)}`]
          : []),
        ...(keepStatus !== 'draft' && prev?.approvedBy
          ? [`    approvedBy: ${q(prev.approvedBy)}`]
          : []),
        `  steps:`,
        `    - launch: true`,
        `    - check-route:`,
        `        route: ${q(g.route)}`,
        `        expect-any:`,
        ...expect.map((e) => `          - ${q(e)}`),
      ].join('\n'),
    );
    generated.push(g);
  }

  const header = [
    '# 由 `npx tsx src/cli.ts --derive` 从源码生成，请勿手改。',
    '# 要改：把需要的用例挪进 cases.yaml，这里的重复项会被自动跳过；',
    '# 或者直接删掉本文件重新生成。',
    '#',
    '# 这些用例只验「页面能打开、不白屏、关键文案还在」，不验业务对错。',
    '# 执行靠深链 + 控件树，不调模型，几秒钟一页。',
    '',
  ].join('\n');

  writeFileSync(
    OUT_FILE(),
    blocks.length ? `${header}\n${blocks.join('\n\n')}\n` : `${header}\n[]\n`,
    'utf-8',
  );
  return {
    routes,
    gaps,
    generated,
    skippedDebug,
    skippedExisting,
    skippedNoCopy,
    outFile: OUT_FILE(),
  };
}

/** 人看的缺口矩阵。 */
export function formatDerive(r: DeriveResult): string {
  const lines: string[] = [];
  const total = r.routes.length;
  const covered = r.gaps.filter((g) => g.touchedBy.length > 0).length;
  const derived = r.gaps.filter((g) => g.derived).length;
  lines.push(`页面路由：${total} 个（调试页 ${r.gaps.filter((g) => g.debug).length} 个）`);
  lines.push(
    `  已有用例碰过：${covered} 个 · 已派生冒烟：${derived} 个 · 本次新生成：${r.generated.length} 个`,
  );
  if (r.skippedDebug) lines.push(`  跳过调试页：${r.skippedDebug} 个（--include-debug 可纳入）`);
  if (r.skippedExisting) lines.push(`  已有派生用例：${r.skippedExisting} 个（--force 可覆盖重写）`);
  if (r.skippedNoCopy) lines.push(`  抽不到文案：${r.skippedNoCopy} 个（这些页面控件树里没中文，需要人写）`);
  lines.push('');
  lines.push('缺口矩阵（★ = 没有任何用例碰过）：');
  for (const g of r.gaps) {
    const mark = g.touchedBy.length ? ' ' : '★';
    const who = g.touchedBy.length ? g.touchedBy.slice(0, 4).join(',') : '—';
    const dbg = g.debug ? ' [调试页]' : '';
    lines.push(
      `  ${mark} ${(g.route === '' ? '/' : '/' + g.route).padEnd(24)}${dbg.padEnd(8)} ${who}`,
    );
  }
  lines.push('');
  lines.push(`已写入 ${r.outFile}`);
  lines.push('下一步：npx tsx src/cli.ts --review-page  然后逐条审核。');
  return lines.join('\n');
}

export function derivedExists(): boolean {
  return existsSync(OUT_FILE());
}
