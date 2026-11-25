/**
 * 项目配置：让框架和「被测的是哪个 App」解耦。
 *
 * 之前所有路径都写死成「我在 App 仓库里」，换个项目就得改代码。
 * 现在每个被测项目在 `projects/<名字>/` 下一个目录：
 *
 *   projects/mono-capture/
 *   ├── project.json      包名、App 源码位置、scheme、用例目录
 *   ├── vision/           appContext.ts / prepare.ts / login.ts / obstacles.project.ts
 *   ├── cases/            用例 YAML
 *   └── python/           项目专属的 python 模块（覆盖率表等）
 *
 * 选哪个项目：`--project <名字>` 或环境变量 `QA_PROJECT`，默认取 projects/ 下唯一那个。
 *
 * App 源码位置有两种给法，后者优先：
 *   1. project.json 的 appSourceDir（相对 project.json 所在目录，方便同仓库使用）
 *   2. 环境变量 QA_APP_SOURCE（绝对路径，框架独立成仓库后必须用这个）
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, isAbsolute, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
/** app-automation/vision/src → app-automation */
export const FRAMEWORK_DIR = resolve(HERE, '..', '..');
export const PROJECTS_DIR = resolve(HERE, '..', 'projects');

export interface ProjectConfig {
  name: string;
  title?: string;
  packageName: string;
  /** App 源码根目录；相对 project.json 所在目录，或绝对路径 */
  appSourceDir?: string;
  /** app.json 位置，用来读深链 scheme */
  appJson?: string;
  scheme?: string;
  casesDir?: string;
  visionDir?: string;
  pythonDir?: string;
  /** 生成的 Appium 定位符写到哪里，相对框架根 */
  locatorsOut?: string;
}

let cachedName: string | null = null;
let cachedConfig: ProjectConfig | null = null;

/** 有哪些项目。 */
export function listProjects(): string[] {
  if (!existsSync(PROJECTS_DIR)) return [];
  return readdirSync(PROJECTS_DIR)
    .filter((n) => {
      const full = resolve(PROJECTS_DIR, n);
      return statSync(full).isDirectory() && existsSync(resolve(full, 'project.json'));
    })
    .sort();
}

/**
 * 当前用哪个项目。
 *
 * 没有显式指定时，如果 projects/ 下只有一个就自动用它；
 * 有多个却没说，直接报错——猜错项目比报错更费时间。
 */
export function activeProjectName(): string {
  if (cachedName) return cachedName;
  const picked = process.env.QA_PROJECT?.trim();
  if (picked) {
    cachedName = picked;
    return picked;
  }
  const all = listProjects();
  if (all.length === 1) {
    cachedName = all[0]!;
    return cachedName;
  }
  if (all.length === 0) {
    throw new Error(
      `projects/ 下没有任何项目。建一个：projects/<名字>/project.json（参考 projects/mono-capture/）`,
    );
  }
  throw new Error(
    `projects/ 下有 ${all.length} 个项目（${all.join('、')}），用 --project 或 QA_PROJECT 指定一个`,
  );
}

export function setActiveProject(name: string): void {
  cachedName = name;
  cachedConfig = null;
}

/** 项目目录（projects/<名字>/）。 */
export function projectDir(name = activeProjectName()): string {
  return resolve(PROJECTS_DIR, name);
}

export function projectConfig(): ProjectConfig {
  if (cachedConfig) return cachedConfig;
  const name = activeProjectName();
  const file = resolve(projectDir(name), 'project.json');
  if (!existsSync(file)) {
    throw new Error(`找不到项目配置：${file}`);
  }
  let raw: Partial<ProjectConfig>;
  try {
    raw = JSON.parse(readFileSync(file, 'utf8')) as Partial<ProjectConfig>;
  } catch (e) {
    throw new Error(
      `${file} 不是合法 JSON：${e instanceof Error ? e.message : String(e)}`,
    );
  }
  if (!raw.packageName) {
    throw new Error(`${file} 缺 packageName（被测 App 的包名，安卓用）`);
  }
  cachedConfig = { ...(raw as ProjectConfig), name: raw.name ?? name };
  return cachedConfig;
}

function resolveInProject(p: string): string {
  return isAbsolute(p) ? p : resolve(projectDir(), p);
}

/**
 * 被测 App 的源码根目录。
 *
 * 没配就返回空串，调用方自己决定是跳过还是报错——
 * 派生用例、文案漂移检查这些功能依赖源码，但没有源码时其余功能仍然可用。
 */
export function appSourceDir(): string {
  const fromEnv = process.env.QA_APP_SOURCE?.trim();
  if (fromEnv) return resolve(fromEnv);
  const cfg = projectConfig();
  if (!cfg.appSourceDir) return '';
  return resolveInProject(cfg.appSourceDir);
}

/** App 的 app.json（Expo 配置），读不到返回空串。 */
export function appJsonPath(): string {
  const cfg = projectConfig();
  if (!cfg.appJson) return '';
  const p = resolveInProject(cfg.appJson);
  return existsSync(p) ? p : '';
}

/** 用例目录：projects/<名字>/cases */
export function casesDir(): string {
  const cfg = projectConfig();
  return resolveInProject(cfg.casesDir ?? 'cases');
}

/** 项目专属的 python 模块目录：projects/<名字>/python */
export function pythonDir(): string {
  const cfg = projectConfig();
  return resolveInProject(cfg.pythonDir ?? 'python');
}

/** 生成的 Appium 定位符文件（相对框架根）。 */
export function locatorsOutPath(): string {
  const cfg = projectConfig();
  return resolve(FRAMEWORK_DIR, cfg.locatorsOut ?? 'pages/ui_locators.py');
}

/** 项目专属的 TypeScript 模块目录：projects/<名字>/vision */
export function projectVisionDir(): string {
  const cfg = projectConfig();
  return resolveInProject(cfg.visionDir ?? 'vision');
}

/** 人看的一行说明，启动时打印，避免跑错项目。 */
export function describeProject(): string {
  const cfg = projectConfig();
  const src = appSourceDir();
  return `${cfg.name}${cfg.title ? `（${cfg.title}）` : ''} ｜ 包名 ${cfg.packageName}` +
    ` ｜ App 源码 ${src || '<未配置，派生/漂移检查不可用>'}`;
}
