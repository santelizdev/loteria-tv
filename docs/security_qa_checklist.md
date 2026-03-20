# Checklist de seguridad y QA (operativo)

Este documento traduce el checklist pendiente a verificaciones ejecutables dentro del proyecto.

Resolución de variables de entorno:
- El host local puede usar `.env.local`.
- Docker Compose usa `.env.docker`.
- Variables exportadas por el sistema o el proceso tienen prioridad sobre ambos.

## Comandos nuevos

### 1) Salud operacional + integridad de fechas

```bash
python manage.py check_ops_health --strict
```

Si ejecutas `manage.py` desde tu shell local en macOS/Linux, usa `.env.local` con `127.0.0.1` para no depender de los hostnames internos de Docker (`postgres`, `redis`).

```bash
docker compose up -d postgres redis
python manage.py check_ops_health --strict
```

Valida:
- Máximo de fechas distintas por tabla (`CurrentResult`, `AnimalitoResult`, `ResultArchive`, `AnimalitoArchive`).
- Que existan resultados del día en tablas current.
- Que existan archivos de ayer en tablas archive.

### 2) Retention con safety checks

```bash
python manage.py run_daily_retention
python manage.py enforce_retention --dry-run
python manage.py enforce_retention
python manage.py purge_telemetry_events --dry-run
python manage.py purge_telemetry_events
```

Desde el host local, con `.env.local` configurado:

```bash
python manage.py enforce_retention --dry-run
```

`enforce_retention` ahora aborta si detecta que **no hay datos de ayer** en `ResultArchive` o `AnimalitoArchive`.

El timer de producción debe ejecutar el wrapper versionado:

```bash
/home/deploy/loteriatv/scripts/daily_retention.sh
```

Si necesitas forzarlo (mantenimiento manual):

```bash
python manage.py enforce_retention --skip-safety-checks
```

## Scheduler/systemd (en servidor)

> Estos comandos se ejecutan en el host donde corren los servicios.

```bash
systemctl status loteriatv-scrape.timer
systemctl status loteriatv-retention.timer
systemctl is-enabled loteriatv-scrape.timer
systemctl is-enabled loteriatv-retention.timer
systemctl list-timers --all | rg loteriatv
journalctl -u loteriatv-scrape.service --since "24 hours ago"
journalctl -u loteriatv-retention.service --since "24 hours ago"
```

## Endpoints QA rápido

```bash
curl -i "http://127.0.0.1:8000/api/results/?code=TU_CODE"
curl -i "http://127.0.0.1:8000/api/animalitos/?code=TU_CODE"
curl -i "http://127.0.0.1:8000/api/devices/status/?code=TU_CODE"
curl -i -X POST "http://127.0.0.1:8000/api/devices/heartbeat/" -H "Content-Type: application/json" -d '{"code":"TU_CODE"}'
```

## Seguridad de configuración

```bash
ls -l .env
rg -n "DEBUG|ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|django_prometheus|CORS_ALLOW_ALL_ORIGINS" config/settings.py config/urls.py
rg -n "SECRET|TOKEN|API_KEY|PASSWORD" config core --glob '!**/migrations/**'
```
