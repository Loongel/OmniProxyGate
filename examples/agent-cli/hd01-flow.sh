#!/usr/bin/env sh
set -eu

# Example: split public SNI traffic to NPM, FRPS, and 3X-UI stacks.
# Requires OMNI_URL and OMNI_AGENT_API_TOKEN.

omni doctor
omni export -o omni-backup-before-hd01-flow.json

omni create backend --name npm-https --host npm_app --port 443 --protocol http --scheme https
omni create backend --name frps-tls --host frps --port 443 --protocol tcp_tls --send-proxy-protocol
omni create backend --name xui-panel --host 3xui --port 2053 --protocol http --scheme https
omni create backend --name xui-grpc --host 3xui --port 10001 --protocol grpc
omni create backend --name xui-xhttp --host 3xui --port 10002 --protocol http --scheme http

omni create sni --name npm-public --sni '*.hd1.813711.xyz' --action tls_passthrough --backend npm-https --priority 50
omni create sni --name frps-public --sni 'frps.hd1.813711.xyz' --action tls_passthrough --backend frps-tls --priority 40
omni create sni --name xui-http-termination --sni 'grpc.hd1.813711.xyz,xhttp.hd1.813711.xyz' --action http_termination --priority 30

omni create http --name xui-grpc --host grpc.hd1.813711.xyz --path /grpc --backend xui-grpc --backend-type grpc --priority 30
omni create http --name xui-xhttp --host xhttp.hd1.813711.xyz --path /xhttp --backend xui-xhttp --backend-type http --http-mode xhttp_stream --priority 40

omni preview --section stream
omni preview --section http
# Apply only after reviewing preview output.
# omni apply --yes
