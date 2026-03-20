#!/bin/bash
# 飞书机器人触发 APL 流水线的包装脚本
# 用法：./feishu_run.sh [--step generate|deploy|all]
#
# 功能：
# - 执行完整流水线（生成 + 部署 + 测试）
# - 将关键日志输出到 stdout，供 OpenClaw agent 捕获后发回飞书

set -euo pipefail

TOOLS_DIR="/Users/yanye/code/test拨号/_tools"
LOCK_FILE="$TOOLS_DIR/.pipeline.lock"
cd "$TOOLS_DIR"

# 防止并发执行（同一时刻只允许一个流水线）
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "⚠️ 流水线正在运行中 (PID=$PID)，请稍后再试"
        exit 1
    fi
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

STEP="${1:-all}"

echo "=============================="
echo "APL 流水线启动: step=$STEP"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================="

# 检查 req.yml 是否存在
if [ ! -f "req.yml" ]; then
    echo "❌ 错误: req.yml 不存在，请先生成需求文件"
    exit 1
fi

# 显示当前需求概要
echo ""
echo "📋 当前需求:"
grep -E "^code_name:|^object_api:|^function_type:" req.yml | sed 's/^/  /'
echo ""

# 执行流水线
echo "🚀 开始执行..."
python3 pipeline.py --req req.yml 2>&1

EXIT_CODE=$?
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 流水线执行完成"
else
    echo "❌ 流水线执行失败 (exit=$EXIT_CODE)"
fi
