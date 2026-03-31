# Sprint: Unificación Docker, Cruz Diaria y Monitoreo

Fecha de cierre: 2026-03-29

## Objetivo del sprint

Cerrar la brecha entre local y producción, mejorar la operación de scrapers y sumar una nueva pieza visual diaria para la PWA sin mezclarla con el loop principal de tablas rotativas.

## Hitos logrados

### 1. Unificación de arquitectura local y productiva

Se dejó el proyecto funcionando sobre una topología única basada en Docker:

- `gateway`: Nginx sirve la PWA y hace proxy a Django y WebSockets.
- `app`: Django + Daphne.
- `worker`: Celery worker.
- `beat`: Celery beat.
- `postgres` y `redis` en local.

En producción se migró el tráfico a Docker manteniendo Hestia como reverse proxy.

Resultado:

- `ssganador.lat` sirve la PWA desde Docker.
- `api.ssganador.lat` sirve admin/API desde Docker.
- se apagaron los servicios legacy `loteriatv-daphne.service`, `loteriatv-scrape.timer` y `loteriatv-retention.timer`.
- Celery Beat quedó como scheduler principal en producción.

## 2. Nueva sección fija "Cruz de la Suerte"

Se integró el contenido diario de `https://cruzdelasuerte.com/` como bloque fijo lateral en la PWA.

Incluye:

- `Cruceta de Hoy`
- `Guía y Probables`
- `Pirámide de la Suerte`

Decisiones de implementación:

- scraper diario propio;
- almacenamiento diario sin histórico;
- endpoint dedicado;
- render fijo en sidebar, fuera del loop de las 4 tablas dinámicas;
- estilo visual propio alineado al pedido de diseño.

Resultado visual:

- encabezado único con fecha del día;
- sin títulos repetidos por tarjeta;
- mayor área útil para ver las imágenes;
- fondo y borde ajustados para mejor legibilidad.

## 3. Calentamiento inicial de datos

Se agregó `warm_scraper_data` para bootstrap del stack al arrancar, incluyendo la carga de Cruz diaria cuando aplica.

Aprendizaje operativo:

- en producción conviene dejar `WARM_SCRAPERS_ON_BOOT=0` para evitar arranques lentos o duplicación de corridas cuando el scheduler normal ya está activo.

## 4. Correcciones en PWA y Service Worker

Se corrigieron varios puntos de estabilidad:

- validación del código de activación guardado en dispositivo;
- re-registro automático cuando el código ya no existe;
- exclusión de `/media/` del Service Worker para evitar fallos con logos;
- sembrado de `media` en Docker local para no arrancar con volumen vacío;
- caché de shell PWA más controlado durante rebuilds.

## 5. Mejora en monitoreo de scrapers

Se reforzó la capa de operación interna:

- `ScraperExecution` y `ScraperIncident` para trazabilidad;
- alertas periódicas con `notify_scraper_alerts`;
- purga automática de `ScraperExecution` viejo;
- soporte para `manual_contingency` como resultado válido en la evaluación.

Impacto:

- se redujo un tipo concreto de falso positivo: cuando una falta de resultado ya fue corregida manualmente.

## 6. Reporte semanal de membresías

Se agregó el módulo semanal administrativo para agrupar dispositivos por ventana de membresía y calcular subtotales.

Incluye:

- fecha de inicio de membresía;
- fecha de fin;
- pantallas activas;
- total semanal por grupo.

## Fixes principales del sprint

### Device code eliminado

Antes:

- si un `activation_code` desaparecía del backend, la PWA seguía intentando usarlo.

Ahora:

- la PWA detecta que el código ya no existe;
- limpia el cache local;
- vuelve a registrarse.

### Falsos positivos por contingencia manual

Antes:

- si faltaba el dato automático pero luego se corregía manualmente, el monitoreo podía seguir tratando ese grupo como faltante.

Ahora:

- `manual_contingency` cuenta como origen usable;
- un grupo corregido manualmente puede cerrar el incidente correspondiente.

### Error de imágenes y logos en la PWA

Antes:

- el Service Worker intentaba responder assets de `media` y rechazaba promesas cuando fallaba la red.

Ahora:

- `/media/` se maneja fuera del SW;
- el error desaparece;
- los logos cargan correctamente.

## Hallazgos operativos importantes

### 1. Telegram no estaba fallando por código

Durante la validación en producción se detectó que el problema real era de configuración:

- `.env.prod` tenía el placeholder `replace-telegram-bot-token`.

Luego, al restaurar el token real, se confirmó que Telegram sí enviaba, pero empezó a responder `429 Too Many Requests` por exceso de incidentes abiertos.

### 2. Los incidentes actuales de Lotoven no son el mismo falso positivo anterior

Se comprobó que los incidentes actuales de `lotoven_triples` provienen de un contrato esperado rígido que hoy no coincide siempre con lo que publica la fuente.

Ejemplos observados:

- `Triple Caracas` faltando en domingo;
- `Triple Caliente` parcial;
- `Triple Tachira` y `Triple Zamorano` con ausencia total en el día analizado.

Conclusión:

- el fix de `manual_contingency` sí quedó aplicado;
- pero quedan pendientes ajustes del `schedule` esperado para eliminar falsos positivos de providers/horarios que no son estables.

## Estado final del deploy de este sprint

Producción quedó sirviendo correctamente:

- `https://ssganador.lat`
- `https://api.ssganador.lat/admin/login/`

Servicios activos:

- `app`
- `worker`
- `beat`
- `gateway`

Servicios legacy apagados:

- `loteriatv-daphne.service`
- `loteriatv-scrape.timer`
- `loteriatv-retention.timer`

Commit operativo desplegado en VPS al cierre:

- `11f11b8`

## Pendientes post-sprint

### Ajustes funcionales

- redefinir qué providers/horarios de `lotoven_triples` siguen siendo válidos;
- bajar ruido de incidentes de `Lotoven`;
- revisar si `Triple Caracas`, `Triple Tachira`, `Triple Zamorano` y `Triple Caliente` deben seguir en monitoreo estricto.

### Endurecimiento técnico

- corregir warning de modelos con cambios sin migración reflejada;
- ejecutar `worker` y `beat` sin usuario root dentro del contenedor;
- limpiar archivos legacy de Hestia que ya no se usan;
- documentar runbook operativo definitivo.

## Comandos útiles de operación

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 app
docker compose -f docker-compose.prod.yml logs --tail=100 worker
docker compose -f docker-compose.prod.yml logs --tail=100 beat
docker compose -f docker-compose.prod.yml up -d --force-recreate app worker beat gateway
docker compose -f docker-compose.prod.yml exec app python manage.py notify_scraper_alerts --dry-run
docker compose -f docker-compose.prod.yml exec app python manage.py purge_scraper_executions --keep-days=14
```

## Cierre

El sprint dejó resuelta la migración grande de arquitectura, incorporó el nuevo bloque diario de Cruz de la Suerte y mejoró la base operativa para monitoreo y despliegues. Lo que queda ahora ya no es caos estructural: es afinación fina de contratos, horarios y ruido operativo.

---

## Continuación 2026-03-30: Afinación Operativa de Scrapers

### Ajustes aplicados en local

- `lotoven_triples` ahora evalúa grupos estrictos con una gracia de `12` minutos antes de abrir incidente.
- el matching de horarios estrictos acepta una tolerancia de hasta `15` minutos entre hora esperada y hora persistida;
  esto reduce ruido en casos como publicaciones reales alrededor de `19:00` frente a horarios rígidos como `19:10`.
- `tuazar_triples` ahora necesita `3` fallas consecutivas antes de disparar alerta de salud `failed_today`.
- `Celery Beat` volvió a una cadencia operativa de `3` minutos para scrapers de resultados.
- `Cruz de la Suerte` se mueve a `08:00 AM` Venezuela tanto en `beat` como en `warm_scraper_data`.
- la PWA ahora tolera pequeños corrimientos de hora al ubicar resultados en tarjetas agrupadas.

### Catálogo comercial activo del sprint

Se dejó un catálogo operativo explícito para no seguir mostrando ni monitoreando providers fuera del alcance comercial actual.

#### Animalitos visibles

- `Guacharito`
- `Guacharo`
- `Cazaloton`
- `La Granjita`
- `Loto Chaima`
- `Lotto Activo`
- `Lotto Activo Interl`
- `Lotto Rey`
- `Mega Animal`
- `SelvaPlus`

#### Loterías visibles

- `Triple Caliente`
- `Triple Caracas`
- `Chance Astral`
- `Triple Tachira`
- `Trio Activo`
- `Triple Facil`
- `Triple Zamorano`
- `Triple Zulia`
- `Triple Gana`
- `Super Gana`
- `Triple Centena`

#### Scrapers activos en esta etapa

- `lotoven_triples`
- `tuazar_triples`
- `lotoven_animalitos`

Scrapers pausados por alcance comercial actual:

- `condor_animalitos`

Providers pausados pero no eliminados del código:

- `Triple Chance`
- `La Ricachona`
- `Triple Dorado`
- `Terminal Trio`
- `Terminal La Granjita`
- `La Ruca`

### Instrucciones para auditar falsos positivos antes de reenviar Telegram

Cuando aparezca una alerta dudosa, no forzar primero `notify_scraper_alerts --force`. Antes revisar:

1. incidentes abiertos del scraper y fecha objetivo;
2. grupos esperados vs persistidos vs faltantes;
3. si la fuente realmente cambió horario, dejó de publicar ese provider o el parser dejó de reconocer la tabla.

Comandos útiles:

```bash
docker compose -f docker-compose.prod.yml exec app python manage.py notify_scraper_alerts --dry-run --force
docker compose -f docker-compose.prod.yml exec app python manage.py shell -c "from django.utils import timezone; from core.services.scraper_execution_service import ScraperExecutionService; draw_date=timezone.localdate(); now=timezone.now(); expected=ScraperExecutionService._get_due_expected_groups('lotoven_triples', draw_date, now=now); persisted=ScraperExecutionService._get_persisted_groups('lotoven_triples', draw_date); missing=ScraperExecutionService._get_missing_groups(expected, persisted); print('EXPECTED'); [print(g) for g in expected]; print('PERSISTED'); [print(g) for g in persisted]; print('MISSING'); [print(g) for g in missing]"
```

Si el ruido viene de contrato rígido y no de una falla real:

- resolver incidentes abiertos del día;
- ajustar catálogo o schedule esperado;
- recién después volver a validar Telegram.

Comando de limpieza operativa temporal:

```bash
docker compose -f docker-compose.prod.yml exec app python manage.py shell -c "from django.utils import timezone; from django.utils.timezone import now; from core.models import ScraperIncident; n=ScraperIncident.objects.filter(status='open', scraper_key='lotoven_triples', draw_date=timezone.localdate()).update(status='resolved', resolved_at=now(), resolution_note='Cierre temporal mientras se redefine contrato esperado'); print(f'lotoven_open_incidents_resolved={n}')"
```

### Nota de operación

El objetivo de esta fase no fue borrar scrapers ni providers, sino dejarlos pausados de forma reversible. El siguiente paso natural, cuando se quiera más flexibilidad, es mover este catálogo a un módulo administrable desde Django.
