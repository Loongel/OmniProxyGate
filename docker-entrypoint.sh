#!/usr/bin/env sh
set -eu

OMNI_RUN_GATEWAY="${OMNI_RUN_GATEWAY:-true}"
OMNI_RUN_UI="${OMNI_RUN_UI:-true}"
OMNI_UI_HOST="${OMNI_UI_HOST:-0.0.0.0}"
OMNI_UI_PORT="${OMNI_UI_PORT:-8080}"

truthy() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

pids=""
term_children() {
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap term_children INT TERM

if truthy "$OMNI_RUN_GATEWAY"; then
  for f in /docker-entrypoint.d/*.sh; do
    [ -e "$f" ] && . "$f"
  done
  cd /app
  python -m app.render_active_configs
  nginx -t
  nginx -g 'daemon off;' &
  pids="$pids $!"
fi

if truthy "$OMNI_RUN_UI"; then
  cd /app
  uvicorn app.main:app --host "$OMNI_UI_HOST" --port "$OMNI_UI_PORT" &
  pids="$pids $!"
fi

if [ -z "$pids" ]; then
  echo "OMNI_RUN_GATEWAY and OMNI_RUN_UI are both disabled; nothing to run" >&2
  exit 1
fi

set +e
while :; do
  for pid in $pids; do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid"
      status=$?
      term_children
      exit "$status"
    fi
  done
  sleep 1
done
