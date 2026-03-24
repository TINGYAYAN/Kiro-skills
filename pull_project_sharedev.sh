#!/bin/bash
# 拉取指定项目的对象和函数到 sharedev_pull/{项目}/
# 用法: bash pull_project_sharedev.sh <项目名>
# 需先在 config.local.yml 配置 fxiaoke.sharedev_projects.{项目名}

set -e
PROJECT="${1:?用法: bash pull_project_sharedev.sh <项目名>}"
TOOLS="$(dirname "$0")"
cd "$TOOLS"

echo "=== 拉取项目: $PROJECT ==="
python3 -m fetcher.sharedev_client --objects --project "$PROJECT"
python3 -m fetcher.sharedev_client --functions --project "$PROJECT"
echo "=== 拉取完成 ==="
