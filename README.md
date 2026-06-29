# OmniProxyGate

面向 **3X-UI / Xray / sing-box / V2Ray 类代理后端** 的 Nginx 前置 TLS 与 HTTP 分流管理器。项目目标是用一个极简 Web UI 管理：

- TCP 443 `stream` 层 SNI 分流。
- SNI 命中后进入本机 HTTPS/H1/H2 终止层。
- Reality / Trojan / VLESS TLS 等后端自管 TLS 的原样透传。
- UDP 443 HTTP/3 / QUIC 终止。
- HTTP/3 终止后复用同一套 Host / Path / ALPN 路由。
- HTTP 类后端：普通 HTTP、WebSocket、XHTTP / SplitHTTP / 流式 HTTP。
- gRPC 类后端：使用 `grpc_pass` 独立模板。
- IPv4 / IPv6 监听模式、配置预览、`nginx -t`、热重载、失败恢复和版本回滚。

## 目录结构

```text
OmniProxyGate/
├── cli/                     # Agent 使用的 omni 零依赖 CLI/CUI
├── Dockerfile               # 生产发布用单镜像：Nginx gateway + UI/API
├── docker-entrypoint.sh     # 单镜像进程入口和运行模式开关
├── docker-compose.yml
├── nginx/                  # 流量入口 Nginx 镜像与 nginx.conf
├── ui/                     # FastAPI Web UI / API / 配置生成器
├── docs/                   # 配置指南、Agent API、Agent CLI 文档
├── examples/               # 样例配置、Agent CLI 场景脚本
├── skills/                 # Codex/Agent 使用的项目 skill
└── scripts/                # 本地开发、部署、CLI 安装和验证脚本
```

## 快速启动

推荐生产部署使用 GitHub Actions 发布的单镜像；本地开发可以先 build 本地镜像，再用同一份 Compose 启动。

生产/单机 Compose：

```bash
cp .env.example .env
# 修改 .env 里的 OMNI_IMAGE、OMNI_ADMIN_PASSWORD、OMNI_AGENT_API_TOKEN
docker compose --env-file .env up -d
```

默认使用 Docker named volumes，不需要提前创建宿主目录。

Swarm Stack：

```bash
cp deploy/omni-proxygate.env.example /opt/omni-proxygate/omni.env
set -a
. /opt/omni-proxygate/omni.env
set +a
./scripts/deploy-omni-proxygate-stack.sh
```

完整部署说明见 `docs/deployment.md`。

本地开发：

```bash
cd OmniProxyGate
docker build -t omni-proxygate:local .
OMNI_IMAGE=omni-proxygate:local docker compose up -d
```

然后访问：

```text
http://127.0.0.1:18081
```

首次打开会要求初始化管理员账号。默认 Compose 只把 UI 绑定到 `127.0.0.1:18081`，不要把管理 UI 裸奔暴露到公网。

## 单镜像运行模式

GitHub Actions 会从根目录 `Dockerfile` 构建一个镜像，默认同时运行 Nginx gateway 和 UI/API。通过环境变量可以切换模式：

| 模式 | 环境变量 |
| --- | --- |
| 默认全功能 | `OMNI_RUN_GATEWAY=true`, `OMNI_RUN_UI=true`, `OMNI_WEB_UI_ENABLED=true` |
| 只保留 Agent API，不暴露浏览器 UI | `OMNI_RUN_GATEWAY=true`, `OMNI_RUN_UI=true`, `OMNI_WEB_UI_ENABLED=false` |
| 只跑 gateway | `OMNI_RUN_GATEWAY=true`, `OMNI_RUN_UI=false` |
| 只跑 UI/API | `OMNI_RUN_GATEWAY=false`, `OMNI_RUN_UI=true` |

单镜像模式下 API 直接写入容器内 Nginx 配置目录并执行 `nginx -t` / `nginx -s reload`，不需要挂载 Docker socket。

## 证书

Nginx 容器启动时会在 `/etc/nginx/certs/default.crt` 与 `/etc/nginx/certs/default.key` 不存在时生成一个自签名默认证书，目的是让容器能够启动和让 `nginx -t` 可运行。

生产环境应将真实证书放入 `omni_certs` / `omni_proxygate_certs` 这类证书卷，或通过你自己的证书同步流程写入容器内 `/etc/nginx/certs`。

在 Web UI 的“证书管理”中填入容器内路径，例如：

```text
/etc/nginx/certs/proxy.example.com/fullchain.pem
/etc/nginx/certs/proxy.example.com/privkey.pem
```

## 使用流程

主使用方式是 Web UI 配置和生成，不是让运维人员手写 Nginx 配置。完整配置模型见 `docs/configuration-guide.md`。

1. 打开 Web UI，初始化管理员。
2. 在“证书管理”添加域名证书；同一证书路径可以一次录入多个精确域名或泛域名。
3. 在“后端管理”添加 Xray / sing-box / 3X-UI / 网站后端。fallback 也必须先作为普通后端创建。
4. 在“SNI 分流规则”中配置；同一目标后端/动作可以一次录入多个 SNI，ALPN 使用固定选项多选：
   - `proxy.example.com, *.hd1.example.com -> 进入 HTTP 终止层`
   - `reality.example.com, grpc.example.com -> TLS 透传到 xray-reality:443`
5. 在“HTTP 路由规则”中配置；Host、Path、ALPN 可任意组合，至少填写其中一个：
   - `Host proxy.example.com + Path /ws -> HTTP 类 / WebSocket`
   - `Host proxy.example.com + Path /xhttp -> HTTP 类 / XHTTP 流式`
   - `Host grpc.example.com + Path /grpc + ALPN h2 -> gRPC 类`
   - `match_type=default / path=/ / is_default_fallback=true -> 选择上一步创建的 fallback 后端`
6. 进入“预览 / 应用”，检查生成的 Nginx 配置。
7. 点击“执行 nginx -t 并应用”。失败时 UI 会恢复旧配置文件，成功时保存配置版本。
8. 本地验收可直接运行 `./scripts/e2e-local.sh`，脚本会同时验证 HTTP 终止路由和 SNI TLS passthrough 路由。

## Agent CLI / CUI

项目提供一个面向 Agent 的本地薄壳命令 `omni`。它通过网络调用 OmniProxyGate Web/API 服务，适合让 AI Agent 读取、备份、修改、预览和应用配置，而不是手写一串 `curl`。

安装：

```bash
./scripts/install-omni-cli.sh
```

配置：

```bash
export OMNI_URL="https://omni.example.com"
export OMNI_AGENT_API_TOKEN="replace-with-server-token"
```

常用命令：

```bash
omni --help
omni doctor
omni status
omni export -o omni-backup.json
omni list backends
omni create sni --name npm-public --sni 'example.com,*.example.com' --action tls_passthrough --backend npm-https
omni preview --section all
omni apply --yes
```

卸载：

```bash
./scripts/uninstall-omni-cli.sh
```

完整说明见 `docs/agent-cli/README.md`；HTTP API 映射见 `docs/agent-api.md`；Agent skill 见 `skills/omni-proxygate-agent/SKILL.md`。

## 配置指南

所有分流规则、fallback 来源、泛域名语义、样例字段和当前限制统一放在：

```text
docs/configuration-guide.md
```

## 加载示例数据

唯一样例配置在：

```text
examples/sample-config.json
```

在一个空数据库中，可以给 UI 容器设置：

```yaml
environment:
  - SAMPLE_DATA_JSON=/app/examples/sample-config.json
```

如果使用 Compose，也可以把 `examples` 挂载到 UI 容器后再设置此环境变量。示例数据只会在数据库没有后端记录时加载。

## Nginx 生成逻辑

### Stream 层

运行时生成目录：

```text
/etc/nginx/stream.d/gateway-stream.conf
```

该目录不作为配置真相持久化；容器启动时会从 `/data` 数据库重新生成。

生成内容包括：

- `map "$ssl_preread_server_name|$ssl_preread_alpn_protocols" $nggm_stream_upstream`
- `upstream nggm_http_termination`
- TLS 透传后端使用 `host:port` 动态目标，配合 Docker DNS 在连接时解析
- `server { listen 443; ssl_preread on; proxy_pass $nggm_stream_upstream; }`
- `tcp_port` 支持单值或数组，例如 `443` 或 `[443, 2053]`；额外 TCP 端口直接进入 HTTP 终止层

### HTTP 层

运行时生成目录：

```text
/etc/nginx/conf.d/gateway-http.conf
```

该目录不作为配置真相持久化；容器启动时会从 `/data` 数据库重新生成。

生成内容包括：

- `map $http_upgrade $nggm_connection_upgrade`
- `resolver 127.0.0.11`，让 Docker 后端容器名在请求时解析
- HTTP / gRPC 后端使用变量形式 `proxy_pass` / `grpc_pass`
- `0.0.0.0:8443 ssl` 内部 HTTPS/H2 终止 server；stream 内部 upstream 仍回连 `127.0.0.1:8443`
- `443 quic reuseport` HTTP/3 终止 server
- `udp_port` 支持单值或数组，例如 `443` 或 `[443, 2053]`；额外 UDP 端口生成对应 HTTP/3 监听
- HTTP 80 -> HTTPS 重定向 server
- 普通 HTTP、WebSocket、XHTTP 流式、gRPC 的不同 location 模板

后端容器或服务暂时不存在时，生成配置仍应通过 `nginx -t` 并保持 Nginx 运行；对应请求返回 502 或超时。后端容器恢复并能被 Docker DNS 解析后，请求会自动恢复，不需要重启 Nginx。

## IPv4 / IPv6 监听模式

Web UI 的“公网入口设置”提供：

| 模式 | 生成语义 |
| --- | --- |
| `split` | `0.0.0.0:port` 和 `[::]:port ipv6only=on` 分离监听，推荐默认 |
| `ipv4_only` | 只监听 IPv4 |
| `ipv6_only` | 只监听 IPv6 |
| `unified` | 使用 `[::]:port ipv6only=off`，依赖系统 / 容器 dual-stack 行为 |

Docker IPv6 需要宿主机 Docker daemon 正确启用。`docker-compose.yml` 中 IPv6 端口映射默认注释，确认环境支持后再打开。

## 安全说明

- UI 启动后必须初始化管理员账号。
- 密码使用 PBKDF2-SHA256 哈希保存。
- 登录使用 HttpOnly Cookie Session。
- 默认 Compose 只监听 `127.0.0.1:18081`。
- API 写操作都要求登录。
- 不允许在 UI 中直接输入任意 Nginx 指令。
- 后端地址、域名、路径、证书路径都会做基础校验。
- Web UI 对多 SNI、多证书域名做聚合录入和聚合展示；底层 API 仍保存为单 SNI / 单域名记录，便于生成器保持确定性。

建议生产环境额外加：

- SSH 隧道或内网访问。
- 防火墙 / IP 白名单。
- 反向代理 Basic Auth 或 SSO。
- 定期备份 `./data`。

## 本地开发

```bash
cd OmniProxyGate
python3 -m venv .venv
. .venv/bin/activate
pip install -r ui/requirements.txt
./scripts/dev-run.sh
```

本地开发默认 `DRY_RUN=true`，不会真正执行 `nginx -t` 或 `reload`。

## 本地验证

```bash
./scripts/validate-local.sh
```

该脚本会：

- 编译检查 `ui/app` 和 `ui/tests`。
- 运行配置生成器测试。
- 运行密码哈希测试。
- 写出 `examples/generated/gateway-http.conf` 与 `examples/generated/gateway-stream.conf`。

## MVP 已实现

- Web UI。
- 初始化管理员、登录、退出。
- 公网入口设置。
- 后端、证书、SNI 规则、HTTP 路由 CRUD。
- TCP 443 stream SNI 分流。
- SNI -> 本机 HTTP 终止层。
- SNI -> TLS 原样透传后端。
- 默认 SNI 动作。
- HTTPS / HTTP/1.1 / HTTP/2 终止模板。
- HTTP/3 / QUIC 终止模板。
- HTTP/3 复用 HTTP 路由规则。
- Host / Path / ALPN 任意组合路由和默认 fallback 路由。
- HTTP 类普通模式、WebSocket 模式、XHTTP / SplitHTTP / 流式模式。
- gRPC 类后端模板。
- IPv4 / IPv6 监听模式。
- Nginx 配置生成、预览、`nginx -t`、reload。
- 应用失败恢复旧配置文件。
- 配置版本保存与回滚。
- Docker Compose 部署示例。

## 第一版暂不做

- 普通 TCP 端口转发。
- 普通 UDP 端口转发。
- UDP QUIC SNI 分流。
- 自动 ACME 证书申请 / 续期。
- 3X-UI API 对接。
- 多用户权限系统。
- 通用 Nginx 面板。
- 完整 Xray / sing-box 配置生成器。

## 注意事项

1. HTTP/3 需要 Nginx 镜像带 `http_v3` / QUIC 支持，且 TLS 库支持 QUIC。
2. `stream` SNI 分流需要 Nginx 带 `stream` 和 `stream_ssl_preread` 模块。
3. gRPC 路由使用 `grpc_pass`，后端协议为 `grpc` / `grpcs` / `h2c` 时请确认后端监听方式一致。
4. 对同一 server 生成重复 `location` 时，生成器会保留优先级更高的规则并在配置末尾写入 warning 注释。
5. 生产环境请替换默认证书，不要长期使用自签名默认证书。
