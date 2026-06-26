#!/usr/bin/env sh
set -eu

BIN_DIR="${OMNI_CLI_BIN_DIR:-$HOME/.local/bin}"
BIN_NAME="${OMNI_CLI_BIN_NAME:-omni}"
SRC_URL="${OMNI_CLI_URL:-}"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LOCAL_SRC="$SCRIPT_DIR/../cli/omni"

mkdir -p "$BIN_DIR"
TARGET="$BIN_DIR/$BIN_NAME"

if [ -n "$SRC_URL" ]; then
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$SRC_URL" -o "$TARGET"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TARGET" "$SRC_URL"
  else
    echo "install failed: curl or wget is required for OMNI_CLI_URL" >&2
    exit 1
  fi
elif [ -f "$LOCAL_SRC" ]; then
  cp "$LOCAL_SRC" "$TARGET"
else
  echo "install failed: set OMNI_CLI_URL or run this script from the OmniProxyGate repo" >&2
  exit 1
fi

chmod +x "$TARGET"
echo "installed $TARGET"
echo "configure: export OMNI_URL=https://omni.example.com && export OMNI_AGENT_API_TOKEN=..."
echo "test: $BIN_NAME doctor"
