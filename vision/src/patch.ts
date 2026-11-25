/**
 * 用例补丁：把修正写成对 cases.yaml 的**文本级**插入。
 *
 * 为什么是文本级而不是解析后再 dump：
 * cases.yaml 是手写维护的，里面全是注释和分组空行。
 * 用 YAML 序列化写回去会把注释全冲掉、字段顺序打乱，
 * 下次人打开就认不出这是自己写的文件了。所以只做「插一行」这种最小改动。
 *
 * 安全边界：
 *   - 只支持「在某个位置插入一个步骤」，不支持删除、替换
 *   - 插入前先校验整份文件还能被 plan.ts 正常加载，否则整轮放弃
 *   - 允不允许留下，由调用方根据重跑结果决定（见 heal.ts）
 */
import { readFileSync, writeFileSync } from 'node:fs';

export interface Insertion {
  caseId: string;
  /** 插到第几行（0-based，插在这一行之前） */
  at: number;
  /** 插入的整行文本，含缩进 */
  line: string;
  /** 给报告看的说明 */
  note: string;
}

interface CaseRange {
  start: number;
  end: number;
  stepsLine: number;
}

function lines(text: string): string[] {
  return text.split('\n');
}

/** 找到某条用例在文件里的行范围，以及它的 `steps:` 行号。 */
function findCase(all: string[], caseId: string): CaseRange | null {
  const idLine = all.findIndex((l) => new RegExp(`^- id:\\s*${caseId}\\s*$`).test(l));
  if (idLine < 0) return null;

  let end = all.length;
  for (let i = idLine + 1; i < all.length; i += 1) {
    if (/^- id:/.test(all[i]!)) {
      end = i;
      break;
    }
  }

  const stepsLine = all.findIndex((l, i) => i > idLine && i < end && /^\s{2}steps:\s*$/.test(l));
  if (stepsLine < 0) return null;

  return { start: idLine, end, stepsLine };
}

/**
 * 计算「把这一步插到用例开头」的位置。
 *
 * 插在 `steps:` 之后、第一个 `wait:` 之前——如果一上来就等某个状态，
 * 而弹窗正挡着，那一步必然等不到。放在它前面才有意义。
 */
export function planInsertion(
  text: string,
  caseId: string,
  stepYaml: string,
): Insertion | { reason: string } {
  const all = lines(text);
  const range = findCase(all, caseId);
  if (!range) return { reason: `cases.yaml 里找不到用例 ${caseId}` };

  for (let i = range.stepsLine + 1; i < range.end; i += 1) {
    // 只找顶层步骤（4 空格缩进），不碰 if/repeat 里面的嵌套步骤
    if (/^\s{4}- wait:/.test(all[i]!)) {
      return { caseId, at: i, line: `    - ${stepYaml}`, note: '插在第一次等待之前' };
    }
  }

  // 没有 wait 就放在步骤最前面
  return { caseId, at: range.stepsLine + 1, line: `    - ${stepYaml}`, note: '插在用例最前面' };
}

/**
 * 一次性套用多个插入，返回新全文。
 *
 * 从后往前插，避免前面的插入把后面的行号顶偏。
 */
export function applyInsertions(text: string, insertions: Insertion[]): string {
  const all = lines(text);
  const sorted = [...insertions].sort((a, b) => b.at - a.at);
  for (const ins of sorted) {
    all.splice(ins.at, 0, ins.line);
  }
  return all.join('\n');
}

/** 只保留指定用例的插入（其余丢弃），用来「验证通过才合并」。 */
export function keepOnly(insertions: Insertion[], caseIds: Set<string>): Insertion[] {
  return insertions.filter((i) => caseIds.has(i.caseId));
}

/** 给报告看的小 diff：上下文一行 + 新增一行。 */
export function diffOf(text: string, ins: Insertion): string {
  const all = lines(text);
  const prev = all[ins.at - 1] ?? '';
  return [prev, `+ ${ins.line}`].join('\n');
}

export function readText(file: string): string {
  return readFileSync(file, 'utf8');
}

export function writeText(file: string, text: string): void {
  writeFileSync(file, text.endsWith('\n') ? text : `${text}\n`, 'utf8');
}
