# Deployment

OmniProxyGate is published as one container image. The image can run the gateway Nginx process, the Web UI/API process, or both.

## Image

GitHub Actions builds the root `Dockerfile` and publishes to GHCR:

```text
ghcr.io/OWNER/REPO:latest
ghcr.io/OWNER/REPO:<branch>
ghcr.io/OWNER/REPO:sha-<commit>
ghcr.io/OWNER/REPO:vX.Y.Z
```

Replace `OWNER/REPO` with the GitHub repository path.

## Runtime Modes

| Mode | Environment |
| --- | --- |
| Default all-in-one | `OMNI_RUN_GATEWAY=true`, `OMNI_RUN_UI=true`, `OMNI_WEB_UI_ENABLED=true` |
| Agent API only, no browser UI | `OMNI_RUN_GATEWAY=true`, `OMNI_RUN_UI=true`, `OMNI_WEB_UI_ENABLED=false` |
| Gateway only | `OMNI_RUN_GATEWAY=true`, `OMNI_RUN_UI=false` |
| UI/API only | `OMNI_RUN_GATEWAY=false`, `OMNI_RUN_UI=true` |

In all-in-one mode the API writes generated config directly into `/etc/nginx/conf.d` and `/etc/nginx/stream.d`, then runs `nginx -t` and `nginx -s reload` inside the same container. No Docker socket is required.

## Persistent Volumes

The default Compose and Swarm examples use Docker named volumes instead of bind-mounted host directories.

| Volume | Target | Purpose |
| --- | --- | --- |
| `omni_data` / `omni_proxygate_data` | `/data` | SQLite database, sessions, config versions |
| `omni_nginx_http` / `omni_proxygate_nginx_http` | `/etc/nginx/conf.d` | Last applied generated HTTP config |
| `omni_nginx_stream` / `omni_proxygate_nginx_stream` | `/etc/nginx/stream.d` | Last applied generated stream config |
| `omni_certs` / `omni_proxygate_certs` | `/etc/nginx/certs` | Certificate and key material |
| optional `omni_logs` / `omni_proxygate_logs` | `/var/log/nginx` | Nginx log retention if container logs are not enough |

The config snippet directories are persisted separately so a gateway restart keeps the last applied Nginx configuration without requiring a Web UI/API regeneration step.

## Migrating From Bind Mount Examples

Older examples used host bind directories such as `/opt/omni-proxygate/data` and `/opt/omni-proxygate/nginx/conf`. When switching an existing deployment to the named-volume stack, copy the old data into the new volumes before redeploying or the service will start with empty state.

A safe migration shape is:

```bash
# Stop the old stack/service first. Then copy each old directory into its matching volume.
docker run --rm \
  -v omni_proxygate_data:/to \
  -v /opt/omni-proxygate/data:/from:ro \
  alpine sh -c 'cd /from && cp -a . /to/'
```

Repeat for `nginx/conf -> omni_proxygate_nginx_http`, `nginx/stream -> omni_proxygate_nginx_stream`, and `certs -> omni_proxygate_certs`. Do not copy logs unless you intentionally enabled the optional log volume.

## Docker Compose

```bash
cp .env.example .env
sed -i 's#ghcr.io/OWNER/REPO:latest#ghcr.io/your-org/your-repo:latest#' .env
docker compose --env-file .env up -d
```

By default the compose file exposes UI/API on `127.0.0.1:${OMNI_UI_PORT:-18081}`. Put it behind OmniProxyGate/NPM/SSH tunnel if public access is needed.

## Docker Swarm Stack

```bash
cp deploy/omni-proxygate.env.example /opt/omni-proxygate.env
# Edit OMNI_IMAGE, OMNI_NODE_HOSTNAME, admin password/token, and ports.
set -a
. /opt/omni-proxygate.env
set +a
./scripts/deploy-omni-proxygate-stack.sh
```

Or directly after exporting the environment variables:

```bash
docker stack deploy --with-registry-auth -c deploy/omni-proxygate.stack.yml "$OMNI_STACK_NAME"
```

The stack pins the service with `node.hostname == ${OMNI_NODE_HOSTNAME}`. Set it to the node that owns the public ports and persistent named volumes.

## Disable Browser UI, Keep Agent API

```env
OMNI_RUN_GATEWAY=true
OMNI_RUN_UI=true
OMNI_WEB_UI_ENABLED=false
OMNI_AGENT_API_TOKEN=replace-with-long-token
```

Then use the Agent CLI:

```bash
export OMNI_URL=http://127.0.0.1:18081
export OMNI_AGENT_API_TOKEN=replace-with-long-token
omni doctor
omni status
```

`/api/*` and `/healthz` remain available. `/` and `/static/*` are not mounted.

## GitHub Actions

Workflow: `.github/workflows/container.yml`

Required repository setting:

- Actions must be allowed to write packages.
- For private images, deployment nodes must `docker login ghcr.io` with a token that can read packages.

The workflow pushes images for default branch, tags, and commit SHA. Pull requests build but do not push.

## Rollback

Use an immutable SHA tag in production:

```env
OMNI_IMAGE=ghcr.io/OWNER/REPO:sha-abcdef123456
```

Rollback by setting `OMNI_IMAGE` back to the previous SHA tag and redeploying the compose/stack.
