/**
 * 直接调 adb 的小工具。
 *
 * 单独放一个文件是为了避免循环依赖：prepare.ts 和 login.ts 互相要用，
 * 各自 import 对方会绕成环，而 adb 本身跟谁都没关系。
 */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const run = promisify(execFile);

/**
 * 当前跑批的设备与被测包名。
 *
 * 存在模块级是为了让 obstacles.ts 能便宜地判断「屏幕还在不在 App 里」——
 * 那件事用 adb 看前台包名就够了，不该花一次模型调用。
 */
let ACTIVE_DEVICE = '';
let ACTIVE_PACKAGE = '';

export function setActiveTarget(deviceId: string, packageName: string): void {
  ACTIVE_DEVICE = deviceId;
  ACTIVE_PACKAGE = packageName;
}

export function activePackage(): string {
  return ACTIVE_PACKAGE;
}

export function activeDevice(): string {
  return ACTIVE_DEVICE;
}

export async function adbShell(deviceId: string, args: string[]): Promise<string> {
  const { stdout } = await run('adb', ['-s', deviceId, ...args], { timeout: 30000 });
  return stdout;
}

/**
 * 当前前台应用包名。读不到返回空串（调用方当作「不知道」，不要当作「不在 App」）。
 *
 * 用途：判断屏幕是不是被通知中心/系统设置顶掉了。这是免费的一次 adb，
 * 比让模型看图快两个数量级。
 */
export async function foregroundPackage(deviceId = ACTIVE_DEVICE): Promise<string> {
  if (!deviceId) return '';
  try {
    const out = await adbShell(deviceId, ['shell', 'dumpsys', 'window']);
    const m =
      out.match(/mCurrentFocus=[^\n]*?\s([A-Za-z][\w.]*)\/[\w.$]+/) ??
      out.match(/mFocusedApp=[^\n]*?\s([A-Za-z][\w.]*)\/[\w.$]+/);
    return m?.[1] ?? '';
  } catch {
    return '';
  }
}

export interface UiNode {
  text: string;
  desc: string;
  cls: string;
  /** 这个节点本身可不可以勾选 */
  checkable: boolean;
  /** 控件树里到底有没有 checked 属性（RN 的 accessibilityState 会给 checked，但不一定给 checkable） */
  hasChecked: boolean;
  /** 是否勾选（只有 checkable 的节点才有意义） */
  checked: boolean;
  /** 屏幕坐标 [x1,y1,x2,y2]，读不到为 null */
  bounds: [number, number, number, number] | null;
}

/**
 * 当前界面的控件树（免费，不调模型）。
 *
 * 用来做那些「看一眼就知道」的判断：是不是登录页（有两个输入框吗）、
 * 输入框里是不是真的有内容。判断不了的时候调用方再退回模型。
 * 读不到返回空数组——**空数组不等于界面空**，只是这条路走不通，别据此下结论。
 */
export async function uiNodes(deviceId = ACTIVE_DEVICE): Promise<UiNode[]> {
  if (!deviceId) return [];
  const remote = '/sdcard/midscene_ui_dump.xml';
  try {
    await adbShell(deviceId, ['shell', 'uiautomator', 'dump', remote]);
    const xml = await adbShell(deviceId, ['shell', 'cat', remote]);
    const out: UiNode[] = [];
    const attr = (attrs: string, k: string) =>
      attrs.match(new RegExp(`${k}="([^"]*)"`))?.[1] ?? '';
    for (const m of xml.matchAll(/<node\b([^>]*)>/g)) {
      const a = m[1] ?? '';
      const b = a.match(/bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/);
      out.push({
        text: attr(a, 'text'),
        desc: attr(a, 'content-desc'),
        cls: attr(a, 'class'),
        checkable: attr(a, 'checkable') === 'true',
        hasChecked: /\bchecked="/.test(a),
        checked: attr(a, 'checked') === 'true',
        bounds: b
          ? [Number(b[1]), Number(b[2]), Number(b[3]), Number(b[4])]
          : null,
      });
    }
    return out;
  } catch {
    return [];
  }
}

/**
 * 输入相关的设备现场。
 *
 * 2026-11-20 的教训：账号 pss2 输进去只剩「2」，报错却写着「账号密码不对」，
 * 人得反过来怀疑账号。把输入法名字贴在报错里，一眼就能判断是不是输入法吃字。
 */
export async function inputDiagnostics(deviceId: string): Promise<string> {
  const [ime, list] = await Promise.all([
    adbShell(deviceId, ['shell', 'settings', 'get', 'secure', 'default_input_method']).catch(
      () => '',
    ),
    adbShell(deviceId, ['shell', 'ime', 'list', '-s']).catch(() => ''),
  ]);
  const current = ime.trim() || '<读不到>';
  const installed = list
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
    .join(', ');
  return `当前输入法 ${current}${installed ? `（已装：${installed}）` : ''}`;
}
