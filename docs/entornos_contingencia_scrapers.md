# Entornos - contingencia de scrapers

Fecha de referencia: 2026-03-24

## 1. Objetivo

Dejar por escrito como separar la configuracion local de la configuracion de staging/produccion para no romper el despliegue actual al subir el trabajo del sprint de contingencia.

## 2. Regla principal

El repo puede subir:

- codigo,
- migraciones,
- templates,
- servicios,
- tests,
- ejemplos de variables (`env.example`, `env.local.example`),
- documentos operativos.

El repo no debe subir:

- `.env.local`,
- `.env`,
- tokens reales,
- `chat_id` reales si son sensibles para operacion,
- decisiones locales de Docker que no apliquen a produccion.

## 3. Como carga variables Django hoy

La carga actual ocurre en [config/env.py](/Users/delorean/loteria-tv/config/env.py):

1. carga `.env.local`,
2. luego carga `.env`,
3. nunca pisa variables ya existentes del sistema.

Consecuencia practica:

- en tu maquina local puedes usar `.env.local` sin afectar el repo,
- en staging/prod puedes usar variables del sistema o un `.env` del servidor,
- si en produccion no usan Docker, no pasa nada mientras `DATABASE_URL` y `REDIS_URL` apunten al host real.

## 4. Distincion recomendada por entorno

### Local

Archivo esperado:

- `.env.local`

Uso esperado:

- Django local,
- Postgres y Redis accesibles en `127.0.0.1`,
- PWA local en `127.0.0.1:8080`,
- `SCRAPER_ADMIN_BASE_URL=http://127.0.0.1:8000`.

Notas:

- local puede apoyarse en `docker compose` para Postgres/Redis,
- `ADMIN_ACTIVITY_TELEGRAM_ENABLED` puede encenderse para pruebas,
- esto no debe inferirse como estrategia de produccion.

### Staging

Archivo esperado:

- variables del servidor o `.env` propio de staging

Uso esperado:

- Postgres real de staging,
- Redis real de staging,
- Telegram con bot/grupo de pruebas,
- `SCRAPER_ADMIN_BASE_URL` accesible desde fuera.

Notas:

- staging es donde se valida migracion, incidentes, carga manual y Telegram real.

### Produccion actual

Condicion conocida hoy:

- produccion no usa Docker en runtime.

Implicacion:

- el codigo nuevo no debe asumir `postgres` o `redis` como hostnames de contenedor,
- todo debe depender de `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL` y `CELERY_RESULT_BACKEND`.

Estado del paquete actual:

- el codigo ya esta alineado a variables de entorno,
- el `docker-compose.yml` es solo ayuda local,
- el deploy productivo no deberia tocarlo.

## 5. Variables nuevas de este sprint

### Minimas para contingencia de scrapers

```env
SCRAPER_ALERT_PRIMARY_CHANNEL=telegram
SCRAPER_TELEGRAM_BOT_TOKEN=
SCRAPER_TELEGRAM_CHAT_IDS=
SCRAPER_TELEGRAM_API_BASE_URL=https://api.telegram.org
SCRAPER_ADMIN_BASE_URL=
SCRAPER_ALERT_NOTIFY_COOLDOWN_MINUTES=180
SCRAPER_INCIDENT_VIEWER_GROUPS=Administradores
SCRAPER_INCIDENT_RESOLVER_GROUPS=Administradores
```

### Opcional para auditoria operativa admin

```env
ADMIN_ACTIVITY_TELEGRAM_ENABLED=0
```

Recomendacion:

- dejar `0` en staging/prod hasta confirmar el nivel de ruido real,
- activarlo primero en local o staging,
- luego decidir si queda fijo en produccion.

## 6. Lo que no debe pasar al repo como “default”

- tokens reales de Telegram,
- grupos reales de Telegram,
- `SCRAPER_ADMIN_BASE_URL` de tu localhost como valor de produccion,
- cambios de puertos por conflictos locales,
- dependencias tacitas en Docker para el runtime productivo.

## 7. Checklist antes de subir

1. Confirmar que `.env.local` no aparece en `git status`.
2. Confirmar que `env.local.example` no tiene secretos reales.
3. Confirmar que `env.example` describe servidor no-Docker y no localhost obligatorio.
4. Confirmar que las migraciones aplican limpias.
5. Confirmar que el flujo manual funciona con `ADMIN_ACTIVITY_TELEGRAM_ENABLED=0`.
6. Confirmar aparte si se quiere activar o no la auditoria admin por Telegram en staging/prod.

## 8. Plan para semanas proximas

Esto no bloquea el merge de hoy, pero conviene agendarlo:

1. Documentar el deploy productivo no-Docker completo.
2. Definir si produccion usara `.env`, variables del sistema o secretos del proveedor.
3. Separar formalmente configuracion `local`, `staging` y `prod`.
4. Agregar smoke test post-deploy para:
   - `/admin/`,
   - `notify_scraper_alerts --dry-run`,
   - simulacion de incidente,
   - prueba de Telegram,
   - verificacion de migraciones.
5. Revisar si `ADMIN_ACTIVITY_TELEGRAM_ENABLED` debe quedar en produccion o limitarse a staging.

## 9. Recomendacion de merge

Subir este sprint como:

- cambios funcionales de contingencia,
- migraciones,
- tests,
- docs,
- ejemplos saneados.

No mezclar en el mismo commit:

- limpieza de conflictos viejos en `README.md`,
- cambios no relacionados en `check_ops_health.py`,
- cambios no relacionados en `enforce_retention.py`,
- assets o experimentos fuera del alcance del sprint.
