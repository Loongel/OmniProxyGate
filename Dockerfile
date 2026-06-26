ARG PYTHON_VERSION=3.12
ARG DEBIAN_RELEASE=bookworm
ARG NGINX_VERSION=1.31.1

FROM debian:${DEBIAN_RELEASE} AS nginx-build
ARG NGINX_VERSION
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential ca-certificates wget libssl-dev libpcre2-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp
RUN wget -q "https://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz" \
    && tar -xzf "nginx-${NGINX_VERSION}.tar.gz"
WORKDIR /tmp/nginx-${NGINX_VERSION}
RUN ./configure \
      --prefix=/etc/nginx \
      --sbin-path=/usr/sbin/nginx \
      --modules-path=/usr/lib/nginx/modules \
      --conf-path=/etc/nginx/nginx.conf \
      --error-log-path=/var/log/nginx/error.log \
      --http-log-path=/var/log/nginx/access.log \
      --pid-path=/var/run/nginx.pid \
      --lock-path=/var/run/nginx.lock \
      --http-client-body-temp-path=/var/cache/nginx/client_temp \
      --http-proxy-temp-path=/var/cache/nginx/proxy_temp \
      --http-fastcgi-temp-path=/var/cache/nginx/fastcgi_temp \
      --http-uwsgi-temp-path=/var/cache/nginx/uwsgi_temp \
      --http-scgi-temp-path=/var/cache/nginx/scgi_temp \
      --user=nginx \
      --group=nginx \
      --with-compat \
      --with-threads \
      --with-pcre-jit \
      --with-http_ssl_module \
      --with-http_v2_module \
      --with-http_v3_module \
      --with-http_realip_module \
      --with-http_gzip_static_module \
      --with-stream \
      --with-stream_ssl_module \
      --with-stream_ssl_preread_module \
      --with-stream_realip_module \
    && make -j"$(getconf _NPROCESSORS_ONLN)" \
    && make install

FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    GENERATED_HTTP_DIR=/etc/nginx/conf.d \
    GENERATED_STREAM_DIR=/etc/nginx/stream.d \
    LOG_DIR=/var/log/nginx \
    USE_DOCKER_CLI=false \
    NGINX_TEST_COMMAND="nginx -t" \
    NGINX_RELOAD_COMMAND="nginx -s reload" \
    OMNI_RUN_GATEWAY=true \
    OMNI_RUN_UI=true \
    OMNI_WEB_UI_ENABLED=true

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates openssl libpcre2-8-0 zlib1g procps \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system nginx \
    && useradd --system --no-create-home --home-dir /var/cache/nginx --shell /usr/sbin/nologin --gid nginx nginx \
    && mkdir -p /var/cache/nginx /var/log/nginx /etc/nginx/conf.d /etc/nginx/stream.d /etc/nginx/certs /docker-entrypoint.d /data /app

COPY --from=nginx-build /usr/sbin/nginx /usr/sbin/nginx
COPY --from=nginx-build /etc/nginx /etc/nginx
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/10-bootstrap-gateway.sh /docker-entrypoint.d/10-bootstrap-gateway.sh
COPY ui/requirements.txt /app/requirements.txt
RUN chmod +x /docker-entrypoint.d/10-bootstrap-gateway.sh \
    && pip install --no-cache-dir -r /app/requirements.txt
COPY ui/app /app/app
COPY ui/templates /app/templates
COPY ui/static /app/static
COPY examples /app/examples
COPY docker-entrypoint.sh /usr/local/bin/omni-entrypoint
RUN chmod +x /usr/local/bin/omni-entrypoint

EXPOSE 80/tcp 443/tcp 443/udp 8080/tcp
STOPSIGNAL SIGTERM
CMD ["/usr/local/bin/omni-entrypoint"]
