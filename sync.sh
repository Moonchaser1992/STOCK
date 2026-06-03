#!/bin/bash
# 手动同步选股数据
set -e
cd "$(dirname "$0")"

echo "=== Git 同步选股数据 ==="

echo "[1/3] 拉取远端..."
git pull --no-rebase

echo "[2/3] 添加本地结果..."
git add data/results/

if git diff --cached --quiet; then
    echo "  无新结果需要提交"
else
    git commit -m "results: sync $(date +%Y-%m-%d)"
fi

echo "[3/3] 推送到远端..."
git push

echo "=== 同步完成 ==="
