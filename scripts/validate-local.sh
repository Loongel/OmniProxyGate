#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m compileall ui/app ui/tests
"$PYTHON_BIN" ui/tests/test_config_generator.py
"$PYTHON_BIN" ui/tests/test_security.py
