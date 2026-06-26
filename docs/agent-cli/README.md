# OmniProxyGate Agent CLI / CUI

`omni` is a zero-dependency command-line shell for Agents. It is a local thin client that calls the authenticated OmniProxyGate Web/API service over HTTP.

Use it as the preferred Agent interface instead of hand-written `curl` because it provides discovery, safe defaults, backend-name resolution, multi-SNI creation, readable output, and `--json` output for automation.

## Design

- Local executable: `omni`
- Network target: `OMNI_URL`, for example `https://omni.example.com`
- Auth: `OMNI_AGENT_API_TOKEN`
- Implementation: Python standard library only
- Safety: destructive commands require `--yes`
- Full coverage: `omni raw METHOD /api/path --data JSON` is always available

This keeps the install disposable: the client is just a shell around the network API and can be removed after use.

## Install

From a checked-out repo:

```bash
cd OmniProxyGate
./scripts/install-omni-cli.sh
```

Custom install path:

```bash
OMNI_CLI_BIN_DIR=/usr/local/bin ./scripts/install-omni-cli.sh
```

From a hosted raw script URL, set `OMNI_CLI_URL` to the raw `cli/omni` URL:

```bash
curl -fsSL https://example.com/install-omni-cli.sh | OMNI_CLI_URL=https://example.com/cli/omni sh
```

The repository does not assume a public download URL. Use your own Git/raw file hosting when publishing the CLI.

## Uninstall

```bash
./scripts/uninstall-omni-cli.sh
```

Or remove a custom location:

```bash
OMNI_CLI_BIN_DIR=/usr/local/bin ./scripts/uninstall-omni-cli.sh
```

## Configure

```bash
export OMNI_URL="https://omni.example.com"
export OMNI_AGENT_API_TOKEN="replace-with-server-token"
```

For local/self-signed testing only:

```bash
export OMNI_INSECURE=true
```

The server must be configured with the same token in `OMNI_AGENT_API_TOKEN`. The CLI sends it as `X-OMNI-API-TOKEN`.

## First Commands

```bash
omni --help
omni doctor
omni status
omni status --json
omni export -o omni-backup.json
omni list backends
omni list sni
omni list http
omni preview --section stream
omni preview --section http
```

## Safe Change Workflow

1. `omni doctor`
2. `omni export -o backup-before-change.json`
3. `omni list backends`, `omni list sni`, `omni list http`
4. Make the smallest CLI mutation.
5. `omni preview --section all`
6. Review generated Nginx stream and HTTP config.
7. `omni apply --yes`
8. Re-read state and run traffic/client tests.

Do not run `import` or `apply` before exporting a backup.

## Command Map

| Need | Command |
| --- | --- |
| Discover features | `omni --help`, `omni <command> --help` |
| Check connectivity/auth | `omni doctor` |
| Object counts and ports | `omni status` |
| Backup config | `omni export -o file.json` |
| Restore config | `omni import file.json --yes` |
| Preview generated Nginx | `omni preview --section all|stream|http` |
| Apply generated config | `omni apply --yes` |
| List objects | `omni list backends|sni|http|certs|versions` |
| Read listener | `omni get listener` |
| Read item by ID | `omni get backends 3` |
| Create backend | `omni create backend ...` |
| Create one/many SNI domains in one route | `omni create sni --sni a,b,c ...` |
| Create HTTP/gRPC route | `omni create http ...` |
| Register cert paths | `omni create cert ...` |
| Delete object | `omni delete backends 3 --yes` |
| Use unsupported API directly | `omni raw GET /api/config/export` |

## Examples

Create a normal HTTP backend:

```bash
omni create backend \
  --name site-web \
  --host site \
  --port 8080 \
  --protocol http \
  --scheme http
```

Create a TLS passthrough backend with PROXY protocol enabled for that backend:

```bash
omni create backend \
  --name frps-tls \
  --host frps \
  --port 443 \
  --protocol tcp_tls \
  --send-proxy-protocol
```

Create one SNI route with multiple domains that share one destination:

```bash
omni create sni \
  --name npm-public \
  --sni 'example.com,*.example.com,api.example.com' \
  --action tls_passthrough \
  --backend npm-https \
  --priority 50
```

Create an SNI route that enters HTTP termination:

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

Create an XHTTP / SplitHTTP streaming route:

```bash
omni create http \
  --name xui-xhttp \
  --host xhttp.example.com \
  --path /xhttp \
  --backend xui-xhttp \
  --backend-type http \
  --http-mode xhttp_stream
```

Call raw API for a command not yet wrapped:

```bash
omni raw PUT /api/listener --data '{"name":"default","tcp_port":[443,2053],"udp_port":[443],"enable_tcp_sni":true,"enable_http3":true,"enable_http80":true,"listen_address_mode":"split","default_sni_action":"http_termination","default_backend_id":null,"internal_http_host":"127.0.0.1","internal_http_port":8443,"enabled":true}'
```

## Output Modes

Human-readable mode is default:

```bash
omni list backends
```

Machine-readable mode is available for Agent parsing:

```bash
omni list backends --json
omni status --json
omni doctor --json
```

## Safety Notes

- Numeric IDs are allowed but not preferred. Use backend names with create commands.
- `omni create sni --sni a,b,c` creates one API route record. The server stores the normalized SNI list and renders it as one Nginx stream map rule.
- `omni import` replaces listener, backends, certificates, SNI routes, and HTTP routes. It does not replace users, sessions, or config version history.
- `omni apply` executes the server-side Nginx test/reload path. If apply fails, inspect output and logs before retrying.
- `OMNI_INSECURE=true` is only for private/local tests with self-signed certificates.

## Troubleshooting

`missing OMNI_URL`:

```bash
export OMNI_URL=https://omni.example.com
```

`HTTP 401` or `HTTP 403`:

```bash
export OMNI_AGENT_API_TOKEN=the-token-configured-on-server
omni doctor
```

TLS verification failure in lab environments:

```bash
OMNI_INSECURE=true omni doctor
```

Backend not found by name:

```bash
omni list backends
```

Generated Nginx looks wrong:

```bash
omni export -o inspect.json
omni preview --section all
```

## API Fallback

The CLI intentionally keeps `raw` available so new server endpoints can be used before a high-level command exists:

```bash
omni raw GET /api/backends
omni raw POST /api/config/apply --data '{}'
omni raw DELETE /api/http-routes/12
```

Prefer high-level commands when they exist because they add safety and name resolution.
