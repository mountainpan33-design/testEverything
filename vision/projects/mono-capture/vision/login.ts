/**
 * 登录相关的少量工具。
 *
 * 注意这里已经没有「登录流程」了——填账号、点登录、等跳转都写进 cases/*.yaml，
 * 谁要测什么就在用例里写清楚，不再藏在一个公共函数里。
 * 这个文件只剩执行层和前置准备都要用的两样东西：运行上下文、以及「这是不是登录页」。
 */
import type { AndroidAgent } from '@midscene/android';

import { uiNodes } from '../../../src/adb.js';

export interface Ctx {
  packageName: string;
  username: string;
  password: string;
  /** 可选：失败时用来读设备现场（当前输入法），不参与登录本身 */
  deviceId?: string;
}

/** 输入框类节点（RN 的 TextInput 在控件树里是 EditText）。 */
function editTexts(nodes: { cls: string; text: string }[]) {
  return nodes.filter((n) => /EditText/i.test(n.cls));
}

/**
 * 当前是否停在登录页。
 *
 * 先用控件树判（免费）：有两个输入框就是登录页；已经出现底部「首页/我的」就肯定不是。
 * 判断不了才问模型——能用便宜手段判断的，不叫模型。
 */
export async function isOnLoginPage(agent: AndroidAgent): Promise<boolean> {
  const nodes = await uiNodes();
  if (nodes.length) {
    if (editTexts(nodes).length >= 2) return true;
    const words = nodes.map((n) => `${n.text} ${n.desc}`).join(' ');
    if (words.includes('首页') && words.includes('我的')) return false;
  }
  return agent.aiBoolean(
    '当前界面是登录页：能看到「用户名」「密码」两个输入框，以及「登录」按钮',
  );
}
