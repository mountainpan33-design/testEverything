// js-yaml 没有自带类型，这里只声明我们要用的两个函数。
declare module 'js-yaml' {
  export function load(input: string): unknown;
  export function dump(obj: unknown, opts?: unknown): string;
  const yaml: { load: typeof load; dump: typeof dump };
  export default yaml;
}
