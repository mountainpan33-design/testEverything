/**
 * 项目专属障碍（这一份是唯一需要按项目改的地方）。
 *
 * 只写「跟这个 App 的文案绑死」的障碍。通用的系统级障碍在 obstacles.ts 的
 * GENERIC_OBSTACLES 里，不用在这里重复。
 *
 * 判断标准：
 *   - 描述里出现了这个 App 特有的字样（按钮文案、产品名）→ 放这里
 *   - 描述的是系统界面（通知中心、权限框）→ 放 obstacles.ts
 *
 * 2026-11-20 真机：pm clear 后冷启动弹「发现新版本」，盖住登录页，
 * 后续点击全落在弹窗坐标上，屏幕滑进通知中心，最后报「没有出现协议同意页」。
 */
import type { Obstacle } from '../../../src/obstacles.js';

export const PROJECT_OBSTACLES: Obstacle[] = [
  {
    id: 'update-prompt',
    detect:
      '一个白底模态弹窗，标题是「发现新版本 / Update available」，' +
      '正文提到不重新安装即可更新；按钮有三个，颜色最突出的是「立即更新」，' +
      '另外两个是「下次启动更新」和「暂不更新」',
    remedy: '点「暂不更新」按钮（不要点「立即更新」，也不要点「下次启动更新」）',
    verify: '这个更新弹窗已经消失，能看到它下面的页面内容',
    attribution: 'environment',
  },
];
