#!/bin/bash
# 飞书机器人触发「批量 APL 函数生成」的包装脚本
# 用法：./feishu_batch.sh [--dry-run]

set -euo pipefail

TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$TOOLS_DIR"

DRY_RUN=""
REGENERATE=""
HEADLESS=""
HEADED=""
NO_REFRESH=""
NO_RETRY=""
NO_NOTIFY=""
RUNTIME_PRECHECK=""
for arg in "$@"; do
    case "$arg" in
        --dry-run)     DRY_RUN="--dry-run" ;;
        --regenerate) REGENERATE="--regenerate" ;;
        --headless)   HEADLESS="--headless" ;;
        --headed)     HEADED="--headed" ;;
        --no-refresh) NO_REFRESH="--no-refresh" ;;
        --no-retry)   NO_RETRY="--no-retry" ;;
        --no-notify)  NO_NOTIFY="--no-notify" ;;
        --runtime-precheck) RUNTIME_PRECHECK="--runtime-precheck" ;;
    esac
done

echo "=============================="
echo "APL 批量生成启动"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================="

LOG_FILE="batch_live_$(date '+%Y%m%d_%H%M%S').log"
echo "日志文件: $TOOLS_DIR/$LOG_FILE"

python3 batch_runner.py \
  $DRY_RUN \
  $REGENERATE \
  $HEADLESS \
  $HEADED \
  $NO_REFRESH \
  $NO_RETRY \
  $NO_NOTIFY \
  $RUNTIME_PRECHECK \
  2>&1 | tee "$LOG_FILE"

EXIT_CODE=$?
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 批量执行完成"
else
    echo "❌ 批量执行失败 (exit=$EXIT_CODE)"
fi
