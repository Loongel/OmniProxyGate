#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export SAMPLE_DATA_JSON="${SAMPLE_DATA_JSON:-/app/examples/sample-config.json}"
echo "Set SAMPLE_DATA_JSON=$SAMPLE_DATA_JSON for the UI container and restart it to load sample data into an empty database."
