/**
 * 源码扫描：把界面上的事实抽出来，用来反查用例有没有跟源码脱节。
 *
 * 解决的是维护成本的根源问题——不是「谁来改用例」，而是
 * **界面改了、用例没改，却没人发现**。
 *
 * 抽三样东西（全部靠正则，不调模型、不确定的事不猜）：
 *   1. accessibilityLabel —— Appium 定位符的唯一来源
 *   2. <Text> 里的字面文案 —— 视觉用例里写的按钮/标题是否还存在
 *   3. 页面文件清单 —— 哪些页面还没有埋 label（生成 Appium 用例的前提）
 *
 * 校验规则：cases.yaml 里每个「引号包起来的文案」，都必须在源码里出现过。
 * 找不到就报出来：要么界面改了文案，要么用例写错了。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

import { appSourceDir, casesDir } from './project.js';

const APP_SRC = () => appSourceDir();
const CASES_FILE = () => resolve(casesDir(), 'cases.yaml');

export interface PageFacts {
  file: string;
  labels: string[];
  texts: string[];
}

export interface ScanResult {
  pages: PageFacts[];
  /** 一个 label 都没埋的页面：Appium 没法可靠定位 */
  pagesWithoutLabels: string[];
  /** 所有出现过的界面文案 */
  allCopy: Set<string>;
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
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === 'node_modules' || name.startsWith('.')) continue;
      out.push(...walk(full));
    } else if (/\.tsx?$/.test(name)) {
      out.push(full);
    }
  }
  return out;
}

function uniq(xs: string[]): string[] {
  return [...new Set(xs)];
}

/** 扫 src/，抽出每个文件的 label 和文案。 */
export function scanSource(): ScanResult {
  const src = APP_SRC();
  if (!src) {
    throw new Error('没有配置 App 源码目录（project.json 的 appSourceDir 或 QA_APP_SOURCE）');
  }
  const pages: PageFacts[] = [];
  const allCopy = new Set<string>();

  for (const file of walk(src)) {
    const text = readFileSync(file, 'utf8');

    // 模板字符串（accessibilityLabel={`${label}${on ? ...}`}）是动态拼出来的，
    // 生成不了静态定位符，直接排除，别让它在生成文件里变成一行垃圾
    const labels = uniq(
      [...text.matchAll(/accessibilityLabel=\{?["'`]([^"'`]+)["'`]\}?/g)]
        .map((m) => m[1]!)
        .filter((l) => !l.includes('${') && !l.includes('{')),
    );
    // <Text ...>纯文字</Text>：只取没有嵌套花括号的字面量
    const texts = uniq(
      [...text.matchAll(/<Text[^>]*>([^<>{}\n]{1,30})<\/Text>/g)]
        .map((m) => m[1]!.trim())
        .filter((s) => s && !/^[\s.·:：]+$/.test(s)),
    );

    // 配置对象里的文案（比如 tab 名、服务器名）不在 <Text> 里，也要算进来，
    // 否则「首页」「我的」这种会被误判成「源码里没有」
    const literals = uniq(
      [...text.matchAll(/["'`]([^"'`\n]{1,30})["'`]/g)]
        .map((m) => m[1]!.trim())
        .filter((x) => x && !/^[\s\w.$/{},;:()=-]*$/.test(x)),
    );

    for (const s of [...labels, ...texts, ...literals]) allCopy.add(s);
    if (labels.length || texts.length) {
      pages.push({ file: relative(src, file), labels, texts });
    }
  }

  const pagesWithoutLabels = pages.filter((p) => p.labels.length === 0).map((p) => p.file);
  return { pages, pagesWithoutLabels, allCopy };
}

/** 用例里「」包起来的文案，必须在源码里出现过。 */
export function checkDrift(scan: ScanResult): { missing: string[]; checked: number } {
  const yaml = readFileSync(CASES_FILE(), 'utf8');
  // 只看真正会送去执行的字段，注释里出现的「」不算（那是给人看的说明）
  const values = [...yaml.matchAll(/^\s*(?:- )?(?:tap|for|expect|target|value|when):\s*(.+)$/gm)]
    .map((m) => m[1]!);
  const quoted = uniq(
    values.flatMap((v) =>
      [...v.matchAll(/[「]([^「」\n]{1,20})[」]/g)].map((m) => m[1]!.trim()),
    ),
  );

  // 占位符和纯符号不算
  const candidates = quoted.filter((q) => !/\{\{|^[\s·.、/]+$/.test(q));

  const missing = candidates.filter((q) => {
    for (const copy of scan.allCopy) {
      // 单字不算数：一个「登」字会让所有含「登」的文案都判成命中
      if (copy.length < 2) continue;
      if (copy.includes(q) || q.includes(copy)) return false;
    }
    return true;
  });

  return { missing, checked: candidates.length };
}

/** 人看的报告。 */
export function formatScan(scan: ScanResult, drift: { missing: string[]; checked: number }): string {
  const lines: string[] = [];
  lines.push(`扫描页面：${scan.pages.length} 个有内容的文件，其中 ${scan.pagesWithoutLabels.length} 个没埋 accessibilityLabel`);
  if (scan.pagesWithoutLabels.length) {
    for (const f of scan.pagesWithoutLabels) lines.push(`  ⚠ ${f}`);
    lines.push('  （这些页面 Appium 只能靠 XPath/文案定位，容易随改版失效）');
  }
  lines.push('');
  lines.push(`用例文案核对：检查 ${drift.checked} 处，找不到 ${drift.missing.length} 处`);
  for (const m of drift.missing) lines.push(`  ✗ 「${m}」在 src/ 里找不到`);
  if (drift.missing.length === 0) lines.push('  ✓ 用例里提到的界面文案在源码里都能找到');
  return lines.join('\n');
}
