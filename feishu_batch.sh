#!/bin/bash
# 飞书机器人触发「批量 APL 函数生成」的包装脚本
# 用法：./feishu_batch.sh [--dry-run]

set -euo pipefail

TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCK_FILE="$TOOLS_DIR/.batch.lock"
cd "$TOOLS_DIR"

# 防止并发执行
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "⚠️ 批量任务正在运行中 (PID=$PID)，请稍后再试"
        exit 1
    fi
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

DRY_RUN=""
REGENERATE=""
HEADED=""
for arg in "$@"; do
    case "$arg" in
        --dry-run)     DRY_RUN="--dry-run" ;;
        --regenerate) REGENERATE="--regenerate" ;;
        --headed)     HEADED="--headed" ;;
    esac
done

echo "=============================="
echo "APL 批量生成启动"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================="

python3 batch_runner.py $DRY_RUN $REGENERATE $HEADED 2>&1

EXIT_CODE=$?
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 批量执行完成"
else
    echo "❌ 批量执行失败 (exit=$EXIT_CODE)"
fi
