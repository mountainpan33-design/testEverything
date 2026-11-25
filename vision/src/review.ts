/**
 * 用例审核页（自包含 HTML）。
 *
 * 为什么需要审核这一步：用例可以自动生成，但「什么算对」代码不知道。
 * 生成出来的断言是推测，没人看过就当正式结果用，等于把 bug 当规范记下来。
 *
 * 流程：
 *   1. `--review-page` 生成 cases/review.html
 *   2. 人在浏览器里逐条点「通过 / 驳回 / 待定」
 *   3. 点「导出」下载 review-result.json
 *   4. `--import-review review-result.json` 写回 cases/*.yaml
 *
 * 为什么是导出文件而不是页面直接写回：浏览器打开的本地文件没有写权限。
 * 导出再导入多一步，但可靠、可留痕、能进评审记录。
 */
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { casesDir } from './project.js';
import {
  describeSteps,
  REVIEW_LABEL,
  SOURCE_LABEL,
  type Plan,
  type ReviewSource,
  type ReviewStatus,
} from './plan.js';

// 审核页跟着用例走：用例在哪个项目目录，页就写到哪
const REVIEW_HTML = () => resolve(casesDir(), 'review.html');

function esc(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** 嵌进 <script> 的 JSON：把 < 转义掉，避免用例文案里出现 </script> 把页面切断。 */
function jsonForScript(v: unknown): string {
  return JSON.stringify(v).replace(/</g, '\\u003c').replace(/>/g, '\\u003e');
}

/** 递归把嵌套在 if / repeat 里的断言捞出来——只看顶层会误报「无断言」。 */
function assertsOf(steps: Plan['steps']): Array<{ rule: string; expect: string; fatal: boolean }> {
  const out: Array<{ rule: string; expect: string; fatal: boolean }> = [];
  for (const s of steps) {
    if (s.kind === 'assert') out.push({ rule: s.rule, expect: s.expect, fatal: s.fatal });
    else if (s.kind === 'repeat') out.push(...assertsOf(s.steps));
    else if (s.kind === 'if') out.push(...assertsOf(s.then), ...assertsOf(s.else));
  }
  return out;
}

/** 断言写得有没有毛病——这几条是审核时最该看的东西。 */
function flagsFor(p: Plan): string[] {
  const flags: string[] = [];
  const asserts = assertsOf(p.steps);
  const hasCheckRoute = p.steps.some((s) => s.kind === 'check-route');

  if (asserts.length === 0 && hasCheckRoute) {
    // check-route 自带「页面能打开 + 文案在」的判定，不需要额外的断言步骤
    return flags;
  }
  if (asserts.length === 0) {
    flags.push('没有任何断言：跑起来永远不会红，等于没测');
    return flags;
  }
  // 注：fatal 只控制「失败后要不要继续跑」，不控制成败——
  // 软断言失败一样会把用例判为 failed（recorder.finish 里统一看 assertions）。
  // 所以「没有 fatal」不是缺陷，不在这里报警。
  const negative = asserts.filter((a) =>
    /看不到|没有看到|没有出现|不显示|不存在|已消失|消失了/.test(a.expect),
  );
  if (negative.length && negative.length === asserts.length) {
    flags.push('只有负向断言：通知中心、锁屏、黑屏也能满足它，要补一条正向主断言');
  }
  // 标题里用「」写明的承诺，断言里必须真的验它。不用泛词（显示/进入）判断，
  // 那样 ONB-01 这种「首次登录进入 consent 同意页」会全部误报。
  const promised = [...p.title.matchAll(/「([^」]{2,20})」/g)].map((m) => m[1]!);
  const missingPromise = promised.filter(
    (word) => !asserts.some((a) => a.expect.includes(word)),
  );
  if (missingPromise.length) {
    flags.push(
      `标题里承诺的「${missingPromise.join('、')}」没有出现在任何断言里——先读实现再写断言`,
    );
  }
  if (p.review.source === 'guess') {
    flags.push('断言是推测出来的，没有出处：请对着实现或需求确认「应该」是什么');
  }
  return flags;
}

export interface ReviewPageStats {
  total: number;
  approved: number;
  draft: number;
  rejected: number;
  guess: number;
  flagged: number;
}

export function reviewStats(plans: Plan[]): ReviewPageStats {
  return {
    total: plans.length,
    approved: plans.filter((p) => p.review.status === 'approved').length,
    draft: plans.filter((p) => p.review.status === 'draft').length,
    rejected: plans.filter((p) => p.review.status === 'rejected').length,
    guess: plans.filter((p) => p.review.source === 'guess').length,
    flagged: plans.filter((p) => flagsFor(p).length > 0).length,
  };
}

interface Item {
  id: string;
  title: string;
  precondition: string;
  order: string;
  tier: string;
  source: string;
  status: string;
  note: string;
  why: string;
  steps: string[];
  asserts: Array<{ rule: string; expect: string; fatal: boolean }>;
  flags: string[];
}

export function buildReviewHtml(plans: Plan[]): string {
  const items: Item[] = plans.map((p) => ({
    id: p.id,
    title: p.title,
    precondition: p.precondition,
    order: p.policy?.order ?? p.policy?.kind ?? 'normal',
    tier: p.policy?.tier ?? '',
    source: p.review.source,
    status: p.review.status,
    note: p.review.note ?? '',
    why: p.policy?.why ?? '',
    steps: describeSteps(p.steps),
    asserts: assertsOf(p.steps),
    flags: flagsFor(p),
  }));
  const stats = reviewStats(plans);
  const ORDER_LABEL: Record<string, string> = {
    normal: '普通',
    costly: '耗额度',
    destructive: '破坏共享',
  };

  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>用例审核（${stats.total} 条）</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;padding:24px 18px 96px;background:#f5f7fb;color:#18222d;
  font:15px/1.6 -apple-system,"PingFang SC",system-ui,sans-serif}
.wrap{max-width:1020px;margin:auto}
h1{font-size:23px;margin:0 0 4px}
.sub{color:#63758b;font-size:13px;margin-bottom:16px}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.stat{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:8px 14px;min-width:84px}
.stat b{display:block;font-size:20px;line-height:1.2}
.stat span{color:#5b6472;font-size:12px}
.stat.bad b{color:#a02020}.stat.warn b{color:#8a4b00}.stat.ok b{color:#12663a}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.filters button{border:1px solid #d8dde4;background:#fff;color:#3d4a5c;border-radius:99px;
  padding:5px 13px;font-size:13px;cursor:pointer}
.filters button.on{background:#33518f;border-color:#33518f;color:#fff}
.card{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin-bottom:12px}
.card.s-approved{border-left:4px solid #2f9e5f}
.card.s-rejected{border-left:4px solid #d64545;opacity:.72}
.head{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.cid{font-family:ui-monospace,Menlo,monospace;font-weight:700;font-size:14px}
.title{font-weight:500}
.tag{font-size:11px;border-radius:4px;padding:1px 6px;background:#f1f3f5;color:#5b6472;white-space:nowrap}
.tag.order-costly{background:#fff4e6;color:#8a4b00}
.tag.order-destructive{background:#fdeaea;color:#a02020}
.tag.src-guess{background:#fdf0e6;color:#a34c00;font-weight:600}
.tag.src-code{background:#eef2fb;color:#33518f}
.tag.src-doc{background:#e7f6ec;color:#12663a}
.tag.src-human{background:#f1f3f5;color:#5b6472}
.flag{background:#fff8e6;border:1px solid #f0dca8;border-radius:6px;padding:6px 10px;
  font-size:13px;color:#7a5300;margin:6px 0}
.flag strong{color:#a04000}
.block{margin-top:10px}
.block h4{font-size:12px;color:#7a828d;font-weight:500;margin:0 0 4px}
ol.steps{margin:0;padding-left:20px;color:#33383f;font-size:13.5px}
ol.steps li{margin-bottom:2px}
table.asserts{width:100%;border-collapse:collapse;font-size:13.5px}
table.asserts th{text-align:left;color:#7a828d;font-weight:500;font-size:11.5px;
  padding:3px 6px;border-bottom:1px solid #eceef1}
table.asserts td{padding:5px 6px;border-bottom:1px solid #f2f4f6;vertical-align:top}
table.asserts td.rule{font-family:ui-monospace,Menlo,monospace;white-space:nowrap;color:#33518f}
.fatal{font-size:11px;color:#a02020}
.verdict{display:flex;gap:6px;align-items:center;margin-top:12px;flex-wrap:wrap}
.verdict button{border:1px solid #d8dde4;background:#fff;border-radius:7px;padding:6px 14px;
  font-size:13.5px;cursor:pointer;color:#3d4a5c}
.verdict button.ok.on{background:#e7f6ec;border-color:#7cc294;color:#12663a;font-weight:600}
.verdict button.no.on{background:#fdeaea;border-color:#e79b9b;color:#a02020;font-weight:600}
.verdict button.hold.on{background:#f1f3f5;border-color:#b9c0c9;color:#2b3138;font-weight:600}
.verdict input{flex:1;min-width:180px;border:1px solid #dfe3e8;border-radius:7px;
  padding:6px 10px;font-size:13px}
.bar{position:fixed;left:0;right:0;bottom:0;background:#fff;border-top:1px solid #dfe3e8;
  padding:12px 18px;display:flex;gap:12px;align-items:center;justify-content:center;flex-wrap:wrap;
  box-shadow:0 -2px 10px rgba(20,30,50,.06)}
.bar .count{font-size:13.5px;color:#3d4a5c}
.bar button{border:0;border-radius:8px;padding:9px 20px;font-size:14px;cursor:pointer;font-weight:600}
.bar button.export{background:#33518f;color:#fff}
.bar button.show{background:#eef2fb;color:#33518f}
pre.json{display:none;background:#f7f8fa;border:1px solid #e3e6ea;border-radius:8px;
  padding:12px;font-size:12px;max-height:260px;overflow:auto;margin:12px 0 0}
.foot{color:#8b929c;font-size:12px;margin-top:18px}
.hidden{display:none!important}
</style></head><body><div class="wrap">
<h1>用例审核</h1>
<div class="sub">生成于 ${esc(new Date().toISOString())} · 共 ${stats.total} 条 ·
未审核的用例照样会跑，但报告里会标出来</div>

<div class="stats">
  <div class="stat"><b>${stats.total}</b><span>用例总数</span></div>
  <div class="stat ok"><b>${stats.approved}</b><span>已审核</span></div>
  <div class="stat warn"><b>${stats.draft}</b><span>未审核</span></div>
  <div class="stat bad"><b>${stats.rejected}</b><span>已驳回</span></div>
  <div class="stat warn"><b>${stats.guess}</b><span>推测断言</span></div>
  <div class="stat bad"><b>${stats.flagged}</b><span>有风险提示</span></div>
</div>

<div class="filters">
  <button data-filter="all" class="on">全部</button>
  <button data-filter="draft">未审核</button>
  <button data-filter="guess">推测断言</button>
  <button data-filter="flagged">有风险提示</button>
  <button data-filter="approved">已审核</button>
  <button data-filter="rejected">已驳回</button>
</div>

<div id="list"></div>

<div class="foot">
  审的是两件事：<strong>这条测的是不是它标题承诺的事</strong>，以及<strong>断言会不会永远绿</strong>。<br>
  点了「导出」会下载 review-result.json，再用
  <span style="font-family:ui-monospace">npx tsx src/cli.ts --import-review review-result.json</span> 写回用例。
</div>

<pre class="json" id="json"></pre>
</div>

<div class="bar">
  <span class="count" id="count"></span>
  <button class="show" id="showJson">显示 JSON</button>
  <button class="export" id="export">导出审核结果</button>
</div>

<script>
const ITEMS = ${jsonForScript(items)};
const ORDER_LABEL = ${jsonForScript(ORDER_LABEL)};
const SOURCE_LABEL = ${jsonForScript(SOURCE_LABEL)};
const STATUS_LABEL = ${jsonForScript(REVIEW_LABEL)};
const state = {};
for (const it of ITEMS) state[it.id] = { status: it.status, note: it.note || '' };

function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function render(){
  const list = document.getElementById('list');
  list.innerHTML = ITEMS.map(it=>{
    const st = state[it.id].status;
    const flags = it.flags.map(f=>'<div class="flag">⚠ '+esc(f)+'</div>').join('');
    const asserts = it.asserts.length
      ? '<table class="asserts"><thead><tr><th>规则</th><th>期望</th><th></th></tr></thead><tbody>'
        + it.asserts.map(a=>'<tr><td class="rule">'+esc(a.rule)+'</td><td>'+esc(a.expect)+'</td>'
        + '<td>'+(a.fatal?'<span class="fatal">硬</span>':'')+'</td></tr>').join('')
        + '</tbody></table>'
      : '<div class="flag">⚠ 没有任何断言</div>';
    return '<div class="card s-'+st+'" data-id="'+esc(it.id)+'" data-status="'+st+'" data-flag="'+(it.flags.length?1:0)+'" data-src="'+esc(it.source)+'">'
      + '<div class="head">'
      + '<span class="cid">'+esc(it.id)+'</span>'
      + '<span class="title">'+esc(it.title)+'</span>'
      + '<span class="tag">前置 '+esc(it.precondition)+'</span>'
      + '<span class="tag order-'+esc(it.order)+'">'+esc(ORDER_LABEL[it.order]||it.order)+'</span>'
      + (it.tier?'<span class="tag">'+esc(it.tier)+'</span>':'')
      + '<span class="tag src-'+esc(it.source)+'">'+esc(SOURCE_LABEL[it.source]||it.source)+'</span>'
      + (it.why?'<span class="tag">'+esc(it.why)+'</span>':'')
      + '</div>'
      + flags
      + '<div class="block"><h4>步骤</h4><ol class="steps">'
      + it.steps.map(s=>'<li>'+esc(s.replace(/^·\\s*/,''))+'</li>').join('')
      + '</ol></div>'
      + '<div class="block"><h4>断言</h4>'+asserts+'</div>'
      + '<div class="verdict">'
      + '<button class="ok'+(st==='approved'?' on':'')+'" data-act="approved">通过</button>'
      + '<button class="no'+(st==='rejected'?' on':'')+'" data-act="rejected">驳回</button>'
      + '<button class="hold'+(st==='draft'?' on':'')+'" data-act="draft">待定</button>'
      + '<input placeholder="审核意见（可选）" value="'+esc(state[it.id].note)+'">'
      + '</div></div>';
  }).join('');
  bind();
  applyFilter();
  updateCount();
}

function bind(){
  document.querySelectorAll('.card').forEach(card=>{
    const id = card.dataset.id;
    card.querySelectorAll('.verdict button').forEach(btn=>{
      btn.onclick = ()=>{ state[id].status = btn.dataset.act; render(); };
    });
    const input = card.querySelector('.verdict input');
    input.oninput = ()=>{ state[id].note = input.value; updateCount(); };
  });
}

let filter = 'all';
function applyFilter(){
  document.querySelectorAll('.card').forEach(card=>{
    const st = card.dataset.status;
    const flag = card.dataset.flag === '1';
    const guess = card.dataset.src === 'guess';
    let show = true;
    if (filter === 'draft') show = st === 'draft';
    else if (filter === 'approved') show = st === 'approved';
    else if (filter === 'rejected') show = st === 'rejected';
    else if (filter === 'guess') show = guess;
    else if (filter === 'flagged') show = flag;
    card.classList.toggle('hidden', !show);
  });
}

document.querySelectorAll('.filters button').forEach(b=>{
  b.onclick = ()=>{
    filter = b.dataset.filter;
    document.querySelectorAll('.filters button').forEach(x=>x.classList.toggle('on', x===b));
    applyFilter();
  };
});

function updateCount(){
  const n = Object.values(state).filter(s=>s.status!=='draft').length;
  const total = Object.keys(state).length;
  document.getElementById('count').textContent = '已处理 '+n+' / '+total+' 条';
}

function payload(){
  return {
    generatedAt: new Date().toISOString(),
    items: ITEMS.map(it=>({ id: it.id, status: state[it.id].status, note: state[it.id].note || '', source: it.source })),
  };
}

document.getElementById('export').onclick = ()=>{
  const text = JSON.stringify(payload(), null, 2);
  const blob = new Blob([text], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'review-result.json';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href), 2000);
};

document.getElementById('showJson').onclick = ()=>{
  const pre = document.getElementById('json');
  const open = pre.style.display === 'block';
  pre.style.display = open ? 'none' : 'block';
  if (!open) { pre.textContent = JSON.stringify(payload(), null, 2); pre.scrollIntoView({block:'nearest'}); }
};

render();
</script>
</body></html>`;
}

/** 写审核页，返回路径和统计。 */
export function writeReviewPage(plans: Plan[]): { path: string; stats: ReviewPageStats } {
  const html = buildReviewHtml(plans);
  writeFileSync(REVIEW_HTML(), html, 'utf-8');
  return { path: REVIEW_HTML(), stats: reviewStats(plans) };
}

export interface ReviewResultFile {
  generatedAt?: string;
  items: Array<{ id: string; status: string; note?: string; source?: string }>;
}

export function isReviewStatus(s: string): s is ReviewStatus {
  return s === 'draft' || s === 'approved' || s === 'rejected';
}

export function isReviewSource(s: string): s is ReviewSource {
  return s === 'doc' || s === 'code' || s === 'guess' || s === 'human';
}
