/**
 * 配置解析：vision/.env 优先，app-automation/.env 兜底。
 *
 * 为什么兜底：包名、UDID、账号本来就在 app-automation/.env 里，
 * 再让人往 vision/.env 抄一遍，抄错了报的错还很难懂（比如包名写成 com.xxx）。
 * vision/.env 只需要放模型那四项。
 */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { config as loadEnv, parse } from 'dotenv';

import { appJsonPath, projectConfig } from './project.js';

const HERE = dirname(fileURLToPath(import.meta.url));
export const VISION_DIR = resolve(HERE, '..');
const APP_AUTOMATION_DIR = resolve(VISION_DIR, '..');

/**
 * 包名从项目配置读（projects/<名字>/project.json 的 packageName）。
 *
 * 不再写死某个 App 的包名——这是框架能测别的项目的前提。
 */
function defaultPackage(): string {
  return projectConfig().packageName;
}

function readEnvFile(path: string): Record<string, string> {
  if (!existsSync(path)) return {};
  try {
    return parse(readFileSync(path, 'utf8'));
  } catch {
    return {};
  }
}

/** vision/.env 里的值不覆盖已有环境变量（方便 CI 注入）。 */
export function hydrateEnv(): void {
  loadEnv({ path: resolve(VISION_DIR, '.env'), override: false });

  /*
   * 空字符串 != 未设置。
   * .env 里写 MIDSCENE_RUN_DIR="" 会让 Midscene 直接抛
   * "run directory must be a non-empty path" —— 它只判断「变量存在」，不判断内容。
   * 所以统一把空的 MIDSCENE_* 删掉，退回默认行为。
   */
  for (const key of Object.keys(process.env)) {
    if (key.startsWith('MIDSCENE_') && !process.env[key]?.trim()) {
      delete process.env[key];
    }
  }

  const fallback = readEnvFile(resolve(APP_AUTOMATION_DIR, '.env'));
  const mapping: Record<string, string | undefined> = {
    EGO_APP_PACKAGE: fallback.ANDROID_APP_PACKAGE,
    EGO_USERNAME: fallback.QA_USERNAME,
    EGO_PASSWORD: fallback.QA_PASSWORD,
    MIDSCENE_ANDROID_DEVICE_ID: fallback.ANDROID_UDID,
  };

  for (const [key, value] of Object.entries(mapping)) {
    if (!process.env[key]?.trim() && value?.trim()) {
      process.env[key] = value.trim();
    }
  }

  if (!process.env.EGO_APP_PACKAGE?.trim()) {
    process.env.EGO_APP_PACKAGE = defaultPackage();
  }
}

export interface MissingItem {
  name: string;
  where: string;
}

/** 一次性把所有缺失项列出来，别让人配一个报一个。 */
export function missingConfig(): MissingItem[] {
  const missing: MissingItem[] = [];
  const need = (name: string, where: string) => {
    if (!process.env[name]?.trim()) missing.push({ name, where });
  };

  need('MIDSCENE_MODEL_BASE_URL', 'vision/.env（中转地址要带 /v1）');
  need('MIDSCENE_MODEL_API_KEY', 'vision/.env');
  need('MIDSCENE_MODEL_NAME', 'vision/.env');
  need('MIDSCENE_MODEL_FAMILY', 'vision/.env');
  need('EGO_USERNAME', 'app-automation/.env 的 QA_USERNAME，或 vision/.env');
  need('EGO_PASSWORD', 'app-automation/.env 的 QA_PASSWORD，或 vision/.env');

  return missing;
}

/**
 * 深链 scheme，用于 `open: <route>` 步骤直接跳路由。
 *
 * 从 app.json 的 expo.scheme 读，读不到再看环境变量，最后退回包名末段。
 * 有了它，结构性冒烟不用「点进去」——一条用例一个路由，互不依赖，
 * 某一条挂了不会把后面全带偏。
 */
export function appScheme(): string {
  const fromEnv = process.env.EGO_DEEP_LINK_SCHEME?.trim();
  if (fromEnv) return fromEnv;
  // 优先项目配置里写的 scheme，其次才去 App 的 app.json 里翻
  const declared = projectConfig().scheme?.trim();
  if (declared) return declared;
  const appJson = appJsonPath();
  if (appJson && existsSync(appJson)) {
    try {
      const doc = JSON.parse(readFileSync(appJson, 'utf8')) as {
        expo?: { scheme?: string | string[] };
        scheme?: string | string[];
      };
      const s = doc.expo?.scheme ?? doc.scheme;
      const first = Array.isArray(s) ? s[0] : s;
      if (first?.trim()) return first.trim();
    } catch {
      /* 读坏了就退回默认值，不为一个跳转把整轮跑挂掉 */
    }
  }
  throw new Error(
    '读不到深链 scheme：在 project.json 里写 scheme，或设 EGO_DEEP_LINK_SCHEME',
  );
}
