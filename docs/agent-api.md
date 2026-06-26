# OmniProxyGate Agent API

OmniProxyGate exposes an authenticated network control interface for Agents. The recommended interface is the `omni` CLI/CUI because it provides help, examples, safe confirmations, backend-name resolution, JSON output, and a `raw` escape hatch.

Use raw HTTP APIs directly only when the CLI does not yet expose a high-level command.

## Preferred Agent Interface

Install the local thin client:

```bash
cd OmniProxyGate
./scripts/install-omni-cli.sh
```

Configure it:

```bash
export OMNI_URL="https://omni.example.com"
export OMNI_AGENT_API_TOKEN="replace-with-token"
```

Verify:

```bash
omni doctor
omni status
omni export -o omni-backup.json
```

Full CLI documentation: `docs/agent-cli/README.md`.

## Authentication

For browser users, use normal login cookies.

For agents, set the UI service environment variable:

```env
OMNI_AGENT_API_TOKEN=replace-with-a-long-random-token
```

Then call APIs with either header:

```bash
X-OMNI-API-TOKEN: replace-with-a-long-random-token
```

or:

```bash
Authorization: Bearer replace-with-a-long-random-token
```

If `OMNI_AGENT_API_TOKEN` is empty, token auth is disabled.

## Base URLs

Examples:

- Local host port: `http://127.0.0.1:18081`
- Public HTTPS via OmniProxyGate: `https://omni.example.com`

## Safe Workflow

1. `GET /healthz`
2. `GET /api/config/export` and save a backup.
3. Read the objects you will modify.
4. Make the smallest mutation.
5. `GET /api/config/preview`.
6. Review `stream` and `http` output.
7. `POST /api/config/apply` only after preview is correct.
8. Verify with real clients or route-level probes.

## Endpoint Map

| Area | Method and path | Purpose |
| --- | --- | --- |
| Health | `GET /healthz` | service health |
| Listener | `GET /api/listener` | read public listener |
| Listener | `PUT /api/listener` | replace public listener settings |
| Backends | `GET /api/backends` | list backends |
| Backends | `POST /api/backends` | create backend |
| Backends | `PUT /api/backends/{id}` | replace backend |
| Backends | `DELETE /api/backends/{id}` | delete backend |
| Certificates | `GET /api/certificates` | list certificates |
| Certificates | `POST /api/certificates` | register certificate paths |
| Certificates | `PUT /api/certificates/{id}` | replace certificate |
| Certificates | `DELETE /api/certificates/{id}` | delete certificate |
| SNI routes | `GET /api/sni-routes` | list stream SNI routes |
| SNI routes | `POST /api/sni-routes` | create one SNI route |
| SNI routes | `PUT /api/sni-routes/{id}` | replace one SNI route |
| SNI routes | `DELETE /api/sni-routes/{id}` | delete one SNI route |
| HTTP routes | `GET /api/http-routes` | list HTTP/gRPC routes |
| HTTP routes | `POST /api/http-routes` | create route |
| HTTP routes | `PUT /api/http-routes/{id}` | replace route |
| HTTP routes | `DELETE /api/http-routes/{id}` | delete route |
| Config | `GET /api/config/export` | export full routing bundle |
| Config | `POST /api/config/import` | replace routing bundle |
| Config | `GET /api/config/preview` | render Nginx config |
| Config | `POST /api/config/apply` | test/reload generated Nginx |
| Config | `GET /api/config/versions` | list recent apply versions |
| Config | `POST /api/config/rollback/{id}` | rollback to a version path |
| Logs | `GET /api/logs/{log_name}?lines=300` | read server-side log tail |

## CLI Equivalents

```bash
omni list backends
omni create backend --name npm --host npm --port 443 --protocol http --scheme https
omni create sni --name npm-public --sni 'example.com,*.example.com' --action tls_passthrough --backend npm
omni create http --name xui-grpc --host grpc.example.com --path /grpc --backend xui-grpc --backend-type grpc
omni preview --section all
omni apply --yes
```

## Raw HTTP Examples

Read:

```bash
curl -fsS -H "X-OMNI-API-TOKEN: $OMNI_AGENT_API_TOKEN" "$OMNI_URL/api/backends"
curl -fsS -H "X-OMNI-API-TOKEN: $OMNI_AGENT_API_TOKEN" "$OMNI_URL/api/sni-routes"
curl -fsS -H "X-OMNI-API-TOKEN: $OMNI_AGENT_API_TOKEN" "$OMNI_URL/api/http-routes"
curl -fsS -H "X-OMNI-API-TOKEN: $OMNI_AGENT_API_TOKEN" "$OMNI_URL/api/config/preview"
```

Apply:

```bash
curl -fsS -X POST -H "X-OMNI-API-TOKEN: $OMNI_AGENT_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' \
  "$OMNI_URL/api/config/apply"
```

Export:

```bash
curl -fsS -H "X-OMNI-API-TOKEN: $OMNI_AGENT_API_TOKEN" \
  "$OMNI_URL/api/config/export" > omni-proxygate-config.json
```

Import:

```bash
curl -fsS -X POST -H "X-OMNI-API-TOKEN: $OMNI_AGENT_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @omni-proxygate-config.json \
  "$OMNI_URL/api/config/import"
```

Import replaces listener, backends, certificates, SNI routes, and HTTP routes. It does not replace admin users, sessions, or config version history.
