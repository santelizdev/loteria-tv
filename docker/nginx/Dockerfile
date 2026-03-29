FROM nginx:1.27-alpine

COPY docker/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY docker/nginx/docker-entrypoint.d/40-build-pwa.sh /docker-entrypoint.d/40-build-pwa.sh
COPY pwa /opt/pwa-src

RUN chmod +x /docker-entrypoint.d/40-build-pwa.sh
