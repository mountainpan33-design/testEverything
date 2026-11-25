/**
 * 视觉层与 pytest 之间的数据契约。
 *
 * pytest 侧 tests/test_vision.py 只认这个结构，不关心 Midscene 内部怎么跑。
 * 想加用例只改 cases/，不要动这里的字段名。
 */

import type { Diagnosis } from './obstacles.js';

export type CaseStatus = 'passed' | 'failed' | 'skipped';

export interface AssertionResult {
  /** 对应 core/rules.py 里的规则编号，例如 R-ONB-01。报告据此归类。 */
  rule: string;
  ok: boolean;
  expected: string;
  actual: string;
  message?: string;
}


export interface CaseResult {
  caseId: string;
  /** 用例标题，落到结果里，自愈分析不用再去查一遍清单 */
  title?: string;
  status: CaseStatus;
  assertions: AssertionResult[];
  /** 整条用例挂掉时的原因（页面跑偏、模型判错、设备断开等）。 */
  error?: string;
  /** 跳过原因，status=skipped 时有值。 */
  skipReason?: string;
  /** 失败现场归因：屏幕上到底是什么、算环境问题还是产品问题 */
  diagnosis?: Diagnosis;
  durationMs: number;
  /** 起止时间（ISO），供 analyze.ts 从日志里切出这条用例的那一段 */
  startedAt?: string;
  finishedAt?: string;
}

export interface RunOutput {
  generatedAt: string;
  deviceId: string;
  packageName: string;
  modelName: string;
  /** 本次跑的档位：smoke / full */
  tier?: string;
  cases: CaseResult[];
}
