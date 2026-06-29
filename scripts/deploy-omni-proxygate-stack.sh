#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
STACK_NAME="${OMNI_STACK_NAME:-omni-proxygate}"
DOCKER_BIN="${DOCKER_BIN:-sudo -E -n docker}"

$DOCKER_BIN stack deploy --with-registry-auth -c deploy/omni-proxygate.stack.yml "$STACK_NAME"
