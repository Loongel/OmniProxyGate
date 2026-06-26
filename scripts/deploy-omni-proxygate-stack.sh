#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
STACK_NAME="${OMNI_STACK_NAME:-omni-proxygate}"
DATA_ROOT="${OMNI_DATA_ROOT:-/opt/omni-proxygate}"
DOCKER_BIN="${DOCKER_BIN:-sudo -E -n docker}"

sudo -E -n mkdir -p \
  "$DATA_ROOT/data" \
  "$DATA_ROOT/nginx/conf" \
  "$DATA_ROOT/nginx/stream" \
  "$DATA_ROOT/certs" \
  "$DATA_ROOT/logs"

$DOCKER_BIN stack deploy --with-registry-auth -c deploy/omni-proxygate.stack.yml "$STACK_NAME"
