from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


def _get(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


def _truthy(obj: Any, name: str, default: bool = False) -> bool:
    return bool(_get(obj, name, default))


def _safe_name(value: Any, prefix: str = "item") -> str:
    raw = str(value if value is not None else prefix)
    safe = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe or not safe[0].isalpha():
        safe = f"{prefix}_{safe}"
    return safe[:80]


def _fmt_host_port(host: str, port: int) -> str:
    if ":" in host and not host.startswith("[") and not host.endswith("]"):
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def _quote_nginx(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _fmt_listen_host_port(host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def _connect_host_for_listen_host(host: str) -> str:
    # Wildcard listen addresses are not good upstream targets. Stream-to-HTTP
    # handoff stays inside this container, so loopback remains the right target.
    normalized = (host or "").strip().lower().strip("[]")
    if normalized in {"", "0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def _domain_to_regex(domain: str) -> str:
    domain = domain.lower().strip()
    if domain.startswith("*."):
        suffix = re.escape(domain[2:])
        return rf"(?:[^|.]+\.)+{suffix}"
    return re.escape(domain)


def _split_route_values(value: Optional[str]) -> list[str]:
    if not value:
        return []
    values: list[str] = []
    for part in re.split(r"[\s,，;；]+", value):
        item = part.strip()
        if item and item not in values:
            values.append(item)
    return values


def _domains_to_regex(domains: str) -> str:
    parts = [_domain_to_regex(domain) for domain in _split_route_values(domains)]
    if not parts:
        return re.escape("")
    if len(parts) == 1:
        return parts[0]
    return "(?:" + "|".join(parts) + ")"


def _alpn_to_regex(alpn: str) -> str:
    parts = [re.escape(value) for value in _split_route_values(alpn)]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "(?:" + "|".join(parts) + ")"


def _http_route_has_alpn(route: Any) -> bool:
    return bool((_get(route, "alpn", None) or "").strip())


def _http_route_is_default(route: Any) -> bool:
    return _get(route, "match_type") == "default" or _truthy(route, "is_default_fallback", False)


def _http_route_specificity(route: Any) -> int:
    return int(bool(_get(route, "host", None))) + int(bool(_get(route, "path", None))) + int(_http_route_has_alpn(route))


def _nginx_server_name(domain: Optional[str]) -> str:
    return domain or "_"


def _domain_matches(pattern: str, host: str) -> bool:
    pattern = (pattern or "").lower()
    host = (host or "").lower()
    if not pattern or pattern == "_":
        return True
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return host.endswith(suffix) and host != pattern[2:]
    return pattern == host


def _domain_list_matches(patterns: str, host: str) -> bool:
    return any(_domain_matches(pattern, host) for pattern in _split_route_values(patterns))


def _domain_list_contains_exact(patterns: str, host: str) -> bool:
    host = (host or "").lower()
    return any(pattern.lower() == host for pattern in _split_route_values(patterns))


def _domain_list_contains_wildcard_match(patterns: str, host: str) -> bool:
    return any(pattern.startswith("*.") and _domain_matches(pattern, host) for pattern in _split_route_values(patterns))


def _split_words(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[\s,]+", value) if part.strip()]


def _coerce_ports(value: Any, default: int) -> list[int]:
    if value is None:
        raw_values = [default]
    elif isinstance(value, list):
        raw_values = value
    elif isinstance(value, str):
        raw_values = _split_words(value)
    else:
        raw_values = [value]
    ports: list[int] = []
    for raw in raw_values:
        try:
            port = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535 and port not in ports:
            ports.append(port)
    return ports or [default]


def _http_backend_var(backend: Any) -> str:
    backend_id = _get(backend, "id", None)
    if backend_id is not None:
        return f"nggm_http_backend_{backend_id}"
    return f"nggm_http_backend_{_safe_name(_get(backend, 'name', 'backend'), 'backend')}"


def _stream_route_key_for_backend(backend: Any) -> str:
    backend_id = _get(backend, "id", None)
    if backend_id is not None:
        return f"backend_{backend_id}"
    return f"backend_{_safe_name(_get(backend, 'name', 'backend'), 'backend')}"


def _listener_listen_lines(port: int, mode: str, *, quic: bool = False, reuseport: bool = True, stream: bool = False) -> list[str]:
    suffix = " quic" if quic else ""
    if quic and reuseport:
        suffix += " reuseport"
    # For repeated HTTP/3 virtual servers, socket options such as reuseport and ipv6only
    # must appear only on the first listen for an address. Subsequent server blocks keep
    # the same address/port/protocol but omit socket-level options.
    omit_socket_options = quic and not reuseport
    if mode == "ipv4_only":
        return [f"listen 0.0.0.0:{port}{suffix};"]
    if mode == "ipv6_only":
        tail = "" if omit_socket_options else " ipv6only=on"
        return [f"listen [::]:{port}{suffix}{tail};"]
    if mode == "unified":
        tail = "" if omit_socket_options else " ipv6only=off"
        return [f"listen [::]:{port}{suffix}{tail};"]
    # split is the recommended default: independent IPv4 and IPv6 sockets.
    tail = "" if omit_socket_options else " ipv6only=on"
    return [f"listen 0.0.0.0:{port}{suffix};", f"listen [::]:{port}{suffix}{tail};"]


@dataclass
class GeneratedConfig:
    http: str
    stream: str
    warnings: list[str] = field(default_factory=list)


class NginxConfigGenerator:
    """Render nginx HTTP and stream snippets from persisted gateway objects.

    The generated files are snippets intended to be included from nginx.conf:
      http   { include /etc/nginx/conf.d/*.conf; }
      stream { include /etc/nginx/stream.d/*.conf; }
    """

    def __init__(
        self,
        listener: Any,
        sni_routes: Iterable[Any],
        http_routes: Iterable[Any],
        backends: Iterable[Any],
        certificates: Iterable[Any],
    ) -> None:
        self.listener = listener
        self.sni_routes = [r for r in sni_routes if _truthy(r, "enabled", True)]
        self.http_routes = [r for r in http_routes if _truthy(r, "enabled", True)]
        self.backends = {_get(b, "id"): b for b in backends}
        self.certificates = list(certificates)
        self.warnings: list[str] = []

    def _tcp_ports(self) -> list[int]:
        return _coerce_ports(_get(self.listener, "tcp_ports", None), int(_get(self.listener, "tcp_port", 443)))

    def _udp_ports(self) -> list[int]:
        return _coerce_ports(_get(self.listener, "udp_ports", None), int(_get(self.listener, "udp_port", 443)))

    def generate(self) -> GeneratedConfig:
        return GeneratedConfig(http=self.generate_http(), stream=self.generate_stream(), warnings=self.warnings)

    def _route_key_for_sni_action(self, action: str, backend_id: Optional[int]) -> str:
        if action == "http_termination":
            return "http_termination"
        if action == "reject":
            return "reject"
        backend = self.backends.get(backend_id)
        if not backend:
            self.warnings.append(f"SNI route references missing backend_id={backend_id}; using reject target")
            return "reject"
        return _stream_route_key_for_backend(backend)

    def _default_stream_route_key(self) -> str:
        action = _get(self.listener, "default_sni_action", "http_termination")
        backend_id = _get(self.listener, "default_backend_id", None)
        return self._route_key_for_sni_action(action, backend_id)

    def _stream_route_endpoint(self, route_key: str, internal_endpoints: dict[str, int]) -> str:
        if route_key == "http_termination":
            internal_host = _get(self.listener, "internal_http_host", "0.0.0.0")
            internal_port = int(_get(self.listener, "internal_http_port", 8443))
            return _fmt_host_port(_connect_host_for_listen_host(internal_host), internal_port)
        if route_key == "reject":
            return "127.0.0.1:9"
        port = internal_endpoints.get(route_key)
        if port is None:
            return "nggm_reject"
        return f"127.0.0.1:{port}"

    def generate_stream(self) -> str:
        if not _truthy(self.listener, "enabled", True) or not _truthy(self.listener, "enable_tcp_sni", True):
            return "# Generated by OmniProxyGate. TCP SNI listener is disabled.\n"

        now = datetime.now(timezone.utc).isoformat()
        lines: list[str] = [
            "# Generated by OmniProxyGate. Do not edit manually.",
            f"# Generated at: {now}",
            "",
            "# Docker embedded DNS lets unresolved backend names fail per connection, not at nginx startup.",
            "resolver 127.0.0.11 ipv6=off valid=10s;",
            "resolver_timeout 2s;",
            "",
            "# SNI/ALPN route map. Routes point to internal stream listeners when backend compatibility differs.",
            "map \"$ssl_preread_server_name|$ssl_preread_alpn_protocols\" $nggm_stream_route {",
        ]

        route_keys: list[str] = []

        def remember_route_key(value: str) -> str:
            if value not in route_keys:
                route_keys.append(value)
            return value

        default_route_key = remember_route_key(self._default_stream_route_key())
        for route in sorted(self.sni_routes, key=lambda r: (_get(r, "priority", 100), _get(r, "id", 0))):
            sni = _get(route, "sni")
            alpn = (_get(route, "alpn", None) or "").strip()
            route_key = remember_route_key(self._route_key_for_sni_action(_get(route, "action"), _get(route, "backend_id", None)))
            sni_regex = _domains_to_regex(sni)
            if alpn:
                # ssl_preread_alpn_protocols is a comma-separated list. Route-level ALPN is optional.
                alpn_regex = _alpn_to_regex(alpn)
                pattern = rf"~^{sni_regex}\|(.*,)?{alpn_regex}(,.*)?$"
            else:
                pattern = rf"~^{sni_regex}\|.*$"
            lines.append(f"    {pattern:<64} {route_key};")
        lines.append(f"    default{'':<57} {default_route_key};")
        lines.extend(["}", ""])

        backend_route_keys = [
            route_key for route_key in route_keys
            if route_key not in {"http_termination", "reject"}
        ]
        internal_endpoints = {route_key: 19000 + idx for idx, route_key in enumerate(backend_route_keys)}

        lines.extend([
            "map $nggm_stream_route $nggm_stream_upstream {",
        ])
        for route_key in route_keys:
            lines.append(f"    {route_key:<61} {self._stream_route_endpoint(route_key, internal_endpoints)};")
        lines.extend([
            "    default                                                       127.0.0.1:9;",
            "}",
            "",
        ])

        internal_host = _get(self.listener, "internal_http_host", "0.0.0.0")
        internal_port = int(_get(self.listener, "internal_http_port", 8443))
        lines.extend([
            "upstream nggm_http_termination {",
            f"    server {_fmt_host_port(_connect_host_for_listen_host(internal_host), internal_port)};",
            "}",
            "",
            "# Reject target: intentionally points to the local discard port so nginx closes quickly.",
            "upstream nggm_reject {",
            "    server 127.0.0.1:9;",
            "}",
            "",
        ])

        for route_key in backend_route_keys:
            backend = next((b for b in self.backends.values() if _stream_route_key_for_backend(b) == route_key), None)
            if backend is None:
                continue
            backend_addr = _fmt_host_port(_get(backend, "host"), int(_get(backend, "port")))
            backend_var = f"nggm_stream_backend_{_safe_name(route_key, 'backend')}"
            lines.extend([
                f"# TLS passthrough backend: {_get(backend, 'name', route_key)}",
                "server {",
                f"    listen 127.0.0.1:{internal_endpoints[route_key]} proxy_protocol;",
                "    set_real_ip_from 127.0.0.1;",
                f"    set ${backend_var} {_quote_nginx(backend_addr)};",
                "    proxy_connect_timeout 5s;",
                "    proxy_timeout 1h;",
            ])
            if _truthy(backend, "send_proxy_protocol", False):
                lines.append("    proxy_protocol on;")
            lines.extend([
                f"    proxy_pass ${backend_var};",
                "}",
                "",
            ])

        tcp_ports = self._tcp_ports()
        tcp_port = tcp_ports[0]
        mode = _get(self.listener, "listen_address_mode", "split")
        lines.extend(["server {"])
        for listen_line in _listener_listen_lines(tcp_port, mode):
            lines.append(f"    {listen_line}")
        lines.extend([
            "    ssl_preread on;",
            "    proxy_connect_timeout 5s;",
            "    proxy_timeout 1h;",
            "    proxy_protocol on;",
        ])
        lines.extend([
            "    proxy_pass $nggm_stream_upstream;",
            "}",
            "",
        ])
        for extra_port in tcp_ports[1:]:
            lines.extend(["server {"])
            for listen_line in _listener_listen_lines(extra_port, mode):
                lines.append(f"    {listen_line}")
            lines.extend([
                "    ssl_preread on;",
                "    proxy_connect_timeout 5s;",
                "    proxy_timeout 1h;",
                "    proxy_protocol on;",
            ])
            lines.extend([
                "    proxy_pass nggm_http_termination;",
                "}",
                "",
            ])
        return "\n".join(lines)

    def _cert_for_host(self, host: str) -> Optional[Any]:
        if not self.certificates:
            return None
        exact = [c for c in self.certificates if _domain_list_contains_exact(_get(c, "domain", ""), host)]
        if exact:
            return exact[0]
        wildcard = [c for c in self.certificates if _domain_list_contains_wildcard_match(_get(c, "domain", ""), host)]
        if wildcard:
            return wildcard[0]
        return self.certificates[0]

    def _all_server_names(self) -> list[str]:
        names: list[str] = []
        needs_catch_all = False
        for cert in self.certificates:
            for domain in _split_route_values(_get(cert, "domain", None)):
                if domain not in names:
                    names.append(domain)
        for route in self.http_routes:
            host = _get(route, "host", None)
            if host and host not in names:
                names.append(host)
            if not host or _http_route_is_default(route):
                needs_catch_all = True
        if needs_catch_all and "_" not in names:
            names.append("_")
        if not names:
            names = ["_"]
        return names

    def _http_dynamic_resolution(self) -> str:
        for route in self.http_routes:
            backend_id = _get(route, "backend_id")
            if backend_id not in self.backends:
                self.warnings.append(f"HTTP route {_get(route, 'name', route)} references missing backend_id={backend_id}")
        return "\n".join([
            "# Backend DNS is resolved at request time so nginx can start before peer containers exist.",
            "resolver 127.0.0.11 ipv6=off valid=10s;",
            "resolver_timeout 2s;",
            "",
        ])

    def _route_applies_to_server(self, route: Any, server_name: str) -> bool:
        route_host = _get(route, "host", None)
        if _http_route_is_default(route):
            return True
        if not route_host:
            return True
        if server_name != "_":
            return _domain_list_matches(route_host, server_name) or route_host == server_name
        return False

    def _render_location(self, route: Any, location_name: Optional[str] = None) -> list[str]:
        backend = self.backends.get(_get(route, "backend_id"))
        if backend is None:
            return ["    # Skipped route with missing backend."]
        path = _get(route, "path", None) or "/"
        backend_type = _get(route, "backend_type", "http")
        route_name = _get(route, "name", "route")
        backend_var = _http_backend_var(backend)
        backend_addr = _fmt_host_port(_get(backend, "host"), int(_get(backend, "port")))
        read_timeout = int(_get(backend, "read_timeout", 3600) or 3600)
        send_timeout = int(_get(backend, "send_timeout", 3600) or 3600)
        connect_timeout = int(_get(backend, "connect_timeout", 60) or 60)
        preserve_host = _truthy(backend, "preserve_host", True)
        forward_real_ip = _truthy(backend, "forward_real_ip", True)
        location = f"@{location_name}" if location_name else path
        lines = [
            f"    # Route: {route_name}",
            f"    location {location} {{",
            f"        set ${backend_var} {_quote_nginx(backend_addr)};",
        ]
        if backend_type == "grpc":
            protocol = _get(backend, "protocol", "grpc")
            scheme = "grpcs" if protocol == "grpcs" or _truthy(backend, "tls_to_backend", False) else "grpc"
            lines.extend([
                f"        grpc_pass {scheme}://${backend_var};",
                f"        grpc_connect_timeout {connect_timeout}s;",
                f"        grpc_read_timeout {read_timeout}s;",
                f"        grpc_send_timeout {send_timeout}s;",
            ])
            if preserve_host:
                lines.append("        grpc_set_header Host $host;")
            if forward_real_ip:
                lines.extend([
                    "        grpc_set_header X-Real-IP $remote_addr;",
                    "        grpc_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                    "        grpc_set_header X-Forwarded-Proto $scheme;",
                ])
        else:
            protocol = _get(backend, "protocol", "http")
            scheme = "https" if protocol == "https" or _truthy(backend, "tls_to_backend", False) else "http"
            mode = _get(route, "http_mode", "normal") or "normal"
            lines.extend([
                "        proxy_http_version 1.1;",
                f"        proxy_pass {scheme}://${backend_var};",
                f"        proxy_connect_timeout {connect_timeout}s;",
                f"        proxy_read_timeout {read_timeout}s;",
                f"        proxy_send_timeout {send_timeout}s;",
                "        proxy_redirect off;",
            ])
            if preserve_host:
                lines.append("        proxy_set_header Host $host;")
            else:
                lines.append(f"        proxy_set_header Host {_get(backend, 'host')};")
            if forward_real_ip:
                lines.extend([
                    "        proxy_set_header X-Real-IP $remote_addr;",
                    "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                    "        proxy_set_header X-Forwarded-Proto $scheme;",
                    "        proxy_set_header X-Forwarded-Host $host;",
                ])
            if mode == "websocket":
                lines.extend([
                    "        proxy_set_header Upgrade $http_upgrade;",
                    "        proxy_set_header Connection $nggm_connection_upgrade;",
                    "        proxy_buffering off;",
                ])
            elif mode == "xhttp_stream":
                lines.extend([
                    "        proxy_buffering off;",
                    "        proxy_request_buffering off;",
                    "        proxy_cache off;",
                    "        proxy_set_header Connection \"\";",
                    "        chunked_transfer_encoding on;",
                ])
        lines.extend(["    }", ""])
        return lines

    def _route_order_key(self, route: Any) -> tuple[int, int, int, int, int]:
        return (
            1 if _http_route_is_default(route) else 0,
            _get(route, "priority", 100),
            -_http_route_specificity(route),
            -len(_get(route, "path", "") or "/"),
            _get(route, "id", 0),
        )

    def _alpn_if_conditions(self, route: Any) -> list[str]:
        values = _split_route_values((_get(route, "alpn", None) or "").strip())
        if not values:
            return []
        conditions = [f'$ssl_alpn_protocol ~* "^{_alpn_to_regex(",".join(values))}$"']
        http3_values = [value for value in values if value.lower().startswith("h3")]
        if http3_values:
            conditions.append(f'$http3 ~* "^{_alpn_to_regex(",".join(http3_values))}$"')
        return conditions

    def _route_location_name(self, server_name: str, route: Any) -> str:
        return f"nggm_http_{_safe_name(server_name, 'server')}_{_safe_name(_get(route, 'id', _get(route, 'name', 'route')), 'route')}"

    def _render_dispatcher_group(self, server_name: str, path: str, routes: list[Any], code_start: int) -> tuple[list[str], int]:
        lines: list[str] = []
        route_targets: list[tuple[Any, int, str]] = []
        next_code = code_start
        for route in routes:
            if next_code > 599:
                self.warnings.append(f"Too many ALPN-dispatched HTTP routes for {server_name}{path}; skipped route {_get(route, 'name', route)}")
                continue
            location_name = self._route_location_name(server_name, route)
            route_targets.append((route, next_code, location_name))
            lines.append(f"    error_page {next_code} = @{location_name};")
            next_code += 1
        lines.extend([
            f"    # Dispatcher: {server_name} {path} by ALPN",
            f"    location {path} {{",
        ])
        for route, code, _location_name in route_targets:
            conditions = self._alpn_if_conditions(route)
            if conditions:
                for condition in conditions:
                    lines.append(f"        if ({condition}) {{ return {code}; }}")
            else:
                lines.append(f"        return {code};")
                break
        lines.extend([
            "        return 404;",
            "    }",
            "",
        ])
        for route, _code, location_name in route_targets:
            lines.extend(self._render_location(route, location_name=location_name))
        return lines, next_code

    def _render_locations_for_server(self, server_name: str) -> str:
        candidates = [r for r in self.http_routes if self._route_applies_to_server(r, server_name)]
        candidates.sort(key=self._route_order_key)
        path_groups: dict[str, list[Any]] = {}
        for route in candidates:
            path = _get(route, "path", None) or "/"
            path_groups.setdefault(path, []).append(route)
        locations: list[str] = []
        seen_paths: set[str] = set()
        dispatch_code = 470
        for path, routes in path_groups.items():
            if path in seen_paths:
                continue
            seen_paths.add(path)
            if len(routes) > 1 or _http_route_has_alpn(routes[0]):
                rendered, dispatch_code = self._render_dispatcher_group(server_name, path, routes, dispatch_code)
                locations.extend(rendered)
            else:
                locations.extend(self._render_location(routes[0]))
        if "/" not in seen_paths:
            locations.extend([
                "    location / {",
                "        return 404;",
                "    }",
                "",
            ])
        return "\n".join(locations)

    def _server_block(self, server_name: str, *, h3: bool = False, h3_reuseport: bool = True, h3_port: Optional[int] = None) -> str:
        cert = self._cert_for_host(server_name if server_name != "_" else "")
        cert_path = _get(cert, "cert_path", "/etc/nginx/certs/default.crt") if cert else "/etc/nginx/certs/default.crt"
        key_path = _get(cert, "key_path", "/etc/nginx/certs/default.key") if cert else "/etc/nginx/certs/default.key"
        lines: list[str] = ["server {"]
        if h3:
            udp_port = h3_port or self._udp_ports()[0]
            mode = _get(self.listener, "listen_address_mode", "split")
            for listen_line in _listener_listen_lines(udp_port, mode, quic=True, reuseport=h3_reuseport):
                lines.append(f"    {listen_line}")
            lines.extend([
                "    http3 on;",
                "    quic_retry on;",
                f"    add_header Alt-Svc 'h3=\":{udp_port}\"; ma=86400' always;",
            ])
        else:
            internal_host = _get(self.listener, "internal_http_host", "0.0.0.0")
            internal_port = int(_get(self.listener, "internal_http_port", 8443))
            lines.append(f"    listen {_fmt_listen_host_port(internal_host, internal_port)} ssl proxy_protocol;")
            lines.append("    set_real_ip_from 127.0.0.1;")
            lines.append("    real_ip_header proxy_protocol;")
            lines.append("    http2 on;")
        lines.extend([
            f"    server_name {_nginx_server_name(server_name)};",
            f"    ssl_certificate {cert_path};",
            f"    ssl_certificate_key {key_path};",
            "    ssl_protocols TLSv1.2 TLSv1.3;",
            "    ssl_session_cache shared:nggm_ssl_cache:10m;",
            "    ssl_session_timeout 1d;",
            "    server_tokens off;",
        ])
        lines.extend([
            "",
            self._render_locations_for_server(server_name),
            "}",
            "",
        ])
        return "\n".join(lines)

    def _http80_block(self) -> str:
        if not _truthy(self.listener, "enable_http80", True):
            return ""
        mode = _get(self.listener, "listen_address_mode", "split")
        lines: list[str] = ["server {"]
        for listen_line in _listener_listen_lines(80, mode):
            lines.append(f"    {listen_line}")
        lines.extend([
            "    server_name _;",
            "    location / {",
            "        return 308 https://$host$request_uri;",
            "    }",
            "}",
            "",
        ])
        return "\n".join(lines)

    def generate_http(self) -> str:
        now = datetime.now(timezone.utc).isoformat()
        lines: list[str] = [
            "# Generated by OmniProxyGate. Do not edit manually.",
            f"# Generated at: {now}",
            "",
            "map $http_upgrade $nggm_connection_upgrade {",
            "    default upgrade;",
            "    '' close;",
            "}",
            "",
            self._http_dynamic_resolution(),
        ]
        server_names = self._all_server_names()
        for name in server_names:
            lines.append(self._server_block(name, h3=False))
        if _truthy(self.listener, "enable_http3", True):
            for udp_port in self._udp_ports():
                for idx, name in enumerate(server_names):
                    lines.append(self._server_block(name, h3=True, h3_reuseport=(idx == 0), h3_port=udp_port))
        lines.append(self._http80_block())
        if self.warnings:
            lines.extend(["", "# Generator warnings:"] + [f"# - {warning}" for warning in self.warnings])
        return "\n".join(part for part in lines if part is not None)
