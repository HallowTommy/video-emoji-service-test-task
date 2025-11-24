#!/bin/sh
set -e

# запускаем бота в фоне
python -m app.bot &

# запускаем API
uvicorn app.main:app --host 0.0.0.0 --port 8000
