# Configuration Guide

本文件是唯一的人读配置指南。主入口是 Web UI；JSON 文件只用于空库种子数据、开发测试和审阅字段结构。

## 目录职责

| 路径 | 用途 |
| --- | --- |
| `README.md` | 快速启动、部署入口、常用命令 |
| `docs/configuration-guide.md` | 配置模型、分流规则、fallback、已知限制 |
| `examples/sample-config.json` | 唯一可加载样例配置，可通过 `SAMPLE_DATA_JSON` 导入空库 |
| `examples/generated/` | 测试生成出来的 Nginx 配置结果，不作为手写输入 |

## 配置入口

正常使用时不要手写 Nginx 配置，按 UI 流程操作：

1. 后端管理：添加网站、Xray、sing-box、3X-UI、Reality、fallback 等后端。
2. 证书管理：添加精确域名或泛域名证书路径；同一证书路径可以一次录入多个域名。
3. SNI 分流规则：决定 TCP 443 ClientHello 命中后进入 HTTP 终止、TLS 透传或 reject；同一动作和后端可以一次录入多个 SNI。
4. HTTP 路由规则：决定 HTTP 终止后的 Host/Path/WebSocket/XHTTP/gRPC/fallback 转发。
5. 预览 / 应用：查看生成的 Nginx 配置，执行 `nginx -t`，成功后 reload。

`examples/sample-config.json` 对应的是这些 UI 表单的字段快照。Web UI 的“预览 / 应用”页支持 JSON 导入/导出；启动时也可以通过 `SAMPLE_DATA_JSON` 给空数据库加载样例。

## 分流层级

| 层级 | 能看到什么 | 可配置规则 | 典型用途 |
| --- | --- | --- | --- |
| TCP stream 443 | SNI、ALPN | `sni`、可选 `alpn`、`action` | HTTP 终止、TLS 透传、reject |
| HTTP 终止层 | Host、Path | `host`、`path`、`match_type`、`backend_type`、`http_mode` | WebSocket、XHTTP、gRPC、普通 HTTP、fallback |
| UDP HTTP/3 443 | QUIC 终止后的 Host、Path | 复用 HTTP 路由 | H3 访问同一套路由表 |

关键限制：HTTP/3 是 UDP QUIC，不经过 TCP stream SNI 分流；它由 HTTP/3 server block 终止后复用 HTTP Host/Path 路由。

入口端口字段支持单值或数组：

```json
{ "tcp_port": 443, "udp_port": 443 }
```

也可以写成：

```json
{ "tcp_port": [443, 2053], "udp_port": [443, 2053] }
```

数组里的第一个端口是主入口。TCP 数组里的额外端口会直接进入 HTTP 终止层，适合 `2053` 这种独立 HTTPS/gRPC/xHTTP 入口；UDP 数组里的额外端口会生成对应 HTTP/3 监听。Web UI 中可以输入 `443` 或 `443,2053`。

## 后端未就绪时的行为

Docker 编排里经常会出现网关先启动、后端容器稍后才加入网络的情况。这里不能使用静态后端 upstream 去强制 Nginx 启动时解析所有后端名称，否则任意一个后端容器名不存在都会让 `nginx -t` 失败，进而在 `restart: unless-stopped` 下形成重启循环。

当前生成策略是：

| 位置 | 策略 | 后端未就绪时 |
| --- | --- | --- |
| HTTP / WebSocket / XHTTP | `resolver 127.0.0.11` + 变量形式 `proxy_pass` | 请求返回 502 或超时，Nginx 继续运行 |
| gRPC | `resolver 127.0.0.11` + 变量形式 `grpc_pass` | 请求返回 502 或超时，Nginx 继续运行 |
| TLS passthrough | stream `resolver 127.0.0.11` + map 到 `host:port` | 连接失败，Nginx 继续运行 |
| 内部 HTTP 终止入口 | 本机 `127.0.0.1:8443` 静态 upstream | 不依赖外部容器 |

后端恢复后，Docker DNS 能解析该容器名，新的请求会自动恢复。这个设计目标是让“单个后端坏了”降级为该路由的 502/连接失败，而不是拖垮整个网关进程。

## SNI 与 ALPN 规则

SNI 规则可以独立按域名匹配，也可以和 ALPN 组合。Web UI 中 ALPN 是固定选项多选：`h2`、`http/1.1`、`h3`；不选表示不限制 ALPN。

| 需求 | 字段组合 | 结果 |
| --- | --- | --- |
| 任意 ALPN 的域名进入 HTTP 终止 | `sni=proxy.example.com`, `alpn=null`, `action=http_termination` | 进入内部 HTTPS/H1/H2 终止层 |
| 只匹配 HTTP/2 | `sni=grpc.example.com`, `alpn=h2`, `action=http_termination` | 只有声明 `h2` 的 TCP TLS 连接命中 |
| 只匹配 HTTP/1.1 | `sni=legacy.example.com`, `alpn=http/1.1`, `action=http_termination` | 只有声明 `http/1.1` 的连接命中 |
| TLS 原样透传 | `sni=reality.example.com`, `action=tls_passthrough`, `backend=xray-reality` | 不解 TLS，直接转发到后端 |
| 拒绝指定 SNI | `sni=blocked.example.com`, `action=reject` | 转到本地 discard 端口，快速关闭 |

示例：

```json
{
  "name": "grpc-h2-only",
  "sni": "grpc.example.com",
  "alpn": "h2",
  "priority": 20,
  "action": "http_termination"
}
```

Web UI 支持把多个 SNI 写在同一条表单里，例如：

```text
proxy.example.com, *.hd1.example.com, grpc.example.com
```

保存时会展开为多条底层 SNI 记录，列表按相同动作、后端、优先级和 ALPN 聚合展示为一组，便于按“同一流向的一组域名”管理。

证书管理同理：同一证书路径可以录入多个域名，保存后按证书路径和私钥路径聚合展示。

## 泛域名规则

支持 `*.example.com` 形式，`*` 表示一层或多层标签：

```text
a.example.com
b.a.example.com
c.b.a.example.com
```

不匹配 apex 域名：

```text
example.com
```

如果 apex 和子域都需要命中，应分别配置：

```text
example.com
*.example.com
```

当前不支持裸 `*`，也不支持 `api.*.example.com` 这种中间通配。

## TLS passthrough 与 PROXY protocol

PROXY protocol 不是全局入口开关，而是后端兼容性：

```json
{
  "name": "xui-reality-443",
  "host": "10.44.102.100",
  "port": 443,
  "protocol": "tcp_tls",
  "send_proxy_protocol": true
}
```

同一个公网 `443` 可以混用：

| 后端 | `send_proxy_protocol` | 典型场景 |
| --- | --- | --- |
| `10.44.102.100:443` | `true` | 3x-ui/Xray Reality，`acceptProxyProtocol=true` |
| `10.44.102.100:1443` | `true` | 3x-ui/Xray TLS fallback，`acceptProxyProtocol=true` |
| `tasks.frps:443` | `false` | frps 旧路径不接收 PROXY header |
| `npm:444` | `false` | 保留 NPM stream 作为 legacy downstream |
| 3x-ui IPv6 direct inbound | `false` | 现有 `[::]:443` Xray inbound 不接收 PROXY header |

生成器实现方式是公网 SNI map 先转到本机内部 stream listener，再由内部 listener 决定是否启用 `proxy_protocol on;`。这样不会出现“为了 3x-ui 打开全局 PROXY，结果 frps 被打坏”的问题。

## HTTP 路由规则

HTTP 路由只在进入 HTTP 终止层后生效，包括 HTTPS/H1/H2 和 HTTP/3 终止后的流量。

| 需求 | 字段组合 | 后端类型 |
| --- | --- | --- |
| Host + Path WebSocket | `host=proxy.example.com`, `path=/ws`, `match_type=host_path`, `http_mode=websocket` | `backend_type=http` |
| Host + Path XHTTP / SplitHTTP | `host=proxy.example.com`, `path=/xhttp`, `match_type=host_path`, `http_mode=xhttp_stream` | `backend_type=http` |
| gRPC | `host=grpc.example.com`, `path=/grpc`, `match_type=host_path` | `backend_type=grpc` |
| 所有 Host 共享路径 | `host=null`, `path=/api`, `match_type=path` | `backend_type=http` |
| 默认 fallback | `host=null`, `path=/`, `match_type=default`, `is_default_fallback=true` | `backend_type=http` 或 `grpc` |

示例：

```json
{
  "name": "proxy-ws",
  "host": "proxy.example.com",
  "path": "/ws",
  "match_type": "host_path",
  "backend_type": "http",
  "http_mode": "websocket",
  "backend_name": "xray-ws"
}
```

## fallback 来源

fallback 不是生成器自动编造的地址。它必须先作为普通后端存在，然后由 HTTP 默认路由引用。

配置链路：

```json
{
  "backends": [
    {
      "name": "web-fallback",
      "host": "web-fallback",
      "port": 80,
      "protocol": "http"
    }
  ],
  "http_routes": [
    {
      "name": "fallback-site",
      "host": null,
      "path": "/",
      "match_type": "default",
      "backend_type": "http",
      "http_mode": "normal",
      "backend_name": "web-fallback",
      "is_default_fallback": true
    }
  ]
}
```

生成结果里的 `server web-fallback:80;` 就来自这个 backend 记录。

如果没有配置 HTTP default fallback，生成器不会发明后端，而是为 `/` 生成 404：

```nginx
location / {
    return 404;
}
```

注意区分两种默认：

| 默认项 | 位置 | 含义 |
| --- | --- | --- |
| `default_sni_action` | TCP stream 层 | 没命中任何 SNI 规则时进入 HTTP 终止、TLS 透传或 reject |
| `match_type=default` | HTTP 路由层 | 进入 HTTP 终止后，没命中更具体 Host/Path 时转发到哪个后端 |

## hd01 3x-ui + NPM + frps 配置例子

这个例子对应 hd01 当前迁移目标：OmniProxyGate 在前，NPM 保持运行并作为 downstream backend。

### 后端

```json
[
  {
    "name": "xui-reality-443",
    "host": "10.44.102.100",
    "port": 443,
    "protocol": "tcp_tls",
    "send_proxy_protocol": true
  },
  {
    "name": "xui-tls-fallback-1443",
    "host": "10.44.102.100",
    "port": 1443,
    "protocol": "tcp_tls",
    "send_proxy_protocol": true
  },
  {
    "name": "frps-tls-443",
    "host": "tasks.frps",
    "port": 443,
    "protocol": "tcp_tls",
    "send_proxy_protocol": false
  },
  {
    "name": "npm-legacy-stream-444",
    "host": "npm",
    "port": 444,
    "protocol": "tcp_tls",
    "send_proxy_protocol": false
  },
  {
    "name": "xui-grpc-D90",
    "host": "3xui",
    "port": 10002,
    "protocol": "grpc"
  },
  {
    "name": "xui-xhttp-D90-grpc-compat",
    "host": "3xui",
    "port": 10003,
    "protocol": "grpc"
  },
  {
    "name": "xui-panel",
    "host": "3xui",
    "port": 2053,
    "protocol": "http"
  },
  {
    "name": "libretv-fallback",
    "host": "tasks.libretv",
    "port": 8080,
    "protocol": "http"
  }
]
```

### 公网入口

```json
{
  "tcp_port": [443, 2053],
  "udp_port": [443, 2053],
  "default_sni_action": "tls_passthrough",
  "default_backend": "npm-legacy-stream-444",
  "internal_http_host": "127.0.0.1",
  "internal_http_port": 8443
}
```

含义：

| 流量 | 第一跳 |
| --- | --- |
| 443 TCP 命中特殊 SNI | 按 SNI 透传到 3x-ui 或 frps |
| 443 TCP 未命中特殊 SNI | 透传到 NPM `npm:444`，让旧 NPM 继续处理 legacy 站点 |
| 2053 TCP | 进入 Omni HTTP 终止层，按 Host/Path 路由 |
| 2053 UDP | 进入 Omni HTTP/3 终止层，复用 HTTP 路由 |

### SNI 分流

```json
[
  { "sni": "hm.813711.xyz", "action": "tls_passthrough", "backend": "frps-tls-443" },
  { "sni": "*.hm.813711.xyz", "action": "tls_passthrough", "backend": "frps-tls-443" },
  { "sni": "hm.whiz.ga", "action": "tls_passthrough", "backend": "frps-tls-443" },
  { "sni": "*.hm.whiz.ga", "action": "tls_passthrough", "backend": "frps-tls-443" },
  { "sni": "hkust.edu.hk", "action": "tls_passthrough", "backend": "xui-reality-443" },
  { "sni": "*.hkust.edu.hk", "action": "tls_passthrough", "backend": "xui-reality-443" },
  { "sni": "cw.813711.xyz", "action": "tls_passthrough", "backend": "xui-reality-443" },
  { "sni": "*.cw.813711.xyz", "action": "tls_passthrough", "backend": "xui-reality-443" },
  { "sni": "tv.813711.xyz", "action": "tls_passthrough", "backend": "xui-tls-fallback-1443" },
  { "sni": "*.tv.813711.xyz", "action": "tls_passthrough", "backend": "xui-tls-fallback-1443" },
  { "sni": "tv6.813711.xyz", "action": "tls_passthrough", "backend": "xui-tls-fallback-1443" },
  { "sni": "*.tv6.813711.xyz", "action": "tls_passthrough", "backend": "xui-tls-fallback-1443" }
]
```

### HTTP / gRPC / xHTTP / panel

```json
[
  {
    "name": "D90-grpc-path",
    "host": null,
    "path": "/D90.grpc",
    "match_type": "path",
    "backend_type": "grpc",
    "backend": "xui-grpc-D90"
  },
  {
    "name": "D90-xhttp-grpc-compat-path",
    "host": null,
    "path": "/D90.xhttp",
    "match_type": "path",
    "backend_type": "grpc",
    "backend": "xui-xhttp-D90-grpc-compat"
  },
  {
    "name": "panel-3xui-hd1",
    "host": "3xui-hd1.813711.xyz",
    "path": "/",
    "match_type": "host_path",
    "backend_type": "http",
    "http_mode": "websocket",
    "backend": "xui-panel"
  },
  {
    "name": "libretv-default-fallback",
    "host": null,
    "path": "/",
    "match_type": "default",
    "backend_type": "http",
    "http_mode": "normal",
    "backend": "libretv-fallback",
    "is_default_fallback": true
  }
]
```

`/D90.xhttp` 目前按旧 NPM 配置保持 `grpc_pass grpc://3xui:10003` 兼容形态。这个点必须在高端口测试中用真实客户端确认；如果确认 xHTTP 需要普通 HTTP 流式代理，应改为 `backend_type=http` + `http_mode=xhttp_stream`。

## 样例配置

唯一样例文件是：

```text
examples/sample-config.json
```

它覆盖这些场景：

| 场景 | 样例名称 |
| --- | --- |
| fallback 网站 | `web-fallback`, `fallback-site` |
| Path-only API | `api`, `shared-api-path` |
| WebSocket | `xray-ws`, `proxy-ws` |
| XHTTP / SplitHTTP | `xray-xhttp`, `proxy-xhttp` |
| gRPC | `xray-grpc`, `grpc-service` |
| TLS passthrough | `xray-reality`, `reality-exact`, `reality-wildcard` |
| SNI + ALPN | `grpc-h2-only`, `legacy-h1-only` |
| 泛域名 SNI | `apps-wildcard-http`, `reality-wildcard` |
| reject | `reject-blocked` |

空库加载样例：

```yaml
environment:
  - SAMPLE_DATA_JSON=/app/examples/sample-config.json
```

## 当前已知限制

1. TCP stream 层可以组合 `SNI + ALPN`，但看不到 HTTP `Path`。
2. HTTP 路由层可以组合 `Host + Path`，但当前模型没有每条 HTTP 路由的 `h1/h2/h3` 协议选择器。
3. HTTP/3 不能通过 TCP stream SNI 分流，因为它是 UDP QUIC。
4. 泛域名只支持前缀 `*.example.com`。
5. `*.example.com` 不匹配 `example.com`，需要单独配置 apex。
6. 动态 DNS 解析默认使用 Docker 内置 DNS `127.0.0.11`，当前运行形态默认面向 Docker/Compose 网络。
7. 当前 UI 是主配置入口；JSON 只有种子数据能力，不是正式导入/导出工作流。

如果后续要让 `SNI + H1/H2/H3 + Path` 都作为可组合分流维度，需要新增 HTTP route 协议条件，例如 `protocol_match = any | h1 | h2 | h3`，并调整生成器按协议拆分或加保护条件。
