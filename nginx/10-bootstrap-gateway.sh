#!/bin/sh
set -eu

mkdir -p /etc/nginx/certs /etc/nginx/conf.d /etc/nginx/stream.d /var/log/nginx

if [ ! -f /etc/nginx/certs/default.crt ] || [ ! -f /etc/nginx/certs/default.key ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 \
    -subj "/CN=localhost" \
    -keyout /etc/nginx/certs/default.key \
    -out /etc/nginx/certs/default.crt >/dev/null 2>&1
fi

if [ ! -f /etc/nginx/conf.d/gateway-http.conf ]; then
  cat > /etc/nginx/conf.d/gateway-http.conf <<'EOF'
# Initial placeholder. The UI will overwrite this file.
map $http_upgrade $nggm_connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 0.0.0.0:8443 ssl;
    http2 on;
    server_name _;
    ssl_certificate /etc/nginx/certs/default.crt;
    ssl_certificate_key /etc/nginx/certs/default.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    location / {
        return 404;
    }
}
EOF
fi

if [ ! -f /etc/nginx/stream.d/gateway-stream.conf ]; then
  cat > /etc/nginx/stream.d/gateway-stream.conf <<'EOF'
# Initial placeholder. The UI will overwrite this file.
map "$ssl_preread_server_name|$ssl_preread_alpn_protocols" $nggm_stream_upstream {
    default nggm_http_termination;
}

upstream nggm_http_termination {
    server 127.0.0.1:8443;
}

server {
    listen 0.0.0.0:443;
    listen [::]:443 ipv6only=on;
    ssl_preread on;
    proxy_connect_timeout 5s;
    proxy_timeout 1h;
    proxy_pass $nggm_stream_upstream;
}
EOF
fi
