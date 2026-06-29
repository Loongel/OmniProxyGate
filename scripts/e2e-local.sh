#!/bin/sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOCKER_BIN="${DOCKER_BIN:-sudo -E -n docker}"
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.e2e.yml"
UI_PORT="${UI_PORT:-50808}"
GATEWAY_HTTP_PORT="${GATEWAY_HTTP_PORT:-50080}"
GATEWAY_HTTPS_PORT="${GATEWAY_HTTPS_PORT:-50443}"
OMNI_DATA_ROOT="${OMNI_DATA_ROOT:-$ROOT_DIR/.e2e-data}"
COOKIE_JAR="$(mktemp)"

docker_cmd() {
  ${DOCKER_BIN} "$@"
}

cleanup() {
  status=$?
  cd "$ROOT_DIR"
  docker_cmd compose $COMPOSE_FILES down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f "$COOKIE_JAR"
  sudo -E -n rm -rf "$OMNI_DATA_ROOT"
  exit "$status"
}

wait_for_health() {
  url="$1"
  attempts=60
  while [ "$attempts" -gt 0 ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 2
  done
  return 1
}

wait_for_gateway() {
  url="$1"
  expected="$2"
  attempts=30
  while [ "$attempts" -gt 0 ]; do
    response="$(curl -fsS --noproxy '*' --http1.1 -k --resolve "proxy.example.com:${GATEWAY_HTTPS_PORT}:127.0.0.1" "$url" 2>/dev/null || true)"
    case "$response" in
      *"$expected"*)
        printf '%s\n' "$response"
        return 0
        ;;
    esac
    attempts=$((attempts - 1))
    sleep 1
  done
  return 1
}

api_post() {
  path="$1"
  payload="$2"
  curl -fsS \
    -b "$COOKIE_JAR" \
    -c "$COOKIE_JAR" \
    -H 'Content-Type: application/json' \
    -X POST \
    -d "$payload" \
    "http://127.0.0.1:${UI_PORT}${path}"
}

trap cleanup EXIT INT TERM

cd "$ROOT_DIR"
export UI_PORT GATEWAY_HTTP_PORT GATEWAY_HTTPS_PORT
export OMNI_UI_PORT="$UI_PORT"
export OMNI_UI_SCHEME=http
export COOKIE_SECURE=false
export OMNI_HTTP_PORT="$GATEWAY_HTTP_PORT"
export OMNI_HTTPS_PORT="$GATEWAY_HTTPS_PORT"
export OMNI_DATA_ROOT
export OMNI_IMAGE="omni-proxygate:e2e"
sudo -E -n rm -rf "$OMNI_DATA_ROOT"
mkdir -p "$OMNI_DATA_ROOT/data" "$OMNI_DATA_ROOT/nginx/conf" "$OMNI_DATA_ROOT/nginx/stream" "$OMNI_DATA_ROOT/certs" "$OMNI_DATA_ROOT/logs"
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 \
  -subj "/CN=reality.example.com" \
  -keyout "$OMNI_DATA_ROOT/certs/reality-backend.key" \
  -out "$OMNI_DATA_ROOT/certs/reality-backend.crt" >/dev/null 2>&1
docker_cmd build -t "$OMNI_IMAGE" -f Dockerfile .
docker_cmd compose $COMPOSE_FILES up -d

wait_for_health "http://127.0.0.1:${UI_PORT}/healthz"

curl -fsS \
  -c "$COOKIE_JAR" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"E2E-Admin-Password!"}' \
  "http://127.0.0.1:${UI_PORT}/api/auth/init" >/dev/null

backend_json="$(api_post /api/backends '{"name":"e2e-backend","host":"e2e-backend","port":18080,"protocol":"http","scheme":null,"tls_to_backend":false,"keepalive":32,"read_timeout":30,"send_timeout":30,"connect_timeout":5,"preserve_host":true,"forward_real_ip":true,"extra_options":"{}"}')"
backend_id="$(printf '%s' "$backend_json" | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')"

api_post /api/certificates '{"name":"proxy","domain":"proxy.example.com","cert_path":"/etc/nginx/certs/reality-backend.crt","key_path":"/etc/nginx/certs/reality-backend.key","managed_by_system":false,"expire_at":null}' >/dev/null
api_post /api/sni-routes '{"listener_id":1,"name":"proxy","enabled":true,"sni":"proxy.example.com","alpn":null,"priority":10,"action":"http_termination","backend_id":null}' >/dev/null
api_post /api/http-routes "{\"name\":\"proxy-root\",\"enabled\":true,\"host\":\"proxy.example.com\",\"path\":\"/\",\"match_type\":\"host_path\",\"priority\":10,\"backend_type\":\"http\",\"http_mode\":\"normal\",\"backend_id\":${backend_id},\"is_default_fallback\":false,\"extra_options\":\"{}\"}" >/dev/null

tls_backend_json="$(api_post /api/backends '{"name":"e2e-tls-backend","host":"nggm-e2e-tls-backend","port":18444,"protocol":"tcp_tls","scheme":null,"tls_to_backend":true,"keepalive":0,"read_timeout":30,"send_timeout":30,"connect_timeout":5,"preserve_host":true,"forward_real_ip":false,"extra_options":"{}"}')"
tls_backend_id="$(printf '%s' "$tls_backend_json" | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')"
api_post /api/sni-routes "{\"listener_id\":1,\"name\":\"reality\",\"enabled\":true,\"sni\":\"reality.example.com\",\"alpn\":null,\"priority\":20,\"action\":\"tls_passthrough\",\"backend_id\":${tls_backend_id}}" >/dev/null

proxy_tls_backend_json="$(api_post /api/backends '{"name":"e2e-proxy-tls-backend","host":"nggm-e2e-proxy-tls-backend","port":18445,"protocol":"tcp_tls","scheme":null,"tls_to_backend":true,"send_proxy_protocol":true,"keepalive":0,"read_timeout":30,"send_timeout":30,"connect_timeout":5,"preserve_host":true,"forward_real_ip":false,"extra_options":"{}"}')"
proxy_tls_backend_id="$(printf '%s' "$proxy_tls_backend_json" | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')"
api_post /api/sni-routes "{\"listener_id\":1,\"name\":\"proxyproto\",\"enabled\":true,\"sni\":\"proxyproto.example.com\",\"alpn\":null,\"priority\":25,\"action\":\"tls_passthrough\",\"backend_id\":${proxy_tls_backend_id}}" >/dev/null

missing_backend_json="$(api_post /api/backends '{"name":"missing-http-backend","host":"missing-http-backend","port":18081,"protocol":"http","scheme":null,"tls_to_backend":false,"keepalive":0,"read_timeout":5,"send_timeout":5,"connect_timeout":1,"preserve_host":true,"forward_real_ip":true,"extra_options":"{}"}')"
missing_backend_id="$(printf '%s' "$missing_backend_json" | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')"
api_post /api/sni-routes '{"listener_id":1,"name":"missing-http","enabled":true,"sni":"missing.example.com","alpn":null,"priority":30,"action":"http_termination","backend_id":null}' >/dev/null
api_post /api/http-routes "{\"name\":\"missing-root\",\"enabled\":true,\"host\":\"missing.example.com\",\"path\":\"/\",\"match_type\":\"host_path\",\"priority\":10,\"backend_type\":\"http\",\"http_mode\":\"normal\",\"backend_id\":${missing_backend_id},\"is_default_fallback\":false,\"extra_options\":\"{}\"}" >/dev/null

missing_tls_backend_json="$(api_post /api/backends '{"name":"missing-tls-backend","host":"missing-tls-backend","port":18443,"protocol":"tcp_tls","scheme":null,"tls_to_backend":true,"keepalive":0,"read_timeout":5,"send_timeout":5,"connect_timeout":1,"preserve_host":true,"forward_real_ip":false,"extra_options":"{}"}')"
missing_tls_backend_id="$(printf '%s' "$missing_tls_backend_json" | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')"
api_post /api/sni-routes "{\"listener_id\":1,\"name\":\"missing-tls\",\"enabled\":true,\"sni\":\"missing-tls.example.com\",\"alpn\":null,\"priority\":40,\"action\":\"tls_passthrough\",\"backend_id\":${missing_tls_backend_id}}" >/dev/null

apply_json="$(curl -fsS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X POST "http://127.0.0.1:${UI_PORT}/api/config/apply")"
printf '%s' "$apply_json" | python3 -c 'import json, sys; data=json.load(sys.stdin); assert data.get("ok") is True, data' >/dev/null

response="$(wait_for_gateway "https://proxy.example.com:${GATEWAY_HTTPS_PORT}/" "E2E gateway OK")"
case "$response" in
  *"E2E gateway OK"*)
    printf '%s\n' "$response"
    printf '%s\n' "E2E test passed"
    ;;
  *)
    printf '%s\n' "Unexpected response:"
    printf '%s\n' "$response"
    exit 1
    ;;
esac

missing_status="$(curl -sk --noproxy '*' --http1.1 -o /dev/null -w '%{http_code}' --resolve "missing.example.com:${GATEWAY_HTTPS_PORT}:127.0.0.1" "https://missing.example.com:${GATEWAY_HTTPS_PORT}/" || true)"
if [ "$missing_status" = "502" ]; then
  printf '%s\n' "Missing backend returned 502 without breaking nginx"
else
  printf '%s\n' "Expected missing backend HTTP 502, got: $missing_status"
  exit 1
fi

gateway_running="$(docker_cmd inspect -f '{{.State.Running}}' omni-proxygate)"
if [ "$gateway_running" = "true" ]; then
  printf '%s\n' "OmniProxyGate container stayed running"
else
  printf '%s\n' "OmniProxyGate container is not running"
  exit 1
fi

missing_tls_output="$(timeout 8 openssl s_client -quiet -servername missing-tls.example.com -connect "127.0.0.1:${GATEWAY_HTTPS_PORT}" </dev/null 2>&1 || true)"
case "$missing_tls_output" in
  *"TLS passthrough OK"*|*"PROXY protocol TLS passthrough OK"*)
    printf '%s\n' "Missing TLS backend unexpectedly returned a healthy response"
    exit 1
    ;;
  *)
    printf '%s\n' "Missing TLS backend failed per connection without breaking nginx"
    ;;
esac

gateway_running="$(docker_cmd inspect -f '{{.State.Running}}' omni-proxygate)"
if [ "$gateway_running" = "true" ]; then
  printf '%s\n' "OmniProxyGate container stayed running after missing TLS backend"
else
  printf '%s\n' "OmniProxyGate container stopped after missing TLS backend"
  exit 1
fi

passthrough_response="$(printf 'GET / HTTP/1.1\r\nHost: reality.example.com\r\nConnection: close\r\n\r\n' | openssl s_client -quiet -servername reality.example.com -connect "127.0.0.1:${GATEWAY_HTTPS_PORT}" 2>/dev/null | tr -d '\r' || true)"
case "$passthrough_response" in
  *"TLS passthrough OK"*)
    printf '%s\n' "$passthrough_response"
    printf '%s\n' "TLS passthrough test passed"
    ;;
  *)
    printf '%s\n' "Unexpected passthrough response:"
    printf '%s\n' "$passthrough_response"
    exit 1
    ;;
esac

proxy_passthrough_response="$(printf 'GET / HTTP/1.1\r\nHost: proxyproto.example.com\r\nConnection: close\r\n\r\n' | openssl s_client -quiet -servername proxyproto.example.com -connect "127.0.0.1:${GATEWAY_HTTPS_PORT}" 2>/dev/null | tr -d '\r' || true)"
case "$proxy_passthrough_response" in
  *"PROXY protocol TLS passthrough OK"*)
    printf '%s\n' "$proxy_passthrough_response"
    printf '%s\n' "PROXY protocol TLS passthrough test passed"
    ;;
  *)
    printf '%s\n' "Unexpected PROXY protocol passthrough response:"
    printf '%s\n' "$proxy_passthrough_response"
    exit 1
    ;;
esac
