#!/usr/bin/env bash
# AI Daily News 项目级 Python 启动器
# 用途：统一使用 Python 3.10+（项目依赖该版本语法）
# 用法：
#   ./run.sh -m layers.syncer --date 2026-04-18 --products "CodeFuse"
#   ./run.sh scripts/list_feishu_fields.py
#   ./run.sh -c "import layers; print(layers.__all__)"
#
# Python 解释器选择顺序：
#   1. 环境变量 $PYTHON_BIN（如需自定义，可在 .env 或 shell 中设置）
#   2. 依次探测 python3.14 → python3.13 → python3.12 → python3.11 → python3.10
#   3. 回退到 python3（要求 >= 3.10，否则报错退出）

set -e

# 切到脚本所在目录，保证相对路径正确
cd "$(dirname "$0")"

# 如果存在 .env，自动加载（仅读取 PYTHON_BIN，避免污染其它变量）
if [ -f .env ]; then
  _env_python_bin=$(grep -E '^\s*PYTHON_BIN\s*=' .env | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | xargs || true)
  if [ -n "$_env_python_bin" ] && [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN="$_env_python_bin"
  fi
fi

# 按优先级探测
if [ -z "$PYTHON_BIN" ]; then
  for _candidate in python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$_candidate" >/dev/null 2>&1; then
      PYTHON_BIN=$(command -v "$_candidate")
      break
    fi
  done
fi

# 最后回退到 python3，并校验版本
if [ -z "$PYTHON_BIN" ]; then
  if command -v python3 >/dev/null 2>&1; then
    _ver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    _major=$(echo "$_ver" | cut -d. -f1)
    _minor=$(echo "$_ver" | cut -d. -f2)
    if [ "$_major" -ge 3 ] && [ "$_minor" -ge 10 ]; then
      PYTHON_BIN=$(command -v python3)
    fi
  fi
fi

if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
  echo "❌ 未找到可用的 Python 3.10+ 解释器" >&2
  echo "   请安装 Python 3.10+，或在环境变量/.env 中设置 PYTHON_BIN" >&2
  exit 1
fi

exec "$PYTHON_BIN" -u "$@"
