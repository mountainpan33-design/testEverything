/**
 * 把审核结果写回 YAML。
 *
 * 为什么动文本而不是 `yaml.dump` 整个文件：cases.yaml 里全是人写的注释，
 * 一 dump 全没了。这边只做「在 id 对应的块里插/换一个 review 子块」这一件事，
 * 其余字节原样保留。
 *
 * 写完必须能用 js-yaml 重新解析并通过结构预检，不通过就回滚——
 * 宁可这次没写进去，也不能把用例文件改坏。
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

import yaml from 'js-yaml';

import { casesDir } from './project.js';
import { isReviewSource, isReviewStatus, type ReviewResultFile } from './review.js';

const CASES_FILE = () => resolve(casesDir(), 'cases.yaml');
const DERIVED_FILE = () => resolve(casesDir(), 'derived.yaml');

/** YAML 单引号字符串：内部的 ' 写成 ''。 */
function quote(s: string): string {
  return `'${s.replace(/'/g, "''")}'`;
}

function reviewBlock(
  indent: string,
  r: { status: string; note?: string; source?: string },
  by: string,
  at: string,
): string {
  const source = isReviewSource(String(r.source ?? '')) ? String(r.source) : 'human';
  const lines = [
    `${indent}review:`,
    `${indent}  status: ${r.status}`,
    `${indent}  source: ${source}`,
  ];
  if (r.note?.trim()) lines.push(`${indent}  note: ${quote(r.note.trim())}`);
  lines.push(`${indent}  approvedAt: ${quote(at)}`);
  lines.push(`${indent}  approvedBy: ${quote(by)}`);
  return lines.join('\n');
}

/**
 * 在一个文件的文本里，为指定 id 插入或替换 review 块。
 * 返回新的文本；找不到 id 返回 null。
 */
function patchOne(text: string, id: string, block: string): string | null {
  const lines = text.split('\n');
  // 找到 `- id: X` 所在行
  const start = lines.findIndex((l) => new RegExp(`^- id:\\s*${id}\\s*$`).test(l));
  if (start < 0) return null;
  // 块结束：下一条 `- id:` 或文件末尾
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i += 1) {
    if (/^- id:\s*\S+/.test(lines[i]!)) {
      end = i;
      break;
    }
  }
  // 块内找已有的 `  review:`（2 空格缩进）
  let reviewAt = -1;
  for (let i = start + 1; i < end; i += 1) {
    if (/^ {2}review:/.test(lines[i]!)) {
      reviewAt = i;
      break;
    }
  }
  if (reviewAt >= 0) {
    // 删到下一个缩进 ≤2 的非空行为止
    let stop = reviewAt + 1;
    while (stop < end) {
      const l = lines[stop]!;
      if (l.trim() === '') {
        stop += 1;
        continue;
      }
      const indent = l.length - l.trimStart().length;
      if (indent <= 2) break;
      stop += 1;
    }
    lines.splice(reviewAt, stop - reviewAt, block);
    return lines.join('\n');
  }
  // 没有就插在 `  steps:` 之前；连 steps 都没有就插在块末尾
  let insertAt = end;
  for (let i = start + 1; i < end; i += 1) {
    if (/^ {2}steps:/.test(lines[i]!)) {
      insertAt = i;
      break;
    }
  }
  lines.splice(insertAt, 0, block);
  return lines.join('\n');
}

export interface ApplyResult {
  updated: string[];
  unknown: string[];
  /** 被拒的 id → 原因 */
  rejected: Record<string, string>;
  files: string[];
}

export function applyReview(result: ReviewResultFile, by = ''): ApplyResult {
  const out: ApplyResult = { updated: [], unknown: [], rejected: {}, files: [] };
  const at = new Date().toISOString();
  const who = by.trim() || 'reviewer';

  const files = [CASES_FILE(), DERIVED_FILE()].filter((f) => existsSync(f));
  const original = new Map<string, string>();
  const current = new Map<string, string>();
  for (const f of files) {
    const t = readFileSync(f, 'utf-8');
    original.set(f, t);
    current.set(f, t);
  }

  /*
   * 记下原有的 note 和 source。审核页里 note 是「审核意见」输入框，空着是常态，
   * 直接覆盖会把派生用例自带的「依据哪个源码生成」说明冲掉；
   * source 更关键——审一条机器生成的用例，不该把它变成「人工编写」。
   */
  const priorNote = new Map<string, string>();
  const priorSource = new Map<string, string>();
  for (const f of files) {
    try {
      const doc = yaml.load(original.get(f)!);
      if (!Array.isArray(doc)) continue;
      for (const it of doc as Array<Record<string, unknown>>) {
        const id = typeof it?.id === 'string' ? it.id : '';
        const rv = it?.review as Record<string, unknown> | undefined;
        if (!id || !rv || typeof rv !== 'object') continue;
        if (typeof rv.note === 'string' && rv.note.trim()) priorNote.set(id, rv.note);
        if (typeof rv.source === 'string' && rv.source.trim()) priorSource.set(id, rv.source);
      }
    } catch {
      /* 读不出来就不保留，反正下面还会整体校验一次 */
    }
  }

  for (const item of result.items ?? []) {
    const id = String(item.id ?? '').trim();
    const status = String(item.status ?? '').trim();
    if (!id) continue;
    if (!isReviewStatus(status)) {
      out.rejected[id] = `状态「${status}」不合法（只能是 draft / approved / rejected）`;
      continue;
    }
    const block = reviewBlock(
      '  ',
      {
        status,
        note: item.note?.trim() || priorNote.get(id),
        source: item.source?.trim() || priorSource.get(id),
      },
      who,
      at,
    );
    let done = false;
    for (const f of files) {
      const next = patchOne(current.get(f)!, id, block);
      if (next !== null) {
        current.set(f, next);
        done = true;
        break;
      }
    }
    if (done) out.updated.push(id);
    else out.unknown.push(id);
  }

  // 写之前先校验：能 parse，且**真正应用了**的那些 id 的 review.status 确实变了
  const applied = new Set(out.updated);
  for (const f of files) {
    const before = original.get(f)!;
    const after = current.get(f)!;
    if (before === after) continue;
    try {
      const doc = yaml.load(after);
      if (!Array.isArray(doc)) throw new Error('解析后不是数组');
      for (const item of result.items ?? []) {
        if (!applied.has(item.id)) continue;      // 被拒/不存在的本来就没写，不该拿它们校验
        const hit = (doc as Array<Record<string, unknown>>).find((c) => c?.id === item.id);
        if (!hit) continue;
        const rv = hit.review as Record<string, unknown> | undefined;
        if (!rv || rv.status !== item.status) {
          throw new Error(`${item.id} 的 review.status 没写对（实际 ${String(rv?.status)}）`);
        }
      }
    } catch (e) {
      out.rejected[`<file:${f.split('/').pop()}>`] = `写回后 YAML 不合法，已回滚：${
        e instanceof Error ? e.message : String(e)
      }`;
      for (const g of files) current.set(g, original.get(g)!);   // 全部回滚
      return out;
    }
  }

  for (const f of files) {
    const after = current.get(f)!;
    if (after !== original.get(f)) {
      writeFileSync(f, after, 'utf-8');
      out.files.push(f);
    }
  }
  return out;
}
