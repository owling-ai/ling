#!/usr/bin/env bash
# 一键启动（uv 管理环境）：./run.sh [uvicorn 额外参数]
set -e
cd "$(dirname "$0")"
uv sync -q
host="${LING_HOST:-0.0.0.0}"
port="${LING_PORT:-8888}"
export LING_ALLOW_UNAUTHENTICATED="${LING_ALLOW_UNAUTHENTICATED:-1}"
exec uv run uvicorn backend.app:app --host "$host" --port "$port" "$@"
