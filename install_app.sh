#!/usr/bin/env bash
# 一键把被测 App 装到设备上，并确认能打开。支持一台、指定一台、或全部。
#
# 用法：
#   ./install_app.sh app.apk              # 自动选：配置里那台在线就用它，否则唯一在线的那台
#   ./install_app.sh app.apk --device X   # 指定一台
#   ./install_app.sh app.apk --all        # 所有在线设备都装（多机并行测试用）
#   ./install_app.sh app.apk --clean      # 装完清数据（回到首次安装状态）
#   ./install_app.sh --all --uninstall    # 全部卸载

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APK=""
DEVICE=""
DO_ALL=0
DO_LAUNCH=1
DO_CLEAN=0
DO_UNINSTALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --device) DEVICE="${2:-}"; [ -n "$DEVICE" ] || { echo "--device 后面要跟序列号" >&2; exit 2; }; shift 2 ;;
    --all) DO_ALL=1; shift ;;
    --no-launch) DO_LAUNCH=0; shift ;;
    --clean) DO_CLEAN=1; shift ;;
    --uninstall) DO_UNINSTALL=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    -*) echo "未知参数：$1" >&2; exit 2 ;;
    *) APK="$1"; shift ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$1" >&2; exit 1; }

command -v adb >/dev/null 2>&1 || die "找不到 adb，先装 Android platform-tools 并放进 PATH"

# 包名：优先 .env，其次默认值
PKG="com.apex.collect"
if [ -f "$HERE/.env" ]; then
  from_env="$(grep -E '^[[:space:]]*ANDROID_APP_PACKAGE[[:space:]]*=' "$HERE/.env" | tail -1 | cut -d= -f2- | tr -d ' "'"'"'\r')"
  [ -n "${from_env:-}" ] && PKG="$from_env"
fi

online="$(adb devices | awk 'NR>1 && $2=="device" {print $1}')"
count="$(printf '%s' "$online" | grep -c . || true)"
[ "$count" -gt 0 ] || die "没有在线设备（adb devices 为空；插上手机并允许 USB 调试）"

# 决定要装哪几台
TARGETS=""
if [ "$DO_ALL" = "1" ]; then
  TARGETS="$online"
elif [ -n "$DEVICE" ]; then
  printf '%s\n' "$online" | grep -qx "$DEVICE" || {
    printf '  当前在线：\n'; printf '%s\n' "$online" | sed 's/^/    /'
    die "设备 $DEVICE 不在线"
  }
  TARGETS="$DEVICE"
else
  # 没指定：配置里那台在线就用它；否则只有一台在线就用它；多台就让人选
  cfg=""
  if [ -f "$HERE/.env" ]; then
    cfg="$(grep -E '^[[:space:]]*ANDROID_UDID[[:space:]]*=' "$HERE/.env" | tail -1 | cut -d= -f2- | tr -d ' "'"'"'\r')"
  fi
  if [ -n "${cfg:-}" ] && printf '%s\n' "$online" | grep -qx "$cfg"; then
    TARGETS="$cfg"
  elif [ "$count" -eq 1 ]; then
    TARGETS="$online"
    [ -n "${cfg:-}" ] && warn "配置的设备 $cfg 不在线，改用唯一在线的 $online"
  else
    printf '  检测到 %s 台在线设备：\n' "$count"
    printf '%s\n' "$online" | sed 's/^/    /'
    die "用 --device <序列号> 指定一台，或 --all 全部安装"
  fi
fi

[ "$DO_UNINSTALL" = "1" ] || {
  [ -n "$APK" ] || die "请给出 apk 路径，例如 ./install_app.sh ../build/app-release.apk"
  [ -f "$APK" ] || die "找不到文件：$APK"
}

install_one() {
  local dev="$1"
  local model ver out front
  model="$(adb -s "$dev" shell getprop ro.product.model 2>/dev/null | tr -d '\r')"
  printf '\n\033[1m▸ %s  %s\033[0m\n' "$dev" "${model:-未知机型}"

  if [ "$DO_UNINSTALL" = "1" ]; then
    if adb -s "$dev" uninstall "$PKG" >/dev/null 2>&1; then ok "已卸载 $PKG"; else warn "$PKG 本来就没装"; fi
    return 0
  fi

  ok "安装包 $(du -h "$APK" | cut -f1)"
  echo "  安装中…"
  if ! out="$(adb -s "$dev" install -r "$APK" 2>&1)"; then
    echo "$out" | sed 's/^/    /'
    warn "安装失败（签名不一致先 --uninstall；降级需 adb install -r -d；也可能是空间不足）"
    return 1
  fi
  echo "$out" | grep -qi success || { echo "$out" | sed 's/^/    /'; warn "adb 没回 Success"; return 1; }
  ok "安装完成"

  ver="$(adb -s "$dev" shell dumpsys package "$PKG" 2>/dev/null | grep -m1 versionName | tr -d '\r')"
  [ -n "$ver" ] && ok "${ver##*versionName=}"

  if [ "$DO_CLEAN" = "1" ]; then
    adb -s "$dev" shell pm clear "$PKG" >/dev/null && ok "已清数据（下次启动是首次安装状态）"
  fi

  [ "$DO_LAUNCH" = "1" ] || return 0
  echo "  启动中…"
  adb -s "$dev" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  sleep 3
  front="$(adb -s "$dev" shell dumpsys window 2>/dev/null | grep -m1 mCurrentFocus | tr -d '\r')"
  if echo "$front" | grep -q "$PKG"; then
    ok "已在前台"
  else
    warn "没确认到前台：${front:-读不到}"
  fi
  return 0
}

FAILED=0
for d in $TARGETS; do
  install_one "$d" || FAILED=1
done

echo
if [ "$FAILED" = "1" ]; then
  echo "有设备安装失败，见上面 ⚠。"
  exit 1
fi
echo "完成，共 ${count} 台在线，本次处理 $(printf '%s\n' "$TARGETS" | grep -c .) 台。"
