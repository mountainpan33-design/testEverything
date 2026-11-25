/**
 * 执行层：把一个 Plan 逐步交给 Midscene 执行。
 *
 * 这一层刻意写得很薄——没有障碍扫描、没有不变量、没有读回校验。
 * 每一步就是一次「点这个 / 填这个 / 等这个 / 判这个」，和手写 Midscene 脚本一样。
 * 卡住之后的补救交给 heal.ts，而不是在执行路径里到处埋检查。
 */
import type { AndroidAgent } from '@midscene/android';

import {
  activeDevice,
  activePackage,
  adbShell,
  foregroundPackage,
  uiNodes,
} from './adb.js';
import { appScheme } from './config.js';
import { resolveValue, type Plan, type Step } from './plan.js';
import { CaseRecorder, runCase } from './recorder.js';
import type { CaseResult } from './types.js';

export interface RunVars {
  username: string;
  password: string;
  package: string;
}

function varsOf(v: RunVars) {
  return { username: v.username, password: v.password, package: v.package };
}

/** 执行一串步骤。depth 只用来防呆，plan.ts 已经卡过嵌套深度。 */
export async function execSteps(
  agent: AndroidAgent,
  steps: Step[],
  rec: CaseRecorder,
  vars: RunVars,
  depth = 0,
): Promise<void> {
  if (depth > 10) throw new Error('步骤嵌套过深，可能是 include 循环引用');
  const v = varsOf(vars);

  for (const s of steps) {
    switch (s.kind) {
      case 'launch':
        await agent.launch(vars.package);
        break;
      case 'terminate':
        await agent.terminate(vars.package).catch(() => {});
        break;
      case 'back':
        await agent.back();
        break;
      case 'open': {
        /*
         * 深链直接跳路由，不靠点。结构性冒烟每页一条，互不依赖——
         * 某页挂了不会像「一路点进去」那样把后面全带偏。
         */
        const dev = activeDevice();
        const uri = `${appScheme()}:///${s.route}`;
        const out = await adbShell(dev, [
          'shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', uri,
        ]);
        if (/Error|Exception|does not exist/i.test(out)) {
          throw new Error(`深链打不开 /${s.route}：${out.trim().slice(0, 200)}`);
        }
        await new Promise((r) => setTimeout(r, 1200));   // 给页面渲染留一帧
        break;
      }

      case 'check-route': {
        /*
         * 结构性冒烟：深链打开 → 查前台包名 → 读控件树 → 看该出现的文案在不在。
         * 全程不调模型：一页一次 dump，几秒钟，不花钱，也不会因为模型看错而误判。
         *
         * 测的是「页面还在不在、有没有白屏崩掉、关键文案有没有被改没」，
         * 不测业务对错——那得靠真机业务用例。
         */
        const dev = activeDevice();
        const pkg = activePackage();
        const uri = `${appScheme()}:///${s.route}`;
        const out = await adbShell(dev, [
          'shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', uri,
        ]);
        if (/Error|Exception|does not exist/i.test(out)) {
          throw new Error(`深链打不开 /${s.route}：${out.trim().slice(0, 200)}`);
        }
        await new Promise((r) => setTimeout(r, 1500));

        const fg = await foregroundPackage(dev);
        if (pkg && fg && !fg.includes(pkg)) {
          throw new Error(`打开 /${s.route} 后前台是「${fg}」，不是被测 App（可能崩了或弹了别的界面）`);
        }
        const nodes = await uiNodes();
        if (nodes.length === 0) {
          // 读不到控件树不等于页面空，但结构化冒烟没有别的证据来源
          throw new Error(`打开 /${s.route} 后读不到控件树（页面可能没渲染出来或 uiautomator 失败）`);
        }
        const texts = nodes.flatMap((n) => [n.text, n.desc]).filter(Boolean);
        const crash = texts.find((t) =>
          /已停止|has stopped|isn't responding|无响应|很抱歉|崩溃/.test(t),
        );
        if (crash) throw new Error(`打开 /${s.route} 后出现崩溃提示：「${crash}」`);
        const hit = s.expectAny.find((e) => texts.some((t) => t.includes(e) || e.includes(t)));
        if (!hit) {
          const seen = texts.slice(0, 12).join(' | ') || '<页面上没有文字>';
          throw new Error(
            `打开 /${s.route} 后没看到预期文案 ${s.expectAny.map((x) => `「${x}」`).join('/')}。` +
              `实际看到：${seen}`,
          );
        }
        break;
      }
      case 'tap':
        await agent.aiTap(resolveValue(s.target, v));
        break;
      case 'input':
        await agent.aiInput(resolveValue(s.value, v), resolveValue(s.target, v));
        break;
      case 'wait':
        // 裸的 aiWaitFor：等的是用例自己声明过的具体状态，
        // 不额外套一层「先看看屏幕归谁」的守卫（那是上一版的成本来源）
        await agent.aiWaitFor(resolveValue(s.for, v), { timeoutMs: s.timeoutMs });
        break;
      case 'assert': {
        const expect = resolveValue(s.expect, v);
        const ok = await rec.expect(agent, s.rule, expect, expect);
        if (!ok && s.fatal) throw new Error(`前置断言不成立：${expect}`);
        break;
      }
      case 'dismiss': {
        /*
         * 用控件树判断有没有这个按钮：免费。真出现了才叫一次模型去点。
         * 轮询三次是因为冷启动时 App 要先渲染出来，弹窗可能晚一两秒才出现；
         * 不轮询的话会漏掉，然后后面的等待白等 30 秒。
         */
        for (let attempt = 0; attempt < 3; attempt += 1) {
          const nodes = await uiNodes();
          const hit = s.labels.find((l) =>
            nodes.some((n) => `${n.text} ${n.desc}`.includes(l)),
          );
          if (hit) {
            console.log(`\n   ↳ 页面上有「${hit}」，点掉`);
            await agent.aiTap(`「${hit}」按钮`);
            break;
          }
          if (attempt < 2) await new Promise((r) => setTimeout(r, 800));
        }
        break;
      }
      case 'check-all': {
        /*
         * 把所有没勾的复选框勾上。
         *
         * 为什么不用 aiTap：协议页有 4 个勾选项，用一句「逐个点选」让模型做，
         * 它经常只点两三个就收工，底部按钮一直是灰的——2026-11-24 那轮 13 条用例
         * 全卡在这里。控件树里 checkable/checked/bounds 都是现成的，直接按坐标点，
         * 一次模型调用都不用。
         */
        const dev = activeDevice();
        // 只认 checkable="true" 的节点。uiautomator 的 dump 里几乎每个节点都带
        // checked="false"，按「有这个属性」筛会把整屏当复选框（实测筛出 61 个），
        // 然后拿坐标乱点，把界面点进了协议文档页。
        const isUncheckedBox = (n: { checkable: boolean; checked: boolean }) =>
          n.checkable && !n.checked;
        for (let round = 0; round < s.rounds; round += 1) {
          const nodes = await uiNodes();
          const todo = nodes.filter((n) => isUncheckedBox(n) && n.bounds);
          if (todo.length === 0) break;
          console.log(`\n   ↳ 勾选 ${todo.length} 个未勾选复选框`);
          for (const n of todo) {
            const [x1, y1, x2, y2] = n.bounds!;
            await adbShell(dev, [
              'shell', 'input', 'tap',
              String(Math.round((x1 + x2) / 2)),
              String(Math.round((y1 + y2) / 2)),
            ]).catch(() => '');
            await new Promise((r) => setTimeout(r, 200));
          }
        }
        const after = await uiNodes();
        const left = after.filter((n) => isUncheckedBox(n)).length;
        if (left > 0) throw new Error(`还有 ${left} 个复选框没勾上（重试 ${s.rounds} 轮后）`);
        break;
      }
      case 'sleep':
        await new Promise((r) => setTimeout(r, s.seconds * 1000));
        break;
      case 'repeat':
        for (let i = 0; i < s.times; i += 1) {
          await execSteps(agent, s.steps, rec, vars, depth + 1);
        }
        break;
      case 'if': {
        const hit = await agent.aiBoolean(resolveValue(s.when, v));
        const branch = hit ? s.then : s.else;
        if (branch.length === 0 && !hit) break;
        await execSteps(agent, branch, rec, vars, depth + 1);
        break;
      }
    }
  }
}

/** 跑一条用例。前置状态由调用方先摆好（见 prepare.ts）。 */
export async function runPlan(
  agent: AndroidAgent,
  plan: Plan,
  vars: RunVars,
): Promise<CaseResult> {
  const res = await runCase(plan.id, async (rec) => {
    await execSteps(agent, plan.steps, rec, vars);
  });
  res.title = plan.title;
  return res;
}
