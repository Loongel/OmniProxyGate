---
name: omni-proxygate-agent
description: Operate OmniProxyGate as an Agent through the local omni CLI/CUI and authenticated network API. Use to discover capabilities, inspect, export, import, create backends, create SNI and HTTP/gRPC routes, preview generated Nginx, apply config, rollback through raw API, and troubleshoot gateway state.
---

# OmniProxyGate Agent Skill

Use this skill when an Agent needs to control an OmniProxyGate instance without the browser UI.

Prefer the `omni` CLI. Use raw API only when a high-level CLI command is missing.

## Mental Model

OmniProxyGate is an entry gateway manager. It configures Nginx stream and HTTP termination rules for:

- public TCP/UDP listener ports
- stream SNI routing
- TLS passthrough to backends such as NPM, FRPS, Xray, or 3X-UI inbound services
- HTTP termination routes for normal HTTP, WebSocket, XHTTP/SplitHTTP streaming, and gRPC
- backend-level `send_proxy_protocol`
- certificate path registration
- generated Nginx preview, apply, versions, and rollback
- full config export/import for backup and migration

## Required Environment

```bash
export OMNI_URL="https://omni.example.com"
export OMNI_AGENT_API_TOKEN="replace-with-token"
```

For local lab/self-signed TLS only:

```bash
export OMNI_INSECURE=true
```

The server must have the same `OMNI_AGENT_API_TOKEN` configured.

## Install CLI

From the repository:

```bash
cd OmniProxyGate
./scripts/install-omni-cli.sh
```

If the CLI is hosted as a raw file, use:

```bash
curl -fsSL https://example.com/install-omni-cli.sh | OMNI_CLI_URL=https://example.com/cli/omni sh
```

Uninstall:

```bash
./scripts/uninstall-omni-cli.sh
```

## First Steps

Always begin with discovery and backup:

```bash
omni --help
omni doctor
omni status
omni export -o omni-backup-before-change.json
omni list backends
omni list sni
omni list http
```

If any of these fail, stop and fix connectivity/auth before mutating config.

## Safe Mutation Rules

- Export a backup before every import, delete, or bulk change.
- Prefer backend names over numeric IDs.
- Do not guess IDs. If an ID is required, run `omni list ...` first.
- Preview before apply: `omni preview --section all`.
- Apply only with explicit confirmation: `omni apply --yes`.
- Treat `omni import FILE --yes` as destructive replacement for routing config.
- After apply, verify with real clients or route-level probes. Nginx config success is not full proxy-service acceptance.

## Command Reference

```bash
omni doctor                         # URL, token, health, auth check
omni status                         # listener ports and object counts
omni status --json                  # machine-readable summary
omni export -o backup.json          # full config backup
omni import backup.json --yes       # destructive restore
omni preview --section all          # generated stream and HTTP config
omni preview --section stream       # generated stream config only
omni preview --section http         # generated HTTP config only
omni apply --yes                    # server-side nginx test/reload
omni list backends                  # backend table
omni list sni                       # SNI route table
omni list http                      # HTTP/gRPC route table
omni list certs                     # certificates
omni list versions                  # config versions
omni get listener                   # listener JSON
omni get backends 3                 # item JSON by ID
omni create backend ...             # add backend
omni create sni ...                 # add one or multiple SNI routes
omni create http ...                # add HTTP/gRPC route
omni create cert ...                # register certificate paths
omni delete backends 3 --yes        # delete by ID
omni raw GET /api/config/export     # fallback direct API access
```

## Common Tasks

Create a backend for NPM HTTPS:

```bash
omni create backend \
  --name npm-https \
  --host npm_app \
  --port 443 \
  --protocol http \
  --scheme https
```

Create a backend for FRPS TLS passthrough with PROXY protocol:

```bash
omni create backend \
  --name frps-tls \
  --host frps \
  --port 443 \
  --protocol tcp_tls \
  --send-proxy-protocol
```

Create multiple SNI names pointing to the same backend:

```bash
omni create sni \
  --name npm-public \
  --sni 'example.com,*.example.com,app.example.com' \
  --action tls_passthrough \
  --backend npm-https \
  --priority 50
```

Create HTTP termination entry SNI for 3X-UI gRPC and XHTTP domains:

```bash
omni create sni \
  --name xui-http-entry \
  --sni 'grpc.example.com,xhttp.example.com' \
  --action http_termination \
  --priority 30
```

Create a gRPC route:

```bash
omni create http \
  --name xui-grpc \
  --host grpc.example.com \
  --path /grpc \
  --backend xui-grpc \
  --backend-type grpc
```

Create an XHTTP/SplitHTTP streaming route:

```bash
omni create http \
  --name xui-xhttp \
  --host xhttp.example.com \
  --path /xhttp \
  --backend xui-xhttp \
  --backend-type http \
  --http-mode xhttp_stream
```

Change listener ports through raw API if no high-level wrapper exists:

```bash
omni raw PUT /api/listener --data '{"name":"default","tcp_port":[443,2053],"udp_port":[443],"enable_tcp_sni":true,"enable_http3":true,"enable_http80":true,"listen_address_mode":"split","default_sni_action":"http_termination","default_backend_id":null,"internal_http_host":"127.0.0.1","internal_http_port":8443,"enabled":true}'
```

## Raw API Fallback

Use `raw` for unwrapped operations:

```bash
omni raw GET /api/backends
omni raw POST /api/config/apply --data '{}'
omni raw POST /api/config/rollback/12 --data '{}'
omni raw GET '/api/logs/error?lines=200'
```

If a raw operation changes config, still follow the backup and preview workflow.

## Troubleshooting

Missing URL:

```bash
export OMNI_URL=https://omni.example.com
```

Auth failure:

```bash
export OMNI_AGENT_API_TOKEN=the-server-token
omni doctor
```

Backend name lookup failure:

```bash
omni list backends
```

Need machine-readable state:

```bash
omni status --json
omni list backends --json
omni raw GET /api/config/export
```

Generated config looks suspicious:

```bash
omni export -o inspect-before-debug.json
omni preview --section all
```

## Documentation

Read `docs/agent-cli/README.md` for the complete CLI guide and `docs/agent-api.md` for the HTTP API map.
