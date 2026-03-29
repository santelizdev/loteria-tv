# Deploy Produccion: Hestia + Docker

Objetivo:
- Hestia conserva SSL y dominios.
- Docker sirve `gateway + app + worker + beat`.
- `ssganador.lat` y `api.ssganador.lat` entran al mismo `gateway`.
- PostgreSQL y Redis siguen en el host.

## Archivos usados

- `docker-compose.prod.yml`
- `.env.prod`
- `docker/nginx/prod.conf`
- `deploy/hestia/ssganador.lat/*`
- `deploy/hestia/api.ssganador.lat/*`

## Secuencia

1. Preparar variables:

```bash
cd /home/deploy/loteriatv
cp .env.prod.example .env.prod
```

2. Editar `.env.prod` con secretos reales y dominios.

3. Actualizar codigo:

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
```

4. Construir stack:

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

5. Verificar internamente:

```bash
curl -I http://127.0.0.1:18080/
curl -I http://127.0.0.1:18080/admin/login/
curl -I http://127.0.0.1:18080/api/results/?code=TEST
docker compose -f docker-compose.prod.yml logs --tail=100 app
docker compose -f docker-compose.prod.yml logs --tail=100 beat
```

6. Desactivar include viejo de `ssganador.lat` que no-cachea JS/HTML:

```bash
mv /home/user/conf/web/ssganador.lat/nginx.ssl.conf_zzz_nocache.conf \
   /home/user/conf/web/ssganador.lat/nginx.ssl.conf_zzz_nocache.conf.disabled
```

7. Instalar includes nuevos de Hestia:

```bash
cp deploy/hestia/ssganador.lat/nginx.conf_zzz_loteriatv_gateway.conf \
   /home/user/conf/web/ssganador.lat/nginx.conf_zzz_loteriatv_gateway.conf
cp deploy/hestia/ssganador.lat/nginx.ssl.conf_zzz_loteriatv_gateway.conf \
   /home/user/conf/web/ssganador.lat/nginx.ssl.conf_zzz_loteriatv_gateway.conf

cp deploy/hestia/api.ssganador.lat/nginx.conf_zzz_loteriatv_gateway.conf \
   /home/user/conf/web/api.ssganador.lat/nginx.conf_zzz_loteriatv_gateway.conf
cp deploy/hestia/api.ssganador.lat/nginx.ssl.conf_zzz_loteriatv_gateway.conf \
   /home/user/conf/web/api.ssganador.lat/nginx.ssl.conf_zzz_loteriatv_gateway.conf
```

8. Validar y recargar Nginx:

```bash
nginx -t
sudo systemctl reload nginx
```

9. Validar externamente:

```bash
curl -Ik https://ssganador.lat
curl -Ik https://api.ssganador.lat/admin/login/
```

10. Ya validado el trafico, apagar legacy:

```bash
sudo systemctl disable --now loteriatv-daphne.service
sudo systemctl disable --now loteriatv-scrape.timer loteriatv-scrape.service
sudo systemctl disable --now loteriatv-retention.timer loteriatv-retention.service
```

## Rollback rapido

```bash
sudo systemctl enable --now loteriatv-daphne.service
sudo systemctl enable --now loteriatv-scrape.timer
sudo systemctl enable --now loteriatv-retention.timer

rm -f /home/user/conf/web/ssganador.lat/nginx.conf_zzz_loteriatv_gateway.conf
rm -f /home/user/conf/web/ssganador.lat/nginx.ssl.conf_zzz_loteriatv_gateway.conf
rm -f /home/user/conf/web/api.ssganador.lat/nginx.conf_zzz_loteriatv_gateway.conf
rm -f /home/user/conf/web/api.ssganador.lat/nginx.ssl.conf_zzz_loteriatv_gateway.conf

if [ -f /home/user/conf/web/ssganador.lat/nginx.ssl.conf_zzz_nocache.conf.disabled ]; then
  mv /home/user/conf/web/ssganador.lat/nginx.ssl.conf_zzz_nocache.conf.disabled \
     /home/user/conf/web/ssganador.lat/nginx.ssl.conf_zzz_nocache.conf
fi

nginx -t
sudo systemctl reload nginx

docker compose -f docker-compose.prod.yml down
```
