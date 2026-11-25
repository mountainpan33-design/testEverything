#!/usr/bin/env bash
# 一键入口：装环境 → （可选）装包 → 跑全部用例 → 打开报告。
#
# 用法：
#   ./go.sh                  # 全部：代码层 + 视觉层（真机）
#   ./go.sh --quick          # 只跑代码层（单元 + 门禁 + 接口），不碰设备，几十秒
#   ./go.sh --check          # 只检查环境，不跑用例
#   ./go.sh --apk app.apk    # 先把包装上再跑
#   ./go.sh --device <序列号> # 多台设备时指定跑哪台
#   ./go.sh --golden         # 额外跑黄金链路（真机 + 录制额度）
#   ./go.sh --no-open        # 跑完不自动打开报告
#   ./go.sh --review         # 新项目接入：从源码派生冒烟用例并生成审核页
#   ./go.sh --import-review f.json  # 把导出的审核结果写回用例
#   ./go.sh --project <名字>        # 测哪个项目（projects/ 下有多份时必填）
#
# 其他参数会原样传给 verification.run_all，例如 --with-artifact。

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUICK=0
CHECK_ONLY=0
REVIEW_ONLY=0
IMPORT_REVIEW=""
APK=""
DEVICE=""
OPEN_REPORT=1
PASSTHRU=()

while [ $# -gt 0 ]; do
  case "$1" in
    --quick) QUICK=1; shift ;;
    --check) CHECK_ONLY=1; shift ;;
    --no-open) OPEN_REPORT=0; shift ;;
    --golden) PASSTHRU+=(--with-golden); shift ;;
    --review) REVIEW_ONLY=1; shift ;;
    --project) QA_PROJECT="${2:-}"; [ -n "$QA_PROJECT" ] || { echo "--project 后面要跟项目名" >&2; exit 2; }; export QA_PROJECT; shift 2 ;;
    --import-review) IMPORT_REVIEW="${2:-}"; [ -n "$IMPORT_REVIEW" ] || { echo "--import-review 后面要跟 JSON 路径" >&2; exit 2; }; shift 2 ;;
    --apk) APK="${2:-}"; [ -n "$APK" ] || { echo "--apk 后面要跟文件路径" >&2; exit 2; }; shift 2 ;;
    --device) DEVICE="${2:-}"; [ -n "$DEVICE" ] || { echo "--device 后面要跟序列号" >&2; exit 2; }; shift 2 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) PASSTHRU+=("$1"); shift ;;
  esac
done

cd "$HERE" || exit 1

bold() { printf '\n\033[1m━━ %s ━━\033[0m\n' "$1"; }

# ---------------------------------------------------------------- 审核环节
# 接入新项目、或者页面加了不少之后走一遍：
#   1. 从源码派生结构性冒烟用例（免费、不碰设备）
#   2. 生成审核页，人在浏览器里逐条过
#   3. 导出 JSON 后 --import-review 写回
if [ "$REVIEW_ONLY" = "1" ] || [ -n "$IMPORT_REVIEW" ]; then
  VISION="$HERE/vision"
  if [ ! -d "$VISION/node_modules" ]; then
    echo "vision/node_modules 还没装，先跑 ./setup.sh"
    exit 1
  fi
  if [ -n "$IMPORT_REVIEW" ]; then
    bold "导入审核结果"
    ( cd "$VISION" && npx tsx src/cli.ts --import-review "$IMPORT_REVIEW" )
  else
    bold "1/2 从源码派生冒烟用例"
    ( cd "$VISION" && npx tsx src/cli.ts --derive )
    bold "2/2 生成审核页"
    ( cd "$VISION" && npx tsx src/cli.ts --review-page )
    PAGE="$VISION/cases/review.html"
    if [ -f "$PAGE" ] && command -v open >/dev/null 2>&1; then
      open "$PAGE" 2>/dev/null || true
    fi
    echo
    echo "在页面上逐条点「通过 / 驳回 / 待定」，然后点右下角「导出审核结果」，再执行："
    echo "  ./go.sh --import-review ~/Downloads/review-result.json"
  fi
  exit $?
fi

# ---------------------------------------------------------------- 1. 环境
bold "1/3 环境"
# --check 只检查，绝不安装
if [ "$CHECK_ONLY" = "1" ]; then
  ./setup.sh --check-only
  exit $?
fi

if ./setup.sh --check-only >/tmp/ego-setup-check.log 2>&1; then
  grep -E '✓|!' /tmp/ego-setup-check.log | sed 's/^  //' | head -20
  echo "  （检查通过）"
else
  echo "  环境还不齐，开始安装…"
  if ! ./setup.sh; then
    echo
    echo "环境安装没通过，见上面 ✗。修好后再跑 ./go.sh"
    exit 1
  fi
fi

# ---------------------------------------------------------------- 2. 装包（可选）
if [ -n "$APK" ]; then
  bold "2/3 安装被测 App"
  if ! ./install_app.sh "$APK" ${DEVICE:+--device "$DEVICE"}; then
    echo "装包失败，先解决再跑用例。"
    exit 1
  fi
else
  bold "2/3 安装被测 App"
  echo "  跳过（要装包就加 --apk <路径>）"
fi

# ---------------------------------------------------------------- 3. 跑用例
bold "3/3 执行用例"
PY="$HERE/.venv/bin/python"
[ -x "$PY" ] || { echo "找不到 .venv/bin/python，先跑 ./setup.sh" >&2; exit 1; }

if [ "$QUICK" = "1" ]; then
  echo "  模式：只跑代码层（--no-vision）"
  "$PY" -m verification.run_all --no-vision ${DEVICE:+--device "$DEVICE"} ${PASSTHRU[@]+"${PASSTHRU[@]}"}
else
  echo "  模式：代码层 + 视觉层（真机，可能要 40 分钟以上）"
  "$PY" -m verification.run_all ${DEVICE:+--device "$DEVICE"} ${PASSTHRU[@]+"${PASSTHRU[@]}"}
fi
RC=$?

REPORT="$HERE/vision/midscene_run/reports/all-latest.html"
echo
if [ -f "$REPORT" ]; then
  echo "报告：$REPORT"
  if [ "$OPEN_REPORT" = "1" ] && command -v open >/dev/null 2>&1; then
    open "$REPORT" 2>/dev/null || true
  fi
else
  echo "没有生成报告，看上面的输出。"
fi
exit $RC
