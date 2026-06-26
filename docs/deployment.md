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

## Required Persistent Paths

```text
/opt/omni-proxygate/data
/opt/omni-proxygate/nginx/conf
/opt/omni-proxygate/nginx/stream
/opt/omni-proxygate/certs
/opt/omni-proxygate/logs
```

## Docker Compose

```bash
cp deploy/omni-proxygate.env.example .env
sed -i 's#ghcr.io/OWNER/REPO:latest#ghcr.io/your-org/your-repo:latest#' .env
mkdir -p /opt/omni-proxygate/{data,nginx/conf,nginx/stream,certs,logs}
docker compose --env-file .env up -d
```

By default the compose file exposes UI/API on `127.0.0.1:${OMNI_UI_PORT:-18081}`. Put it behind OmniProxyGate/NPM/SSH tunnel if public access is needed.

## Docker Swarm Stack

```bash
cp deploy/omni-proxygate.env.example /opt/omni-proxygate/omni.env
set -a
. /opt/omni-proxygate/omni.env
set +a
./scripts/deploy-omni-proxygate-stack.sh
```

Or directly:

```bash
docker stack deploy --with-registry-auth -c deploy/omni-proxygate.stack.yml omni-proxygate
```

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
