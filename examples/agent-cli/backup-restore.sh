#!/usr/bin/env sh
set -eu

stamp=$(date +%Y%m%d-%H%M%S)
omni doctor
omni export -o "omni-backup-$stamp.json"
omni status

# Restore is destructive; review the file first.
# omni import omni-backup-$stamp.json --yes
# omni preview --section all
# omni apply --yes
