#!/usr/bin/env bash
# 一键把测试环境装好：Python venv、依赖、node_modules、配置检查、设备检查。
#
# 新机器或同事接手时跑一次就行。脚本是幂等的，重复跑不会坏。
#
# 用法：
#   ./setup.sh              # 全部装 + 检查
#   ./setup.sh --check-only # 只检查，不安装
#   ./setup.sh --skip-node  # 不动 node_modules（已经装好了）

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
VISION="$HERE/vision"

CHECK_ONLY=0
SKIP_NODE=0
for arg in "$@"; do
  case "$arg" in
    --check-only) CHECK_ONLY=1 ;;
    --skip-node) SKIP_NODE=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FAILED=1; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }
FAILED=0

step "1/6 基础工具"
if command -v python3 >/dev/null 2>&1; then
  ok "python3 $(python3 -V 2>&1 | awk '{print $2}')"
else
  bad "缺 python3（macOS: xcode-select --install）"
fi
if command -v node >/dev/null 2>&1; then
  ok "node $(node -v)"
else
  bad "缺 node（需要 ≥20.19 / 22.12 / 24）"
fi
if command -v npm >/dev/null 2>&1; then ok "npm $(npm -v)"; else bad "缺 npm"; fi
if command -v adb >/dev/null 2>&1; then
  ok "adb $(adb version 2>/dev/null | head -1 | awk '{print $NF}')"
else
  bad "缺 adb（Android platform-tools，并确保在 PATH 里）"
fi

if [ "$FAILED" = "1" ] && [ "$CHECK_ONLY" = "0" ]; then
  echo
  echo "基础工具没齐，先装上面缺的再跑一次。"
  exit 1
fi

step "2/6 Python 虚拟环境"
if [ -d "$HERE/.venv" ]; then
  ok ".venv 已存在"
else
  if [ "$CHECK_ONLY" = "1" ]; then
    bad ".venv 不存在"
  else
    python3 -m venv "$HERE/.venv"
    ok "已创建 .venv"
  fi
fi

PY="$HERE/.venv/bin/python"
if [ -x "$PY" ]; then
  ok "解释器：$("$PY" -V 2>&1)"
else
  bad ".venv/bin/python 不可用"
fi

step "3/6 Python 依赖"
if [ "$CHECK_ONLY" = "1" ]; then
  if "$PY" -c "import appium, pytest, requests" >/dev/null 2>&1; then
    ok "appium / pytest / requests 都在"
  else
    bad "Python 依赖不全（跑不带 --check-only 的版本会装）"
  fi
else
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r "$HERE/requirements.txt"
  ok "requirements.txt 已装"
fi

step "4/6 Node 依赖"
check_node_deps() {
  local dir="$1" label="$2"
  if [ ! -d "$dir/node_modules" ]; then
    bad "$label 缺 node_modules"
    return 1
  fi
  # 只有真的装了 esbuild 才需要检查平台（它带原生二进制，跨平台复制必炸）。
  # 仓库根是 React Native，压根没有 esbuild；vision 才有。
  if [ ! -d "$dir/node_modules/esbuild" ]; then
    ok "$label node_modules 正常（未使用 esbuild）"
    return 0
  fi
  local want
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) want="@esbuild/darwin-arm64" ;;
    Darwin-x86_64) want="@esbuild/darwin-x64" ;;
    Linux-aarch64|Linux-arm64) want="@esbuild/linux-arm64" ;;
    Linux-x86_64) want="@esbuild/linux-x64" ;;
    *) want="" ;;
  esac
  if [ -n "$want" ] && [ ! -d "$dir/node_modules/$want" ]; then
    bad "$label 的 node_modules 是别的平台装的（缺 ${want}），删掉重装"
    return 1
  fi
  ok "$label node_modules 正常"
}
if [ "$SKIP_NODE" = "1" ]; then
  warn "跳过 Node 依赖检查（--skip-node）"
elif [ "$CHECK_ONLY" = "1" ]; then
  check_node_deps "$REPO" "仓库根（jest）" || true
  check_node_deps "$VISION" "vision" || true
else
  if [ ! -d "$REPO/node_modules" ]; then
    echo "  安装仓库根依赖（jest，可能要几分钟）…"
    (cd "$REPO" && npm install --no-audit --no-fund)
  fi
  check_node_deps "$REPO" "仓库根（jest）" || true

  if [ ! -d "$VISION/node_modules" ]; then
    echo "  安装 vision 依赖（Midscene）…"
    (cd "$VISION" && npm install --no-audit --no-fund)
  fi
  check_node_deps "$VISION" "vision" || true
fi

step "5/6 配置"
if [ -f "$HERE/.env" ]; then
  ok ".env 存在"
  missing=""
  for key in QA_USERNAME QA_PASSWORD QA_API_BASE ANDROID_APP_PACKAGE; do
    grep -qE "^[[:space:]]*$key[[:space:]]*=[[:space:]]*[^[:space:]]" "$HERE/.env" || missing="$missing $key"
  done
  if [ -n "$missing" ]; then bad "app-automation/.env 缺：$missing"; else ok "常用配置项齐全"; fi
else
  bad "缺 app-automation/.env（cp .env.example .env 后填账号）"
fi
if [ -f "$VISION/.env" ]; then
  ok "vision/.env 存在"
  for key in MIDSCENE_MODEL_BASE_URL MIDSCENE_MODEL_API_KEY MIDSCENE_MODEL_NAME MIDSCENE_MODEL_FAMILY; do
    grep -qE "^[[:space:]]*$key[[:space:]]*=[[:space:]]*[^[:space:]]" "$VISION/.env" || bad "vision/.env 缺 $key"
  done
else
  bad "缺 vision/.env（cp vision/.env.example vision/.env，填模型四项）"
fi

step "6/6 设备"
if ! command -v adb >/dev/null 2>&1; then
  bad "没有 adb，跳过设备检查"
  devices=""
elif [ -z "${devices:-}" ]; then
  devices="$(adb devices 2>/dev/null | awk 'NR>1 && $2=="device" {print $1}')"
fi
if [ -n "${devices:-}" ]; then
  for d in $devices; do
    model="$(adb -s "$d" shell getprop ro.product.model 2>/dev/null | tr -d '\r')"
    ok "$d  ${model:-未知机型}"
  done
elif command -v adb >/dev/null 2>&1; then
  bad "没有已授权的设备（adb devices 为空；插上手机并允许 USB 调试）"
fi

# 配置里写的那台设备必须真的在线，否则跑到视觉层才报「device not found」
if [ -f "$HERE/.env" ] && command -v adb >/dev/null 2>&1; then
  cfg_udid="$(grep -E '^[[:space:]]*ANDROID_UDID[[:space:]]*=' "$HERE/.env" | tail -1 | cut -d= -f2- | tr -d ' "\r')"
  if [ -n "${cfg_udid:-}" ]; then
    if printf '%s\n' "${devices:-}" | grep -qx "$cfg_udid"; then
      ok "配置里的设备 $cfg_udid 在线"
    else
      # 不算失败：跑的时候会自动降级到唯一在线的那台，多台时才会要求 --device
      warn "配置里的 ANDROID_UDID=$cfg_udid 不在线；当前在线：${devices:-无}"
      warn "跑的时候会自动用在线的那台；多台同时在线时用 --device 指定"
    fi
  fi
  dev_count="$(printf '%s\n' "${devices:-}" | grep -c . || true)"
  if [ "${dev_count:-0}" -gt 1 ]; then
    warn "检测到 $dev_count 台设备同时在线，跑用例时要用 --device <序列号> 指定"
  fi
fi

echo
if [ "$FAILED" = "1" ]; then
  echo "有项目没通过，见上面的 ✗。"
  exit 1
fi
echo "环境就绪。下一步："
echo "  .venv/bin/python -m verification.run_all --no-vision    # 先验代码层（快）"
echo "  .venv/bin/python -m verification.run_all                # 再跑视觉层（真机，慢）"
