#!/usr/bin/env bash
# 一键启动：python3 -m venv 可选；最少只需要 fastapi + uvicorn
set -e
cd "$(dirname "$0")"
pip install -r requirements.txt -q
exec uvicorn backend.app:app --host 0.0.0.0 --port 8000 "$@"
