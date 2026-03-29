# Lotería TV (Django + Channels + PWA)

Sistema para mostrar resultados de lotería en pantallas tipo TV mediante una PWA liviana y un backend Django con APIs HTTP y WebSockets.

Incluye:
- Resultados Triples y Animalitos.
- Registro y activación de dispositivos.
- Validación por sucursal y suscripción.
- Redis para cache y Channels.
- Panel admin para operación y monitoreo.

## Stack unificado

Servicios principales:
- `gateway`: Nginx sirve la PWA, `static`, `media` y hace proxy a Django y WebSockets.
- `app`: Django ASGI con Daphne.
- `worker`: Celery worker.
- `beat`: Celery beat.
- `postgres`: base de datos.
- `redis`: cache, broker y channel layer.

Con esto local y producción comparten la misma topología base: un solo stack Docker y un único punto de entrada HTTP.

## Arranque local con Docker

Levanta todo el stack:

```bash
docker compose up --build
```

Puntos de acceso:
- App/PWA: `http://127.0.0.1:8080`
- Admin Django: `http://127.0.0.1:8080/admin/`
- API: `http://127.0.0.1:8080/api/`
- WebSocket: `ws://127.0.0.1:8080/ws/...`

Notas:
- La PWA ahora usa mismo origen por defecto, así que ya no necesita un contenedor o deploy separado para hablar con el backend.
- `.env.local` queda reservado para correr Django desde el host.
- `.env.docker` define el entorno del stack Docker.

## Producción

La idea recomendada es replicar el mismo `docker compose` y exponer solo el `gateway`.

Opciones habituales:
- Publicar el puerto del `gateway` directamente detrás de un firewall o balanceador.
- Mantener Hestia solo como reverse proxy hacia el contenedor `gateway`, sin volver a copiar la PWA a `public_html`.

Resultado esperado:
- Un solo dominio principal sirviendo PWA y backend.
- Sin separación manual entre carpeta web de Hestia y carpeta del proyecto Django.
- Mismo comportamiento entre local y prod para `/`, `/api/`, `/admin/`, `/ws/` y `/static/`.

## Variables de entorno

Orden de carga fuera de Docker:
- Variables reales del sistema o proceso.
- `.env.local`
- `.env`

En Docker:
- `docker compose` usa `.env.docker` para `app`, `worker` y `beat`.

## Comandos útiles

Host local:

```bash
./venv/bin/python manage.py check_ops_health --strict
./venv/bin/python manage.py notify_scraper_alerts --dry-run
```

Dentro del stack:

```bash
docker compose exec app python manage.py migrate
docker compose exec app python manage.py createsuperuser
docker compose exec app python manage.py check_ops_health --strict
```

## Monitoreo interno de scrapers

El backend incluye control interno de salud para scrapers en Django Admin.

Variables opcionales:
- `SCRAPER_ALERT_EMAILS=ops1@dominio.com,ops2@dominio.com`
- `SCRAPER_ALERT_USERNAMES=admin1,operaciones1`
- `SCRAPER_ALERT_GROUPS=Administradores,Operadores`
- `SCRAPER_ALERT_NOTIFY_COOLDOWN_MINUTES=180`
- `DEFAULT_FROM_EMAIL=noreply@ssganador.lat`

Comandos útiles:

```bash
python manage.py run_scraper_suite
python manage.py run_scraper_suite --notify
python manage.py run_daily_retention
python manage.py purge_telemetry_events --dry-run
python manage.py purge_telemetry_events
python manage.py notify_scraper_alerts --dry-run
python manage.py notify_scraper_alerts
python manage.py check_ops_health --strict
```

Notas:
- Todo este monitoreo es interno y vive en Django Admin y comandos de operación.
- `Scraper health` resume `OK / fallo hoy / sin OK hoy / stale`.
- Si producción usa timers externos en vez de Celery, deben ejecutar `python manage.py run_scraper_suite`.
- El timer de retention en producción debe apuntar a `scripts/daily_retention.sh`.
- `DeviceTelemetryEvent` persiste `LOAD_ERROR` y `LOW_MEMORY`; los eventos informativos solo actualizan snapshot.

## Referencias operativas

- Diagnóstico PWA TV: `pwa/TV_VENEZUELA_DIAGNOSTICO.md`
- Seguridad y QA: `docs/security_qa_checklist.md`
