#!/usr/bin/env bash
# MiniYuxi 提交前硬卡点（360 七坑 · 坑3 一键生成防护）
#
# 这是卡点的「源真理」：提交进仓库，所有协作者共用。
# 安装方式（任选其一）：
#   1) 复制到 git 钩子目录：
#        cp scripts/verify-precommit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
#   2) 或统一钩子路径（推荐团队）：
#        git config core.hooksPath scripts
# 注：本地卡点仅为便利；真正的「合并硬闸门」是 .github/workflows/verify.yml（PR 未过即阻断）。
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

PY="${PYTHON:-python}"

run() { echo "▶ $*"; "$@"; }

echo "===== MiniYuxi 提交前卡点 ====="

# 1) 前端未定义符号扫描（纯 stdlib，必跑）
run "$PY" tests/_scan_undef.py

# 2) 法条「无引用不出文」闸门单测（纯 stdlib，必跑）
run "$PY" tests/_verify_citation_gate.py

# 3) 前端路由冒烟（需 fastapi+httpx；本机缺失则提示，由 CI 兜底，不阻断本地提交）
if "$PY" -c "import fastapi, httpx" >/dev/null 2>&1; then
  run "$PY" tests/_smoke_routes.py
else
  echo "⚠ 本机未装 fastapi/httpx，跳过路由冒烟（CI 会自动跑）。"
  echo "  如需本地强校验：pip install -r requirements.txt httpx"
fi

echo "===== 卡点全部通过 ====="
