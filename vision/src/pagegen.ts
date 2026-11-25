/**
 * 从源码生成 Appium 定位符（Page Object 的定位部分）。
 *
 * 为什么这么做：Appium 用例脆在定位符上——`accessibilityLabel` 一改，
 * 手抄的 Python 常量就断了，而这类改动几乎每周都有。定位符本来就 100% 由源码决定，
 * 那就让机器抄，人不用再跟着改。
 *
 * 生成规则（全部确定性，不调模型）：
 *   - 每个有 label 的页面生成一个 dict：{label: (AppiumBy.ACCESSIBILITY_ID, label)}
 *   - dict 名由文件路径推出：src/app/login.tsx → LOGIN
 *   - 没埋 label 的页面也列出来，缺口不能藏
 *
 * 手写的 page object 不动。生成的模块是「定位符清单」，
 * 手写逻辑照旧 import 它即可。
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { appSourceDir, locatorsOutPath } from './project.js';
import { scanSource, type PageFacts } from './scan.js';

const OUT_FILE = () => locatorsOutPath();
const SRC_ROOT = () => appSourceDir();

/** src/app/login.tsx → APP_LOGIN；重名时退回完整路径。 */
function dictName(file: string, used: Set<string>): string {
  const base = file
    .replace(/\.tsx?$/, '')
    .replace(/[^A-Za-z0-9]+/g, '_')
    .toUpperCase();
  if (!used.has(base)) return base;
  const full = file
    .replace(/\.tsx?$/, '')
    .replace(/[^A-Za-z0-9]+/g, '_')
    .toUpperCase();
  return full;
}

function pyStr(s: string): string {
  // Python 字符串里只需要转义反斜杠和双引号
  return `"${s.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

export function renderLocators(pages: PageFacts[], missing: string[]): string {
  const used = new Set<string>();
  const lines: string[] = [];

  lines.push('"""Appium 定位符清单（自动生成，请勿手改）。');
  lines.push('');
  lines.push('来源：src/ 下各组件的 accessibilityLabel。');
  lines.push('重新生成：cd app-automation/vision && npx tsx src/cli.ts --gen-pages --write');
  lines.push('检查是否过期：npx tsx src/cli.ts --gen-pages   （有差异时退出码 1）');
  lines.push('');
  lines.push('为什么自动生成：label 改了，手抄的常量就断。定位符由源码唯一决定，交给机器抄。');
  lines.push('"""');
  lines.push('');
  lines.push('from appium.webdriver.common.appiumby import AppiumBy');
  lines.push('');

  const named: Array<{ name: string; page: PageFacts }> = [];
  for (const p of pages) {
    if (p.labels.length === 0) continue;
    named.push({ name: dictName(p.file, used), page: p });
    used.add(named[named.length - 1]!.name);
  }

  for (const { name, page } of named) {
    lines.push(`# 来源：src/${page.file}`);
    lines.push(`${name} = {`);
    for (const label of page.labels) {
      lines.push(`    ${pyStr(label)}: (AppiumBy.ACCESSIBILITY_ID, ${pyStr(label)}),`);
    }
    lines.push('}');
    lines.push('');
  }

  if (missing.length) {
    lines.push('# 以下页面没有埋 accessibilityLabel：Appium 只能靠 XPath/文案定位，容易随改版失效。');
    for (const f of missing) lines.push(`#   - src/${f}`);
    lines.push('');
  }

  lines.push('');
  lines.push('def locator(page: dict, label: str):');
  lines.push('    """按 label 取定位符；取不到时直接抛出，别让用例静默跑错元素。"""');
  lines.push('    try:');
  lines.push('        return page[label]');
  lines.push('    except KeyError:');
  lines.push('        hint = "如果界面确实有这个元素，先给它补 accessibilityLabel。"');
  lines.push('        raise KeyError(f"定位符 {label!r} 不在此页。可用：{sorted(page)}。{hint}") from None');
  lines.push('');

  return lines.join('\n');
}

export interface GenResult {
  content: string;
  current: string | null;
  changed: boolean;
  pageCount: number;
  labelCount: number;
  missing: string[];
}

export function generate(): GenResult {
  const scan = scanSource();
  const pages = scan.pages.filter((p) => existsSync(resolve(SRC_ROOT(), p.file)));
  const content = renderLocators(pages, scan.pagesWithoutLabels);
  const current = existsSync(OUT_FILE()) ? readFileSync(OUT_FILE(), 'utf8') : null;
  const labelCount = pages.reduce((n, p) => n + p.labels.length, 0);
  return {
    content,
    current,
    changed: current !== content,
    pageCount: pages.filter((p) => p.labels.length > 0).length,
    labelCount,
    missing: scan.pagesWithoutLabels,
  };
}

/** 写盘。返回是否真的写了。 */
export function write(result: GenResult): boolean {
  if (!result.changed) return false;
  writeFileSync(OUT_FILE(), result.content, 'utf8');
  return true;
}

export const OUT_PATH = () => OUT_FILE();
