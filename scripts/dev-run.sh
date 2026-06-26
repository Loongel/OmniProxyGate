#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
export DATA_DIR="${DATA_DIR:-$PWD/data}"
export GENERATED_HTTP_DIR="${GENERATED_HTTP_DIR:-$PWD/data/nginx/conf}"
export GENERATED_STREAM_DIR="${GENERATED_STREAM_DIR:-$PWD/data/nginx/stream}"
export LOG_DIR="${LOG_DIR:-$PWD/data/logs}"
export DRY_RUN="${DRY_RUN:-true}"
mkdir -p "$DATA_DIR" "$GENERATED_HTTP_DIR" "$GENERATED_STREAM_DIR" "$LOG_DIR"
cd ui
"$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
