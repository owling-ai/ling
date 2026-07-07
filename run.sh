#!/usr/bin/env bash
# 一键启动（uv 管理环境）：./run.sh [uvicorn 额外参数]
set -e
cd "$(dirname "$0")"
uv sync -q
exec uv run uvicorn backend.app:app --host 0.0.0.0 --port 8000 "$@"
