#!/usr/bin/env node
/**
 * 视觉层 CLI。
 *
 * 三层各管一段：
 *   用例生成层  cases/*.yaml  →  plan.ts 编译校验
 *   执行层      run.ts        →  逐步交给 Midscene，不带守卫
 *   修正层      heal.ts       →  卡住才读日志、写数据修正、重跑（最多 3 轮）
 *
 * 用法：
 *   npx tsx src/cli.ts --list
 *   npx tsx src/cli.ts --dry-run                 # 只校验和打印计划，不碰设备
 *   npx tsx src/cli.ts --all --out ./last.json   # 跑完自动自愈最多 3 轮
 *   npx tsx src/cli.ts --cases AUTH-01 --no-heal # 只跑一遍不修
 *   npx tsx src/cli.ts --analyze ./last.json     # 只分析历史结果
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import { createAgent } from './agent.js';
import { setActiveTarget } from './adb.js';
import { analyzeRun } from './analyze.js';
import { readCooldown, remainingMinutes } from './cooldown.js';
import { generate, OUT_PATH, write as writeLocators } from './pagegen.js';
import { checkDrift, formatScan, scanSource } from './scan.js';
import { derive, formatDerive } from './derive.js';
import { hydrateEnv, missingConfig, VISION_DIR } from './config.js';
import { describeProject, listProjects } from './project.js';
import { runWithHeal } from './heal.js';
import type { Ctx } from './project-login.js';
import type { CaseMedia } from './media.js';
import {
  REVIEW_LABEL,
  SOURCE_LABEL,
  describeSteps,
  loadPlans,
  orderRank,
  unknownPlaceholders,
  type Plan,
} from './plan.js';
import { renderRunReport } from './report.js';
import { writeReviewPage, type ReviewResultFile } from './review.js';
import { applyReview } from './reviewApply.js';
import type { CaseResult, RunOutput } from './types.js';

function parseArgs(argv: string[]) {
  const out = {
    list: false,
    all: false,
    cases: [] as string[],
    out: '',
    device: process.env.MIDSCENE_ANDROID_DEVICE_ID || '',
    report: `ego-vision-${new Date().toISOString().replace(/[:.]/g, '-')}`,
    dryRun: false,
    heal: true,
    rounds: 3,
    video: true,
    ignoreCooldown: false,
    checkDrift: false,
    genPages: false,
    write: false,
    tier: 'full' as 'smoke' | 'full',
    html: '',
    analyze: '',
    apply: false,
    reviewPage: false,
    importReview: '',
    derive: false,
    useProject: '',
    includeDebug: false,
    force: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    const next = () => argv[++i] ?? '';
    if (a === '--list') out.list = true;
    else if (a === '--all') out.all = true;
    else if (a === '--cases') out.cases = next().split(',').map((s) => s.trim()).filter(Boolean);
    else if (a === '--out') out.out = next();
    else if (a === '--device') out.device = next();
    else if (a === '--report') out.report = next();
    else if (a === '--dry-run') out.dryRun = true;
    else if (a === '--heal') out.heal = true;
    else if (a === '--no-heal') out.heal = false;
    else if (a === '--rounds') out.rounds = Number.parseInt(next(), 10) || 3;
    else if (a === '--video') out.video = true;
    else if (a === '--no-video') out.video = false;
    else if (a === '--ignore-cooldown') out.ignoreCooldown = true;
    else if (a === '--check-drift') out.checkDrift = true;
    else if (a === '--gen-pages') out.genPages = true;
    else if (a === '--write') out.write = true;
    else if (a === '--tier') {
      const v = next();
      if (v !== 'smoke' && v !== 'full') throw new Error(`--tier 只能是 smoke 或 full，收到「${v}」`);
      out.tier = v;
    }
    else if (a === '--html') out.html = next();
    else if (a === '--analyze') out.analyze = next();
    else if (a === '--apply') out.apply = true;
    else if (a === '--review-page') out.reviewPage = true;
    else if (a === '--import-review') out.importReview = next();
    else if (a === '--derive') out.derive = true;
    else if (a === '--use-project') out.useProject = next();
    else if (a === '--include-debug') out.includeDebug = true;
    else if (a === '--force') out.force = true;
    else throw new Error(`未知参数：${a}`);
  }
  // 修正轮数上限写死 3：修不好的东西，第四轮也修不好
  out.rounds = Math.min(Math.max(out.rounds, 1), 3);
  return out;
}

function envOrThrow(name: string): string {
  const v = process.env[name]?.trim();
  if (!v) throw new Error(`缺环境变量 ${name}。在 vision/.env 里补上（可参考 .env.example）。`);
  return v;
}

function printConfigStatus(): boolean {
  // 先说是哪个项目：跑错项目比缺配置更隐蔽
  try {
    console.log(`项目：${describeProject()}`);
  } catch (e) {
    console.log(`项目：${e instanceof Error ? e.message : String(e)}`);
  }
  const missing = missingConfig();
  if (missing.length === 0) {
    console.log('配置：齐全');
    console.log(
      `  包名 ${process.env.EGO_APP_PACKAGE} ｜ 账号 ${process.env.EGO_USERNAME} ｜ ` +
        `设备 ${process.env.MIDSCENE_ANDROID_DEVICE_ID || '<自动选第一台>'} ｜ ` +
        `模型 ${process.env.MIDSCENE_MODEL_NAME}`,
    );
    return true;
  }
  console.log('配置：还缺这些，补齐之后才能真跑——');
  for (const m of missing) console.log(`  ${m.name.padEnd(24)} ${m.where}`);
  return false;
}

/** 加载用例；有校验问题就把所有问题一次说完，不跑到一半才炸。 */
function loadOrExit(): Plan[] {
  const { plans, errors } = loadPlans();
  const extra: string[] = [];
  for (const p of plans) {
    const unknown = unknownPlaceholders(p);
    if (unknown.length) extra.push(`${p.id}：未知占位符 ${unknown.join('、')}`);
  }
  const all = [...errors, ...extra];
  if (all.length) {
    console.error(`\n用例定义有问题（${all.length} 处），一条都不会跑：`);
    for (const e of all) console.error(`  - ${e}`);
    process.exit(2);
  }
  return plans;
}

function pick(plans: Plan[], cases: string[]): Plan[] {
  if (cases.length === 0) return plans;
  const unknown = cases.filter((c) => !plans.some((p) => p.id === c));
  if (unknown.length) {
    throw new Error(
      `这些用例不存在：${unknown.join(', ')}（现有：${plans.map((p) => p.id).join('、')}）`,
    );
  }
  return plans.filter((p) => cases.includes(p.id));
}

async function main(): Promise<void> {
  hydrateEnv();
  const args = parseArgs(process.argv.slice(2));

  // 源码 ↔ 用例 的一致性检查：不连设备、不花钱
  if (args.checkDrift) {
    const scan = scanSource();
    const drift = checkDrift(scan);
    console.log(formatScan(scan, drift));
    if (drift.missing.length) process.exitCode = 1;
    return;
  }

  // 从源码的 accessibilityLabel 生成 Appium 定位符
  if (args.genPages) {
    const r = generate();
    if (!r.changed) {
      console.log(`定位符已是最新：${r.pageCount} 个页面、${r.labelCount} 个 label`);
      if (r.missing.length) {
        console.log(`还有 ${r.missing.length} 个页面没埋 accessibilityLabel：`);
        for (const f of r.missing) console.log(`  - src/${f}`);
      }
      return;
    }
    if (args.write) {
      writeLocators(r);
      console.log(`已生成 ${OUT_PATH()}`);
      console.log(`  ${r.pageCount} 个页面、${r.labelCount} 个 label 的定位符已更新`);
      if (r.missing.length) {
        console.log(`  ⚠ ${r.missing.length} 个页面没埋 label，未纳入：${r.missing.join('、')}`);
      }
      return;
    }
    console.log('定位符与源码不一致（加 --write 写入）：');
    console.log(`  现有文件：${OUT_PATH()}`);
    process.exitCode = 1;
    return;
  }

  if (args.list) {
    for (const p of loadOrExit()) {
      const mark =
        orderRank(p) === 2 ? '  ⚠ 会破坏共享状态'
          : orderRank(p) === 1 ? '  ⚠ 耗额度' : '';
      const tier = p.policy?.tier === 'smoke' ? '[冒烟] ' : '[全量] ';
      const rv = p.review.status === 'approved' ? '' : `  ← ${REVIEW_LABEL[p.review.status]}`;
      console.log(`${tier}${p.id.padEnd(9)} ${p.precondition.padEnd(22)} ${p.title}${mark}${rv}`);
      if (p.policy?.why) console.log(`${' '.repeat(11)}↳ ${p.policy.why}`);
    }
    return;
  }

  // 只分析历史结果：不碰设备
  if (args.analyze) {
    await analyzeRun({ run: resolve(args.analyze), apply: args.apply });
    return;
  }

  // 切换项目：只重写一个绑定文件，不改任何代码
  if (args.useProject) {
    const name = args.useProject.trim();
    const all = listProjects();
    if (!all.includes(name)) {
      console.error(`没有这个项目：${name}（现有：${all.join('、') || '无'}）`);
      process.exitCode = 2;
      return;
    }
    const dir = resolve(VISION_DIR, 'projects', name, 'vision');
    if (!existsSync(dir)) {
      console.error(`项目 ${name} 下没有 vision/ 目录（放 appContext.ts / prepare.ts / login.ts / obstacles.project.ts）`);
      process.exitCode = 2;
      return;
    }
    const rel = `../projects/${name}/vision`;
    // 拆成四个小文件而不是一个：障碍表在模块加载时就要拼好，
    // 合成一个文件会让 obstacles → bindings → prepare → agent → bindings 成环。
    const targets: Array<[string, string, string]> = [
      [
        'project-appcontext.ts',
        '当前项目的 App 常识（页面结构、危险按钮）。',
        `export { APP_CONTEXT, ACT_CONTEXT } from '${rel}/appContext.js';`,
      ],
      [
        'project-obstacles.ts',
        '当前项目的专属障碍（更新弹窗、引导蒙层等）。',
        `export { PROJECT_OBSTACLES } from '${rel}/obstacles.project.js';`,
      ],
      [
        'project-prepare.ts',
        '当前项目的前置状态摆法。',
        `export { prepare } from '${rel}/prepare.js';`,
      ],
      [
        'project-login.ts',
        '当前项目的登录页判断与登录上下文。',
        `export { isOnLoginPage, type Ctx } from '${rel}/login.js';`,
      ],
    ];
    for (const [file, title, body] of targets) {
      const content =
        `/**\n * ${title}\n * **由 \`--use-project <项目名>\` 生成，不要手改。**\n */\n${body}\n`;
      writeFileSync(resolve(VISION_DIR, 'src', file), content, 'utf-8');
    }
    console.log(`已切换到项目：${name}`);
    console.log(`  绑定文件已重写（src/project-*.ts 共 ${targets.length} 个）`);
    console.log('  改完记得跑一次 tsc --noEmit 确认能编译。');
    return;
  }

  // 从源码派生结构性冒烟用例：不碰设备
  if (args.derive) {
    const { plans, errors } = loadPlans();
    if (errors.length) {
      console.log(`⚠ 当前用例有 ${errors.length} 处问题，派生照做，但这些要先修：`);
      for (const e of errors) console.log(`  - ${e}`);
      console.log('');
    }
    const r = derive(plans, { includeDebug: args.includeDebug, force: args.force });
    console.log(formatDerive(r));
    return;
  }

  // 生成审核页：不碰设备，不花钱
  if (args.reviewPage) {
    const all = loadOrExit();
    const { path, stats } = writeReviewPage(all);
    console.log(`审核页：${path}`);
    console.log(
      `  共 ${stats.total} 条：已审核 ${stats.approved}、未审核 ${stats.draft}、` +
        `已驳回 ${stats.rejected}；推测断言 ${stats.guess} 条，有风险提示 ${stats.flagged} 条`,
    );
    console.log('  在浏览器里逐条点「通过 / 驳回 / 待定」，再点右下角「导出审核结果」。');
    console.log(
      '  导出后写回：npx tsx src/cli.ts --import-review ~/Downloads/review-result.json',
    );
    return;
  }

  // 导入审核结果：只改数据，不碰设备
  if (args.importReview) {
    const file = resolve(args.importReview);
    if (!existsSync(file)) {
      console.error(`找不到审核结果文件：${file}`);
      process.exitCode = 2;
      return;
    }
    loadOrExit();                     // 当前文件得先是合法的，否则改了也是废的
    let doc: ReviewResultFile;
    try {
      doc = JSON.parse(readFileSync(file, 'utf-8')) as ReviewResultFile;
    } catch (e) {
      console.error(`审核结果不是合法 JSON：${e instanceof Error ? e.message : String(e)}`);
      process.exitCode = 2;
      return;
    }
    const r = applyReview(doc, process.env.EGO_REVIEWER ?? '');
    console.log(`导入审核结果：更新 ${r.updated.length} 条`);
    for (const f of r.files) console.log(`  写入 ${f}`);
    if (r.unknown.length) console.log(`  跳过（用例不存在）：${r.unknown.join('、')}`);
    for (const [id, why] of Object.entries(r.rejected)) console.log(`  ✗ ${id}：${why}`);
    // 再完整校验一遍，确认没把文件写坏
    const after = loadPlans();
    if (after.errors.length) {
      console.error(`\n写回后用例校验没通过（${after.errors.length} 处）：`);
      for (const e of after.errors) console.error(`  - ${e}`);
      process.exitCode = 1;
      return;
    }
    console.log('  写回后校验通过。');
    return;
  }

  const all = loadOrExit();
  const plans = pick(
    args.tier === 'smoke' ? all.filter((p) => p.policy?.tier === 'smoke') : all,
    args.cases,
  );
  if (plans.length === 0) {
    console.error(`\n没有 ${args.tier} 档的用例，检查 cases/policy.yaml 的 tier 设置。`);
    process.exitCode = 2;
    return;
  }


  if (args.dryRun) {
    printConfigStatus();
    console.log(`\n共 ${plans.length} 条用例，执行计划如下：\n`);
    for (const p of plans) {
      const rv = p.review.status === 'approved' ? '' : `  [${REVIEW_LABEL[p.review.status]}]`;
      console.log(`${p.id} ${p.title}   [前置：${p.precondition}]${rv}`);
      if (p.review.status !== 'approved') {
        console.log(`   ↳ 断言来源：${SOURCE_LABEL[p.review.source]}，跑出来的结果需要人工确认`);
      }
      if (orderRank(p) === 2) {
        console.log(`   ⚠ 会破坏共享状态：${p.policy?.why ?? '—'}`);
        console.log(`     排在最后跑，跑完环境冷却 ${p.policy?.cooldownMinutes ?? 0} 分钟`);
      } else if (orderRank(p) === 1) {
        console.log(`   ⚠ 耗额度：${p.policy?.why ?? '—'}（排在普通用例之后）`);
      }
      for (const line of describeSteps(p.steps)) console.log(`   ${line}`);
      console.log('');
    }
    return;
  }

  if (plans.length > 3) {
    console.log(
      `⚠ 连续跑 ${plans.length} 条视觉用例：每个界面动作都要调一次模型，按次计费。\n` +
        `  8 条一轮约 10~15 分钟；开启自愈时最多再跑 2 轮（只重跑卡住的）。\n`,
    );
  }
  const unreviewed = plans.filter((p) => p.review.status !== 'approved').length;
  if (unreviewed > 0) {
    // 不拦：用户明确要求「都跑，但报告里标未审核」
    console.log(
      `⚠ 其中有 ${unreviewed} 条没经过人工审核，结果只作参考。\n` +
        `  生成审核页：npx tsx src/cli.ts --review-page\n`,
    );
  }

  const missing = missingConfig();
  if (missing.length) {
    printConfigStatus();
    process.exitCode = 2;
    return;
  }

  // 上一轮刚跑过会锁账号的用例，现在跑只会得到一堆「登录失败」
  const cd = readCooldown();
  if (cd && !args.ignoreCooldown) {
    console.error(
      `\n账号还在冷却（还剩约 ${remainingMinutes(cd)} 分钟）：${cd.caseId} 跑过，${cd.why}。\n` +
        `现在跑只会得到一串「登录失败」，看着像产品坏了。\n` +
        `等冷却结束再跑，或用 --ignore-cooldown 强制跑。`,
    );
    process.exitCode = 2;
    return;
  }

  const ctx: Ctx = {
    packageName: envOrThrow('EGO_APP_PACKAGE'),
    username: envOrThrow('EGO_USERNAME'),
    password: envOrThrow('EGO_PASSWORD'),
  };
  const vars = { username: ctx.username, password: ctx.password, package: ctx.packageName };

  console.log(`设备：${args.device || '<自动选第一台>'}  包名：${ctx.packageName}`);
  console.log(`模型：${process.env.MIDSCENE_MODEL_NAME}  用例：${plans.map((p) => p.id).join(', ')}`);
  console.log(
    `自愈：${args.heal ? `开（最多 ${args.rounds} 轮）` : '关'}  录屏：${args.video ? '开' : '关'}`,
  );
  if (args.video) {
    console.log('  提示：录屏会把测试账号和密码输入过程一起录进去，带视频的报告只可内部使用。');
  }
  console.log('');

  // 报告路径要在跑之前定下来：录屏文件要相对它算路径
  const mediaDir = resolve(VISION_DIR, 'midscene_run');
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const htmlPath = args.html
    ? resolve(args.html)
    : resolve(mediaDir, 'reports', `run-${stamp}.html`);
  const reportDir = dirname(htmlPath);
  const media = new Map<string, CaseMedia>();

  const { agent, deviceId } = await createAgent({
    deviceId: args.device,
    reportName: args.report,
  });
  ctx.deviceId = deviceId;
  setActiveTarget(deviceId, ctx.packageName);

  const started = Date.now();
  let outcome;
  try {
    outcome = await runWithHeal({
      agent,
      plans,
      vars,
      ctx,
      deviceId,
      maxRounds: args.heal ? args.rounds : 1,
      video: args.video,
      reportDir,
      mediaDir,
      media,
    });
  } finally {
    await agent.destroy();
  }

  // 每条用例取「最后一次」的结果：中途修好并重跑过的，以重跑为准
  const merged = new Map<string, CaseResult>();
  for (const round of outcome.rounds) {
    for (const r of round.results) merged.set(r.caseId, r);
  }
  const cases = plans.map((p) => merged.get(p.id)).filter((c): c is CaseResult => Boolean(c));

  const output: RunOutput = {
    generatedAt: new Date().toISOString(),
    deviceId,
    packageName: ctx.packageName,
    modelName: process.env.MIDSCENE_MODEL_NAME ?? '',
    tier: args.tier,
    cases,
  };

  // 固定入口：不管谁触发（手动 / 钩子 / CI），都只需认这两个文件
  const latestJson = resolve(mediaDir, 'last-run.json');
  mkdirSync(dirname(latestJson), { recursive: true });
  writeFileSync(latestJson, JSON.stringify(output, null, 2), 'utf-8');

  if (args.out) {
    const path = resolve(args.out);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify(output, null, 2), 'utf-8');
    console.log(`\n结果已写入：${path}`);
  }

  mkdirSync(dirname(htmlPath), { recursive: true });
  const execIndex = new Map<string, number>();
  outcome.rounds[0]?.results.forEach((r, i) => execIndex.set(r.caseId, i + 1));
  const tier = new Map<string, string>();
  const review = new Map<string, { status: string; source?: string }>();
  for (const p of plans) {
    tier.set(p.id, p.policy?.order ?? 'normal');
    review.set(p.id, { status: p.review.status, source: p.review.source });
  }
  const meta = { execIndex, tier, review };

  writeFileSync(htmlPath, renderRunReport(output, [], outcome.rounds, media, meta), 'utf-8');

  const failed = cases.filter((c) => c.status === 'failed').length;
  const passed = cases.filter((c) => c.status === 'passed').length;
  const skipped = cases.filter((c) => c.status === 'skipped').length;
  console.log(
    `\n汇总：共 ${cases.length} 条，通过 ${passed}，失败 ${failed}，跳过 ${skipped}，` +
      `耗时 ${((Date.now() - started) / 60000).toFixed(1)} 分钟`,
  );
  console.log(`自愈：${outcome.rounds.length} 轮，${outcome.stoppedBecause}`);
  // latest.html 永远指向最近一次结果，报告路径不用记
  const latestHtml = resolve(mediaDir, 'reports', 'latest.html');
  writeFileSync(latestHtml, renderRunReport(output, [], outcome.rounds, media, meta), 'utf-8');
  console.log(`报告（HTML）：${htmlPath}`);
  console.log(`最新报告：${latestHtml}`);
  console.log(`结果 JSON：${latestJson}`);
  if (failed > 0) process.exitCode = 1;
}

main().catch((e) => {
  console.error(`\n[vision] 启动失败：${e instanceof Error ? e.message : String(e)}`);
  process.exit(2);
});
