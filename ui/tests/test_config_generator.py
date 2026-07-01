from __future__ import annotations

import os
from types import SimpleNamespace as NS
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config_generator import NginxConfigGenerator


def sample_objects():
    listener = NS(
        id=1,
        name="default",
        tcp_port=443,
        udp_port=443,
        enable_tcp_sni=True,
        enable_http3=True,
        enable_http80=True,
        listen_address_mode="split",
        default_sni_action="http_termination",
        default_backend_id=None,
        internal_http_host="0.0.0.0",
        internal_http_port=8443,
        enabled=True,
    )
    backends = [
        NS(id=1, name="xray-ws", host="xray-ws", port=10001, protocol="http", tls_to_backend=False, send_proxy_protocol=False, keepalive=32, read_timeout=3600, send_timeout=3600, connect_timeout=60, preserve_host=True, forward_real_ip=True),
        NS(id=2, name="xray-xhttp", host="xray-xhttp", port=10002, protocol="http", tls_to_backend=False, send_proxy_protocol=False, keepalive=32, read_timeout=3600, send_timeout=3600, connect_timeout=60, preserve_host=True, forward_real_ip=True),
        NS(id=3, name="xray-grpc", host="xray-grpc", port=10003, protocol="grpc", tls_to_backend=False, send_proxy_protocol=False, keepalive=32, read_timeout=3600, send_timeout=3600, connect_timeout=60, preserve_host=True, forward_real_ip=True),
        NS(id=4, name="web-fallback", host="web-fallback", port=80, protocol="http", tls_to_backend=False, send_proxy_protocol=False, keepalive=32, read_timeout=300, send_timeout=300, connect_timeout=30, preserve_host=True, forward_real_ip=True),
        NS(id=5, name="xray-reality", host="xray-reality", port=443, protocol="tcp_tls", tls_to_backend=False, send_proxy_protocol=True, keepalive=0, read_timeout=3600, send_timeout=3600, connect_timeout=60, preserve_host=True, forward_real_ip=False),
        NS(id=6, name="frps-tls", host="frps", port=443, protocol="tcp_tls", tls_to_backend=False, send_proxy_protocol=False, keepalive=0, read_timeout=3600, send_timeout=3600, connect_timeout=60, preserve_host=True, forward_real_ip=False),
    ]
    certs = [
        NS(id=1, name="proxy", domain="proxy.example.com,grpc.example.com,*.apps.example.com", cert_path="/etc/nginx/certs/default.crt", key_path="/etc/nginx/certs/default.key"),
    ]
    sni_routes = [
        NS(id=1, listener_id=1, name="proxy", enabled=True, sni="proxy.example.com", alpn=None, priority=10, action="http_termination", backend_id=None),
        NS(id=2, listener_id=1, name="grpc", enabled=True, sni="grpc.example.com", alpn="h2", priority=20, action="http_termination", backend_id=None),
        NS(id=3, listener_id=1, name="reality", enabled=True, sni="reality.example.com", alpn=None, priority=30, action="tls_passthrough", backend_id=5),
        NS(id=4, listener_id=1, name="wildcard", enabled=True, sni="*.apps.example.com", alpn=None, priority=40, action="http_termination", backend_id=None),
        NS(id=5, listener_id=1, name="legacy-h1", enabled=True, sni="legacy.example.com", alpn="http/1.1", priority=50, action="http_termination", backend_id=None),
        NS(id=6, listener_id=1, name="frps", enabled=True, sni="hm.example.com", alpn=None, priority=60, action="tls_passthrough", backend_id=6),
        NS(id=7, listener_id=1, name="multi", enabled=True, sni="a.example.com,*.multi.example.com", alpn="h2,http/1.1", priority=70, action="http_termination", backend_id=None),
    ]
    http_routes = [
        NS(id=1, name="ws", enabled=True, host="proxy.example.com", path="/ws", match_type="host_path", priority=10, backend_type="http", http_mode="websocket", backend_id=1, is_default_fallback=False),
        NS(id=2, name="xhttp", enabled=True, host="proxy.example.com", path="/xhttp", match_type="host_path", priority=20, backend_type="http", http_mode="xhttp_stream", backend_id=2, is_default_fallback=False),
        NS(id=3, name="grpc", enabled=True, host="grpc.example.com", path="/grpc", match_type="host_path", priority=10, backend_type="grpc", http_mode=None, backend_id=3, is_default_fallback=False),
        NS(id=4, name="fallback", enabled=True, host=None, path="/", match_type="default", priority=1000, backend_type="http", http_mode="normal", backend_id=4, is_default_fallback=True),
        NS(id=5, name="same-path-h2", enabled=True, host="combo.example.com", path="/mux", alpn="h2", match_type="host_path_alpn", priority=10, backend_type="grpc", http_mode=None, backend_id=3, is_default_fallback=False),
        NS(id=6, name="same-path-h1", enabled=True, host="combo.example.com", path="/mux", alpn="http/1.1", match_type="host_path_alpn", priority=20, backend_type="http", http_mode="normal", backend_id=1, is_default_fallback=False),
        NS(id=7, name="alpn-only", enabled=True, host=None, path=None, alpn="h2,h3", match_type="alpn", priority=50, backend_type="grpc", http_mode=None, backend_id=3, is_default_fallback=False),
    ]
    return listener, sni_routes, http_routes, backends, certs


def test_generate_contains_required_blocks():
    generated = NginxConfigGenerator(*sample_objects()).generate()
    assert "ssl_preread on;" in generated.stream
    assert "proxy\\.example\\.com" in generated.stream
    assert "resolver 127.0.0.11 ipv6=off valid=10s;" in generated.stream
    assert "set $nggm_stream_backend_backend_5 \"xray-reality:443\";" in generated.stream
    assert "~^(?:[^|.]+\\.)+apps\\.example\\.com\\|.*$" in generated.stream
    assert "~^legacy\\.example\\.com\\|(.*,)?http/1\\.1(,.*)?$" in generated.stream
    assert "~^(?:a\\.example\\.com|(?:[^|.]+\\.)+multi\\.example\\.com)\\|(.*,)?(?:h2|http/1\\.1)(,.*)?$" in generated.stream
    assert "listen 0.0.0.0:443;" in generated.stream
    assert "listen [::]:443 ipv6only=on;" in generated.stream
    assert "set $nggm_http_backend_3 \"xray-grpc:10003\";" in generated.http
    assert "grpc_pass grpc://$nggm_http_backend_3;" in generated.http
    assert "proxy_pass http://$nggm_http_backend_1;" in generated.http
    assert "server_name proxy.example.com;" in generated.http
    assert "server_name grpc.example.com;" in generated.http
    assert "server_name combo.example.com;" in generated.http
    assert "server_name *.apps.example.com;" not in generated.http
    assert "# Dispatcher: combo.example.com /mux by ALPN" in generated.http
    assert 'if ($ssl_alpn_protocol ~* "^h2$") { return 470; }' in generated.http
    assert 'if ($ssl_alpn_protocol ~* "^http/1\\.1$") { return 471; }' in generated.http
    assert 'if ($http3 ~* "^h3$")' in generated.http
    assert "location @nggm_http_combo_example_com_route_5 {" in generated.http
    assert "location @nggm_http_combo_example_com_route_6 {" in generated.http
    assert "proxy_set_header Upgrade $http_upgrade;" in generated.http
    assert "proxy_request_buffering off;" in generated.http
    assert "listen 0.0.0.0:443 quic default_server reuseport;" in generated.http
    assert "ssl_reject_handshake on;" in generated.http
    assert "listen 0.0.0.0:443 quic;" in generated.http


def test_generate_supports_per_backend_proxy_protocol_and_port_arrays():
    listener, sni_routes, http_routes, backends, certs = sample_objects()
    listener.tcp_ports = [443, 2053]
    listener.udp_ports = [443, 2053]
    generated = NginxConfigGenerator(listener, sni_routes, http_routes, backends, certs).generate()

    assert "listen 0.0.0.0:2053;" in generated.stream
    assert "backend_5" in generated.stream
    assert "backend_6" in generated.stream
    assert "set $nggm_stream_backend_backend_5 \"xray-reality:443\";" in generated.stream
    assert "set $nggm_stream_backend_backend_6 \"frps:443\";" in generated.stream
    assert "listen 127.0.0.1:190" in generated.stream
    assert " proxy_protocol;" in generated.stream
    assert "set_real_ip_from 127.0.0.1;" in generated.stream
    assert generated.stream.count("proxy_protocol on;") == 3
    assert "proxy_pass nggm_http_termination;" in generated.stream
    assert "listen 0.0.0.0:8443 ssl proxy_protocol;" in generated.http
    assert "set_real_ip_from 127.0.0.1;" in generated.http
    assert "real_ip_header proxy_protocol;" in generated.http
    assert "listen 0.0.0.0:2053 quic default_server reuseport;" in generated.http
    assert "upstream nggm_http_termination {\n    server 127.0.0.1:8443;" in generated.stream


def test_cert_only_domains_do_not_create_http_servers():
    listener = NS(
        id=1,
        name="ora01",
        tcp_port=443,
        udp_port=443,
        enable_tcp_sni=True,
        enable_http3=True,
        enable_http80=True,
        listen_address_mode="split",
        default_sni_action="tls_passthrough",
        default_backend_id=1,
        internal_http_host="0.0.0.0",
        internal_http_port=8443,
        enabled=True,
    )
    backends = [
        NS(id=1, name="npm", host="npm", port=8443, protocol="tcp_tls", tls_to_backend=False, send_proxy_protocol=True, keepalive=0, read_timeout=3600, send_timeout=3600, connect_timeout=5, preserve_host=True, forward_real_ip=False),
    ]
    certs = [
        NS(id=1, name="npm-wildcard", domain="*.813711.xyz,*.ora1.813711.xyz", cert_path="/etc/letsencrypt/live/npm-23/cert.pem", key_path="/etc/letsencrypt/live/npm-23/privkey.pem"),
    ]
    sni_routes = [
        NS(id=1, listener_id=1, name="npm-wildcards", enabled=True, sni="*.813711.xyz,*.ora1.813711.xyz", alpn=None, priority=10, action="tls_passthrough", backend_id=1),
    ]

    generated = NginxConfigGenerator(listener, sni_routes, [], backends, certs).generate()

    assert "server_name *.813711.xyz;" not in generated.http
    assert "server_name *.ora1.813711.xyz;" not in generated.http
    assert "~^(?:(?:[^|.]+\\.)+813711\\.xyz|(?:[^|.]+\\.)+ora1\\.813711\\.xyz)\\|.*$" in generated.stream
    assert 'set $nggm_stream_backend_backend_1 "npm:8443";' in generated.stream
    assert "listen 127.0.0.1:19000 proxy_protocol;" in generated.stream
    assert "proxy_pass $nggm_stream_backend_backend_1;" in generated.stream


def write_examples():
    generated = NginxConfigGenerator(*sample_objects()).generate()
    out = ROOT.parent / "examples" / "generated"
    out.mkdir(exist_ok=True)
    (out / "gateway-http.conf").write_text(generated.http, encoding="utf-8")
    (out / "gateway-stream.conf").write_text(generated.stream, encoding="utf-8")


if __name__ == "__main__":
    test_generate_contains_required_blocks()
    test_generate_supports_per_backend_proxy_protocol_and_port_arrays()
    test_cert_only_domains_do_not_create_http_servers()
    if os.getenv("WRITE_GENERATED_EXAMPLES", "").lower() in {"1", "true", "yes", "on"}:
        write_examples()
    print("config generator tests passed")
