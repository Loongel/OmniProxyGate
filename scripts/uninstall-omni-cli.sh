#!/usr/bin/env sh
set -eu
BIN_DIR="${OMNI_CLI_BIN_DIR:-$HOME/.local/bin}"
BIN_NAME="${OMNI_CLI_BIN_NAME:-omni}"
TARGET="$BIN_DIR/$BIN_NAME"
if [ -e "$TARGET" ]; then
  rm -f "$TARGET"
  echo "removed $TARGET"
else
  echo "not installed: $TARGET"
fi
