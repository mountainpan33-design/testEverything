/**
 * 结果报告（自包含 HTML）。
 *
 * 为什么是 HTML：报告是给人看、给开发看的，要能直接双击打开、能截图贴到群里。
 * 所以 CSS 全内联、不引任何 CDN——内网和墙外都打不开外链。
 *
 * 为什么不嵌截图：Midscene 的 html 报告里是完整截图，含测试账号和密码，
 * 单份能到 100MB+，不能外发也不适合当交付物。这里只放文字证据链，
 * 需要看截图时按页面底部给的路径自己打开。
 */
import type { AnalysisEntry } from './analyze.js';
import type { HealRound } from './heal.js';
import type { CaseMedia } from './media.js';
import type { CaseResult, RunOutput } from './types.js';

const ROOT_CAUSE_LABEL: Record<string, string> = {
  'obstacle-missing': '环境障碍（弹窗/系统界面遮挡）',
  'input-truncated': '输入被截断',
  'assertion-wrong': '断言写错',
  'precondition-wrong': '前置状态没摆对',
  'product-defect': '疑似产品缺陷',
  flaky: '偶发（时序）',
  unknown: '证据不足',
};

function esc(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function statusChip(c: CaseResult): string {
  if (c.status === 'passed') return '<span class="chip ok">通过</span>';
  if (c.status === 'skipped') return '<span class="chip skip">跳过</span>';
  return '<span class="chip bad">失败</span>';
}

function assertionsTable(c: CaseResult): string {
  if (!c.assertions.length) return '';
  const rows = c.assertions
    .map(
      (a) => `<tr class="${a.ok ? 'ok-row' : 'bad-row'}">
      <td>${a.ok ? '✓' : '✗'}</td>
      <td class="mono">${esc(a.rule)}</td>
      <td>${esc(a.expected)}</td>
      <td>${esc(a.actual)}</td>
    </tr>`,
    )
    .join('\n');
  return `<table class="assert">
    <thead><tr><th></th><th>规则</th><th>期望</th><th>实际</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function analysisBlock(e: AnalysisEntry): string {
  if (!e.analysis) {
    return `<div class="analysis muted">自愈分析：${esc(e.note ?? '未执行')}</div>`;
  }
  const a = e.analysis;
  const label = ROOT_CAUSE_LABEL[a.rootCause] ?? a.rootCause;
  const conf = Math.round((a.confidence ?? 0) * 100);
  const evidence = (a.evidence ?? [])
    .map((x) => `<li>${esc(x)}</li>`)
    .join('');
  const fix = a.fix?.obstacle
    ? `<pre class="code">${esc(JSON.stringify(a.fix.obstacle, null, 2))}</pre>`
    : a.fix?.assertion
      ? `<p class="mono">${esc(a.fix.assertion.from)} → ${esc(a.fix.assertion.to)}</p>`
      : '';
  const applied = e.applied
    ? `<p class="applied">已自动修复：${esc(e.applyReason ?? '')}</p>`
    : `<p class="muted">未自动修复：${esc(e.applyReason ?? '')}</p>`;

  return `<div class="analysis">
    <div class="line"><span class="lbl">根因</span><strong>${esc(label)}</strong>
      <span class="conf">置信度 ${conf}%</span>
      <span class="chip ${a.rootCause === 'product-defect' ? 'bad' : 'warn'}">${esc(a.rootCause)}</span>
    </div>
    <p class="reason">${esc(a.reasoning)}</p>
    ${evidence ? `<ul class="evidence">${evidence}</ul>` : ''}
    ${a.fix?.note ? `<p class="note">建议：${esc(a.fix.note)}</p>` : ''}
    ${fix}
    ${applied}
    <details><summary>完整失败现场</summary><pre class="digest">${esc(e.digest)}</pre></details>
  </div>`;
}

/** 自愈过程：每一轮跑了什么、改了什么、为什么这么改。 */
function healBlock(rounds: HealRound[]): string {
  if (rounds.length === 0) return '';
  const rows = rounds
    .map((r) => {
      const passed = r.results.filter((c) => c.status === 'passed').length;
      const failed = r.results.filter((c) => c.status === 'failed').length;
      const skipped = r.results.filter((c) => c.status === 'skipped').length;
      const fixes = r.fixes.length
        ? r.fixes
            .map(
              (f) => `<li>
                <span class="cid mono">${esc(f.caseId)}</span>
                <span class="chip ${f.applied ? 'ok' : 'warn'}">${f.applied ? '已合并' : '未合并'}</span>
                <strong>${esc(ROOT_CAUSE_LABEL[f.rootCause] ?? f.rootCause)}</strong>
                <div class="reason">${esc(f.reasoning)}</div>
                <div class="muted">处理：${esc(f.action)}</div>
                ${f.diff ? `<pre class="code diff">${esc(f.diff)}</pre>` : ''}
              </li>`,
            )
            .join('')
        : '<li class="muted">这一轮没有产生修正</li>';
      return `<tr>
        <td>第 ${r.round} 轮</td>
        <td>${r.results.length}</td>
        <td>${passed} / ${failed} / ${skipped}</td>
        <td><ul class="fixlist">${fixes}</ul></td>
      </tr>`;
    })
    .join('');

  return `<div class="heal">
    <h2>自愈过程（最多 3 轮）</h2>
    <table class="healtable">
      <thead><tr><th>轮次</th><th>跑了</th><th>过/挂/跳</th><th>这一轮做了什么</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="muted">修正直接写进用例（<span class="mono">cases/cases.yaml</span>），
    但必须重跑那一条并跑通才会合并；没跑通自动还原。判为产品缺陷的不重试。</p>
  </div>`;
}

/** 现场媒体：失败截图内联（报告仍是单文件），录屏用相对路径引用（太大）。 */
function mediaBlock(m: CaseMedia | undefined): string {
  if (!m) return '';
  const parts: string[] = [];
  if (m.screenshot) {
    parts.push(`<details class="shotwrap" open>
      <summary>失败截图</summary>
      <img class="shot" src="${esc(m.screenshot)}" alt="失败时刻的屏幕">
    </details>`);
  }
  if (m.video) {
    parts.push(`<div class="videowrap">
      <div class="lbl">过程录屏${m.videoTruncated ? '（超过 180s，被截断）' : ''}</div>
      <video class="clip" controls preload="metadata" src="${esc(m.video)}"></video>
      <div class="muted">文件：<span class="mono">${esc(m.video)}</span></div>
    </div>`);
  }
  return parts.length ? `<div class="media">${parts.join('')}</div>` : '';
}

/** 执行顺序与档位，用于在报告里标出「它是第几个跑的、属于哪一档」。 */
export interface RunMeta {
  /** 用例编号 → 执行序号（从 1 开始），按实际执行顺序 */
  execIndex?: Map<string, number>;
  /** 用例编号 → 档位 normal / costly / destructive */
  tier?: Map<string, string>;
  /** 用例编号 → 审核状态 draft / approved / rejected；不写就当未审核 */
  review?: Map<string, { status: string; source?: string }>;
}

const TIER_LABEL: Record<string, string> = {
  normal: '普通',
  costly: '耗额度',
  destructive: '破坏共享状态',
};

const REVIEW_CHIP: Record<string, string> = {
  draft: '<span class="chip unreviewed">未审核</span>',
  rejected: '<span class="chip rejected">已驳回</span>',
};

export function renderRunReport(
  run: RunOutput,
  entries: AnalysisEntry[] = [],
  rounds: HealRound[] = [],
  media?: Map<string, CaseMedia>,
  meta?: RunMeta,
): string {
  const passed = run.cases.filter((c) => c.status === 'passed').length;
  const failed = run.cases.filter((c) => c.status === 'failed').length;
  const skipped = run.cases.filter((c) => c.status === 'skipped').length;
  const verdict =
    failed === 0
      ? '<div class="verdict ok">全部通过</div>'
      : `<div class="verdict bad">${failed} 条失败</div>`;

  const byId = new Map(entries.map((e) => [e.caseId, e]));

  const unreviewed = run.cases.filter(
    (c) => (meta?.review?.get(c.caseId)?.status ?? 'draft') !== 'approved',
  ).length;
  const banner =
    unreviewed > 0
      ? `<div class="banner"><strong>${unreviewed} / ${run.cases.length} 条用例还没经过人工审核。</strong>
         生成出来的断言是推测，绿了不代表产品对——先用
         <span class="mono">npx tsx src/cli.ts --review-page</span> 过一遍再看结论。</div>`
      : '';

  const cards = run.cases
    .map((c) => {
      const e = byId.get(c.caseId);
      const diag = c.diagnosis
        ? `<div class="diag">
             <span class="lbl">现场</span>${esc(c.diagnosis.detail)}
             <br><span class="lbl">归因</span><strong>${esc(c.diagnosis.attribution)}</strong>
             <span class="muted">（屏幕=${esc(c.diagnosis.screen)}）</span>
             <br><span class="lbl">建议</span>${esc(c.diagnosis.suggestion)}
           </div>`
        : '';
      const idx = meta?.execIndex?.get(c.caseId);
      const tier = meta?.tier?.get(c.caseId) ?? 'normal';
      const rv = meta?.review?.get(c.caseId);
      const rvChip = REVIEW_CHIP[rv?.status ?? 'draft'] ?? REVIEW_CHIP.draft;
      const orderBits =
        (idx ? `<span class="order no">#${idx}</span>` : '') +
        `<span class="order tier-${tier}">${TIER_LABEL[tier] ?? tier}</span>` +
        rvChip;
      return `<section class="case ${c.status}">
        <header>
          ${orderBits}
          ${statusChip(c)}
          <span class="cid mono">${esc(c.caseId)}</span>
          <span class="title">${esc(c.title ?? '')}</span>
          <span class="dur">${(c.durationMs / 1000).toFixed(1)}s</span>
        </header>
        ${c.error ? `<p class="err">${esc(c.error)}</p>` : ''}
        ${diag}
        ${assertionsTable(c)}
        ${mediaBlock(media?.get(c.caseId))}
        ${c.status === 'failed' && e ? analysisBlock(e) : ''}
        ${c.skipReason ? `<p class="muted">跳过原因：${esc(c.skipReason)}</p>` : ''}
      </section>`;
    })
    .join('\n');

  const causes = new Map<string, number>();
  for (const e of entries) {
    const k = e.analysis?.rootCause ?? 'unknown';
    causes.set(k, (causes.get(k) ?? 0) + 1);
  }
  const causeRows = [...causes.entries()]
    .map(([k, n]) => `<li><strong>${esc(ROOT_CAUSE_LABEL[k] ?? k)}</strong> — ${n} 条</li>`)
    .join('');

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>视觉层测试报告 ${esc(run.generatedAt)}</title>
<style>
:root { color-scheme: light }
* { box-sizing: border-box }
body { margin: 0; padding: 28px 20px 60px; background: #f6f7f9; color: #1c2024;
  font: 15px/1.65 -apple-system, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif }
.wrap { max-width: 1000px; margin: 0 auto }
h1 { font-size: 22px; margin: 0 0 6px }
.meta { color: #5b6472; font-size: 13px; margin-bottom: 18px }
.meta span { margin-right: 16px }
.tiles { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px }
.tile { background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; padding: 10px 16px; min-width: 96px }
.tile b { display: block; font-size: 22px; line-height: 1.2 }
.tile span { color: #5b6472; font-size: 12px }
.verdict { display: inline-block; padding: 6px 14px; border-radius: 999px; font-weight: 600; margin-bottom: 18px }
.verdict.ok { background: #e7f6ec; color: #12663a }
.verdict.bad { background: #fdeaea; color: #a02020 }
.causes { background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; padding: 12px 18px; margin-bottom: 20px }
.causes h2 { font-size: 15px; margin: 6px 0 8px }
.causes ul { margin: 0; padding-left: 20px }
.heal { background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; padding: 12px 18px; margin-bottom: 20px }
.heal h2 { font-size: 15px; margin: 6px 0 10px }
table.healtable { width: 100%; border-collapse: collapse; font-size: 14px }
table.healtable th { text-align: left; color: #7a828d; font-weight: 500; font-size: 12px; padding: 4px 8px; border-bottom: 1px solid #eceef1; white-space: nowrap }
table.healtable td { padding: 8px; border-bottom: 1px solid #f2f4f6; vertical-align: top }
table.healtable td:nth-child(1), table.healtable td:nth-child(2) { white-space: nowrap }
ul.fixlist { margin: 0; padding-left: 18px }
ul.fixlist li { margin-bottom: 8px }
.case { background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; padding: 14px 16px; margin-bottom: 14px }
.case.failed { border-left: 4px solid #d64545 }
.case.passed { border-left: 4px solid #2f9e5f }
.case.skipped { border-left: 4px solid #c8a020 }
.case header { display: flex; align-items: center; gap: 10px; flex-wrap: wrap }
.cid { font-weight: 600 }
.title { color: #33383f }
.dur { margin-left: auto; color: #5b6472; font-size: 13px }
.order { font-size: 11px; color: #5b6472; background: #f1f3f5; border-radius: 4px; padding: 1px 6px }
.order.no { font-family: ui-monospace,Menlo,monospace; color: #33518f; background: #eef2fb }
.order.tier-costly { background: #fff4e6; color: #8a4b00 }
.order.tier-destructive { background: #fdeaea; color: #a02020 }
.chip { font-size: 12px; padding: 2px 9px; border-radius: 999px; background: #eef0f3; color: #42474e }
.chip.ok { background: #e7f6ec; color: #12663a }
.chip.bad { background: #fdeaea; color: #a02020 }
.chip.skip { background: #fdf6e3; color: #7a5c00 }
.chip.unreviewed { background: #fff8e6; color: #8a4b00; border: 1px solid #f0dca8 }
.chip.rejected { background: #fdeaea; color: #a02020 }
.banner { background: #fff8e6; border: 1px solid #f0dca8; border-radius: 8px;
  padding: 10px 14px; font-size: 13.5px; color: #7a5300; margin-bottom: 16px }
.banner strong { color: #a04000 }
.chip.warn { background: #fff3e0; color: #8a4b00 }
.err { color: #a02020; margin: 8px 0 0; font-size: 14px }
.diag { background: #fafbfc; border: 1px solid #eceef1; border-radius: 8px; padding: 10px 12px; margin: 10px 0 0; font-size: 14px }
.lbl { display: inline-block; min-width: 34px; color: #7a828d; font-size: 12px; margin-right: 6px }
table.assert { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 14px }
table.assert th { text-align: left; color: #7a828d; font-weight: 500; font-size: 12px; padding: 4px 8px; border-bottom: 1px solid #eceef1 }
table.assert td { padding: 6px 8px; border-bottom: 1px solid #f2f4f6; vertical-align: top }
table.assert th:first-child, table.assert td:first-child { width: 24px }
table.assert td:nth-child(2) { white-space: nowrap }
.ok-row td:first-child { color: #2f9e5f }
.bad-row td:first-child { color: #d64545 }
.analysis { margin-top: 14px; padding: 12px 14px; background: #fbfbfc; border: 1px dashed #dfe3e8; border-radius: 8px }
.media { margin-top: 14px }
.shotwrap summary { cursor: pointer; color: #5b6472; font-size: 13px; margin-bottom: 6px }
img.shot { display: block; width: 100%; max-width: 380px; border: 1px solid #e3e6ea; border-radius: 8px; background: #fff }
.videowrap { margin-top: 12px }
video.clip { display: block; width: 100%; max-width: 480px; border: 1px solid #e3e6ea; border-radius: 8px; background: #000 }
.analysis .line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap }
.conf { color: #5b6472; font-size: 13px }
.reason { margin: 8px 0 }
ul.evidence { margin: 8px 0; padding-left: 20px; color: #33383f; font-size: 14px }
ul.evidence li { margin-bottom: 4px }
.note { color: #42474e; font-size: 14px }
.applied { color: #12663a; font-size: 14px; margin: 8px 0 0 }
.muted { color: #7a828d; font-size: 13px }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace }
pre.code { background: #f2f4f6; border-radius: 6px; padding: 10px; overflow: auto; font-size: 12.5px }
pre.code.diff { background: #f7fbf8; border: 1px solid #dbeade; margin: 6px 0 0; white-space: pre-wrap }
pre.digest { background: #f7f8fa; border-radius: 6px; padding: 10px; overflow: auto;
  font-size: 12px; max-height: 420px; white-space: pre-wrap }
details summary { cursor: pointer; color: #5b6472; font-size: 13px; margin-top: 8px }
footer { color: #8b929c; font-size: 12px; margin-top: 28px; line-height: 1.8 }
</style>
</head>
<body>
<div class="wrap">
  <h1>视觉层测试报告</h1>
  <div class="meta">
    <span>生成于 ${esc(run.generatedAt)}</span>
    ${run.tier ? `<span>档位 ${esc(run.tier === 'smoke' ? '冒烟' : '全量')}</span>` : ''}
    <span>设备 ${esc(run.deviceId)}</span>
    <span>包名 ${esc(run.packageName)}</span>
    <span>模型 ${esc(run.modelName)}</span>
  </div>

  ${banner}
  ${verdict}
  <div class="tiles">
    <div class="tile"><b>${run.cases.length}</b><span>用例总数</span></div>
    <div class="tile"><b>${passed}</b><span>通过</span></div>
    <div class="tile"><b>${failed}</b><span>失败</span></div>
    <div class="tile"><b>${skipped}</b><span>跳过</span></div>
  </div>

  ${causeRows ? `<div class="causes"><h2>失败根因分布</h2><ul>${causeRows}</ul></div>` : ''}

  ${healBlock(rounds)}

  ${cards}

  <footer>
    报告自包含，截图已内联。<strong>含测试账号与操作过程的截图/录屏，只可内部使用，不要外发。</strong><br>
    录屏文件在报告同级目录的 <span class="mono">../videos/</span> 下，移动报告时一起带走；<br>
    需要逐步截图时看 <span class="mono">vision/midscene_run/report/*.html</span>。
  </footer>
</div>
</body>
</html>`;
}
