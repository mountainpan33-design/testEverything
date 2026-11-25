/**
 * 现场取证：失败截图 + 每条用例的录屏。
 *
 * 为什么要在执行时抓：这两个东西事后补不回来。截图必须失败那一刻的屏幕，
 * 录屏必须覆盖整个过程，跑完了再想拿只能重跑。
 *
 * 取舍：
 *   - 截图**只对失败用例**抓，并且直接内联进 HTML（几百 KB，报告还是单文件）。
 *   - 录屏每条用例一段，存成 mp4 放在报告旁边，报告里用相对路径引用（视频太大，不内联）。
 *   - screenrecord 单段上限 180 秒，超时的用例会被截断，报告里标注出来。
 *
 * 注意：录屏和截图会把测试账号、密码输入过程一起录进去。
 * 带媒体的报告只能内部看，不能外发。
 */
import { execFile } from 'node:child_process';
import type { ChildProcess } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { promisify } from 'node:util';

const run = promisify(execFile);

const DEVICE_VIDEO = '/sdcard/vision_case.mp4';
const MAX_RECORD_SECONDS = 180;

export interface CaseMedia {
  /** data:image/png;base64,... 直接内联 */
  screenshot?: string;
  /** 相对报告目录的路径 */
  video?: string;
  /** 用例超过 screenrecord 单段上限，视频是截断的 */
  videoTruncated?: boolean;
}

async function adb(deviceId: string, args: string[], timeout = 30000): Promise<string> {
  const { stdout } = await run('adb', ['-s', deviceId, ...args], { timeout, encoding: 'buffer' });
  return (stdout as unknown as Buffer).toString('utf8');
}

/** 开始录这一条用例。返回句柄，失败返回 null（录不了不该挡住测试）。 */
export async function startVideo(deviceId: string): Promise<ChildProcess | null> {
  try {
    await adb(deviceId, ['shell', 'rm', '-f', DEVICE_VIDEO]);
  } catch {
    // 删不掉也无所谓，screenrecord 会覆盖
  }
  try {
    const child = execFile(
      'adb',
      [
        '-s', deviceId,
        'shell', 'screenrecord',
        '--bit-rate', '2000000',
        '--time-limit', String(MAX_RECORD_SECONDS),
        DEVICE_VIDEO,
      ],
      { maxBuffer: 1024 * 1024 },
    );
    child.on('error', () => {});
    // 给它一点时间真正开始录，否则极短的用例会拉出一个空文件
    await new Promise((r) => setTimeout(r, 300));
    return child;
  } catch {
    return null;
  }
}

/** 结束录制并把文件拉回本地。返回相对报告目录的路径。 */
export async function stopVideo(
  deviceId: string,
  child: ChildProcess | null,
  caseId: string,
  videosDir: string,
  reportDir: string,
  startedAt: number,
): Promise<CaseMedia | null> {
  if (!child) return null;
  try {
    // SIGINT 让 screenrecord 正常收尾，文件才可播
    await adb(deviceId, ['shell', 'pkill', '-INT', 'screenrecord']).catch(() => '');
    await new Promise((r) => setTimeout(r, 800));
    child.kill();

    mkdirSync(videosDir, { recursive: true });
    const local = resolve(videosDir, `${caseId}.mp4`);
    let ok = false;
    for (let i = 0; i < 3 && !ok; i += 1) {
      try {
        await adb(deviceId, ['pull', DEVICE_VIDEO, local], 60000);
        ok = existsSync(local);
      } catch {
        await new Promise((r) => setTimeout(r, 400));
      }
    }
    if (!ok) return null;

    const elapsed = (Date.now() - startedAt) / 1000;
    const rel = relativeFrom(reportDir, local);
    return { video: rel, videoTruncated: elapsed > MAX_RECORD_SECONDS + 5 };
  } catch {
    return null;
  }
}

/** 失败现场截图，返回 data URL；失败返回 undefined（截不到不该影响结论）。 */
export async function captureScreenshot(
  deviceId: string,
  caseId: string,
  shotsDir: string,
): Promise<string | undefined> {
  try {
    mkdirSync(shotsDir, { recursive: true });
    const local = resolve(shotsDir, `${caseId}.png`);
    const { stdout } = await run('adb', ['-s', deviceId, 'exec-out', 'screencap', '-p'], {
      timeout: 30000,
      encoding: 'buffer',
      maxBuffer: 40 * 1024 * 1024,
    });
    const buf = stdout as unknown as Buffer;
    if (!buf || buf.length < 1000) return undefined;
    // 存一份在磁盘上，报告里再内联一份（内联是为了报告能单独发出去）
    writeFileSync(local, buf);
    return `data:image/png;base64,${buf.toString('base64')}`;
  } catch {
    return undefined;
  }
}

/** 相对路径（相对报告所在目录），Unix 分隔符，供 HTML 用。 */
function relativeFrom(fromDir: string, toFile: string): string {
  const from = resolve(fromDir).split(/[\\/]/);
  const to = resolve(toFile).split(/[\\/]/);
  let i = 0;
  while (i < from.length && i < to.length && from[i] === to[i]) i += 1;
  const up = new Array(from.length - i).fill('..');
  return [...up, ...to.slice(i)].join('/');
}
