/**
 * 断言记录器：把 Midscene 的 aiAssert 结果转成 core/rules.py 那套 rule 编号。
 *
 * 为什么不让 aiAssert 的异常直接冒出去：一条用例里通常有多条断言，
 * 第一条失败就中断的话，报告里只能看到一条「挂了」，看不出后面是真通过还是没跑。
 * 所以分两种：
 *   expect()  —— 软断言，失败记下来继续，用来攒完整证据
 *   require() —— 硬断言，失败即终止，用于「没有这一步后面全是瞎跑」的前置
 */
import type { AndroidAgent } from '@midscene/android';

import type { AssertionResult, CaseResult } from './types.js';

function errText(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  // Midscene 的报错会带很长的模型推理过程，留前 400 字够定位了
  return raw.length > 400 ? `${raw.slice(0, 400)}…` : raw;
}

export class CaseRecorder {
  readonly assertions: AssertionResult[] = [];
  private readonly startedAt = Date.now();
  private readonly startedAtIso = new Date().toISOString();

  constructor(readonly caseId: string) {}

  /** 软断言：失败只记录，不中断。 */
  async expect(
    agent: AndroidAgent,
    rule: string,
    assertion: string,
    expected: string,
  ): Promise<boolean> {
    try {
      await agent.aiAssert(assertion);
      this.assertions.push({ rule, ok: true, expected, actual: '符合预期' });
      return true;
    } catch (e) {
      this.assertions.push({ rule, ok: false, expected, actual: errText(e) });
      return false;
    }
  }

  /** 硬断言：失败直接抛，终止这条用例。 */
  async require(
    agent: AndroidAgent,
    rule: string,
    assertion: string,
    expected: string,
  ): Promise<void> {
    const ok = await this.expect(agent, rule, assertion, expected);
    if (!ok) {
      throw new Error(`前置断言不成立：${assertion}`);
    }
  }

  /** 不是 AI 判的检查（比如「接口返回了 X」「文件存在」），直接记账。 */
  plain(rule: string, ok: boolean, expected: string, actual: string, message?: string): void {
    this.assertions.push({ rule, ok, expected, actual, message });
  }

  finish(error?: unknown): CaseResult {
    const failed = this.assertions.some((a) => !a.ok);
    const status: CaseResult['status'] = error || failed ? 'failed' : 'passed';
    return {
      caseId: this.caseId,
      status,
      assertions: this.assertions,
      ...(error ? { error: errText(error) } : {}),
      durationMs: Date.now() - this.startedAt,
      startedAt: this.startedAtIso,
      finishedAt: new Date().toISOString(),
    };
  }

  skipped(reason: string): CaseResult {
    return {
      caseId: this.caseId,
      status: 'skipped',
      assertions: this.assertions,
      skipReason: reason,
      durationMs: Date.now() - this.startedAt,
      startedAt: this.startedAtIso,
      finishedAt: new Date().toISOString(),
    };
  }
}

/** 统一的用例外壳：开局记时间，收尾把异常转成 failed，绝不把进程搞崩。 */
export async function runCase(
  caseId: string,
  body: (rec: CaseRecorder) => Promise<CaseResult | void>,
): Promise<CaseResult> {
  const rec = new CaseRecorder(caseId);
  try {
    const explicit = await body(rec);
    return explicit ?? rec.finish();
  } catch (e) {
    return rec.finish(e);
  }
}
