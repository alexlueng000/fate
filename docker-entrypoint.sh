#!/bin/bash
set -e

# ============================================
# Docker 启动脚本
# 根据 APP_ENV 环境变量选择启动模式
# ============================================

echo "============================================"
echo "Fate Backend Starting..."
echo "APP_ENV: ${APP_ENV:-production}"
echo "============================================"

# 根据 APP_ENV 选择启动模式
if [ "$APP_ENV" = "development" ]; then
    echo "Starting in DEVELOPMENT mode (hot reload enabled)..."
    exec python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
else
    echo "Starting in PRODUCTION mode (multi-worker)..."
    exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
fi
